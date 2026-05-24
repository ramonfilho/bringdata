"""Testes das regras de critical_alerts migradas para o LeadRepository.

Rodável sem pytest:  python tests/test_critical_alerts_via_repo.py

A injeção de dependência (regra recebe `repo`, não `conn`) destrava teste
sem banco — passamos um `FakeRepo` populado com `LeadRecord`s pré-fabricados.

Regras cobertas nesta passagem:
  - rule_capi_success_low (Etapa 2 do refator do monitoramento, 2026-05-24)

Próximas regras serão adicionadas aqui conforme migrarem.
"""
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data import LeadRecord
from src.monitoring.critical_alerts import rule_capi_success_low


@dataclass
class FakeRepo:
    """Repositório fake: devolve a lista pré-programada de leads."""
    leads: list

    def recent_leads(self, window_minutes, limit=10_000):
        return self.leads

    def leads_in_range(self, start, end, limit=10_000):
        return self.leads


def _lead(status: str, idx: int = 0) -> LeadRecord:
    """Helper: cria um LeadRecord mínimo com o status_envio dado."""
    return LeadRecord(
        event_id=f'evt-{idx}',
        email=f'lead{idx}@test.dev',
        criado_em=datetime.now(timezone.utc),
        status_envio=status,
    )


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
