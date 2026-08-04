"""
Trava de tráfego: relatório só sai se houve veiculação paga na janela.

O teste que mais importa aqui é o do fail-safe: quando a medição falha, o
relatório TEM que ir. O prejuízo de um relatório de zeros é irritação; o de um
relatório que desaparece calado no dia em que o tráfego voltou é operar às
cegas por dias.
"""

import pytest

from src.monitoring.traffic_gate import (
    MIN_SPEND_BRL,
    PAID_SOURCES,
    avaliar_trafego,
    check_from_daily_check,
    check_from_utm_result,
    contar_leads_pagos,
    trava_habilitada,
)


# ── A regra pura ─────────────────────────────────────────────────────────────

def test_gasto_acima_do_piso_libera():
    c = avaliar_trafego(spend=13641.48, leads=2092)
    assert c.ativo is True
    assert c.medido is True


def test_gasto_e_leads_zerados_bloqueia():
    c = avaliar_trafego(spend=0.0, leads=0)
    assert c.ativo is False
    assert c.medido is True
    assert 'sem tráfego' in c.motivo


def test_lead_pago_sem_gasto_ainda_libera():
    """Gasto pode chegar zerado por lag da API; um lead pago já prova veiculação."""
    c = avaliar_trafego(spend=0.0, leads=7)
    assert c.ativo is True


def test_gasto_sem_lead_ainda_libera():
    """Campanha nova queimando verba sem converter é tráfego e precisa de relatório."""
    c = avaliar_trafego(spend=500.0, leads=0)
    assert c.ativo is True


def test_centavo_residual_nao_conta_como_trafego():
    """Conta de anúncio devolve resíduo de campanha encerrando; não é veiculação."""
    c = avaliar_trafego(spend=0.37, leads=0)
    assert c.ativo is False
    assert MIN_SPEND_BRL == 1.0


def test_nada_medido_libera_e_marca_como_nao_medido():
    c = avaliar_trafego(spend=None, leads=None)
    assert c.ativo is True
    assert c.medido is False
    assert 'não medido' in c.motivo


# ── Extrator do digest ───────────────────────────────────────────────────────

def _payload(*, meta=None, google=None):
    p = {}
    if meta is not None:
        p['traffic_metrics'] = {'dia_anterior': meta}
    if google is not None:
        p['operational_routines'] = {'google_funnel': google}
    return p


def test_digest_soma_meta_e_google():
    c = check_from_daily_check(_payload(
        meta={'spend': 13641.48, 'meta_leads': 2092},
        google={'total_spend': 2315.98, 'n_leads': 275},
    ))
    assert c.ativo is True
    assert c.spend == pytest.approx(13641.48 + 2315.98)
    assert c.leads == 2092 + 275


def test_digest_bloqueia_com_as_duas_plataformas_em_zero():
    c = check_from_daily_check(_payload(
        meta={'spend': 0.0, 'meta_leads': 0},
        google={'total_spend': 0.0, 'n_leads': 0},
    ))
    assert c.ativo is False


def test_digest_uma_plataforma_fora_nao_zera_a_outra():
    """Meta fora do ar (bloco ausente) + Google gastando = manda o relatório."""
    c = check_from_daily_check(_payload(google={'total_spend': 2315.98, 'n_leads': 275}))
    assert c.ativo is True
    assert c.medido is True
    assert c.spend == pytest.approx(2315.98)


def test_digest_payload_sem_bloco_de_trafego_libera():
    c = check_from_daily_check({})
    assert c.ativo is True
    assert c.medido is False


def test_digest_valor_lixo_conta_como_nao_medido():
    c = check_from_daily_check(_payload(meta={'spend': 'n/d', 'meta_leads': None}))
    assert c.ativo is True
    assert c.medido is False


# ── Extrator do relatório de criativo ────────────────────────────────────────

class _Rec:
    def __init__(self, source):
        self.utm_source = source


def test_conta_so_origem_paga():
    recs = [_Rec('facebook-ads'), _Rec('google-ads'), _Rec('organic'),
            _Rec(None), _Rec(''), _Rec('IG')]
    assert contar_leads_pagos(recs) == 3


def test_organico_sozinho_nao_e_trafego():
    """Entre lançamentos o orgânico continua pingando. Não tem custo nem criativo,
    então não pode manter o relatório de criativo no ar."""
    class _R:
        window = {'n_total': 84, 'n_pago': 0}
    c = check_from_utm_result(_R())
    assert c.ativo is False
    assert c.medido is True


def test_criativo_com_lead_pago_libera():
    class _R:
        window = {'n_total': 2231, 'n_pago': 2080}
    c = check_from_utm_result(_R())
    assert c.ativo is True
    assert c.leads == 2080


def test_criativo_sem_a_chave_libera():
    """Resultado antigo/mockado sem `n_pago` não pode fazer o relatório sumir."""
    class _R:
        window = {'n_total': 2231}
    c = check_from_utm_result(_R())
    assert c.ativo is True
    assert c.medido is False


def test_utm_quality_publica_n_pago_na_janela():
    """Contrato com o endpoint: `compute_utm_quality` precisa expor `n_pago`,
    senão a trava do relatório de criativo cai em 'não medido' pra sempre."""
    import inspect
    from src.monitoring import utm_quality
    src = inspect.getsource(utm_quality.compute_utm_quality)
    assert "'n_pago'" in src


def test_google_ads_esta_na_lista_de_pagas():
    """Google é canal pago próprio, não fallback de Lead nem orgânico."""
    assert 'google-ads' in PAID_SOURCES
    assert 'organic' not in PAID_SOURCES


# ── Kill-switch ──────────────────────────────────────────────────────────────

def test_trava_ligada_por_default():
    assert trava_habilitada({}) is True


@pytest.mark.parametrize('valor', ['0', 'false', 'FALSE', 'no', 'off'])
def test_env_desliga_a_trava(valor):
    assert trava_habilitada({'REPORTS_REQUIRE_TRAFFIC': valor}) is False


def test_env_qualquer_outro_valor_mantem_ligada():
    assert trava_habilitada({'REPORTS_REQUIRE_TRAFFIC': '1'}) is True
    assert trava_habilitada({'REPORTS_REQUIRE_TRAFFIC': 'sim'}) is True
