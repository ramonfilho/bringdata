"""O fator de rastreamento lido dos DOIS formatos de payload da referência.

POR QUE ESTE ARQUIVO (24/08/2026): a tabela `reference_rolling` guarda duas formas
do mesmo número e nenhuma linha tem as duas. As 6 linhas novas trazem
`conversion.tracking.factor`; a de window_end 2026-07-13 (a que a produção servia
quando o LF64 começou a captar) só tem `conversion.economics.late_purchase_uplift`
= 1,2105. O teto lia apenas a primeira chave com `or 1.0`, então contra a linha
antiga ele saía com fator 1,0: teto ~17% menor, sem erro e sem log. Os valores
abaixo são os MEDIDOS nessas linhas, não inventados.

Rodável:  PYTHONPATH=. python -m pytest tests/test_fator_de_rastreamento.py -q
"""
import logging

from src.data.reference_reader import fator_de_rastreamento
from src.monitoring.teto import CalculadoraDeTeto

# Payload de HOJE (window_end 2026-08-03, gerado 24/08 06:32).
CONV_NOVO = {
    "tracking": {"factor": 1.2312},
    "economics": {"value_per_sale": 1362.27},
    "by_decile": {"D09": {"leads": 10859, "conv": 135},
                  "D10": {"leads": 11523, "conv": 180}},
}
# Payload ANTIGO (window_end 2026-07-13, gerado 03/08 19:15).
CONV_ANTIGO = {
    "economics": {"value_per_sale": 1362.27, "late_purchase_uplift": 1.2105},
    "by_decile": CONV_NOVO["by_decile"],
}
# Payload das linhas de maio/junho: não tem nenhum dos dois.
CONV_SEM_NADA = {
    "economics": {"value_per_sale": 1362.27},
    "by_decile": CONV_NOVO["by_decile"],
}
DIST = {"D09": 500, "D10": 500}


def _ref(conv, window_end):
    return {"as_of": "2026-08-24", "window_end": window_end,
            "referencia_id": f"{window_end}T06:32", "conversion": conv}


def test_leitor_prefere_a_chave_nova():
    assert fator_de_rastreamento(CONV_NOVO) == (1.2312, "tracking")


def test_leitor_cai_no_uplift_legado():
    assert fator_de_rastreamento(CONV_ANTIGO) == (1.2105, "late_purchase_uplift_legado")


def test_leitor_sem_nenhum_dos_dois_e_ausente():
    assert fator_de_rastreamento(CONV_SEM_NADA) == (1.0, "ausente")
    assert fator_de_rastreamento({}) == (1.0, "ausente")
    assert fator_de_rastreamento(None) == (1.0, "ausente")


def test_valor_impossivel_nao_vira_fator():
    """Zero, negativo ou texto não são fator: caem pro próximo candidato. Fator <= 0
    zeraria ou inverteria o teto, que é pior que o default conservador."""
    for ruim in (0, -3, "não é número"):
        conv = {"tracking": {"factor": ruim},
                "economics": {"late_purchase_uplift": 1.2105}}
        assert fator_de_rastreamento(conv) == (1.2105, "late_purchase_uplift_legado")
        assert fator_de_rastreamento({"tracking": {"factor": ruim}}) == (1.0, "ausente")


def test_teto_carimba_a_procedencia_e_nao_muda_com_a_referencia_de_hoje():
    """O caso que NÃO pode mudar: linha de formato novo continua com 1,2312."""
    t = CalculadoraDeTeto.de_referencia_carregada(
        _ref(CONV_NOVO, "2026-08-03")).por_mistura_de_decis(DIST)
    assert t.ok and t.fator_rastreamento == 1.2312
    assert t.fator_procedencia == "tracking"


def test_teto_da_referencia_antiga_sobe_do_1_para_o_uplift_medido():
    """A mudança desejada, e SÓ nela: com a linha de 13/07 o fator vai de 1,0
    (o silêncio de antes) para 1,2105, e o teto sobe exatamente 21,05%."""
    antiga = CalculadoraDeTeto.de_referencia_carregada(
        _ref(CONV_ANTIGO, "2026-07-13")).por_mistura_de_decis(DIST)
    sem_fator = CalculadoraDeTeto.de_referencia_carregada(
        _ref(CONV_SEM_NADA, "2026-07-13")).por_mistura_de_decis(DIST)
    assert antiga.fator_procedencia == "late_purchase_uplift_legado"
    assert antiga.fator_rastreamento == 1.2105
    assert abs(antiga.valor / sem_fator.valor - 1.2105) < 1e-12
    assert sem_fator.fator_rastreamento == 1.0        # o comportamento antigo


def test_ausencia_de_fator_grita_e_fica_consultavel(caplog):
    """Não pode voltar a ser silêncio: ERRO nomeando a linha, e a procedência
    consultável na calculadora e em cada Teto que ela devolve."""
    with caplog.at_level(logging.ERROR, logger="src.monitoring.teto"):
        calc = CalculadoraDeTeto.de_referencia_carregada(
            _ref(CONV_SEM_NADA, "2026-06-04"))
    assert calc.fator_procedencia == "ausente" and calc.fator_rastreamento == 1.0
    erros = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert erros, "ausência de fator tem que virar ERRO no log"
    assert "2026-06-04" in erros[0].getMessage()
    assert calc.por_mistura_de_decis(DIST).fator_procedencia == "ausente"


def test_sem_referencia_nao_vira_erro_de_fator(caplog):
    """Sem referência nenhuma o motivo já é `sem_referencia`; um segundo erro só
    faria barulho em cima do alarme que já existe."""
    with caplog.at_level(logging.ERROR, logger="src.monitoring.teto"):
        calc = CalculadoraDeTeto.de_referencia_carregada(None)
    assert calc.fator_procedencia == "ausente"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
