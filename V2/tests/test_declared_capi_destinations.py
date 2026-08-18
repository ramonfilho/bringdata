"""Destinos CAPI declarados: derivação ÚNICA a partir do YAML.

Contexto (18/08/2026): o conceito "quais (pixel, evento) este cliente dispara"
vivia em dois lugares, e os dois estavam errados:

  - `api/app.py` tinha `_ML_EVENTS` chumbado. Com o jul_24 no ar desde 29/07 e as
    campanhas novas desde 09/08, o gasto delas era classificado como "Lead padrão".
    Em 17/08 o relatório do grupo publicou "0% em ML" com R$ 4.528,70 de gasto real
    em adsets otimizando por jul_24_top30/top50 e abr_28_top30.
  - `api/startup_capi_check` ignorava `capi_secondary_hq_events`, então o pixel que
    só recebe evento secundário nunca era validado no arranque.

Rodar: python3 V2/tests/test_declared_capi_destinations.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

from src.core.client_config import (
    ABTestConfig, ClientConfig, declared_capi_destinations, ml_event_names,
)
from api.startup_capi_check import _collect_pixel_event_pairs

PIXEL_DEFAULT = "1937807493703815"
PIXEL_API = "1513132406527995"
PIXEL_NOVO = "1349518197389751"

_TAXAS = ("conversion_rates: {D01: 0.001, D02: 0.001, D03: 0.001, D04: 0.001, D05: 0.001, "
          "D06: 0.001, D07: 0.001, D08: 0.001, D09: 0.001, D10: 0.01}")

YAML_AB = f"""
ab_test:
  enabled: true
  variants:
    champion_x:
      run_id: run_x
      role: champion
      utm_pattern: {{utm_campaign: ["TAGX"]}}
      pixel_id_override: "{PIXEL_API}"
      capi_event_name: x_lq
      capi_event_name_high_quality: x_hq
      capi_secondary_hq_events:
        - event_name: x_top30
          pixel_id: "{PIXEL_NOVO}"
          decils: ['D08', 'D09', 'D10']
      {_TAXAS}
    challenger_y:
      run_id: run_y
      role: challenger
      utm_pattern: {{utm_campaign: ["TAGY"]}}
      pixel_id_override: "{PIXEL_API}"
      capi_event_name: y_lq
      capi_event_name_high_quality: y_top30
      capi_secondary_hq_events:
        - event_name: y_top30
          pixel_id: "{PIXEL_NOVO}"
          decils: ['D08', 'D09', 'D10']
        - event_name: y_top50
          pixel_id: "{PIXEL_NOVO}"
          decils: ['D06', 'D07', 'D08', 'D09', 'D10']
      {_TAXAS}
"""


class _Capi:
    pixel_id = PIXEL_DEFAULT
    event_name_with_value = "LeadQualified"
    event_name_high_quality = "LeadQualifiedHighQuality"
    extra_hq_destinations = None


class _Cliente:
    capi = _Capi()


def _ab():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(YAML_AB)
        caminho = f.name
    return ABTestConfig.from_active_model_yaml(caminho)


def test_eventos_secundarios_entram():
    """A regressão do relatório: evento secundário fora da derivação = gasto dele
    classificado como 'Lead padrão' e pixel dele sem validação no arranque."""
    nomes = ml_event_names(_Cliente(), _ab())
    for esperado in ("x_top30", "y_top30", "y_top50"):
        assert esperado in nomes, f"{esperado} ficou de fora: {sorted(nomes)}"


def test_eventos_primarios_e_default_continuam():
    nomes = ml_event_names(_Cliente(), _ab())
    assert {"LeadQualified", "LeadQualifiedHighQuality", "x_lq", "x_hq", "y_lq"} <= nomes


def test_pixel_que_so_recebe_secundario_e_validado():
    """O pixel novo não é destino de NENHUM evento primário. Antes ele não
    aparecia no arranque — a salvaguarda ficava cega justamente nele."""
    pares = _collect_pixel_event_pairs(_Cliente(), _ab())
    assert PIXEL_NOVO in pares, f"pixel só-secundário sumiu: {sorted(pares)}"
    assert pares[PIXEL_NOVO] == {"x_top30", "y_top30", "y_top50"}
    assert pares[PIXEL_DEFAULT] == {"LeadQualified", "LeadQualifiedHighQuality"}
    assert pares[PIXEL_API] == {"x_lq", "x_hq", "y_lq", "y_top30"}


def test_variante_sem_override_herda_pixel_default():
    texto = f"""
ab_test:
  enabled: true
  variants:
    v:
      run_id: r
      utm_pattern: {{utm_campaign: ["T"]}}
      capi_event_name: v_lq
      capi_event_name_high_quality: v_hq
      {_TAXAS}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(texto)
        caminho = f.name
    cfg = ABTestConfig.from_active_model_yaml(caminho)   # ler só depois de fechar
    pares = _collect_pixel_event_pairs(_Cliente(), cfg)
    assert pares[PIXEL_DEFAULT] >= {"v_lq", "v_hq"}


def test_sem_config_nao_explode():
    assert declared_capi_destinations(None, None) == []
    assert ml_event_names(None, None) == set()


def test_ab_desligado_so_traz_o_default():
    class _Off:
        enabled = False
        variants = {}
    assert ml_event_names(_Cliente(), _Off()) == {"LeadQualified", "LeadQualifiedHighQuality"}


def test_config_vivo_cobre_os_eventos_das_campanhas_de_hoje():
    """Config REAL: os 3 eventos que as campanhas em produção otimizam TÊM que
    ser reconhecidos como ML, senão o gasto delas volta a sair como Lead padrão."""
    raiz = Path(__file__).resolve().parent.parent
    cliente = ClientConfig.from_yaml(str(raiz / "configs" / "clients" / "devclub.yaml"))
    ab = ABTestConfig.from_active_model_yaml(str(raiz / "configs" / "active_models" / "devclub.yaml"))
    nomes = ml_event_names(cliente, ab)
    for evento in ("abr_28_top30", "jul_24_top30", "jul_24_top50"):
        assert evento in nomes, f"{evento} não reconhecido como ML: {sorted(nomes)}"
    # e o pixel novo tem que ser validado no arranque
    pares = _collect_pixel_event_pairs(cliente, ab)
    assert "1349518197389751" in pares, f"pixel novo fora do startup check: {sorted(pares)}"


if __name__ == "__main__":
    for nome, fn in sorted(list(globals().items())):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"✅ {nome}")
    print("\nTodos os testes passaram.")
