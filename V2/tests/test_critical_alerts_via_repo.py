"""Testes das regras de critical_alerts migradas para o LeadRepository.

Rodável sem pytest:  python tests/test_critical_alerts_via_repo.py

A injeção de dependência (regra recebe `repo`, não `conn`) destrava teste
sem banco — passamos um `FakeRepo` populado com `LeadRecord`s pré-fabricados.

Regras cobertas:
  - rule_capi_success_low                  (Etapa 2 do refator — 2026-05-24)
  - rule_variant_no_capi                   (Etapa 3 — 2026-05-24)
  - rule_utm_source_missing                (Etapa 3 — 2026-05-24)
  - rule_score_drift                       (Etapa 3 — 2026-05-24)
"""
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data import LeadRecord
from src.monitoring.critical_alerts import (
    rule_capi_success_low,
    rule_variant_no_capi,
    rule_utm_source_missing,
    rule_score_drift,
)


@dataclass
class FakeRepo:
    """Repositório fake: devolve a lista pré-programada de leads."""
    leads: list = field(default_factory=list)

    def recent_leads(self, window_minutes, limit=10_000):
        return self.leads

    def leads_in_range(self, start, end, limit=10_000):
        return self.leads


def _lead(status: str, idx: int = 0, **extras) -> LeadRecord:
    """Helper: cria um LeadRecord mínimo com o status_envio dado.

    Campos opcionais (variant, score, decil, utm_source, etc.) passam por
    **extras. Mantém o teste enxuto sem expor 14 kwargs em cada caso.
    """
    base = dict(
        event_id=f'evt-{idx}',
        email=f'lead{idx}@test.dev',
        criado_em=datetime.now(timezone.utc),
        status_envio=status,
    )
    base.update(extras)
    return LeadRecord(**base)


# ──────────────────────────────────────────────────────────────────────────
# rule_capi_success_low
# ──────────────────────────────────────────────────────────────────────────

def test_capi_success_low_amostra_insuficiente_pula():
    # sent (success + error) = 5 → abaixo do mínimo de 10 → skip
    leads = [_lead('success', i) for i in range(3)] + [_lead('error', i+100) for i in range(2)]
    result = rule_capi_success_low(FakeRepo(leads))
    assert result.fired is False, f"esperava fired=False, recebi {result}"
    assert 'amostra insuficiente' in (result.skipped_reason or '')
    assert 'sent=5' in (result.skipped_reason or '')


def test_capi_success_low_taxa_alta_nao_dispara():
    # sent=20, ok=20 → 100% > 95% → não dispara
    leads = [_lead('success', i) for i in range(20)]
    result = rule_capi_success_low(FakeRepo(leads))
    assert result.fired is False


def test_capi_success_low_taxa_baixa_dispara():
    # sent=20, ok=10 → 50% < 95% → dispara
    leads = [_lead('success', i) for i in range(10)] + [_lead('error', i+100) for i in range(10)]
    result = rule_capi_success_low(FakeRepo(leads))
    assert result.fired is True
    assert result.details['sent'] == 20
    assert result.details['ok'] == 10
    assert result.details['err'] == 10
    assert result.details['rate_pct'] == 50.0


def test_capi_success_low_skipped_nao_contam_no_sent():
    # 9 success + 1 error = 10 enviados (acima do mínimo); 100 skipped não contam
    # → rate = 90% < 95% → dispara
    leads = (
        [_lead('success', i) for i in range(9)]
        + [_lead('error', 100)]
        + [_lead('skipped_allowlist', i+200) for i in range(50)]
        + [_lead('skipped_missing_data', i+300) for i in range(50)]
    )
    result = rule_capi_success_low(FakeRepo(leads))
    assert result.fired is True
    assert result.details['sent'] == 10, "skipped_* não devem contar no sent"
    assert result.details['ok'] == 9
    assert result.details['err'] == 1
    assert result.details['rate_pct'] == 90.0


def test_capi_success_low_borda_minima_taxa_perfeita_nao_dispara():
    # Exatamente 10 enviados, todos success → 100% → não dispara
    leads = [_lead('success', i) for i in range(10)]
    result = rule_capi_success_low(FakeRepo(leads))
    assert result.fired is False


# ──────────────────────────────────────────────────────────────────────────
# rule_variant_no_capi (per-variant)
# ──────────────────────────────────────────────────────────────────────────

def test_variant_no_capi_champion_100pct_erro_dispara():
    # Champion: 10 leads, todos com erro → 0 sucessos em 10 tentativas → dispara
    leads = [_lead('error', i, variant='champion') for i in range(10)]
    result = rule_variant_no_capi(FakeRepo(leads))
    assert result.fired is True
    assert 'champion' in result.details['variantes_afetadas']
    assert result.details['detalhes_por_variante']['champion']['scoreados'] == 10
    assert result.details['detalhes_por_variante']['champion']['erros'] == 10


def test_variant_no_capi_challenger_quebrado_champion_ok_dispara_so_challenger():
    # Champion funcionando (10/10 success); Challenger todo com erro (0/10 success)
    leads = (
        [_lead('success', i, variant='champion') for i in range(10)]
        + [_lead('error', i+100, variant='challenger') for i in range(10)]
    )
    result = rule_variant_no_capi(FakeRepo(leads))
    assert result.fired is True
    assert result.details['variantes_afetadas'] == ['challenger']


def test_variant_no_capi_amostra_insuficiente_pula():
    # Total scoreado = 5 < 10 → skip
    leads = [_lead('error', i, variant='champion') for i in range(5)]
    result = rule_variant_no_capi(FakeRepo(leads))
    assert result.fired is False
    assert 'amostra insuficiente' in (result.skipped_reason or '')


def test_variant_no_capi_ambas_variantes_ok_nao_dispara():
    leads = (
        [_lead('success', i, variant='champion') for i in range(10)]
        + [_lead('success', i+100, variant='challenger') for i in range(10)]
    )
    result = rule_variant_no_capi(FakeRepo(leads))
    assert result.fired is False


# ──────────────────────────────────────────────────────────────────────────
# rule_utm_source_missing
# ──────────────────────────────────────────────────────────────────────────

def test_utm_source_missing_amostra_pequena_pula():
    leads = [_lead('success', i, utm_source=None) for i in range(20)]  # n<50
    result = rule_utm_source_missing(FakeRepo(leads))
    assert result.fired is False
    assert 'amostra insuficiente' in (result.skipped_reason or '')


def test_utm_source_missing_taxa_baixa_nao_dispara():
    # 100 leads, 3 sem source → 3% < 5% → não dispara
    leads = (
        [_lead('success', i, utm_source='facebook') for i in range(97)]
        + [_lead('success', i+200, utm_source=None) for i in range(3)]
    )
    result = rule_utm_source_missing(FakeRepo(leads))
    assert result.fired is False


def test_utm_source_missing_taxa_alta_dispara():
    # 100 leads, 10 sem source → 10% > 5% → dispara
    leads = (
        [_lead('success', i, utm_source='facebook') for i in range(90)]
        + [_lead('success', i+200, utm_source=None) for i in range(10)]
    )
    result = rule_utm_source_missing(FakeRepo(leads))
    assert result.fired is True
    assert result.details['pct'] == 10.0


def test_utm_source_missing_string_vazia_conta_como_missing():
    # 60 leads, 6 com utm_source='' (string vazia) → 10% → dispara
    leads = (
        [_lead('success', i, utm_source='facebook') for i in range(54)]
        + [_lead('success', i+200, utm_source='   ') for i in range(6)]  # whitespace
    )
    result = rule_utm_source_missing(FakeRepo(leads))
    assert result.fired is True
    assert result.details['sem_source'] == 6


# ──────────────────────────────────────────────────────────────────────────
# rule_score_drift (usa 2 repositórios — janela e baseline)
# ──────────────────────────────────────────────────────────────────────────

def test_score_drift_amostra_janela_pequena_pula():
    janela = [_lead('success', i, score=0.3, decil=5) for i in range(20)]  # <50
    baseline = [_lead('success', i, score=0.3, decil=5) for i in range(2000)]
    result = rule_score_drift(FakeRepo(janela), FakeRepo(baseline), {'D10': 0.10})
    assert result.fired is False
    assert 'amostra de scores insuficiente' in (result.skipped_reason or '')


def test_score_drift_baseline_pequeno_pula():
    janela = [_lead('success', i, score=0.3, decil=5) for i in range(60)]
    baseline = [_lead('success', i, score=0.3, decil=5) for i in range(500)]  # <1000
    result = rule_score_drift(FakeRepo(janela), FakeRepo(baseline), {'D10': 0.10})
    assert result.fired is False
    assert 'baseline rolling 30d insuficiente' in (result.skipped_reason or '')


def test_score_drift_media_dentro_de_1sigma_nao_dispara():
    # Janela tem média 0.40; baseline tem média 0.40, σ=0.10 → z=0 → não dispara
    import random
    random.seed(42)
    janela = [_lead('success', i, score=0.40 + random.gauss(0, 0.05), decil=5)
              for i in range(60)]
    baseline = [_lead('success', i, score=0.40 + random.gauss(0, 0.10), decil=5)
                for i in range(2000)]
    result = rule_score_drift(FakeRepo(janela), FakeRepo(baseline), {'D10': 0.10})
    assert result.fired is False


def test_score_drift_media_deslocada_dispara_A():
    # Janela tem média ~0.80; baseline tem média ~0.40 σ~0.10 → z>>1 → dispara (A)
    janela = [_lead('success', i, score=0.80, decil=5) for i in range(60)]
    import random
    random.seed(7)
    baseline = [_lead('success', i, score=0.40 + random.gauss(0, 0.10), decil=5)
                for i in range(2000)]
    result = rule_score_drift(FakeRepo(janela), FakeRepo(baseline), {'D10': 0.10})
    assert result.fired is True
    assert result.details['fired_a_mean'] is True


def test_score_drift_d10_deslocado_dispara_B():
    # Janela: 50% no decil 10. Baseline esperado: 10%. ΔD10 = 40pp > 5pp → dispara (B)
    janela = (
        [_lead('success', i, score=0.40, decil=10) for i in range(50)]
        + [_lead('success', i+100, score=0.40, decil=5) for i in range(50)]
    )
    import random
    random.seed(11)
    baseline = [_lead('success', i, score=0.40 + random.gauss(0, 0.10), decil=5)
                for i in range(2000)]
    result = rule_score_drift(FakeRepo(janela), FakeRepo(baseline), {'D10': 0.10})
    assert result.fired is True
    assert result.details['fired_b_decil'] is True


# ──────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    tests = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]
    print(f"Rodando {len(tests)} testes...")
    falhas = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            falhas += 1
            print(f"  ✗ {t.__name__}: {e}")
        except Exception as e:
            falhas += 1
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\nResultado: {len(tests) - falhas}/{len(tests)} passaram")
    sys.exit(0 if falhas == 0 else 1)
