"""Testes da tabela-fato do lançamento (lancamento_unidades).

Tudo sintético, zero banco. O que está travado aqui, e por quê:

  1. a GUARDA DE CANAL: unidade do Google nunca recebe gasto da Meta (medido no
     DEV-AD0138: a fusão derrubava o CPL em 52% — parecia barato, era mistura);
  2. a REGRA DE OURO: sem venda ingerida, dinheiro é None, nunca 0;
  3. os cinco ESTADOS do lançamento com datas fixas;
  4. o rótulo por MODELO (identidade estável), nunca por papel;
  5. os três julgamentos novos do teto (meta com tolerância, lucro > R$ 1.000,
     deu mais do que gastou) e o modo previsão (sem venda → None).
"""
from datetime import date

import pandas as pd
import pytest

from src.validation import lancamento_unidades as L


# ───────────────────────── fixtures sintéticas ───────────────────────────────
class _Teto:
    def __init__(self, valor=None):
        self.ok = valor is not None
        self.valor = valor
        self.motivo = None if self.ok else "sem_base"


def _cfg():
    """ArmConfig mínimo: uma tag de modelo, um display name."""
    from src.core.ab_arm import ArmConfig
    return ArmConfig(
        variant_roles=(),
        tag_variants=(("ABR_28_TOP30", "challenger_abr28"), ("HQLB", "challenger_abr28")),
        display_names=(("challenger_abr28", "abr_28"),),
    )


def _neg(tem_venda=False):
    """Cadastros já casados: 3 Meta (2 da camp 120..1, 1 da 120..2), 2 Google, 1 orgânico."""
    rows = [
        # email, utm_source, utm_campaign, utm_content, utm_term, converted, sale_value, sale_origin
        ("a@x.com", "facebook-ads", "CAP | X|12024500000000001", "DEV-AD0100", None, tem_venda, 2000.0, "guru"),
        ("b@x.com", "facebook-ads", "CAP | X|12024500000000001", "DEV-AD0100", None, False, None, None),
        ("c@x.com", "facebook-ads", "CAP | Y|12024500000000002", "DEV-AD0200", None, False, None, None),
        ("d@x.com", "google-ads", "devlf", "9999990001", "22334455667--1--1", False, None, None),
        ("e@x.com", "google-ads", "devlf", "9999990001", "22334455667--1--1", tem_venda, 1000.0, "tmb"),
        ("f@x.com", "whatsapp", None, "2907", None, False, None, None),
    ]
    df = pd.DataFrame(rows, columns=["email", "utm_source", "utm_campaign",
                                     "utm_content", "utm_term", "converted",
                                     "sale_value", "sale_origin"])
    return L.prepara_leads(df, {"9999990001": "DEV-AD0300"})


def _spend():
    return pd.DataFrame([
        {"platform": "meta", "campaign_id": "12024500000000001", "campaign_name": "CAP | ABR_28_TOP30 | X", "spend": 100.0},
        {"platform": "meta", "campaign_id": "12024500000000002", "campaign_name": "CAP | FRIA | Y", "spend": 50.0},
        {"platform": "google", "campaign_id": "22334455667", "campaign_name": "DEVLF | CAP", "spend": 30.0},
    ])


def _por_unidade():
    return [
        # unidade Meta com gasto casado
        dict(campanha="CAP | X|12024500000000001", criativo="dev-ad0100", n=10,
             pct=20.0, teto=_Teto(8.0), n_hist=500, lift_criativo=1.2,
             peso=0.2, compradores_hist=5, esperados=4.2),
        # unidade Meta SEM par no gerenciador
        dict(campanha="CAP | Y|12024500000000002", criativo="dev-ad0200", n=4,
             pct=25.0, teto=_Teto(6.0), n_hist=0, lift_criativo=None,
             peso=0.0, compradores_hist=0, esperados=0.0),
        # unidade do GOOGLE (campanha devlf, criativo já resolvido pra nome)
        dict(campanha="devlf", criativo="dev-ad0300", n=5,
             pct=40.0, teto=_Teto(9.0), n_hist=100, lift_criativo=1.5,
             peso=0.05, compradores_hist=3, esperados=2.0),
    ]


def _gasto_unid():
    return {
        ("12024500000000001", "dev-ad0100"): {"spend": 100.0, "leads_gerenciador": 12, "ad_ids": {"a1"}},
        # armadilha da guarda de canal: um gasto Meta gravado com o MESMO nome
        # do criativo do Google — não pode vazar pra unidade do Google
        ("12024500000000009", "dev-ad0300"): {"spend": 77.0, "leads_gerenciador": 9, "ad_ids": {"a9"}},
    }


# ───────────────────────── estados ───────────────────────────────────────────
@pytest.mark.parametrize("as_of,esperado", [
    (date(2026, 8, 10), "captacao_aberta"),
    (date(2026, 8, 17), "captacao_aberta"),          # último dia ainda é captação
    (date(2026, 8, 20), "captacao_fechada_venda_nao_aberta"),
    (date(2026, 8, 24), "venda_aberta"),
    (date(2026, 8, 30), "venda_aberta"),             # último dia de carrinho
    (date(2026, 9, 5), "venda_fechada_imatura"),
    (date(2026, 11, 1), "maduro"),
])
def test_estados_do_lf64(as_of, esperado):
    got = L.estado_do_lancamento(date(2026, 8, 7), date(2026, 8, 17),
                                 date(2026, 8, 24), date(2026, 8, 30),
                                 as_of=as_of, sales_max=date(2026, 12, 1))
    assert got == esperado


def test_maduro_rebaixado_quando_ingestao_atrasa():
    """60 dias passaram mas a última venda no banco é ANTERIOR ao fim do carrinho:
    o número está subcontado, então o estado segura em imaturo."""
    got = L.estado_do_lancamento(date(2026, 8, 7), date(2026, 8, 17),
                                 date(2026, 8, 24), date(2026, 8, 30),
                                 as_of=date(2026, 11, 1), sales_max=date(2026, 8, 26))
    assert got == "venda_fechada_imatura"


# ───────────────────────── rótulo por modelo ─────────────────────────────────
def test_rotulo_google_ignora_o_nome():
    """Campanha do Google passa no is_captacao — o canal decide primeiro."""
    assert L.rotulo_do_modelo("DEVLF | CAP | Cold", "google", _cfg()) == "Google Ads"


def test_rotulo_meta_por_tag_e_identidade_estavel():
    cfg = _cfg()
    # dois batismos da mesma campanha de modelo → mesmo rótulo
    assert L.rotulo_do_modelo("CAP | ABR_28_TOP30 | X", "meta", cfg) == "abr_28"
    assert L.rotulo_do_modelo("CAP | HQLB | X", "meta", cfg) == "abr_28"


def test_rotulo_meta_sem_tag_e_lead_padrao():
    assert L.rotulo_do_modelo("CAP | FRIA | Y", "meta", _cfg()) == L.ROTULO_LEAD_PADRAO


# ───────────────────────── prepara_leads ─────────────────────────────────────
def test_prepara_leads_chaves():
    neg = _neg()
    meta = neg[neg["canal"] == "meta"]
    assert set(meta["cid"]) == {"12024500000000001", "12024500000000002"}
    goog = neg[neg["canal"] == "google"]
    # cid do Google vem do utm_term (ValueTrack), nunca do utm_campaign
    assert set(goog["cid"]) == {"22334455667"}
    # id numérico do criativo resolvido pra nome canônico via mapa
    assert set(goog["criativo"]) == {"dev-ad0300"}
    # orgânico: sem cid, criativo curto NÃO vira anúncio (o '2907' do grupo)
    org = neg[neg["canal"] == "organic"]
    assert list(org["cid"]) == [""] and list(org["criativo"]) == ["2907"]
    # nenhum lead descartado
    assert len(neg) == 6


# ───────────────────────── tabela de campanhas (item a) ──────────────────────
def test_tabela_campanhas_grao_e_grossup():
    t = L.tabela_campanhas(_neg(), _spend(), haircut=0.5, meta_gross_up=1.13,
                           tem_venda=False, cfg=_cfg())
    # 2 campanhas Meta + Google agregado + orgânico
    assert len(t) == 4
    m1 = t[t["cid"] == "12024500000000001"].iloc[0]
    assert m1["gasto"] == pytest.approx(113.0)          # imposto só na Meta
    assert m1["leads"] == 2 and m1["modelo"] == "abr_28"
    g = t[t["plataforma"] == "google"].iloc[0]
    assert g["gasto"] == pytest.approx(30.0)            # Google sem gross-up
    assert g["leads"] == 2
    org = t[t["modelo"] == L.ROTULO_ORGANICO].iloc[0]
    assert org["leads"] == 1 and pd.isna(org["gasto"])


def test_tabela_campanhas_sem_venda_dinheiro_none():
    """Regra de ouro: carrinho sem venda ingerida → dinheiro None, nunca 0."""
    t = L.tabela_campanhas(_neg(), _spend(), haircut=0.5, tem_venda=False, cfg=_cfg())
    for col in ("vendas", "faturamento", "roas", "lucro"):
        assert t[col].isna().all(), f"{col} deveria ser toda None sem venda"
    # gasto/leads/CPL existem desde a captação — continuam preenchidos
    assert t[t["cid"] == "12024500000000001"]["cpl"].notna().all()


def test_tabela_campanhas_com_venda():
    t = L.tabela_campanhas(_neg(tem_venda=True), _spend(), haircut=0.5,
                           tem_venda=True, cfg=_cfg())
    m1 = t[t["cid"] == "12024500000000001"].iloc[0]
    assert m1["vendas"] == 1 and m1["faturamento"] == pytest.approx(2000.0)  # guru=cartão
    g = t[t["plataforma"] == "google"].iloc[0]
    assert g["faturamento"] == pytest.approx(500.0)     # tmb=boleto → haircut 0,5


# ───────────────────────── tabela de unidades ────────────────────────────────
def test_unidades_join_e_guarda_de_canal():
    u = L.tabela_unidades(_neg(), _por_unidade(), _gasto_unid(),
                          haircut=0.5, tem_venda=False)
    assert len(u) == 3
    a = u[u["criativo"] == "dev-ad0100"].iloc[0]
    assert a["gasto"] == pytest.approx(100.0)
    assert a["cpl"] == pytest.approx(10.0)
    assert a["folga"] == pytest.approx(-2.0) and a["dentro_do_teto"] == False  # noqa: E712
    assert a["leads_gerenciador"] == 12 and a["cadastros"] == 2
    # GUARDA DE CANAL: a unidade do Google NÃO herda o gasto Meta homônimo
    g = u[u["criativo"] == "dev-ad0300"].iloc[0]
    assert g["canal"] == "google"
    assert pd.isna(g["gasto"]) and pd.isna(g["cpl"]) and pd.isna(g["folga"])
    assert g["motivo_sem_gasto"] == "google_sem_gasto_por_criativo"
    assert pd.isna(g["dentro_do_teto"])
    # unidade Meta sem par no gerenciador: motivo nomeado, nunca silêncio
    b = u[u["criativo"] == "dev-ad0200"].iloc[0]
    assert b["motivo_sem_gasto"] == "sem_par_no_gerenciador"


def test_unidades_sem_venda_dinheiro_none():
    u = L.tabela_unidades(_neg(), _por_unidade(), _gasto_unid(),
                          haircut=0.5, tem_venda=False)
    for col in ("vendas", "faturamento", "roas", "lucro", "conversao"):
        assert u[col].isna().all()


def test_unidades_com_venda():
    u = L.tabela_unidades(_neg(tem_venda=True), _por_unidade(), _gasto_unid(),
                          haircut=0.5, tem_venda=True)
    a = u[u["criativo"] == "dev-ad0100"].iloc[0]
    assert a["vendas"] == 1 and a["faturamento"] == pytest.approx(2000.0)
    assert a["roas"] == pytest.approx(20.0)
    assert a["conversao"] == pytest.approx(0.5)


# ───────────────────────── julgamento do teto (item c) ───────────────────────
def _unid_julgaveis(com_dinheiro: bool):
    base = [
        # dentro do teto
        dict(dentro_do_teto=True, gasto=100.0, leads_ledger=50, vendas=2,
             faturamento=400.0, roas=4.0, lucro=300.0),
        dict(dentro_do_teto=True, gasto=100.0, leads_ledger=40, vendas=1,
             faturamento=197.0, roas=1.97, lucro=97.0),
        # acima do teto
        dict(dentro_do_teto=False, gasto=200.0, leads_ledger=30, vendas=1,
             faturamento=210.0, roas=1.05, lucro=10.0),
        dict(dentro_do_teto=False, gasto=100.0, leads_ledger=20, vendas=0,
             faturamento=0.0, roas=0.0, lucro=-100.0),
        # sem teto (Google sem gasto) — fica fora do julgamento, contada à parte
        dict(dentro_do_teto=None, gasto=None, leads_ledger=10, vendas=None,
             faturamento=None, roas=None, lucro=None),
    ]
    if not com_dinheiro:
        for r in base:
            for c in ("vendas", "faturamento", "roas", "lucro"):
                r[c] = None
    return pd.DataFrame(base)


def test_julga_modo_previsao_sem_venda():
    j = L.julga_dentro_vs_acima(_unid_julgaveis(com_dinheiro=False))
    assert j["julgaveis"] == 4 and j["sem_julgamento"] == 1
    assert j["dentro"]["n"] == 2 and j["acima"]["n"] == 2
    assert j["dentro"]["gasto"] == pytest.approx(200.0)
    # nada de dinheiro fabricado
    for lado in ("dentro", "acima"):
        for campo in ("vendas", "faturamento", "roas_ponderado", "lucro",
                      "bateu_meta", "lucro_acima_1000", "roas_positivo"):
            assert j[lado][campo] is None
    assert j["fisher_p"] is None and j["mannwhitney_p"] is None


def test_julga_com_venda_e_os_tres_cortes():
    j = L.julga_dentro_vs_acima(_unid_julgaveis(com_dinheiro=True))
    d, a = j["dentro"], j["acima"]
    # tolerância de 2%: o ROAS 1,97 conta como meta batida (decisão de 24/08)
    assert d["bateu_meta"] == 2
    assert a["bateu_meta"] == 0
    # lucro substancial: só o de R$ 300 passa de R$ 1.000? não — nenhum passa
    assert d["lucro_acima_1000"] == 0 and a["lucro_acima_1000"] == 0
    # deu mais do que gastou (lucro > 0)
    assert d["roas_positivo"] == 2 and a["roas_positivo"] == 1
    assert d["roas_ponderado"] == pytest.approx(597.0 / 200.0)
    assert j["fisher_p"] is not None and 0.0 <= j["fisher_p"] <= 1.0
    # A coluna dentro_do_teto tem True/False/None (dtype object) de propósito:
    # o Mann-Whitney precisa sobreviver a isso (quebrou na rodada real do LF64).
    assert j["mannwhitney_p"] is not None and 0.0 <= j["mannwhitney_p"] <= 1.0


def test_julga_tolerancia_zero_derruba_o_197():
    j = L.julga_dentro_vs_acima(_unid_julgaveis(com_dinheiro=True),
                                tolerancia_meta=0.0)
    assert j["dentro"]["bateu_meta"] == 1


# ───────────────────────── criativos por tipo (item b) ───────────────────────
def test_criativos_por_tipo():
    neg = _neg()
    camp = L.tabela_campanhas(neg, _spend(), haircut=0.5, tem_venda=False, cfg=_cfg())
    u = L.tabela_unidades(neg, _por_unidade(), _gasto_unid(),
                          haircut=0.5, tem_venda=False)
    b = L.criativos_por_tipo(u, camp)
    # o criativo da campanha abr_28 herda o rótulo do MODELO, não do papel
    assert set(b["modelo"]) == {"abr_28", L.ROTULO_LEAD_PADRAO, L.ROTULO_GOOGLE}
    linha = b[(b["modelo"] == "abr_28") & (b["criativo"] == "dev-ad0100")].iloc[0]
    assert linha["gasto"] == pytest.approx(100.0)
    assert linha["leads_ledger"] == 10
    # sem venda: dinheiro None mesmo agregado (sum com min_count=1)
    assert pd.isna(linha["vendas"]) and pd.isna(linha["faturamento"])


# ───────────────────────── linha "Não está na base" ──────────────────────────
def test_linha_naobase():
    """Venda do lançamento sem cadastro casado vira linha própria: leads=0,
    gasto/CPL/ROAS/lucro None (nunca 0), boleto com haircut."""
    nb = pd.DataFrame([
        {"sale_date": "2026-08-24", "sale_value": 2000.0, "origem": "guru"},
        {"sale_date": "2026-08-24", "sale_value": 1000.0, "origem": "tmb"},
    ])
    r = L.linha_naobase(nb, haircut=0.5)
    assert r["vendas"] == 2 and r["leads"] == 0
    assert r["faturamento"] == pytest.approx(2500.0)  # cartão + boleto×0,5
    assert r["gasto"] is None and r["roas"] is None and r["lucro"] is None
    assert L.linha_naobase(nb.iloc[0:0], haircut=0.5) is None


# ───────────────────────── temperatura (quente/frio) ─────────────────────────
def test_temperatura_da_campanha():
    from src.core.ab_arm import (TEMPERATURA_SEM_PUBLICO,
                                 temperatura_da_campanha as T)
    assert T("DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1") == "frio"
    # formato de colchetes do gestor (09/08) passa pela MESMA normalização
    assert T("[17][DEVLF][CAP][LEADS][SITE][QUENTE][X]|12345") == "quente"
    # etiqueta de modelo NÃO apaga o público: quente com HQLB continua quente
    assert T("DEVLF | CAP | QUENTE | FASE 04 | LEADHQLB") == "quente"
    assert T("CAP | FRIA | Y") == "frio"          # variante feminina
    assert T("CAP | ABR_28_TOP30 | X") == TEMPERATURA_SEM_PUBLICO
    assert T(None) == TEMPERATURA_SEM_PUBLICO


def test_tabela_campanhas_tem_temperatura():
    from src.core.ab_arm import TEMPERATURA_SEM_PUBLICO
    t = L.tabela_campanhas(_neg(), _spend(), haircut=0.5, tem_venda=False, cfg=_cfg())
    m2 = t[t["cid"] == "12024500000000002"].iloc[0]   # "CAP | FRIA | Y"
    assert m2["temperatura"] == "frio"
    m1 = t[t["cid"] == "12024500000000001"].iloc[0]   # sem público no nome
    assert m1["temperatura"] == TEMPERATURA_SEM_PUBLICO
    # temperatura é conceito de campanha da META: Google e orgânico saem None
    g = t[t["plataforma"] == "google"].iloc[0]
    assert g["temperatura"] is None


# ───────────────────────── separação por temperatura ─────────────────────────
def _ledger_temperatura():
    return pd.DataFrame({
        "utm_campaign": ["A | FRIO |1"] * 4 + ["A | QUENTE |2"] * 4,
        "decil": [10, 9, 2, 1, 10, 9, 2, 1],
        "converted": [True, False, False, False, False, False, True, False],
    })


def test_separacao_por_temperatura_com_venda():
    s = {r["temperatura"]: r
         for r in L.separacao_por_temperatura(_ledger_temperatura(), tem_venda=True)}
    frio = s["frio"]
    assert frio["leads"] == 4 and frio["leads_topo"] == 2
    assert frio["taxa_topo"] == pytest.approx(0.5)
    assert frio["taxa_base"] == pytest.approx(0.0)
    assert frio["lift"] is None                     # base zerada: nada fabricado
    quente = s["quente"]
    assert quente["taxa_topo"] == pytest.approx(0.0)
    assert quente["taxa_base"] == pytest.approx(0.5)
    assert quente["lift"] == pytest.approx(0.0)


def test_separacao_por_temperatura_sem_venda_e_vazio():
    s = L.separacao_por_temperatura(_ledger_temperatura(), tem_venda=False)
    assert s and all(r["lift"] is None and r["taxa_topo"] is None for r in s)
    assert L.separacao_por_temperatura(None) == []
    assert L.separacao_por_temperatura(pd.DataFrame()) == []


def test_separacao_divide_por_canal_quando_ha_utm_source():
    """Nota do Ramon (31/08): 'sem público no nome' escondia Google + rastro
    quebrado + orgânico num balde só. Com utm_source, o canal decide primeiro."""
    df = pd.DataFrame({
        "utm_campaign": ["A | FRIO |1", "A | FRIO |1", "devlf", "devlf",
                         "CAP | X", None],
        "utm_source": ["facebook-ads", "facebook-ads", "google-ads",
                       "google-ads", "facebook-ads", "whatsapp"],
        "decil": [10, 1, 10, 1, 9, 2],
        "converted": [True, False, True, False, False, False],
    })
    s = {r["temperatura"]: r for r in L.separacao_por_temperatura(df)}
    assert set(s) == {"frio", "Google", "Meta, sem público no nome",
                      "orgânico / sem rastro"}
    assert s["Google"]["leads"] == 2 and s["Google"]["taxa_topo"] == pytest.approx(1.0)
    assert s["frio"]["leads"] == 2
    # sem utm_source (contrato antigo/teste), cai no comportamento antigo
    velho = {r["temperatura"] for r in L.separacao_por_temperatura(_ledger_temperatura())}
    assert velho == {"frio", "quente"}
