"""Fallback de origem (utm_source) pelo slug da landing page em payload_to_utm.

Cobre a regra: quando o payload chega SEM utm_source mas a URL de captura tem o
canal no slug do path, deriva source do mapa {slug: source}. Nunca sobrescreve
origem presente; sem o mapa, comportamento idêntico ao legado.
"""
from pathlib import Path

import pytest

from src.core.client_config import ClientConfig
from src.core.payload_normalization import payload_to_utm

# Mapa igual ao do devclub.yaml
MAP = {"cap-meta": "facebook-ads", "cap-go": "google-ads", "cap-org": "organic"}

META_URL = "https://lp6.rodolfomori.com.br/cap-meta-a-v1/?_v=019f3291&_p=019e50"
GO_URL = "https://lp6.rodolfomori.com.br/cap-go-b-v2/"
ORG_URL = "https://lp6.rodolfomori.com.br/cap-org-a-v1/?utm_campaign=encurtadorevento"


def _p(url=None, source=None):
    utm = {}
    if url is not None:
        utm["url"] = url
    if source is not None:
        utm["source"] = source
    return {"utm": utm}


def test_slug_meta_preenche_facebook_ads():
    assert payload_to_utm(_p(url=META_URL), MAP)["source"] == "facebook-ads"


def test_slug_google_preenche_google_ads():
    assert payload_to_utm(_p(url=GO_URL), MAP)["source"] == "google-ads"


def test_slug_org_preenche_organic():
    assert payload_to_utm(_p(url=ORG_URL), MAP)["source"] == "organic"


def test_origem_presente_nunca_sobrescreve():
    # source já veio no payload → mapa é ignorado mesmo com url de outro canal
    got = payload_to_utm(_p(url=META_URL, source="google-ads"), MAP)
    assert got["source"] == "google-ads"


def test_origem_string_vazia_conta_como_ausente():
    assert payload_to_utm(_p(url=META_URL, source="   "), MAP)["source"] == "facebook-ads"


def test_sem_mapa_e_comportamento_legado():
    # Sem o mapa (None): só a cópia rasa, source segue ausente
    assert payload_to_utm(_p(url=META_URL)).get("source") is None
    assert payload_to_utm(_p(url=META_URL), None).get("source") is None


def test_url_sem_slug_conhecido_nao_preenche():
    got = payload_to_utm(_p(url="https://lp6.rodolfomori.com.br/obrigado/"), MAP)
    assert got.get("source") is None


def test_sem_url_nao_quebra():
    assert payload_to_utm(_p(source=None), MAP).get("source") is None


def test_url_malformada_degrada_sem_excecao():
    got = payload_to_utm(_p(url=12345), MAP)  # tipo inesperado
    assert got.get("source") is None


def test_slug_casa_no_path_ignora_querystring():
    # o slug está no path; querystring com _v/_p não atrapalha
    url = "https://lp6.rodolfomori.com.br/cap-meta-a-v1/?cap-go=1"
    assert payload_to_utm(_p(url=url), MAP)["source"] == "facebook-ads"


def test_payload_sem_bloco_utm():
    assert payload_to_utm({}, MAP) == {}


def test_devclub_yaml_carrega_o_mapa():
    cfg_path = Path(__file__).resolve().parents[1] / "configs" / "clients" / "devclub.yaml"
    cfg = ClientConfig.from_yaml(cfg_path)
    assert cfg.utm.source_from_url_slug == {
        "cap-meta": "facebook-ads",
        "cap-go": "google-ads",
        "cap-org": "organic",
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
