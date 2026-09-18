"""gspread 6 inverteu a ordem de `Worksheet.update` (valores primeiro, intervalo depois).

Chamar por nome (`range_name=`, `values=`) vale nas duas versões (5.12 e 6.x). A forma
posicional antiga só avisa na 6 e a ordem nova quebra na 5; este teste prende a forma por
nome (18/09/2026, preparação para a PR #316 do Dependabot).
"""
import re
from pathlib import Path

FONTE = Path(__file__).resolve().parents[1] / "src" / "validation" / "sheets_uploader.py"


def test_update_do_gspread_e_chamado_por_nome():
    s = FONTE.read_text(encoding="utf-8")
    assert not re.search(r"\.update\(\s*['\"]A1['\"]", s), "update posicional (intervalo primeiro) encontrado"
    assert s.count("worksheet.update(range_name='A1', values=data") == 2
