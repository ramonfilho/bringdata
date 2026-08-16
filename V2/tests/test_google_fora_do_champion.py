"""Lead do Google/orgânico não pode ser atribuído ao CHAMPION por default.

Contexto (varredura de 16/08/2026, aprovação do Ramon): quatro lugares davam
o balde do Champion a leads que nenhum modelo roteou por campanha:

1. Relatório de criativos: ~6,5k leads google/orgânico por mês na coluna do
   Champion (default do classificador quando não há variante nem match).
2. Contador Champion×Challenger do DM: ~217 leads/dia não-Meta inflando o
   Champion (a variante default é o pega-tudo).
3. Tabela de campanhas vs TOP5: a pseudo-campanha 'devlf' (100% google,
   938 emails/7d) julgada como campanha da Meta na régua do champion.
4. Divisão por variante da previsão: variant vazio = Champion, google incluso.

Desenho: fora da Meta → balde/segmento PRÓPRIO ('fora_do_ab'/'fora_meta') ou
filtro de fonte. O ranking de criativos CONTINUA incluindo google (deliberado,
rotulado pelo source_hint) — só a atribuição por modelo sai.

Rodável sem pytest: python tests/test_google_fora_do_champion.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.monitoring.utm_quality import (
    FORA_DO_AB,
    _aggregate,
    _classify_variant_from_record,
    _combined_avg_decil,
)


class _AbCfgFake:
    """match_variant sempre None (lead sem etiqueta); variants com 2 nomes."""
    variants = {'challenger_abr28': object(), 'challenger_jul_24': object()}

    def match_variant(self, utms, event_source_url=''):
        return None


def _rec(variant=None, source='facebook-ads', decil=5, content='ad-x'):
    return SimpleNamespace(variant=variant, utm_source=source, utm_medium='m',
                          utm_campaign='c', utm_content=content, utm_term='t',
                          utm_url='', score=0.4, decil=decil)


# ─────────── 1. relatório de criativos ───────────

def test_google_sem_variante_vai_pro_balde_proprio():
    cfg = _AbCfgFake()
    v = _classify_variant_from_record(_rec(source='google-ads'), cfg,
                                      'challenger_abr28', 'challenger_jul_24')
    assert v == FORA_DO_AB
    v2 = _classify_variant_from_record(_rec(source='manychat'), cfg,
                                       'challenger_abr28', 'challenger_jul_24')
    assert v2 == FORA_DO_AB


def test_meta_sem_match_continua_no_default_champion():
    """Não-enfraquecimento: lead da META sem etiqueta segue no default do
    champion (o pega-tudo scoreia mesmo) — só o não-Meta sai."""
    cfg = _AbCfgFake()
    v = _classify_variant_from_record(_rec(source='facebook-ads'), cfg,
                                      'challenger_abr28', 'challenger_jul_24')
    assert v == 'challenger_abr28'


def test_variante_gravada_no_ledger_sempre_vence():
    cfg = _AbCfgFake()
    v = _classify_variant_from_record(
        _rec(variant='challenger_jul_24', source='google-ads'), cfg,
        'challenger_abr28', 'challenger_jul_24')
    assert v == 'challenger_jul_24'


def test_criativo_google_continua_no_ranking_via_combinado():
    """O criativo google não some do relatório: entra no n e na média
    combinada pelo balde próprio; só as colunas Champion/Challenger limpam."""
    cfg = _AbCfgFake()
    records = [_rec(source='google-ads', decil=8, content='ad-g'),
               _rec(source='google-ads', decil=6, content='ad-g'),
               _rec(source='facebook-ads', decil=4, content='ad-g')]
    agg = _aggregate(records, 'ad', cfg, 'challenger_abr28', 'challenger_jul_24')
    b = agg['ad-g']
    assert b[FORA_DO_AB]['n'] == 2
    assert b['challenger_abr28']['n'] == 1  # o lead Meta
    media = _combined_avg_decil(b.get('challenger_abr28'),
                                b.get('challenger_jul_24'), b.get(FORA_DO_AB))
    assert media == pytest.approx((8 + 6 + 4) / 3)


# ─────────── 3. tabela de campanhas vs TOP5 ───────────

class _ConexaoQueRegistra:
    def __init__(self):
        self.chamadas = []

    def run(self, sql, **params):
        self.chamadas.append((sql, params))
        return []


def test_nivel_campanha_filtra_fontes_meta():
    from src.data.scores_historicos import challenger_quality_by_utm
    conn = _ConexaoQueRegistra()
    challenger_quality_by_utm(
        'LF64', level='campaign', challenger_run_id='run-x',
        win_start='2026-08-01', win_end='2026-08-10', pin_lf=False, conn=conn,
        meta_sources=['facebook-ads', 'fb'])
    sql, params = conn.chamadas[0]
    assert 'utm_source IN' in sql, \
        "nível campanha precisa filtrar fonte — a pseudo-campanha 'devlf' é 100% google"
    assert params['msrc0'] == 'facebook-ads' and params['msrc1'] == 'fb'


def test_sem_meta_sources_nada_muda():
    from src.data.scores_historicos import challenger_quality_by_utm
    conn = _ConexaoQueRegistra()
    challenger_quality_by_utm(
        'LF64', level='creative', challenger_run_id='run-x',
        win_start='2026-08-01', win_end='2026-08-10', pin_lf=False, conn=conn)
    sql, _ = conn.chamadas[0]
    assert 'utm_source IN' not in sql, \
        "nível criativo inclui google de propósito (source_hint rotula)"


def test_top5_passa_o_filtro_so_no_nivel_campanha():
    """Anti-deriva: o montador do vs-TOP5 tem que pedir o filtro pro nível
    campaign e NÃO pedir pro creative."""
    src = (Path(__file__).resolve().parent.parent /
           'src' / 'monitoring' / 'utm_quality.py').read_text()
    assert "meta_sources=(sorted(_META_SOURCES) if level == 'campaign' else None)" in src


# ─────────── 2 e 4. contador do DM e split da previsão (anti-deriva) ───────────

def test_contador_ab_do_dm_filtra_allowlist():
    """As DUAS queries por variante (scored e capi) carregam o filtro que
    tira google/orgânico da conta do A/B."""
    src = (Path(__file__).resolve().parent.parent /
           'src' / 'monitoring' / 'orchestrator.py').read_text()
    assert src.count("base_status != 'skipped_allowlist'") >= 2, \
        "o contador leads_scored perdeu o filtro de canal (tinha só o irmão capi)"


def test_split_da_previsao_separa_fora_meta():
    src = (Path(__file__).resolve().parent.parent / 'api' / 'app.py').read_text()
    assert "_vk = 'fora_meta'" in src, \
        "o split por variante da previsão voltou a rotular google como Champion"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
