"""Testes do parser/builder do calendário de LFs (src/data/launch_calendar.py).

Casos aterrados nos formatos REAIS da planilha FORMS (datas sujas, sem ano,
typo de digitação). Rodar:
  python3 -m pytest V2/tests/test_launch_calendar.py
ou: python3 V2/tests/test_launch_calendar.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

from src.data.launch_calendar import parse_range, build_calendar

# (raw, esperado) — formatos reais vistos na aba FORMS
PARSE_CASES = [
    ("25/05 - 30/05", ((25, 5), (30, 5))),     # range padrão
    ("01 a 07/06", ((1, 6), (7, 6))),          # 'a', início sem mês herda do fim
    ("08 a 14/06", ((8, 6), (14, 6))),
    (" 27/04 - 03/05 ", ((27, 4), (3, 5))),    # espaços + cruza mês
    ("29 a 04/05", ((29, 4), (4, 5))),         # início mês anterior (29>04)
    ("22/08 - 28/12", ((22, 8), (28, 12))),    # typo da planilha: parseia, guard rejeita depois
    ("24/03 - 29/03", ((24, 3), (29, 3))),
    ("22 a 28", None),                          # sem mês em nenhuma ponta → fallback
    ("30/05", None),                            # ponto único, não-range
    ("nan", None), ("", None), (None, None),    # vazios
]


def test_parse_range():
    for raw, exp in PARSE_CASES:
        got = parse_range(raw)
        assert got == exp, f"parse_range({raw!r}) = {got}, esperado {exp}"


def test_build_calendar_year_inference_and_guards():
    # ordem cronológica (topo→base = antigo→recente), como na planilha
    rows = [
        {"tag": "LF42", "cap_raw": "09/12 - 15/12", "vendas_raw": "22/08 - 28/12"},  # dez/2025, vendas com typo
        {"tag": "DEV19", "cap_raw": "16/12 - 14/01", "vendas_raw": "19/01 - 25/01"},  # cruza virada de ano
        {"tag": "LF55", "cap_raw": "12/05 - 18/05", "vendas_raw": "25/05 a 31/05"},   # mai/2026
        {"tag": "LF56", "cap_raw": "25/05 - 30/05", "vendas_raw": "08/06 a 14/06"},
        {"tag": "LF61", "cap_raw": "nan", "vendas_raw": "nan"},                        # sem datas → ignorado
    ]
    cal, warns = build_calendar(rows, today=date(2026, 6, 30))

    # ano inferido pela cronologia + âncora no LF recente
    assert cal["LF56"]["cap_start"] == "2026-05-25" and cal["LF56"]["cap_end"] == "2026-05-30"
    assert cal["LF55"]["cap_start"] == "2026-05-12"
    assert cal["LF42"]["cap_start"] == "2025-12-09"          # voltou pra 2025
    assert cal["DEV19"]["cap_start"] == "2025-12-16" and cal["DEV19"]["cap_end"] == "2026-01-14"  # rollover

    # vendas plausíveis ficam; typo cai no fallback + aviso "corrigir na planilha"
    assert cal["LF56"]["vendas_start"] == "2026-06-08"
    assert cal["LF42"].get("vendas_inferred") is True
    assert any("LF42" in w and "corrigir na planilha" in w for w in warns)

    # LF sem datas de captação é ignorado (não inventa)
    assert "LF61" not in cal
    assert any("LF61" in w and "ignorado" in w for w in warns)


if __name__ == "__main__":
    test_parse_range()
    test_build_calendar_year_inference_and_guards()
    print("OK — todos os testes do launch_calendar passaram")
