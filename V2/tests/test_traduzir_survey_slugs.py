"""Testes da tradução slug→PT em api/railway_mapping.

Rodável sem pytest:  python tests/test_traduzir_survey_slugs.py

Cobre:
  1. Cada slug do vocabulário do sistema novo traduz pra a string PT longa
     que os MAPA_* do pipeline esperam.
  2. PARIDADE DE ENCODING: survey_lead_to_sheets_row(slug-form) ==
     survey_lead_to_sheets_row(PT-form). Esse é o requisito real — o vetor
     que entra no modelo tem que ser idêntico.
  3. IDEMPOTÊNCIA: passar PT-form pela tradução não muda nada.
  4. FAIL-LOUD: slug fora do vocabulário levanta ValueError com mensagem útil.
  5. Bordas: None/{} não quebram; campos vazios passam direto.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.railway_mapping import (
    SLUG_ATRACAO_PROFISSAO,
    SLUG_FAIXA_SALARIAL,
    SLUG_GENERO,
    SLUG_IDADE,
    SLUG_INTERESSE_EVENTO,
    SLUG_OCUPACAO,
    SLUG_SIM_NAO,
    traduzir_survey_slugs,
)
from api.survey_mapping import survey_lead_to_sheets_row


# Survey inputs reais do payload Pub/Sub do dono (slug-form), todas as variantes
# vistas nas 9 mensagens capturadas em 2026-05-23 e o que o JSON-schema dele
# documenta como possível.

def _slug_survey_completo():
    """Slug-form coerente; serve de base p/ paridade contra PT-form."""
    return {
        "genero":             "masculino",     # já casa após unidecode+lower
        "idade":              "25-34",         # slug
        "ocupacao":           "clt",           # slug
        "faixaSalarial":      "1000-2000",     # slug
        "cartaoCredito":      "sim",           # já casa
        "estudouProgramacao": "nao",           # já casa
        "faculdade":          "sim",           # já casa
        "investiuCurso":      "nao",           # já casa
        "atracaoProfissao":   "trabalhar_exterior",  # slug
        "interesseEvento":    "transicao_carreira",  # slug
    }


def _pt_survey_completo():
    """Mesma resposta lógica em PT-form (legacy / lead_surveys row)."""
    return {
        "genero":             "Masculino",
        "idade":              "25 - 34 anos",
        "ocupacao":           "Sou CLT/Funcionário Público",
        "faixaSalarial":      "Entre R$1.000 a R$2.000 reais ao mês",
        "cartaoCredito":      "Sim",
        "estudouProgramacao": "Não",
        "faculdade":          "Sim",
        "investiuCurso":      "Não",
        "atracaoProfissao":   "Trabalhar para outros países e ganhar em outra moeda",
        "interesseEvento":    "Fazer transição de carreira e conseguir meu primeiro emprego na área",
    }


def test_cada_slug_traduz():
    """Cobertura: todo slug declarado vira a PT correspondente."""
    pares = [
        (SLUG_IDADE,              "idade"),
        (SLUG_OCUPACAO,           "ocupacao"),
        (SLUG_FAIXA_SALARIAL,     "faixaSalarial"),
        (SLUG_ATRACAO_PROFISSAO,  "atracaoProfissao"),
        (SLUG_INTERESSE_EVENTO,   "interesseEvento"),
        (SLUG_GENERO,             "genero"),
    ]
    for mapa, campo in pares:
        for slug, pt in mapa.items():
            r = traduzir_survey_slugs({campo: slug})
            assert r[campo] == pt, (
                f"{campo}: slug {slug!r} → esperava {pt!r}, veio {r[campo]!r}"
            )
    # cartaoCredito/estudouProgramacao/faculdade/investiuCurso compartilham SLUG_SIM_NAO
    for campo in ("cartaoCredito", "estudouProgramacao",
                  "faculdade", "investiuCurso"):
        for slug, pt in SLUG_SIM_NAO.items():
            r = traduzir_survey_slugs({campo: slug})
            assert r[campo] == pt, (
                f"{campo}: slug {slug!r} → esperava {pt!r}, veio {r[campo]!r}"
            )


def test_paridade_encoding_slug_vs_pt():
    """Requisito: o dict que entra no scorer é o mesmo entre slug e PT-form."""
    slug = traduzir_survey_slugs(_slug_survey_completo())
    pt   = _pt_survey_completo()

    # ambos passam por survey_lead_to_sheets_row com mesmo email/UTM/enrich
    common_envelope = {
        "id": "evt-test",
        "submittedAt": "2026-05-23T11:00:00Z",
        "clientEmail": "x@y.com",
    }
    utm = {"source": "facebook-ads", "medium": "aberto",
           "campaign": "c", "content": "ct", "term": "fb",
           "url": "https://x"}
    enrich = {"computador": "SIM", "telefone": "+5511",
              "nome": "Fulano de Tal",
              "fbp": "fb.x", "fbc": "fb.y", "ip": "1.1.1.1",
              "user_agent": "ua"}

    got_slug = survey_lead_to_sheets_row({**common_envelope, **slug}, utm, enrich)
    got_pt   = survey_lead_to_sheets_row({**common_envelope, **pt},   utm, enrich)

    assert got_slug == got_pt, (
        "Encoding divergiu entre slug-form e PT-form.\n"
        f"  só em slug-form: { {k: got_slug[k] for k in got_slug if got_slug.get(k) != got_pt.get(k)} }\n"
        f"  só em PT-form:   { {k: got_pt[k]   for k in got_pt   if got_pt.get(k)   != got_slug.get(k)} }"
    )


def test_idempotencia_pt_form():
    """PT-form passa direto (não há retradução double-encode)."""
    pt = _pt_survey_completo()
    r = traduzir_survey_slugs(pt)
    for campo, esperado in pt.items():
        assert r[campo] == esperado, (
            f"PT-form deveria passar direto em {campo}: "
            f"era {esperado!r}, virou {r[campo]!r}"
        )


def test_fail_loud_slug_desconhecido():
    """Slug fora do vocabulário levanta ValueError com mensagem informativa."""
    casos = [
        ("idade",            "70+"),
        ("ocupacao",         "freelancer"),
        ("faixaSalarial",    "10000+"),
        ("atracaoProfissao", "nao_sei"),
        ("interesseEvento",  "outros"),
        ("genero",           "outro"),
        ("cartaoCredito",    "talvez"),
    ]
    for campo, slug_invalido in casos:
        try:
            traduzir_survey_slugs({campo: slug_invalido})
        except ValueError as e:
            msg = str(e)
            assert campo in msg, (
                f"mensagem não cita o campo {campo!r}: {msg!r}"
            )
            assert slug_invalido in msg, (
                f"mensagem não cita o valor {slug_invalido!r}: {msg!r}"
            )
        else:
            raise AssertionError(
                f"{campo}={slug_invalido!r} deveria ter levantado ValueError"
            )


def test_none_e_vazio_passam_direto():
    """`None`, `''` e dict vazio não quebram."""
    assert traduzir_survey_slugs(None) is None
    assert traduzir_survey_slugs({}) == {}
    r = traduzir_survey_slugs({"idade": None, "ocupacao": ""})
    assert r["idade"] is None
    assert r["ocupacao"] == ""


def test_todos_10_campos_canonicalizam():
    """Os 10 campos da pesquisa saem em forma PT-Long canônica."""
    survey = {
        "genero":             "feminino",
        "cartaoCredito":      "nao",
        "estudouProgramacao": "sim",
        "faculdade":          "nao",
        "investiuCurso":      "sim",
        "idade":              "<18",
        "ocupacao":           "autonomo",
        "faixaSalarial":      "0",
        "atracaoProfissao":   "home_office",
        "interesseEvento":    "freelancer",
    }
    r = traduzir_survey_slugs(survey)
    assert r["genero"]             == "Feminino"
    assert r["cartaoCredito"]      == "Não"
    assert r["estudouProgramacao"] == "Sim"
    assert r["faculdade"]          == "Não"
    assert r["investiuCurso"]      == "Sim"
    assert r["idade"]              == "Menos de 18 anos"
    assert r["ocupacao"]           == "Sou autonomo"
    assert r["faixaSalarial"]      == "Não tenho renda"
    assert r["atracaoProfissao"]   == "Poder trabalhar de qualquer lugar do mundo"
    assert r["interesseEvento"]    == "Fazer freelancer como programador"


def test_nao_muta_input():
    """A função é pura — não mexe no dict de entrada."""
    original = {"idade": "25-34", "ocupacao": "clt"}
    snapshot = dict(original)
    traduzir_survey_slugs(original)
    assert original == snapshot, "traduzir_survey_slugs mutou o input!"


def _run():
    tests = [
        test_cada_slug_traduz,
        test_paridade_encoding_slug_vs_pt,
        test_idempotencia_pt_form,
        test_fail_loud_slug_desconhecido,
        test_none_e_vazio_passam_direto,
        test_todos_10_campos_canonicalizam,
        test_nao_muta_input,
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
