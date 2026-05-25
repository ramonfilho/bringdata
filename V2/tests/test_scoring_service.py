"""Testes da casa do scoring (`src/scoring/service.py`).

Rodável sem pytest:  python tests/test_scoring_service.py

Cobre o que é testável sem carregar pipeline real (que puxa MLflow):
  - imutabilidade do DTO ScoringExplanation
  - `_variant_name` helper (mesma semântica do pubsub_branch)
  - propagação de ValueError quando slug é inválido

Testes end-to-end (pipeline real, score correto, vetor encodado completo)
ficam pro caminho de paridade — Passo 4 do plano.
"""
import os
import sys
from dataclasses import FrozenInstanceError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.scoring.service import (
    ScoringExplanation,
    _variant_name,
    score_lead_from_payload,
)


def test_scoring_explanation_eh_frozen():
    exp = ScoringExplanation(
        payload_normalizado={"a": 1},
        dataframe_row={"b": 2},
        encoded_features={"feat_x": 1.0},
        lead_score=0.42,
        decil=5,
        variant=None,
    )
    try:
        exp.lead_score = 0.99  # tentar mutar campo de frozen=True dataclass
    except FrozenInstanceError:
        return
    raise AssertionError("ScoringExplanation deveria ser imutável (frozen)")


def test_scoring_explanation_campos_obrigatorios():
    exp = ScoringExplanation(
        payload_normalizado={},
        dataframe_row={},
        encoded_features={},
        lead_score=0.0,
        decil=1,
        variant="champion",
    )
    assert exp.payload_normalizado == {}
    assert exp.dataframe_row == {}
    assert exp.encoded_features == {}
    assert exp.lead_score == 0.0
    assert exp.decil == 1
    assert exp.variant == "champion"


def test_variant_name_retorna_none_quando_ab_variant_none():
    class _PipelineFake:
        class _AbTestConfig:
            variants = {}
        _ab_test_config = _AbTestConfig()

    assert _variant_name(_PipelineFake(), None) is None


def test_variant_name_acha_pelo_objeto_identity():
    class _Variant:
        pass

    champ = _Variant()
    chall = _Variant()

    class _PipelineFake:
        class _AbTestConfig:
            variants = {"champion": champ, "challenger": chall}
        _ab_test_config = _AbTestConfig()

    assert _variant_name(_PipelineFake(), champ) == "champion"
    assert _variant_name(_PipelineFake(), chall) == "challenger"


def test_variant_name_retorna_none_quando_objeto_nao_esta_no_dict():
    class _Variant:
        pass

    class _PipelineFake:
        class _AbTestConfig:
            variants = {"champion": _Variant()}
        _ab_test_config = _AbTestConfig()

    objeto_de_fora = _Variant()
    assert _variant_name(_PipelineFake(), objeto_de_fora) is None


def test_score_lead_propaga_valueerror_em_slug_invalido():
    payload = {
        "eventId": "x",
        "email": "a@b.com",
        "ip4": "1.2.3.4",
        "firstName": "A",
        "lastName": "B",
        "phone": "+5511999",
        "hasComputer": "SIM",
        "fbp": "fb.x",
        "fbc": None,
        "userAgent": "UA",
        "utm": {"source": "org"},
        "survey": {"idade": "fora_do_vocabulario"},
    }
    # Pipeline pode ser None — vai estourar ValueError na 1ª linha (normalização)
    # antes de tocar no pipeline.
    try:
        score_lead_from_payload(payload, pipeline=None)
    except ValueError as e:
        assert "idade" in str(e)
        return
    raise AssertionError("score_lead_from_payload deveria ter propagado ValueError")


if __name__ == "__main__":
    tests = [
        test_scoring_explanation_eh_frozen,
        test_scoring_explanation_campos_obrigatorios,
        test_variant_name_retorna_none_quando_ab_variant_none,
        test_variant_name_acha_pelo_objeto_identity,
        test_variant_name_retorna_none_quando_objeto_nao_esta_no_dict,
        test_score_lead_propaga_valueerror_em_slug_invalido,
    ]
    n_pass = n_fail = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            n_pass += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            n_fail += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            n_fail += 1
    print(f"\n{n_pass}/{len(tests)} passaram")
    sys.exit(0 if n_fail == 0 else 1)
