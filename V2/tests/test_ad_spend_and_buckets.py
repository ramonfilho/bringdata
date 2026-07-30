"""Testes do relatório de negócio+modelo: forma de pagamento (core), montagem do
bucket_map/rótulos (ModelRegistry) e métricas de negócio por balde.

Rodar: python3 V2/tests/test_ad_spend_and_buckets.py
"""
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # V2/ no path

import pandas as pd

from src.core.payment_method import forma_pagamento, CARTAO, BOLETO, DESCONHECIDO


def test_forma_pagamento():
    assert forma_pagamento("guru") == CARTAO
    assert forma_pagamento("Hotmart") == CARTAO          # normaliza case
    assert forma_pagamento("tmb") == BOLETO
    assert forma_pagamento("boletex") == BOLETO
    assert forma_pagamento("asaas") == BOLETO
    assert forma_pagamento("pix_novo") == DESCONHECIDO   # gateway fora do mapa não chuta
    assert forma_pagamento(None) == DESCONHECIDO


# ─────────────────────────── fixture de config (não é produção) ───────────────────────────
# A versão anterior destes testes lia `configs/active_models/devclub.yaml` (o config VIVO) e
# ficou vermelha por 5 dias sem ninguém notar: a promoção do abr28 a Champion em 25/07/2026
# invalidou `assert tags.get("HQLB") == "Challenger"`. Teste que lê config de produção testa
# a operação, não o código, e quebra a cada mudança legítima.
#
# Os nomes são fictícios de propósito (`modelo_a`/`modelo_b`), pra o teste nunca voltar a
# depender de qual modelo está no ar. O `modelo_a` troca de papel em 01/03/2026 pra
# exercitar a datação. Fica INLINE porque `V2/tests/fixtures/` é gitignorado (o arquivo não
# viajaria no repo nem na imagem, e o teste passaria só nesta máquina).
FIXTURE_YAML = """
active_model:
  model_name: fixture_modelo_a
  mlflow_run_id: run_a
  trained_at: '2026-01-01T00:00:00'
ab_test:
  enabled: true
  variants:
    modelo_a:
      run_id: run_a
      role: champion
      role_history:
        - {role: challenger, from: 2026-01-01}
        - {role: champion,   from: 2026-03-01}
      campaign_tag: "TAGA"
      display_name: "Champion (modelo_a)"
      utm_pattern: {utm_campaign: "TAGA"}
      capi_event_name: a_lq
      capi_event_name_high_quality: a_hq
      conversion_rates: {D01: 0.001, D02: 0.001, D03: 0.001, D04: 0.001, D05: 0.001,
                         D06: 0.001, D07: 0.001, D08: 0.001, D09: 0.001, D10: 0.01}
    modelo_b:
      run_id: run_b
      role: challenger
      role_history:
        - {role: challenger, from: 2026-06-01}
      campaign_tag: "TAGB"
      display_name: "Challenger (modelo_b)"
      utm_pattern: {utm_campaign: "TAGB"}
      capi_event_name: b_lq
      capi_event_name_high_quality: b_hq
      conversion_rates: {D01: 0.001, D02: 0.001, D03: 0.001, D04: 0.001, D05: 0.001,
                         D06: 0.001, D07: 0.001, D08: 0.001, D09: 0.001, D10: 0.01}
"""

_FIXTURE_CACHE = []


def fixture_path() -> Path:
    """Materializa a fixture num arquivo temporário (o loader recebe caminho, não texto)."""
    if not _FIXTURE_CACHE:
        d = Path(tempfile.mkdtemp(prefix="ab_arm_fixture_"))
        p = d / "active_models_fixture.yaml"
        p.write_text(FIXTURE_YAML, encoding="utf-8")
        _FIXTURE_CACHE.append(p)
    return _FIXTURE_CACHE[0]


def test_bucket_map_e_rotulos():
    from src.validation.model_performance import ModelRegistry
    reg = ModelRegistry(fixture_path())
    # tags do YAML viram (TAG, balde); Challenger antes de Champion (precedência)
    tags = dict(reg.bucket_map["tags"])
    assert tags.get("TAGA") == "Champion"        # modelo_a: papel de hoje na fixture
    assert tags.get("TAGB") == "Challenger"
    assert reg.bucket_map["fallback"] == "Lead"
    # precedência: challenger vem antes de champion na lista
    assert reg.bucket_map["tags"][0][1] == "Challenger"
    # rótulos vêm do display_name do YAML (fonte única, = digest)
    assert "modelo_a" in reg.bucket_label("Champion")
    assert "modelo_b" in reg.bucket_label("Challenger")
    # baldes de canal (espelham as linhas do debriefing do cliente)
    assert reg.bucket_label("Lead") == "Lead Padrão (Meta)"
    assert reg.bucket_label("Google") == "Google"
    assert reg.bucket_label("Organico") == "Orgânico/Outro"


def test_bucket_map_e_o_mesmo_dos_dois_construtores():
    """`ModelRegistry.bucket_map` e `ABTestConfig.campaign_bucket_map` eram DUAS
    implementações independentes da mesma derivação tag->papel; divergiram na promoção
    do abr28. Agora as duas delegam pro miolo — este teste é a guarda de que continuam
    delegando (e roda sobre o config VIVO de propósito: o que se exige aqui é igualdade
    entre as duas, não um valor específico)."""
    from src.core.client_config import ABTestConfig
    from src.validation.model_performance import ModelRegistry

    vivo = Path(__file__).resolve().parents[1] / "configs" / "active_models" / "devclub.yaml"
    reg = ModelRegistry(vivo)
    ab = ABTestConfig.from_active_model_yaml(vivo)
    assert reg.bucket_map["tags"] == ab.campaign_bucket_map()["tags"]
    assert reg.bucket_map["fallback"] == ab.campaign_bucket_map()["fallback"]


def test_papel_tem_data():
    """Promoção não reescreve o passado: a MESMA tag resolve diferente antes e depois."""
    from src.core.ab_arm import bucket_map_for, load_arm_config

    cfg = load_arm_config(fixture_path())
    assert dict(bucket_map_for(as_of=date(2026, 2, 1), config=cfg)["tags"]) == {
        "TAGA": "Challenger"}                      # modelo_b ainda não existia
    assert dict(bucket_map_for(as_of=date(2026, 3, 1), config=cfg)["tags"])["TAGA"] == \
        "Champion"                                  # dia da promoção (from é inclusivo)
    assert dict(bucket_map_for(as_of=date(2026, 6, 1), config=cfg)["tags"]) == {
        "TAGB": "Challenger", "TAGA": "Champion"}
    # e o papel resolve por PAPEL, não pela substring do nome da chave
    assert cfg.variant_for_role("champion") == "modelo_a"
    assert cfg.variant_for_role("challenger") == "modelo_b"
    assert cfg.variant_for_role("champion", date(2026, 2, 1)) is None


def test_channel_from_source():
    from src.monitoring.campaign_classifier import channel_from_source
    assert channel_from_source("facebook-ads") == "meta"
    assert channel_from_source("FB") == "meta"          # alias + case
    assert channel_from_source("ig") == "meta"
    assert channel_from_source("google-ads") == "google"
    assert channel_from_source("organico") == "organic"
    assert channel_from_source("manychat") == "organic"  # fora de Meta/Google
    assert channel_from_source(None) == "organic"        # vazio → sem gasto


def test_bucket_of_lead_canal_x_tag():
    from src.validation.model_performance import _bucket_of_lead, ModelRegistry
    bm = ModelRegistry(fixture_path()).bucket_map
    # Meta: split pela tag A/B
    assert _bucket_of_lead("facebook-ads", "DEVLF|...|TAGA|...", bm) == "Champion"
    assert _bucket_of_lead("facebook-ads", "DEVLF|...|TAGB", bm) == "Challenger"
    assert _bucket_of_lead("facebook-ads", "DEVLF sem tag", bm) == "Lead"   # Meta sem tag
    # Nome SEM prefixo de captação continua sendo classificado pela tag. É por isso que
    # `bucket_from_utm` NÃO passa pelo filtro de captação do `resolve_arm`: aqui o filtro
    # de canal já aconteceu antes (utm_source), e exigir o padrão de nome jogaria campanha
    # real em 'Lead'.
    assert _bucket_of_lead("facebook-ads", "TAGB solta", bm) == "Challenger"
    # canal vence a tag: Google e orgânico saem do Meta mesmo com tag no nome
    assert _bucket_of_lead("google-ads", "qualquer TAGA", bm) == "Google"
    assert _bucket_of_lead("organico", "qualquer TAGB", bm) == "Organico"


def test_vocabulario_dos_involucros_e_fechado():
    """Contrato de saída: `daily_check_aggregations` cria o dict com 3 chaves e faz
    `if bucket in agg` sem `else`. Rótulo fora do vocabulário não levanta erro, ZERA o
    balde em silêncio e o funil sai no Slack sem as linhas por variante. Esta é a guarda
    de que nenhum invólucro vaza 'Controle'/'Indeterminado'."""
    from src.monitoring.campaign_classifier import bucket_from_utm
    from src.monitoring.daily_check_aggregations import _VARIANT_BUCKETS
    from src.validation.campaign_classifier import classify_variant

    permitido_variant = set(_VARIANT_BUCKETS) | {"EXTERNO"}
    nomes = [
        "DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | 2026-06-18 | LEADHQLB",
        "DEVLF | CAP | QUENTE | FASE 04 | ADV | LEAD | PG1 | LEADHQLB",
        "DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1 | JUL24_TOP10",
        "DEVLF | CAP | FRIO | FASE 04 | ADV | LEAD | PG1",
        "DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO API | LEAD | PG2",   # ambíguo
        "*DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO | LEAD | PG2",      # asterisco
        "devlf", "", None, float("nan"),
    ]
    for n in nomes:
        assert classify_variant(n) in permitido_variant, n
        assert bucket_from_utm(n, {"tags": [("HQLB", "Champion")], "fallback": "Lead"}) \
            in set(_VARIANT_BUCKETS), n


def test_captacao_aceita_publico_e_prefixo_sujo():
    """Duas correções com dinheiro medido atrás (auditoria 30/07/2026):
    QUENTE (R$ 2.271 em 29/07) caía em EXTERNO por o filtro exigir 'FRIO'; e a campanha
    real com asterisco na frente (R$ 7.383 / 1.813 leads em mai/2026) cairia em EXTERNO
    se o filtro fosse `startswith` em vez de substring."""
    from src.core.ab_arm import is_captacao

    assert is_captacao("DEVLF | CAP | QUENTE | FASE 04 | ADV | LEAD | PG1 | LEADHQLB")
    assert is_captacao("DEVLF | CAP | MORNO | FASE 04 | ADV | LEAD | PG1")
    assert is_captacao("*DEVLF | CAP | FRIO | FASE 04 | ADV | PIXEL NOVO | LEAD | PG2")
    assert not is_captacao("devlf")
    assert not is_captacao("DEVLF | AQUECIMENTO | FASE 01")


def test_bucket_metrics_negocio():
    from src.validation.model_performance import _bucket_metrics
    # 3 leads: 2 compraram (1 cartão guru R$2000, 1 boleto tmb R$1000), 1 não.
    df = pd.DataFrame({
        "converted": [True, True, False],
        "sale_value": [2000.0, 1000.0, 0.0],
        "sale_origin": ["guru", "tmb", None],
        "lead_score": [0.9, 0.8, 0.1],
        "decil": [10, 9, 1],
    })
    df["decile"] = df["decil"].apply(lambda d: f"D{int(d)}")
    b = _bucket_metrics(df, "Challenger", "Champion (abr_28)", investimento=1000.0, haircut=0.5)
    assert b.compradores_cartao == 1 and b.compradores_boleto == 1 and b.n_conversions == 2
    assert b.valor_cartao == 2000.0
    assert b.valor_boleto == 500.0            # 1000 × haircut 0.5
    assert b.faturamento == 2500.0            # 2000 + 500
    assert b.cpl == 1000.0 / 3                # invest / leads
    assert abs(b.roas - 2500.0 / 1000.0) < 1e-9
    assert b.lucro == 2500.0 - 1000.0


if __name__ == "__main__":
    test_forma_pagamento()
    test_bucket_map_e_rotulos()
    test_bucket_map_e_o_mesmo_dos_dois_construtores()
    test_papel_tem_data()
    test_channel_from_source()
    test_bucket_of_lead_canal_x_tag()
    test_vocabulario_dos_involucros_e_fechado()
    test_captacao_aceita_publico_e_prefixo_sujo()
    test_bucket_metrics_negocio()
    print("OK — testes de negócio+modelo passaram")
