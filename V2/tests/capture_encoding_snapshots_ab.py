"""
Captura de snapshots de output de encoding por variante A/B.

Lê tests/fixtures/snapshot_encoding_input.pkl e, para cada variante ativa em
configs/active_models/{client}.yaml, aplica merge_encoding(base, variant.encoding_overrides)
e salva o output em tests/fixtures/snapshot_encoding_output_{variant_name}.pkl.

Encoding é função pura — não depende do dataset de treino. Logo, este script não
precisa rodar o pipeline de treino. O que muda entre variantes é só a configuração
mesclada (ordinal_variables + ohe_columns), que é determinística sobre o input.

Uso:
    cd bring_data/
    python -m V2.tests.capture_encoding_snapshots_ab [--client devclub]

Limitação atual (resolve em T1-19):
    artifacts={} aqui — não baixa feature_registry do MLflow para validar
    alinhamento de schema. T1-19 fecha esse gap.
"""

import os
import sys
import argparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

import pandas as pd

from V2.src.core.encoding import apply_encoding, merge_encoding
from V2.src.core.client_config import ClientConfig, ABTestConfig

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def capture(client: str = 'devclub') -> int:
    client_yaml = os.path.join(ROOT, 'V2', 'configs', 'clients', f'{client}.yaml')
    ab_yaml     = os.path.join(ROOT, 'V2', 'configs', 'active_models', f'{client}.yaml')
    input_pkl   = os.path.join(FIXTURES, 'snapshot_encoding_input.pkl')

    if not os.path.exists(input_pkl):
        print(f"[ERRO] {input_pkl} não existe — capture o input primeiro:")
        print("       python -m V2.src.train_pipeline --capture-parity-snapshots")
        return 1

    config = ClientConfig.from_yaml(client_yaml)
    ab     = ABTestConfig.from_active_model_yaml(ab_yaml)

    if not ab.enabled or not ab.variants:
        print(f"[SKIP] ab_test desabilitado ou sem variantes em {ab_yaml}")
        return 0

    df_input = pd.read_pickle(input_pkl)
    print(f"Input: {df_input.shape[0]:,} linhas × {df_input.shape[1]} colunas")
    print(f"Capturando {len(ab.variants)} variante(s)...\n")

    captured = 0
    for variant_name, variant in ab.variants.items():
        eff_encoding = merge_encoding(config.encoding, variant.encoding_overrides)
        df_out = apply_encoding(df_input.copy(), eff_encoding, artifacts={})

        out_pkl = os.path.join(FIXTURES, f'snapshot_encoding_output_{variant_name}.pkl')
        df_out.to_pickle(out_pkl)
        n_ord = len(eff_encoding.ordinal_variables or {})
        print(f"  [OK] {variant_name}: {df_out.shape[0]:,} × {df_out.shape[1]} "
              f"({n_ord} ordinais) → {os.path.basename(out_pkl)}")
        captured += 1

    print(f"\n{captured} snapshot(s) capturado(s) em {FIXTURES}")
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', default='devclub')
    args = parser.parse_args()
    sys.exit(capture(args.client))
