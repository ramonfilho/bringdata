"""Os três leitores que a máquina de relatório por LANÇAMENTO precisa, e os
contratos que impedem cada um de mudar o que já está no ar.

O que se trava aqui:

1. `read_ad_insights` tem a MESMA borda de janela do `read_ad_spend` (end
   EXCLUSIVO). Não é preciosismo: LF64 termina a captação em 17/08 e o LF65
   começa em 18/08, colados, então um dia de erro na borda mistura dois
   lançamentos inteiros.
2. `gasto_por_unidade` soma na unidade (campanha, criativo canônico) e o
   `gross_up` (imposto de 1,13 da mídia da Meta) multiplica SÓ o dinheiro:
   imposto não compra lead.
3. `calcula_historico(corte=...)` congela o relógio do histórico. Sem corte,
   comportamento de hoje, byte a byte (o refresh semanal depende dele).
4. `criativo_do_lead` resolve id numérico -> nome e canoniza, sem decidir
   plataforma.
5. `read_cadastros` só devolve as 3 UTMs novas quando pedido; o default é a
   saída de sempre, coluna por coluna.

Rodar: cd V2 && python3 -m pytest tests/test_leitores_por_lancamento.py -q
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src.data.ad_insights_reader import (  # noqa: E402
    _COLS, gasto_por_unidade, read_ad_insights,
)
from src.data.ad_spend_reader import read_ad_spend  # noqa: E402
from src.data.cadastro_records import _CAD_COLS, read_cadastros  # noqa: E402
from src.data.criativo_historico import (  # noqa: E402
    calcula_historico, criativo_do_lead, mapa_de_nomes,
)


class _Conn:
    """Conexão de mentira: guarda o SQL e os parâmetros, devolve linhas prontas."""

    def __init__(self, linhas=()):
        self._linhas = list(linhas)
        self.sqls = []
        self.params = []

    def run(self, sql, **kw):
        self.sqls.append(sql)
        self.params.append(kw)
        return self._linhas

    def close(self):
        pass


# ───────────────────────── 1. borda da janela ────────────────────────────────
def test_borda_igual_a_do_ad_spend_end_exclusivo():
    ci, cs = _Conn(), _Conn()
    read_ad_insights(date(2026, 8, 7), date(2026, 8, 18), conn=ci)
    read_ad_spend(date(2026, 8, 7), date(2026, 8, 18), conn=cs)
    assert "insight_date >= :s AND insight_date < :e" in ci.sqls[0]
    assert "spend_date >= :s AND spend_date < :e" in cs.sqls[0]
    assert ci.params[0] == cs.params[0] == {"cid": "devclub", "s": "2026-08-07",
                                            "e": "2026-08-18"}


def test_dia_do_end_nao_entra():
    """A captação do LF65 começa em 18/08, o dia seguinte ao fim do LF64: com end
    inclusivo o gasto do LF65 entraria no LF64."""
    ci = _Conn()
    read_ad_insights(date(2026, 8, 7), date(2026, 8, 18), conn=ci)
    assert "<= :e" not in ci.sqls[0], "end tem que ser EXCLUSIVO"


def test_sem_linha_devolve_dataframe_com_as_colunas():
    df = read_ad_insights(date(2026, 8, 7), date(2026, 8, 8), conn=_Conn([]))
    assert list(df.columns) == list(_COLS)
    assert df.empty


def test_colunas_do_shape_canonico():
    assert list(_COLS) == ["ad_id", "ad_name", "campaign_id", "adset_id",
                           "adset_name", "insight_date", "spend", "leads",
                           "impressions", "clicks"]


# ───────────────────── 2. gasto por unidade (campanha, criativo) ─────────────
def _df(linhas):
    return pd.DataFrame(linhas, columns=list(_COLS))


def _linha(ad_id, ad_name, campaign_id, spend, leads=0):
    return [ad_id, ad_name, campaign_id, "cj1", "conjunto", date(2026, 8, 8),
            spend, leads, 0, 0]


def test_unidade_e_campanha_x_criativo_canonico():
    """Meta sem carimbo e Google com `[G] ` são o MESMO criativo (PR #237)."""
    u = gasto_por_unidade(_df([
        _linha("1", "DEV-AD0150", "120100", 100.0, 10),
        _linha("2", "[G] dev-ad0150", "120100", 50.0, 5),
        _linha("3", "DEV-AD0150", "120200", 25.0, 2),
    ]))
    assert set(u) == {("120100", "dev-ad0150"), ("120200", "dev-ad0150")}
    a = u[("120100", "dev-ad0150")]
    assert a["spend"] == 150.0 and a["leads_gerenciador"] == 15
    assert a["ad_ids"] == {"1", "2"}, "cópia é o mesmo anúncio, ids somam na unidade"


def test_campaign_id_numerico_vira_string():
    u = gasto_por_unidade(_df([_linha("1", "AD", 120100, 10.0)]))
    assert ("120100", "ad") in u, "chave da campanha é sempre texto"


def test_gross_up_so_no_dinheiro():
    u = gasto_por_unidade(_df([_linha("1", "AD", "c", 100.0, 10)]), gross_up=1.13)
    v = u[("c", "ad")]
    assert round(v["spend"], 2) == 113.0
    assert v["leads_gerenciador"] == 10, "imposto não compra lead"


def test_chave_criativo_injetavel():
    u = gasto_por_unidade(_df([_linha("1", "AD-X", "c", 7.0)]),
                          chave_criativo=lambda n: "fixo")
    assert list(u) == [("c", "fixo")]


def test_df_vazio_devolve_dict_vazio():
    assert gasto_por_unidade(_df([])) == {}
    assert gasto_por_unidade(None) == {}


def test_nome_nulo_nao_vira_a_gaveta_nan():
    u = gasto_por_unidade(_df([_linha("1", None, None, 5.0)]))
    assert list(u) == [("", "")], "None não pode virar a string 'nan'"


# ─────────────────── 3. corte point-in-time do histórico ─────────────────────
def test_sem_corte_e_o_relogio_de_hoje():
    c = _Conn([])   # calendário vazio: para no primeiro SELECT, que é o que interessa
    calcula_historico(c)
    assert "vendas_end < CURRENT_DATE - 2" in c.sqls[0]
    assert "corte" not in c.params[0]


def test_com_corte_o_relogio_congela_na_data():
    """O DEV21 fechou vendas em 16/08 e desde 22/08 já é 'lançamento fechado'.
    O backtest do LF64 (captação começa em 07/08) não pode enxergá-lo."""
    c = _Conn([])
    calcula_historico(c, corte=date(2026, 8, 7))
    assert "vendas_end < :corte" in c.sqls[0]
    assert "CURRENT_DATE" not in c.sqls[0]
    assert c.params[0]["corte"] == date(2026, 8, 7)


def test_corte_aceita_texto_e_chega_como_data():
    c = _Conn([])
    calcula_historico(c, corte="2026-08-07")
    assert c.params[0]["corte"] == date(2026, 8, 7), "date < text quebra no Postgres"


# ─────────────────────────── 4. mapa e criativo do lead ──────────────────────
def test_mapa_de_nomes_normaliza_espaco_e_filtra_cliente():
    c = _Conn([["991", "DEV-AD0150   vid  captação"]])
    m = mapa_de_nomes(c, client_id="devclub")
    assert m == {"991": "DEV-AD0150 vid captação"}
    assert "client_id = :c" in c.sqls[0] and c.params[0]["c"] == "devclub"


def test_mapa_de_nomes_degrada_pra_vazio():
    class _Quebra:
        def run(self, *a, **k):
            raise RuntimeError("relation does not exist")

    assert mapa_de_nomes(_Quebra()) == {}


def test_criativo_do_lead_resolve_id_e_canoniza():
    mapa = {"819975593994": "[G] DEV-AD0150 vid"}
    assert criativo_do_lead("819975593994", mapa) == "dev-ad0150 vid"


def test_criativo_do_lead_id_desconhecido_fica_o_proprio_id():
    assert criativo_do_lead("819975593994", {}) == "819975593994"


def test_criativo_do_lead_nome_passa_pela_canonica():
    assert criativo_do_lead("  DEV-AD0140  vid ", {}) == "dev-ad0140 vid"


def test_criativo_do_lead_vazio_e_none():
    assert criativo_do_lead(None, {}) == ""
    assert criativo_do_lead("   ", {}) == ""


def test_criativo_do_lead_numero_curto_nao_e_id():
    """Menos de 6 dígitos não é ad_id da Meta/Google: fica como nome mesmo."""
    assert criativo_do_lead("12345", {"12345": "NAO USAR"}) == "12345"


# ───────────────────────── 5. UTMs extras do cadastro ────────────────────────
class _ConnCad(_Conn):
    """Devolve linhas no formato da UTMTracking; o número de colunas depende do
    SELECT, então o teste passa a linha já do tamanho certo."""


def test_read_cadastros_default_e_a_saida_de_sempre():
    c = _ConnCad([["a@x.com", "11999998888", "camp", "facebook-ads", 10]])
    df = read_cadastros(c, date(2026, 7, 21), date(2026, 8, 3))
    assert list(df.columns) == _CAD_COLS
    assert "u.content" not in c.sqls[0] and "u.term" not in c.sqls[0]


def test_read_cadastros_com_utms_extras():
    c = _ConnCad([["a@x.com", "11999998888", "camp", "google-ads", 10,
                   "819975593994", "cpc", "1234567890"]])
    df = read_cadastros(c, date(2026, 7, 21), date(2026, 8, 3), utms_extras=True)
    assert list(df.columns) == _CAD_COLS + ["utm_content", "utm_medium", "utm_term"]
    assert df.iloc[0]["utm_term"] == "1234567890", "campanha do Google viaja no term"
    assert "u.content AS content" in c.sqls[0]


def test_utms_extras_vem_do_mesmo_toque_do_last_touch():
    """As três UTMs têm que ser do toque VENCEDOR, nunca costuradas de toques
    diferentes: o lead que trocou de anúncio no meio da janela conta pelo último."""
    c = _ConnCad([
        ["a@x.com", "11", "camp_antiga", "google-ads", 10, "id_antigo", "cpc", "t1"],
        ["a@x.com", "11", "camp_nova", "google-ads", 20, "id_novo", "cpc", "t2"],
    ])
    df = read_cadastros(c, date(2026, 7, 21), date(2026, 8, 3), utms_extras=True)
    assert len(df) == 1
    linha = df.iloc[0]
    assert linha["utm_campaign"] == "camp_nova"
    assert linha["utm_content"] == "id_novo" and linha["utm_term"] == "t2"


def test_read_cadastros_vazio_respeita_a_bandeira():
    assert list(read_cadastros(_ConnCad([]), date(2026, 7, 21),
                               date(2026, 8, 3)).columns) == _CAD_COLS
    assert list(read_cadastros(_ConnCad([]), date(2026, 7, 21), date(2026, 8, 3),
                               utms_extras=True).columns) == \
        _CAD_COLS + ["utm_content", "utm_medium", "utm_term"]
