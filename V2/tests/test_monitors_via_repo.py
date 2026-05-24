"""Testes dos monitors filhos do daily-check migrados para o LeadRepository.

Rodável sem pytest:  python tests/test_monitors_via_repo.py

Cobre:
  - OperationalMonitor (Etapa 4 do refator do monitoramento — 2026-05-24)
  - CAPIQualityMonitor (Etapa 4 do refator do monitoramento — 2026-05-24)
"""
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data import LeadRecord
from src.monitoring.operational_monitor import OperationalMonitor
from src.monitoring.capi_monitor import CAPIQualityMonitor


@dataclass
class FakeRepo:
    """Repositório fake — devolve a lista pré-programada."""
    leads: list = field(default_factory=list)

    def recent_leads(self, window_minutes, limit=10_000):
        return self.leads

    def leads_in_range(self, start, end, limit=10_000):
        return self.leads


def _lead(status='success', idx=0, hours_ago=1, capi_hours_ago=None, **extras):
    """Cria LeadRecord. `hours_ago` controla `criado_em`; `capi_hours_ago`
    controla `capi_enviado_em` (None = não enviado)."""
    now = datetime.now(timezone.utc)
    base = dict(
        event_id=f'evt-{idx}',
        email=f'lead{idx}@test.dev',
        criado_em=now - timedelta(hours=hours_ago),
        status_envio=status,
        capi_enviado_em=(now - timedelta(hours=capi_hours_ago)) if capi_hours_ago is not None else None,
    )
    base.update(extras)
    return LeadRecord(**base)


# ──────────────────────────────────────────────────────────────────────────
# OperationalMonitor
# ──────────────────────────────────────────────────────────────────────────

def test_operational_repo_none_retorna_vazio():
    mon = OperationalMonitor(None)
    assert mon.check() == []


def test_operational_sem_leads_no_lookback_sem_alerta():
    mon = OperationalMonitor(FakeRepo([]))
    assert mon.check() == []


def test_operational_lead_recente_sem_alerta_no_leads():
    # último lead 1h atrás, threshold default 6h → sem alerta
    leads = [_lead(hours_ago=1, idx=1)]
    mon = OperationalMonitor(FakeRepo(leads))
    alerts = mon.check()
    no_leads_alerts = [a for a in alerts if a['type'] == 'no_leads_received']
    assert no_leads_alerts == []


def test_operational_sem_leads_recentes_dispara_no_leads():
    # último lead 10h atrás (threshold 6h) → alerta MEDIUM
    leads = [_lead(hours_ago=10, idx=1)]
    mon = OperationalMonitor(FakeRepo(leads))
    alerts = mon.check()
    no_leads = [a for a in alerts if a['type'] == 'no_leads_received']
    assert len(no_leads) == 1
    assert no_leads[0]['severity'] == 'MEDIUM'
    assert no_leads[0]['details']['hours_since'] >= 10


def test_operational_silencio_longo_dispara_no_leads_HIGH():
    leads = [_lead(hours_ago=15, idx=1)]
    mon = OperationalMonitor(FakeRepo(leads))
    alerts = mon.check()
    no_leads = [a for a in alerts if a['type'] == 'no_leads_received']
    assert len(no_leads) == 1
    assert no_leads[0]['severity'] == 'HIGH'


def test_operational_capi_recente_sem_alerta():
    # tem lead recente e CAPI enviado 2h atrás → sem alerta
    leads = [_lead(hours_ago=1, capi_hours_ago=2, idx=1)]
    mon = OperationalMonitor(FakeRepo(leads))
    alerts = mon.check()
    no_capi = [a for a in alerts if a['type'] == 'no_capi_sent']
    assert no_capi == []


def test_operational_sem_capi_dispara():
    # lead recente mas CAPI mais antigo (10h atrás) → alerta no_capi_sent
    leads = [_lead(hours_ago=1, capi_hours_ago=10, idx=1)]
    mon = OperationalMonitor(FakeRepo(leads))
    alerts = mon.check()
    no_capi = [a for a in alerts if a['type'] == 'no_capi_sent']
    assert len(no_capi) == 1
    assert no_capi[0]['severity'] == 'MEDIUM'


# ──────────────────────────────────────────────────────────────────────────
# CAPIQualityMonitor
# ──────────────────────────────────────────────────────────────────────────

def test_capi_quality_repo_none_retorna_vazio():
    mon = CAPIQualityMonitor(None)
    assert mon.check() == []


def test_capi_missing_data_rate_baixa_sem_alerta():
    # 90% success, 10% skipped_missing_data → 10% < 50% (threshold) → sem alerta
    leads = (
        [_lead(status='success', idx=i) for i in range(90)]
        + [_lead(status='skipped_missing_data', idx=i+100) for i in range(10)]
    )
    mon = CAPIQualityMonitor(FakeRepo(leads))
    alerts = mon.check()
    missing = [a for a in alerts if a['type'] == 'capi_missing_data_high']
    assert missing == []


def test_capi_missing_data_rate_alta_dispara():
    # 30% success, 70% skipped_missing_data → 70% > 50% → dispara
    leads = (
        [_lead(status='success', idx=i) for i in range(30)]
        + [_lead(status='skipped_missing_data', idx=i+100) for i in range(70)]
    )
    mon = CAPIQualityMonitor(FakeRepo(leads))
    alerts = mon.check()
    missing = [a for a in alerts if a['type'] == 'capi_missing_data_high']
    assert len(missing) == 1
    assert missing[0]['severity'] == 'MEDIUM'  # 70% < 75% (HIGH cut)


def test_capi_missing_data_ignora_skipped_allowlist():
    # 90 skipped_allowlist (não-Meta-elegível) não devem entrar no denominador.
    # 10 elegíveis = 5 success + 5 skipped_missing_data → 50% missing → não bate >50%
    leads = (
        [_lead(status='skipped_allowlist', idx=i) for i in range(90)]
        + [_lead(status='success', idx=i+100) for i in range(5)]
        + [_lead(status='skipped_missing_data', idx=i+200) for i in range(5)]
    )
    mon = CAPIQualityMonitor(FakeRepo(leads))
    alerts = mon.check()
    missing = [a for a in alerts if a['type'] == 'capi_missing_data_high']
    assert missing == []


def test_capi_rejection_rate_baixa_sem_alerta():
    # 95% success, 5% error → 5% < 10% → sem alerta
    leads = (
        [_lead(status='success', idx=i) for i in range(95)]
        + [_lead(status='error', idx=i+100) for i in range(5)]
    )
    mon = CAPIQualityMonitor(FakeRepo(leads))
    alerts = mon.check()
    rej = [a for a in alerts if a['type'] == 'capi_rejection_rate_high']
    assert rej == []


def test_capi_rejection_rate_alta_dispara():
    # 70% success, 30% error → 30% > 10% → dispara HIGH (≥25%)
    leads = (
        [_lead(status='success', idx=i) for i in range(70)]
        + [_lead(status='error', idx=i+100) for i in range(30)]
    )
    mon = CAPIQualityMonitor(FakeRepo(leads))
    alerts = mon.check()
    rej = [a for a in alerts if a['type'] == 'capi_rejection_rate_high']
    assert len(rej) == 1
    assert rej[0]['severity'] == 'HIGH'


def test_capi_zero_decil_volume_baixo_skipa():
    # Só 50 success — abaixo do min_leads (100) → skipa silenciosamente
    leads = [_lead(status='success', idx=i, decil=10) for i in range(50)]
    mon = CAPIQualityMonitor(FakeRepo(leads))
    alerts = mon.check()
    zero = [a for a in alerts if a['type'] == 'capi_zero_decil_events']
    assert zero == []


def test_capi_zero_decil_volume_ok_todos_decis_sem_alerta():
    # 200 success distribuídos em todos os decis → sem alerta
    leads = []
    idx = 0
    for d in range(1, 11):
        for _ in range(20):
            leads.append(_lead(status='success', idx=idx, decil=d))
            idx += 1
    mon = CAPIQualityMonitor(FakeRepo(leads))
    alerts = mon.check()
    zero = [a for a in alerts if a['type'] == 'capi_zero_decil_events']
    assert zero == []


def test_capi_zero_decil_d9_invisivel_dispara():
    # 150 success cobrindo todos os decis exceto D9 → dispara HIGH
    leads = []
    idx = 0
    for d in range(1, 11):
        if d == 9:
            continue
        for _ in range(20):
            leads.append(_lead(status='success', idx=idx, decil=d))
            idx += 1
    mon = CAPIQualityMonitor(FakeRepo(leads))
    alerts = mon.check()
    zero = [a for a in alerts if a['type'] == 'capi_zero_decil_events']
    assert len(zero) == 1
    assert zero[0]['severity'] == 'HIGH'
    assert 'D09' in zero[0]['details']['zero_decils']


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
