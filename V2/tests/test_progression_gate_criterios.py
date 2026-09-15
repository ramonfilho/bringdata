"""Critérios do progression_gate dizem o que o código faz.

Em 15/09/2026 dois achados no primeiro dia da pipeline no GitHub Actions:
1. `min_hours_observed` era a janela de consulta (quantas horas para trás), não espera
   mínima, e `min_days_observed: 7` no estágio 100 não era lido por linha nenhuma. Quem
   lia o arquivo achava que 100% levava uma semana.
2. O daily-check devolve taxas em porcentagem (66.6) e os limiares são fração (0.90); a
   comparação `66.6 < 0.90` nunca é verdadeira, então os critérios de CAPI e Meta nunca
   seguraram nada.
"""
import sys
from pathlib import Path

_V2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2 / "scripts"))

import progression_gate as pg  # noqa: E402

_FEAT_OK = {'ok': True, 'status': 'OK', 'total_batches': 3}
_DAILY_OK = {'ok': True, 'capi_sent_rate': 0.95, 'meta_acceptance_rate': 0.97,
             'decil_zero_events': [], 'd10_divergence_pp': 0.5}


def test_criterios_nao_carregam_espera_minima_morta():
    for estagio, c in pg.STAGE_CRITERIA.items():
        assert 'min_hours_observed' not in c and 'min_days_observed' not in c, estagio
        assert isinstance(c['janela_horas'], int) and c['janela_horas'] >= 1, estagio


def test_fracao_normaliza_porcentagem_do_daily_check():
    assert pg._fracao(66.63) == 0.6663
    assert pg._fracao(0.9) == 0.9
    assert pg._fracao(100) == 1.0
    assert pg._fracao(1.0) == 1.0
    assert pg._fracao(None) is None


def test_taxa_da_meta_em_porcentagem_baixa_segura_a_promocao():
    # antes do conserto, 60.0 (60%) passava por 0.85 porque 60.0 < 0.85 é falso
    daily = dict(_DAILY_OK, meta_acceptance_rate=pg._fracao(60.0))
    r = pg.decide(10, 50, _FEAT_OK, daily, pg.STAGE_CRITERIA[50])
    assert r.verdict == 'HOLD'
    assert any('acceptance_rate 60.00% < 85.00%' in m for m in r.reasons), r.reasons


def test_capi_send_rate_desligado_nao_segura():
    daily = dict(_DAILY_OK, capi_sent_rate=pg._fracao(66.6))
    for estagio in (50, 100):
        r = pg.decide(estagio // 5, estagio, _FEAT_OK, daily, pg.STAGE_CRITERIA[estagio])
        assert r.verdict == 'PROMOTE', (estagio, r.reasons)


def test_sem_lote_na_janela_e_hold_nao_rollback():
    r = pg.decide(10, 50, dict(_FEAT_OK, total_batches=0), _DAILY_OK, pg.STAGE_CRITERIA[50])
    assert r.verdict == 'HOLD' and r.exit_code == 1


def test_feature_report_error_e_rollback():
    r = pg.decide(10, 50, dict(_FEAT_OK, status='ERROR'), _DAILY_OK, pg.STAGE_CRITERIA[50])
    assert r.verdict == 'ROLLBACK' and r.exit_code == 2


def test_decil_sem_evento_capi_e_rollback():
    r = pg.decide(50, 100, _FEAT_OK, dict(_DAILY_OK, decil_zero_events=['D3']), pg.STAGE_CRITERIA[100])
    assert r.verdict == 'ROLLBACK'


def test_tudo_bem_promove():
    for de, para in ((10, 50), (50, 100)):
        r = pg.decide(de, para, _FEAT_OK, _DAILY_OK, pg.STAGE_CRITERIA[para])
        assert r.verdict == 'PROMOTE' and r.exit_code == 0, (de, para, r.reasons)
