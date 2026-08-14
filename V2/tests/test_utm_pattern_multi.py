"""Roteamento por UTM quando DUAS gerações de campanha servem o MESMO modelo.

Contexto (09/08/2026): o gestor subiu uma estrutura nova de campanhas no pixel
"DEVLF - NOVO" (1349518197389751) enquanto a antiga seguia gastando:

    geração antiga: "DEVLF | CAP | FRIO | ... | JUL24_TOP30|<id>"       (pixel 1513)
    geração nova:   "[14][DEVLF][CAP]...[PIXELNOVO][JUL_24_TOP30]|<id>" (pixel 1349)

As duas etiquetas precisam apontar para o MESMO modelo ao mesmo tempo. Note o
underline: "JUL24" não é substring de "JUL_24_TOP30" — trocar a etiqueta em vez de
somar teria derrubado a geração antiga no mesmo commit, e os leads dela cairiam
calados no fallback (eventos padrão, pixel errado).

Rodar: python3 V2/tests/test_utm_pattern_multi.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

from src.core.client_config import ABTestConfig

# Nomes REAIS colhidos da Graph API em 09/08/2026 (conta act_188005769808959).
# As ads usam url_tags `utm_campaign={{campaign.name}}|{{campaign.id}}`, então o nome
# INTEIRO da campanha chega no utm_campaign do lead.
CAMP_ANTIGA_CHAMPION = "DEVLF | CAP | QUENTE | FASE 04 | ADV | LEAD | PG1 | 2026-06-29 | LEADHQLB|120248441854840390"
CAMP_ANTIGA_CHALLENGER = "DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-18 | JUL24_TOP30|120248442473610390"
CAMP_NOVA_CHAMPION = "[13][DEVLF][CAP][LEADS][SITE][FRIO][ADVTG_ABERTO][CBO][AUT][09.08][TESTE_CONVERSAO][PG1] [PIXELNOVO][ABR_28_TOP30]|120248733363790390"
CAMP_NOVA_CHALLENGER = "[14][DEVLF][CAP][LEADS][SITE][FRIO][ADVTG_ABERTO][CBO][AUT][09.08][TESTE_CONVERSAO][PG1] [PIXELNOVO][JUL_24_TOP30]|120248733674690390"
CAMP_NOVA_CHALLENGER_TOP50 = "[15][DEVLF][CAP][LEADS][SITE][FRIO][ADVTG_ABERTO][CBO][AUT][09.08][TESTE_CONVERSAO][PG1] [PIXELNOVO][JUL_24_TOP50]|120248733679820390"

_TAXAS = ("conversion_rates: {D01: 0.001, D02: 0.001, D03: 0.001, D04: 0.001, D05: 0.001, "
          "D06: 0.001, D07: 0.001, D08: 0.001, D09: 0.001, D10: 0.01}")

YAML_LISTA = f"""
ab_test:
  enabled: true
  variants:
    champion_x:
      run_id: run_x
      role: champion
      utm_pattern: {{utm_campaign: ["LEADHQLB", "ABR_28_TOP30"]}}
      capi_event_name: x_lq
      capi_event_name_high_quality: x_hq
      {_TAXAS}
    challenger_y:
      run_id: run_y
      role: challenger
      utm_pattern: {{utm_campaign: ["JUL24", "JUL_24"]}}
      capi_event_name: y_lq
      capi_event_name_high_quality: y_hq
      {_TAXAS}
"""

YAML_STRING_SOLTA = f"""
ab_test:
  enabled: true
  variants:
    champion_x:
      run_id: run_x
      role: champion
      utm_pattern: {{utm_campaign: "LEADHQLB"}}
      capi_event_name: x_lq
      capi_event_name_high_quality: x_hq
      {_TAXAS}
"""


def _carrega(texto):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(texto)
        caminho = f.name
    return ABTestConfig.from_active_model_yaml(caminho)


def _qual(cfg, utm_campaign):
    v = cfg.match_variant({"utm_campaign": utm_campaign})
    if v is None:
        return None
    return next(n for n, x in cfg.variants.items() if x is v)


def test_as_duas_geracoes_apontam_para_o_mesmo_modelo():
    cfg = _carrega(YAML_LISTA)
    assert _qual(cfg, CAMP_ANTIGA_CHAMPION) == "champion_x"
    assert _qual(cfg, CAMP_NOVA_CHAMPION) == "champion_x"
    assert _qual(cfg, CAMP_ANTIGA_CHALLENGER) == "challenger_y"
    assert _qual(cfg, CAMP_NOVA_CHALLENGER) == "challenger_y"
    # A campanha do top50 novo é do mesmo challenger (a etiqueta é o modelo, não o tier)
    assert _qual(cfg, CAMP_NOVA_CHALLENGER_TOP50) == "challenger_y"


def test_underline_nao_e_detalhe_cosmetico():
    """A regressão que este teste tranca: 'JUL24' NÃO casa 'JUL_24_TOP30'.

    Se alguém 'simplificar' a lista de volta para uma substring só, uma das duas
    gerações para de rotear — e o sintoma em produção é silencioso (variant=None,
    evento padrão, pixel errado), não um erro.
    """
    cfg = _carrega(YAML_LISTA)
    v = cfg.variants["challenger_y"]
    assert "JUL24" not in CAMP_NOVA_CHALLENGER.upper().replace("JUL_24", "")
    assert "JUL24" in v.utm_pattern["utm_campaign"]
    assert "JUL_24" in v.utm_pattern["utm_campaign"]


def test_campanha_de_fora_nao_casa_ninguem():
    cfg = _carrega(YAML_LISTA)
    assert _qual(cfg, "DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-04") is None
    assert _qual(cfg, None) is None
    assert _qual(cfg, "") is None


def test_casamento_ignora_caixa():
    cfg = _carrega(YAML_LISTA)
    assert _qual(cfg, CAMP_NOVA_CHAMPION.lower()) == "champion_x"
    assert _qual(cfg, CAMP_NOVA_CHALLENGER.lower()) == "challenger_y"


def test_string_solta_continua_valendo():
    """Forma antiga do YAML (uma substring, sem lista) não pode quebrar."""
    cfg = _carrega(YAML_STRING_SOLTA)
    assert cfg.variants["champion_x"].utm_pattern == {"utm_campaign": ["LEADHQLB"]}
    assert _qual(cfg, CAMP_ANTIGA_CHAMPION) == "champion_x"
    assert _qual(cfg, CAMP_NOVA_CHAMPION) is None   # etiqueta nova não estava declarada


def test_padrao_torto_falha_alto():
    """utm_pattern é o que decide qual modelo scoreia e qual evento a Meta recebe.
    Entrada inválida tem que explodir no carregamento, não virar 'nunca casa'."""
    for ruim in ['utm_pattern: {utm_campaign: []}',
                 'utm_pattern: {utm_campaign: ["", "OK"]}',
                 'utm_pattern: {utm_campaign: [123]}',
                 'utm_pattern: "LEADHQLB"']:
        texto = f"""
ab_test:
  enabled: true
  variants:
    v:
      run_id: r
      {ruim}
      capi_event_name: a
      capi_event_name_high_quality: b
      {_TAXAS}
"""
        try:
            _carrega(texto)
        except ValueError:
            continue
        raise AssertionError(f"deveria ter falhado alto: {ruim}")


def test_config_vivo_roteia_as_campanhas_de_hoje():
    """Config REAL do cliente: as 5 campanhas ativas em 09/08/2026 têm que cair
    no modelo certo. Este é o teste que teria pego o problema antes do deploy."""
    caminho = Path(__file__).resolve().parent.parent / "configs" / "active_models" / "devclub.yaml"
    cfg = ABTestConfig.from_active_model_yaml(caminho)
    assert _qual(cfg, CAMP_ANTIGA_CHAMPION) == "challenger_abr28"
    assert _qual(cfg, CAMP_NOVA_CHAMPION) == "challenger_abr28"
    assert _qual(cfg, CAMP_ANTIGA_CHALLENGER) == "challenger_jul_24"
    assert _qual(cfg, CAMP_NOVA_CHALLENGER) == "challenger_jul_24"
    assert _qual(cfg, CAMP_NOVA_CHALLENGER_TOP50) == "challenger_jul_24"


def test_config_vivo_manda_o_evento_certo_pro_pixel_certo():
    """Cada campanha nova otimiza por um evento específico num pixel específico.
    Se o evento não sair naquele pixel, a campanha treina no vazio."""
    caminho = Path(__file__).resolve().parent.parent / "configs" / "active_models" / "devclub.yaml"
    cfg = ABTestConfig.from_active_model_yaml(caminho)
    PIXEL_NOVO = "1349518197389751"

    champion = cfg.variants["challenger_abr28"]
    destinos_champion = {(d.event_name, d.pixel_id) for d in (champion.capi_secondary_hq_events or [])}
    assert ("abr_28_top30", PIXEL_NOVO) in destinos_champion

    challenger = cfg.variants["challenger_jul_24"]
    destinos_challenger = {(d.event_name, d.pixel_id) for d in (challenger.capi_secondary_hq_events or [])}
    assert ("jul_24_top30", PIXEL_NOVO) in destinos_challenger
    assert ("jul_24_top50", PIXEL_NOVO) in destinos_challenger

    # top30 = top 30% = D8-D10 nos dois modelos (mesma régua, senão a comparação mente)
    for destinos, nome in ((champion.capi_secondary_hq_events, "abr_28_top30"),
                           (challenger.capi_secondary_hq_events, "jul_24_top30")):
        d = next(x for x in destinos if x.event_name == nome and x.pixel_id == PIXEL_NOVO)
        assert list(d.decils) == ["D08", "D09", "D10"], f"{nome}: faixa {d.decils}"


if __name__ == "__main__":
    for nome, fn in sorted(list(globals().items())):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"✅ {nome}")
    print("\nTodos os testes passaram.")
