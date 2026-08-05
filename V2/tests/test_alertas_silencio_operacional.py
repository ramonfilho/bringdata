"""
Alertas de silêncio operacional (`no_leads_received` / `no_capi_sent`).

Estes dois só disparam quando o pipeline fica QUIETO, que é exatamente o estado
normal entre lançamentos. Por isso ficaram muito tempo sem nunca aparecer num
payload, os campos deles nunca foram declarados no schema, e a primeira pausa de
captação real (05/08/2026) derrubou os dois digests do Slack com 500.

Dois contratos aqui:
  1. Os campos são declarados — silêncio operacional não pode quebrar o relatório.
  2. Nenhum deles carrega e-mail — o alerta é renderizado no Slack, inclusive no
     canal do cliente, e o timestamp já localiza o lead no ledger sem expor PII.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.monitoring.operational_monitor import OperationalMonitor
from src.monitoring.payload_schema import PAYLOAD_SCHEMA


class _Lead:
    def __init__(self, criado_em, capi_enviado_em=None, email='alguem@exemplo.com'):
        self.criado_em = criado_em
        self.capi_enviado_em = capi_enviado_em
        self.email = email


class _Repo:
    def __init__(self, leads):
        self._leads = leads

    def recent_leads(self, window_minutes=None):
        return self._leads


def _monitor(leads, horas=1):
    m = OperationalMonitor.__new__(OperationalMonitor)
    m.repo = _Repo(leads)
    m._thresholds = {'operational': {'no_leads_hours': horas, 'no_capi_hours': horas}}
    m._LOOKBACK_MINUTES = 1440
    return m


def _velho(horas):
    return datetime.now(timezone.utc) - timedelta(hours=horas)


# ── Contrato 1: os campos existem e estão declarados ─────────────────────────

def test_alerta_de_lead_parado_dispara_e_traz_o_relogio():
    a = _monitor([_Lead(criado_em=_velho(11))])._check_no_leads()
    assert len(a) == 1
    d = a[0]['details']
    assert d['hours_since'] >= 10
    assert 'last_lead_at' in d


def test_alerta_de_capi_parado_dispara_e_traz_o_relogio():
    a = _monitor([_Lead(criado_em=_velho(11), capi_enviado_em=_velho(11))])._check_no_capi()
    assert len(a) == 1
    d = a[0]['details']
    assert d['hours_since'] >= 10
    assert 'last_capi_at' in d


@pytest.mark.parametrize('chave', [
    'alerts[].details.hours_since',
    'alerts[].details.last_lead_at',
    'alerts[].details.last_capi_at',
])
def test_campo_declarado_no_schema(chave):
    """Sem isto, a auditoria fail-loud derruba o digest inteiro com 500 na
    primeira vez que o pipeline ficar quieto."""
    assert chave in PAYLOAD_SCHEMA


def test_todo_campo_emitido_esta_declarado():
    """Trava geral: qualquer campo NOVO nestes dois alertas precisa ser declarado
    junto, senão o relatório morre na próxima pausa de captação."""
    leads = [_Lead(criado_em=_velho(11), capi_enviado_em=_velho(11))]
    m = _monitor(leads)
    for alerta in m._check_no_leads() + m._check_no_capi():
        for campo in alerta['details']:
            assert f'alerts[].details.{campo}' in PAYLOAD_SCHEMA, (
                f"campo '{campo}' do alerta '{alerta['type']}' não está em PAYLOAD_SCHEMA"
            )


# ── Contrato 2: nada de PII ──────────────────────────────────────────────────

def test_nenhum_alerta_de_silencio_carrega_email():
    """Estes alertas vão pro Slack, inclusive pro canal do cliente."""
    leads = [_Lead(criado_em=_velho(11), capi_enviado_em=_velho(11),
                   email='pessoa.real@gmail.com')]
    m = _monitor(leads)
    for alerta in m._check_no_leads() + m._check_no_capi():
        blob = repr(alerta)
        assert 'pessoa.real@gmail.com' not in blob, f"e-mail vazou em {alerta['type']}"
        assert not any('email' in k for k in alerta['details']), alerta['details']


def test_email_segue_indeclarado_de_proposito():
    """Se alguém reintroduzir o e-mail, a auditoria PRECISA estourar em vez de
    aceitar calada. Declarar como suprimido deixaria PII entrar sem ninguém ver."""
    assert 'alerts[].details.last_lead_email' not in PAYLOAD_SCHEMA


# ── Não disparar quando está tudo bem ────────────────────────────────────────

def test_silencio_curto_nao_alerta():
    m = _monitor([_Lead(criado_em=_velho(0.2), capi_enviado_em=_velho(0.2))], horas=6)
    assert m._check_no_leads() == []
    assert m._check_no_capi() == []
