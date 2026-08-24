"""Teto por CHAVE: identidade do caminho de produção + as entradas injetáveis.

PRIMEIRO teste desta função (24/08/2026). Ela publica o teto de todo criativo no
painel da agência e nunca teve rede: o teste (a) trava o resultado do caminho SEM
parâmetro nenhum, que é o que a produção roda, para que os parâmetros novos
(calc, historico, chave_criativo) fiquem provadamente aditivos.

Puro: fakes de conexão, sem banco (fixtures em tests/fixtures_teto_por_chave.py).
Rodável:  PYTHONPATH=. python -m pytest tests/test_teto_por_chave.py -q
"""
import unicodedata

from src.data.criativo_historico import chave_canonica, le_historico
from src.data.reference_reader import read_rolling_reference
from src.monitoring.teto import CalculadoraDeTeto
from src.monitoring.teto_por_chave import (
    tetos_completos, tetos_por_chave, unidades_finas,
)
from tests.fixtures_teto_por_chave import (
    FATOR, VPS, FakeAnalytics, FakeLedger,
)

# O resultado do caminho de produção com as fixtures acima, medido em 24/08/2026.
# São os números que o painel publicaria: se algum se mexer sem que a mudança
# esteja escrita no teste, é regressão.
TETO_POR_CHAVE = {
    ("campaign", "CAMP_FRIA"): 10.218853,
    ("campaign", "CAMP_QUENTE"): 8.361592,
    ("campaign", "devlf"): 9.671002,
    ("creative", "DEV-AD0140"): 10.980373,
    ("creative", "DEV-AD0999"): 7.477379,
    ("creative", "DEV-AD0001"): 8.361592,
    ("creative", "1234567890"): 9.671002,
}
# (campanha, criativo) -> (n, pct, teto)
UNIDADES = {
    ("CAMP_FRIA", "DEV-AD0140"): (900, 55.555556, 10.980373),
    ("CAMP_FRIA", "DEV-AD0999"): (250, 0.0, 7.477379),
    ("CAMP_QUENTE", "DEV-AD0001"): (300, 50.0, 8.361592),
    ("devlf", "1234567890"): (500, 0.0, 9.671002),
}
# (campanha, conjunto, criativo) -> (n, teto)
CONJUNTOS = {
    ("CAMP_FRIA", "conj_a", "DEV-AD0140"): (500, 16.077601),
    ("CAMP_FRIA", "conj_b", "DEV-AD0140"): (400, 4.608838),
    ("CAMP_FRIA", "conj_a", "DEV-AD0999"): (250, 7.477379),
    ("CAMP_QUENTE", "conj_c", "DEV-AD0001"): (300, 8.361592),
    ("devlf", "", "1234567890"): (500, 9.671002),
}


def _roda(**kw):
    return tetos_completos(FakeAnalytics(), FakeLedger(), run_id="abr28",
                           win_start="2026-07-21", win_end="2026-08-04", **kw)


def _so_o_que_o_push_le(unidades, chaves):
    """As chaves que `push_scores_zanelato` consome, e só elas."""
    return {tuple(u[c] for c in chaves): (u["n"], round(u["pct"], 6),
                                          round(u["teto"].valor, 6))
            for u in unidades}


def test_identidade_sem_parametros_novos():
    """(a) O caminho de produção continua devolvendo exatamente o mesmo."""
    chave, uni, conj = _roda()
    assert {k: round(t.valor, 6) for k, t in chave.items()} == TETO_POR_CHAVE
    assert _so_o_que_o_push_le(uni, ("campanha", "criativo")) == {
        k: (n, round(p, 6), t) for k, (n, p, t) in UNIDADES.items()}
    assert {(c["campanha"], c["conjunto"], c["criativo"]):
            (c["n"], round(c["teto"].valor, 6)) for c in conj} == CONJUNTOS
    # o atalho de compatibilidade continua sendo o [0] do trio
    assert {k: round(t.valor, 6) for k, t in tetos_por_chave(
        FakeAnalytics(), FakeLedger(), run_id="abr28",
        win_start="2026-07-21", win_end="2026-08-04").items()} == TETO_POR_CHAVE


def test_chaves_que_o_push_publica_seguem_existindo():
    """O único consumidor externo lê estas chaves. Chave nova não pode empurrar
    nenhuma delas pra fora (foi o que autorizou carregar a decomposição junto)."""
    _chave, uni, conj = _roda()
    for u in uni:
        assert {"campanha", "criativo", "n", "pct", "teto"} <= set(u)
    for c in conj:
        assert {"campanha", "conjunto", "criativo", "n", "pct", "teto"} <= set(c)


def test_injetar_as_mesmas_entradas_nao_muda_numero_e_nao_le_o_banco():
    """calc e historico injetados IGUAIS aos de hoje devolvem o mesmo resultado,
    e a conexão do analytics não é tocada (é isso que permite backtest sem
    depender do estado de hoje)."""
    an = FakeAnalytics()
    calc = CalculadoraDeTeto.de_referencia_carregada(read_rolling_reference(conn=an))
    historico = le_historico(an)
    lidos = len(an.sqls)
    an2 = FakeAnalytics()
    chave, uni, _c = tetos_completos(an2, FakeLedger(), run_id="abr28",
                                     win_start="2026-07-21", win_end="2026-08-04",
                                     calc=calc, historico=historico)
    assert an2.sqls == []          # nada foi lido do analytics
    assert lidos >= 2              # e as duas leituras existiam mesmo
    assert {k: round(t.valor, 6) for k, t in chave.items()} == TETO_POR_CHAVE
    assert _so_o_que_o_push_le(uni, ("campanha", "criativo")) == {
        k: (n, round(p, 6), t) for k, (n, p, t) in UNIDADES.items()}


def test_calc_injetada_manda_no_numero():
    """Prova que a injeção não é decorativa: uma referência com OUTRO valor por
    venda move todo teto na mesma proporção (é backtest, não fachada)."""
    an = FakeAnalytics()
    ref = read_rolling_reference(conn=an)
    ref["conversion"]["economics"]["value_per_sale"] = VPS / 2
    chave, _u, _c = tetos_completos(
        an, FakeLedger(), run_id="abr28", win_start="a", win_end="b",
        calc=CalculadoraDeTeto.de_referencia_carregada(ref),
        historico=le_historico(FakeAnalytics()))
    for k, t in chave.items():
        assert abs(t.valor - TETO_POR_CHAVE[k] / 2) < 1e-6


def test_decomposicao_bate_com_a_formula():
    """As parcelas novas explicam o número publicado, sem refazer conta por fora:
    conv = conv_modelo × (peso × lift + (1 − peso)) e teto = conv × fator × vps ÷ roas."""
    _chave, uni, _c = _roda()
    por = {(u["campanha"], u["criativo"]): u for u in uni}
    u = por[("CAMP_FRIA", "DEV-AD0140")]
    assert u["n_hist"] == 6000 and u["compradores_hist"] == 90 and u["esperados"] == 60.0
    assert abs(u["lift_criativo"] - 1.5) < 1e-12      # 90 ÷ 60
    assert abs(u["peso"] - 0.75) < 1e-12              # 6000 ÷ (6000 + 2000)
    esperado = u["conv_modelo"] * (u["peso"] * u["lift_criativo"] + (1 - u["peso"]))
    assert abs(u["conv"] - esperado) < 1e-15
    assert abs(u["teto"].valor - u["conv"] * FATOR * VPS / 2.0) < 1e-9
    # o contrafactual: o mesmo criativo SEM o histórico dele
    assert abs(u["teto_so_modelo"].valor - u["conv_modelo"] * FATOR * VPS / 2.0) < 1e-9
    assert u["teto"].valor > u["teto_so_modelo"].valor   # lift 1,5 sobe o teto
    # estreante com prior do TEXTO: a conv vem do prior, não do modelo
    novato = por[("CAMP_FRIA", "DEV-AD0999")]
    assert novato["n_hist"] == 0 and novato["lift_criativo"] is None
    assert novato["conv"] == 0.009 and novato["conv"] != novato["conv_modelo"]


def test_chave_criativo_funde_grafias_e_default_nao_funde():
    """O tradutor opcional é o que deixa um lançamento passado ser reagrupado pela
    grafia que o histórico usa. Sem ele, NFC e NFD continuam duas unidades (o
    comportamento de hoje, byte a byte)."""
    nfc = unicodedata.normalize("NFC", "DEV-captação")
    nfd = unicodedata.normalize("NFD", "DEV-captação")
    assert nfc != nfd
    linhas = [("CAMP", nfc, "conj", 9, 100), ("CAMP", nfd, "conj", 9, 50)]
    cru = unidades_finas(FakeLedger(linhas), run_id="r", win_start="a", win_end="b")
    assert len(cru) == 2
    junto = unidades_finas(FakeLedger(linhas), run_id="r", win_start="a",
                           win_end="b", chave_criativo=chave_canonica)
    assert len(junto) == 1 and list(junto.values())[0] == {"D09": 150}


def test_chave_criativo_que_explode_cai_na_grafia_crua():
    """Tradutor quebrado não pode sumir com a unidade do relatório."""
    def bomba(_):
        raise ValueError("grafia esquisita")
    saida = unidades_finas(FakeLedger([("CAMP", "AD1", "conj", 9, 7)]),
                           run_id="r", win_start="a", win_end="b",
                           chave_criativo=bomba)
    assert saida == {("CAMP", "conj", "AD1"): {"D09": 7}}
