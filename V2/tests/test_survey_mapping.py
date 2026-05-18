"""Testes do I2 — adaptador api/survey_mapping.

Rodável sem pytest:  python tests/test_survey_mapping.py
(o ambiente não tem pytest; segue o padrão dos demais test_*.py do projeto.)

Cobre:
  1. EQUIVALÊNCIA: mesmo dado entrado como `Lead` (direto na função canônica)
     vs. como survey+utm+enrich (via adaptador) → dict do scorer IDÊNTICO.
  2. VOCABULÁRIO: frases reais da lead_surveys caem nas categorias canônicas
     que o funil `Lead` já produz (trava o 100% medido).
  3. COMPUTADOR: vem do enriquecimento; ausente → None (I4 trata o skip).
  4. UTM AUSENTE: utm None/{} não quebra; campos viram None.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.railway_mapping import railway_lead_to_sheets_row
from api.survey_mapping import survey_lead_to_sheets_row, survey_to_lead_shaped


def _lead_shaped():
    return {
        "id": "cmp_abc",
        "data": "2026-05-18 10:00:00",
        "email": "fulano@exemplo.com",
        "nomeCompleto": "Fulano Silva",
        "telefone": "+5511999998888",
        "source": "facebook-ads",
        "medium": "aberto",
        "campaign": "devlf",
        "content": "ad0150",
        "term": "ig",
        "pesquisa": {
            "genero": "Masculino",
            "idade": "25 - 34 anos",
            "ocupacao": "Sou CLT/Funcionário Público",
            "faixaSalarial": "Entre R$1.000 a R$2.000 reais ao mês",
            "cartaoCredito": "Sim",
            "interesseEvento": "Fazer um projeto na prática",
            "computador": "SIM",
            "estudouProgramacao": "Não",
            "faculdade": "Sim",
            "investiuCurso": "Não",
            "atracaoProfissao": "Poder trabalhar de qualquer lugar do mundo",
        },
    }


def _survey_inputs():
    survey = {
        "id": "cmp_abc",
        "submittedAt": "2026-05-18 10:00:00",
        "clientEmail": "fulano@exemplo.com",
        "genero": "Masculino",
        "idade": "25 - 34 anos",
        "ocupacao": "Sou CLT/Funcionário Público",
        "faixaSalarial": "Entre R$1.000 a R$2.000 reais ao mês",
        "cartaoCredito": "Sim",
        "interesseEvento": "Fazer um projeto na prática",
        "estudouProgramacao": "Não",
        "faculdade": "Sim",
        "investiuCurso": "Não",
        "atracaoProfissao": "Poder trabalhar de qualquer lugar do mundo",
        "eventId": "survey_123",
        "ip": "1.2.3.4",
    }
    utm = {
        "source": "facebook-ads",
        "medium": "aberto",
        "campaign": "devlf",
        "content": "ad0150",
        "term": "ig",
        "url": "https://lp.devclub.com.br/x",
    }
    enrich = {
        "computador": "SIM",
        "telefone": "+5511999998888",
        "nome": "Fulano Silva",
        "fbp": "fb.1.x",
        "fbc": "fb.2.x",
        "ip": "1.2.3.4",
        "user_agent": "Mozilla/5.0",
    }
    return survey, utm, enrich


def test_equivalencia_lead_vs_survey():
    expected = railway_lead_to_sheets_row(_lead_shaped())
    survey, utm, enrich = _survey_inputs()
    got = survey_lead_to_sheets_row(survey, utm, enrich)
    assert got == expected, (
        "Adaptador divergiu da função canônica.\n"
        f"  só no esperado: { {k: expected[k] for k in expected if expected.get(k) != got.get(k)} }\n"
        f"  só no obtido:   { {k: got[k] for k in got if got.get(k) != expected.get(k)} }"
    )


def test_vocabulario_categorias_canonicas():
    survey, utm, enrich = _survey_inputs()
    r = survey_lead_to_sheets_row(survey, utm, enrich)
    esperado = {
        "Qual a sua idade?": "25 34 anos",
        "O que você faz atualmente?": "sou cltfuncionario publico",
        "Atualmente, qual a sua faixa salarial?": "entre r1000 a r2000 reais ao mes",
        "O que mais você quer ver no evento?": "fazer um projeto na pratica",
        "interesse_programacao": "poder trabalhar de qualquer lugar do mundo",
        "Você possui cartão de crédito?": "sim",
        "Tem computador/notebook?": "sim",
        "O seu gênero:": "Masculino",
    }
    for col, val in esperado.items():
        assert r.get(col) == val, f"{col!r}: esperava {val!r}, veio {r.get(col)!r}"


def test_computador_vem_do_enrich():
    survey, utm, enrich = _survey_inputs()
    # NAO (de activecampaign campo 144 / n8n tem_computador)
    enrich["computador"] = "NAO"
    r = survey_lead_to_sheets_row(survey, utm, enrich)
    assert r.get("Tem computador/notebook?") == "nao", r.get("Tem computador/notebook?")
    # ausente → None (I4 fará o skip pela regra dura, não este módulo)
    enrich2 = dict(enrich)
    enrich2.pop("computador")
    r2 = survey_lead_to_sheets_row(survey, utm, enrich2)
    assert r2.get("Tem computador/notebook?") is None, r2.get("Tem computador/notebook?")
    # e não está na lead_surveys: garantir que o survey cru não carrega computador
    assert "computador" not in survey


def test_utm_ausente_nao_quebra():
    survey, _, enrich = _survey_inputs()
    r = survey_lead_to_sheets_row(survey, None, enrich)
    for col in ("Source", "Medium", "Campaign", "Term", "Content"):
        assert r.get(col) is None, f"{col} deveria ser None sem UTM, veio {r.get(col)!r}"
    # pesquisa continua íntegra mesmo sem UTM
    assert r.get("Qual a sua idade?") == "25 34 anos"


def test_shape_intermediario():
    survey, utm, enrich = _survey_inputs()
    shaped = survey_to_lead_shaped(survey, utm, enrich)
    assert shaped["email"] == "fulano@exemplo.com"
    assert shaped["nomeCompleto"] == "Fulano Silva"
    assert shaped["source"] == "facebook-ads"
    assert shaped["pesquisa"]["computador"] == "SIM"
    assert set(shaped["pesquisa"]) == {
        "genero", "idade", "ocupacao", "faixaSalarial", "cartaoCredito",
        "interesseEvento", "estudouProgramacao", "faculdade", "investiuCurso",
        "atracaoProfissao", "computador",
    }


def _run():
    tests = [
        test_equivalencia_lead_vs_survey,
        test_vocabulario_categorias_canonicas,
        test_computador_vem_do_enrich,
        test_utm_ausente_nao_quebra,
        test_shape_intermediario,
    ]
    fails = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {t.__name__}\n        {e}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - fails}/{len(tests)} passaram")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_run())
