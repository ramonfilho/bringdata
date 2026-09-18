"""Os routers de api/routers/ resolvem caminhos a partir da raiz do V2, não de api/.

Na refatoração que tirou as rotas do app.py (PR #299, 17/09/2026), os trechos que
calculavam a raiz com `Path(__file__).parent.parent` vieram junto, mas o arquivo desceu
um nível (api/routers/), então a raiz virou api/. O canário 01179-jux respondeu 500 no
daily-check por 'api/configs/active_models/devclub.yaml' não existir, e o gate segurou
o deploy em 10% (HOLD). Este teste recusa as duas formas e confere que a raiz que os
routers usam contém o que eles abrem.
"""
import re
from pathlib import Path

V2 = Path(__file__).resolve().parents[1]
ROUTERS = sorted((V2 / "api" / "routers").glob("*.py"))
_FORMAS_ERRADAS = (
    r"Path\(__file__\)\.parent\.parent(?!\.parent)",
    r"os\.path\.dirname\(os\.path\.dirname\(os\.path\.abspath\(__file__\)\)\)",
)


def test_nenhum_router_calcula_a_raiz_com_dois_parent():
    ruins = []
    for f in ROUTERS:
        for i, linha in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if linha.lstrip().startswith("#"):
                continue
            for forma in _FORMAS_ERRADAS:
                if re.search(forma, linha):
                    ruins.append(f"{f.name}:{i}: {linha.strip()[:80]}")
    assert not ruins, "\n".join(ruins)


def test_a_raiz_dos_routers_e_o_v2_e_tem_o_que_eles_abrem():
    for f in ROUTERS:
        s = f.read_text(encoding="utf-8")
        if "_RAIZ" not in s:
            continue
        assert "_RAIZ = Path(__file__).resolve().parents[2]" in s, f.name
    raiz = (V2 / "api" / "routers" / "daily_check.py").resolve().parents[2]
    assert raiz == V2
    assert (raiz / "configs" / "active_models" / "devclub.yaml").is_file()
    assert (raiz / "src" / "validation" / "validate_ml_performance.py").is_file()
