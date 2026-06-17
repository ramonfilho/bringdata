"""Testes do resolvedor de braço A/B (core/ab_arm.py).

Casos aterrados em nomes de campanha reais extraídos dos relatórios de validação.
Rodar: python3 -m pytest V2/tests/test_ab_arm.py   (de bring_data/ ou V2/)
ou:    python3 V2/tests/test_ab_arm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

from src.core.ab_arm import (
    resolve_arm, CHAMPION, CHALLENGER, CONTROLE, EXTERNO, INDETERMINADO,
)

# (descrição, kwargs, esperado)
CASES = [
    # 1. variant do ledger é a verdade — vence qualquer nome
    ("variant challenger vence", dict(variant="challenger_abr28",
        campaign_name="DEVLF | CAP | FRIO | ... | LEADQUALIFIED|1"), CHALLENGER),
    ("variant champion vence", dict(variant="champion_jan30",
        campaign_name="DEVLF | CAP | FRIO | ... | LEADHQLB|1"), CHAMPION),
    ("variant desconhecido -> indeterminado", dict(variant="modelo_xpto"), INDETERMINADO),

    # 2. ML_MAR (mar/2026) = Challenger (confirmado pelo usuário)
    ("ML_MAR HLQC = challenger", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | ML_MAR | HLQC | PG2 | 2025-03-31|120241438584920390",
        captured_at="2026-03-31"), CHALLENGER),
    ("ML_MAR LQC = challenger", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | ML_MAR | LQC | PG2 | 2025-03-31|120241438584940390",
        captured_at="2026-03-31"), CHALLENGER),

    # 3. Era moderna (27/05+): LEADHQLB = Challenger, LEADQUALIFIED = Champion
    ("LEADHQLB = challenger", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-26 | LEADHQLB|120244794184240390",
        captured_at="2026-05-26"), CHALLENGER),
    ("LEADQUALIFIED = champion", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-26 | LEADQUALIFIED|120244717912530390",
        captured_at="2026-05-26"), CHAMPION),
    ("MACHINE LEARNING sem marcador challenger = champion", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 01 | ADV | MACHINE LEARNING | PG2 | 2026-06-08|1",
        captured_at="2026-06-08"), CHAMPION),

    # 4. Era ambígua (PIXEL NOVO API, 29/04-27/05): sem variant -> indeterminado
    ("PIXEL NOVO API ambíguo sem variant -> indeterminado", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO API | MACHINE LEARNING | LEAD | PG2 | 1",
        captured_at="2026-05-10"), INDETERMINADO),
    ("PIXEL NOVO API + variant champion -> champion (variant vence)", dict(
        variant="champion_jan30",
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO API | MACHINE LEARNING | LEAD | PG2 | 1",
        captured_at="2026-05-10"), CHAMPION),

    # 5. Controle: captação sem evento ML (lead puro, score, faixa)
    ("LEAD puro = controle", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-25|120244621534140390",
        captured_at="2026-05-25"), CONTROLE),
    ("ABERTO ADV+ SCORE = controle", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 01 | ABERTO ADV+ | PG2 | SCORE | 2025-04-15|1",
        captured_at="2026-04-15"), CONTROLE),
    ("FAIXA A = controle", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | FAIXA A | PG2 | 2025-08-13|1",
        captured_at="2026-04-13"), CONTROLE),
    ("ESCALA SCORE = controle", dict(
        campaign_name="DEVLF | CAP | FRIO | FASE 04 | ADV | ESCALA SCORE | PG2 | 1",
        captured_at="2026-04-13"), CONTROLE),

    # 6. Externo: não-captação
    ("devlf minúsculo (Google) = externo", dict(campaign_name="devlf"), EXTERNO),
    ("vazio = externo", dict(campaign_name="", captured_at="2026-06-01"), EXTERNO),
    ("None = externo", dict(campaign_name=None, utm_campaign=None), EXTERNO),

    # 7. utm_campaign tem prioridade sobre campaign_name (mesma tag, fontes diferentes)
    ("utm_campaign usado quando presente", dict(
        utm_campaign="DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-05-26 | LEADHQLB|1",
        campaign_name="qualquer coisa", captured_at="2026-05-26"), CHALLENGER),
]


def run():
    fails = 0
    for desc, kwargs, expected in CASES:
        got = resolve_arm(**kwargs)
        ok = got == expected
        if not ok:
            fails += 1
        print(f"{'OK ' if ok else 'FAIL'}  {desc}: esperado={expected} got={got}")
    print(f"\n{len(CASES)-fails}/{len(CASES)} passaram")
    return fails


# pytest
def test_all_cases():
    for desc, kwargs, expected in CASES:
        assert resolve_arm(**kwargs) == expected, desc


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
