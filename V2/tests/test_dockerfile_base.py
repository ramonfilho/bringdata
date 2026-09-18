"""A imagem da API tem que se reconstruir do zero em qualquer máquina.

Em 14/09/2026 o primeiro deploy pelo GitHub Actions caiu no apt-get do Dockerfile: a
base era python:3.10-slim-bullseye, o Debian 11 tinha saído de suporte em 31/08/2026 e
o pool de bullseye-security respondia 404. No Mac ninguém via, por cache de camada.

Este teste lê o FROM e recusa distro fora de suporte. Quando o bookworm vencer
(suporte estendido até meados de 2028), a lista abaixo ganha mais um nome e o FROM sobe.
"""
import re
from pathlib import Path

_DOCKERFILE = Path(__file__).resolve().parents[1] / "api" / "Dockerfile"
_FORA_DE_SUPORTE = ("stretch", "buster", "bullseye")


def _from():
    linhas = [l for l in _DOCKERFILE.read_text().splitlines() if l.startswith("FROM ")]
    assert linhas, "Dockerfile sem linha FROM"
    return linhas[0]


def test_base_nao_e_distro_fora_de_suporte():
    linha = _from()
    for distro in _FORA_DE_SUPORTE:
        assert distro not in linha, f"{linha!r}: {distro} está fora de suporte, o apt-get do build quebra em máquina limpa"


def test_base_continua_no_python_3_10_slim():
    # o Python da imagem é o que os pins do requirements.txt e os pickles do modelo assumem
    assert re.search(r"^FROM python:3\.10-slim-\w+(@sha256:[0-9a-f]{64})?( AS \w+)?$", _from()), _from()
