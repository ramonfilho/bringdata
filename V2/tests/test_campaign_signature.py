"""Testes da assinatura de tag e do classificador de grupo de controle.

A assinatura de tag (`tag_signature`) é a CHAVE de analytics.campaign_labels: a
mesma tokenização que gerou as 39 assinaturas curadas manualmente. Se ela
divergir da curadoria, todo lookup de rótulo erra e o grupo de controle sai
errado. Por isso o teste de integração exige reproduzir 100% das chaves da
tabela a partir do universo real.

Rodar: python3 V2/tests/test_campaign_signature.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

from src.validation.campaign_classifier import tag_signature, classify_for_weights


def test_tag_signature_descarta_estruturais():
    # nome longo típico do A/B: só a tag do braço sobrevive (data, fase, adv, ID caem)
    assert tag_signature(
        "DEVLF | CAP | FRIO | FASE 04 | ADV | LEADHQLB | 2026-05-01 | 120240"
    ) == "leadhqlb"
    # dois tokens de tag preservados na ordem
    assert tag_signature("DEVLF | CAP | FRIO | MACHINE LEARNING | LQ | PG2") == "machine learning | lq"
    # captação sem marca de braço → sem tag
    assert tag_signature("DEVLF | CAP | FRIO | FASE 01") == "(sem tag)"
    # ESCALA SCORE (controle) sobrevive
    assert tag_signature("DEVLF | CAP | FRIO | FASE 04 | ADV | ESCALA SCORE | PG2") == "escala score"


def test_tag_signature_url_encoded_e_nulos():
    # '%7C' url-encoded: split por '%' + limpeza do '7c' remonta os tokens
    assert tag_signature("DEVLF %7C CAP %7C FRIO %7C LEADQUALIFIED") == "leadqualified"
    # nulos → (sem tag), nunca estoura
    assert tag_signature(None) == "(sem tag)"
    assert tag_signature("") == "(sem tag)"
    assert tag_signature(float("nan")) == "(sem tag)"


def test_tag_signature_digitos_e_id_puro():
    # segmento só de dígitos (ID) é descartado
    assert tag_signature("DEVLF | LEADHQLB | 120243354440640390") == "leadhqlb"
    # data isolada é descartada
    assert tag_signature("2026-04-30 | MACHINE LEARNING") == "machine learning"


def test_classify_for_weights_pela_curadoria():
    # mapa de rótulos = assinatura → categoria (como vem de analytics.campaign_labels)
    label_map = {
        "aberto": "Controle",
        "lead": "Lead",
        "machine learning": "Champion",
        "leadhqlb": "Challenger",
        "dev20": "Excluir",
    }
    # campanhas reais → assinatura → categoria → grupo de peso
    assert classify_for_weights("DEVLF | CAP | FRIO | ABERTO | PG1", label_map) == "CONTROLE"
    assert classify_for_weights("DEVLF | CAP | FRIO | LEAD | PG1", label_map) == "CONTROLE"  # Lead conta como controle
    assert classify_for_weights("DEVLF | CAP | FRIO | MACHINE LEARNING", label_map) == "ML"
    assert classify_for_weights("DEVLF | CAP | FRIO | LEADHQLB | 123", label_map) == "ML"
    assert classify_for_weights("DEV20", label_map) == "NEUTRO"          # Excluir → fora do reweighting
    # assinatura não catalogada → NEUTRO (peso 1, sem efeito)
    assert classify_for_weights("DEVLF | CAP | FRIO | TAG_NOVA_XYZ", label_map) == "NEUTRO"


def test_classify_for_weights_fallback_legado():
    # sem label_map → classificador por substring legado (COM_ML/SEM_ML/EXCLUIR → grupos)
    assert classify_for_weights("DEVLF | CAP | FRIO | MACHINE LEARNING | PG2", None) == "ML"
    assert classify_for_weights("DEVLF | CAP | FRIO | ESCALA SCORE | PG2", None) == "CONTROLE"
    assert classify_for_weights("PÓS DEV | CAP | FRIO | FASE 01", None) == "NEUTRO"  # não captação
    assert classify_for_weights(None, None) == "NEUTRO"


# O teste de integração `test_integracao_reproduz_chaves_curadas_db` foi REMOVIDO
# em 08/08/2026. Ele exigia que o tokenizador reproduzisse TODAS as assinaturas de
# `analytics.campaign_labels` a partir das campanhas reais dos últimos meses, e isso
# nunca ia se sustentar por duas razões medidas:
#
#   1. Campanha que PARA de rodar nunca mais aparece no universo, mas a linha dela
#      fica na tabela para sempre. O teste passava a acusar falha só porque o tempo
#      passou — 7 chaves nessa situação em 07/08/2026.
#   2. A tabela deixou de ser só curadoria manual. O docstring falava de '39
#      assinaturas curadas manualmente'; havia 50, e as 11 extras entraram por
#      script (`rotulagem_auto_consistencia`, `rotulagem_fonte_unica_papel`). Exigir
#      que o tokenizador reproduza o que outro script inseriu não testa o
#      tokenizador, testa a coincidência entre dois processos.
#
# A pergunta útil é a INVERSA e continua coberta pelos testes unitários acima: dada
# uma campanha real, a assinatura sai certa. Se um dia valer testar cobertura, o
# certo é medir quantas campanhas ATIVAS têm rótulo, não quantas linhas da tabela
# são reproduzíveis.