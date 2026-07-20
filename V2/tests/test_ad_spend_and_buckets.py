"""Testes do relatório de negócio+modelo: forma de pagamento (core), montagem do
bucket_map/rótulos (ModelRegistry) e métricas de negócio por balde.

Rodar: python3 V2/tests/test_ad_spend_and_buckets.py
"""
import sys
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


def test_bucket_map_e_rotulos():
    from src.validation.model_performance import ModelRegistry
    reg = ModelRegistry()
    # tags do YAML viram (TAG, balde); Challenger antes de Champion (precedência)
    tags = dict(reg.bucket_map["tags"])
    assert tags.get("HQLB") == "Challenger"
    assert tags.get("LEADQUALIFIED") == "Champion"
    assert reg.bucket_map["fallback"] == "Lead"
    # rótulos vêm do display_name do YAML (fonte única, = digest)
    assert "abr_28" in reg.bucket_label("Challenger")
    assert "jan_30" in reg.bucket_label("Champion")
    # baldes de canal (espelham as linhas do debriefing do cliente)
    assert reg.bucket_label("Lead") == "Lead Padrão (Meta)"
    assert reg.bucket_label("Google") == "Google"
    assert reg.bucket_label("Organico") == "Orgânico/Outro"


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
    bm = ModelRegistry().bucket_map
    # Meta: split pela tag A/B
    assert _bucket_of_lead("facebook-ads", "DEVLF|...|LEADHQLB|...", bm) == "Challenger"
    assert _bucket_of_lead("facebook-ads", "DEVLF|...|LEADQUALIFIED", bm) == "Champion"
    assert _bucket_of_lead("facebook-ads", "DEVLF sem tag", bm) == "Lead"   # Meta sem tag
    # canal vence a tag: Google e orgânico saem do Meta mesmo com tag no nome
    assert _bucket_of_lead("google-ads", "qualquer LEADHQLB", bm) == "Google"
    assert _bucket_of_lead("organico", "qualquer LEADQUALIFIED", bm) == "Organico"


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
    test_channel_from_source()
    test_bucket_of_lead_canal_x_tag()
    test_bucket_metrics_negocio()
    print("OK — testes de negócio+modelo passaram")
