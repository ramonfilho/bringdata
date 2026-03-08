"""
Audit de paridade treino × produção.

Carrega os snapshots gerados por train_pipeline.py --capture-parity-snapshots
e compara o output das implementações de treino e produção sobre o mesmo input.

Uso:
    cd smart_ads/
    python V2/tests/parity_audit.py [--function utm|medium|fe|encoding|all]

Pré-requisito:
    python -m V2.src.train_pipeline --capture-parity-snapshots

Output:
    Para cada função: divergências coluna a coluna com exemplos de valores.
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _load(name: str) -> pd.DataFrame:
    path = os.path.join(FIXTURES, f'{name}.pkl')
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Snapshot '{name}.pkl' não encontrado.\n"
            "Execute: python -m V2.src.train_pipeline --capture-parity-snapshots"
        )
    return pd.read_pickle(path)


def _compare(df_treino: pd.DataFrame, df_prod: pd.DataFrame, label: str) -> bool:
    """Compara dois DataFrames coluna a coluna. Retorna True se idênticos."""
    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")
    print(f"  Treino  : {df_treino.shape[0]:,} linhas × {df_treino.shape[1]} colunas")
    print(f"  Produção: {df_prod.shape[0]:,} linhas × {df_prod.shape[1]} colunas")

    cols_so_treino = set(df_treino.columns) - set(df_prod.columns)
    cols_so_prod   = set(df_prod.columns)   - set(df_treino.columns)

    if cols_so_treino:
        print(f"\n  [!] Colunas só no treino  ({len(cols_so_treino)}): {sorted(cols_so_treino)}")
    if cols_so_prod:
        print(f"\n  [!] Colunas só na produção ({len(cols_so_prod)}): {sorted(cols_so_prod)}")

    cols_comuns = sorted(set(df_treino.columns) & set(df_prod.columns))
    divergencias = []

    for col in cols_comuns:
        s_t = df_treino[col].reset_index(drop=True)
        s_p = df_prod[col].reset_index(drop=True)
        n = min(len(s_t), len(s_p))
        s_t, s_p = s_t.iloc[:n], s_p.iloc[:n]

        try:
            if s_t.dtype == object or s_p.dtype == object:
                diff_mask = s_t.astype(str) != s_p.astype(str)
            else:
                diff_mask = ~np.isclose(
                    pd.to_numeric(s_t, errors='coerce').fillna(0),
                    pd.to_numeric(s_p, errors='coerce').fillna(0),
                    equal_nan=True
                )
        except Exception:
            diff_mask = s_t.astype(str) != s_p.astype(str)

        n_diff = diff_mask.sum()
        if n_diff > 0:
            divergencias.append((col, n_diff, 100 * n_diff / n, diff_mask, s_t, s_p))

    if not divergencias and not cols_so_treino and not cols_so_prod:
        print("\n  OK — outputs idênticos\n")
        return True

    if divergencias:
        print(f"\n  DIVERGÊNCIAS em {len(divergencias)} colunas comuns:\n")
        print(f"  {'Coluna':<45} {'# linhas':>10} {'%':>7}")
        print(f"  {'-'*45} {'-'*10} {'-'*7}")
        for col, n_diff, pct, *_ in sorted(divergencias, key=lambda x: -x[1]):
            print(f"  {col:<45} {n_diff:>10,} {pct:>6.1f}%")

        print()
        for col, n_diff, pct, diff_mask, s_t, s_p in sorted(divergencias, key=lambda x: -x[1])[:3]:
            exemplos = pd.DataFrame({
                'treino':   s_t[diff_mask].values[:5],
                'producao': s_p[diff_mask].values[:5],
            })
            print(f"  Exemplos — {col}:")
            print(exemplos.to_string(index=False))
            print()

    return False


# ---------------------------------------------------------------------------
# Audit por função
# ---------------------------------------------------------------------------

def audit_utm():
    from V2.src.data_processing.utm_training import unificar_utm_source_term
    from V2.src.data_processing.utm_unification import unify_utm_columns

    df_input = _load('snapshot_utm_input')
    df_treino = unificar_utm_source_term(df_input.copy())
    df_prod   = unify_utm_columns(df_input.copy())
    return _compare(df_treino, df_prod,
                    "UTM — unificar_utm_source_term (treino) vs unify_utm_columns (produção)")


def audit_medium():
    from V2.src.data_processing.medium_training import extrair_publico_medium
    from V2.src.data_processing.medium_production_training import unificar_medium_para_producao
    from V2.src.data_processing.medium_unification import unify_medium_columns

    df_input = _load('snapshot_medium_input')
    n_bruto  = df_input['Medium'].nunique() if 'Medium' in df_input.columns else 0

    df_step1, _ = extrair_publico_medium(df_input.copy())
    df_treino   = unificar_medium_para_producao(df_step1, n_bruto=n_bruto)
    df_prod     = unify_medium_columns(df_input.copy())
    return _compare(df_treino, df_prod,
                    "Medium — treino (extrair + unificar_para_producao) vs produção (unify_medium_columns)")


def audit_fe():
    from V2.src.features.feature_engineering_training import criar_features_derivadas
    from V2.src.features.engineering import create_derived_features

    df_input  = _load('snapshot_fe_input')
    df_treino = criar_features_derivadas(df_input.copy())
    df_prod   = create_derived_features(df_input.copy())
    return _compare(df_treino, df_prod,
                    "Feature Engineering — criar_features_derivadas (treino) vs create_derived_features (produção)")


def audit_encoding():
    from V2.src.features.encoding_training import aplicar_encoding_estrategico
    from V2.src.features.encoding import apply_categorical_encoding

    df_input  = _load('snapshot_encoding_input')
    df_treino = aplicar_encoding_estrategico(df_input.copy())
    try:
        df_prod = apply_categorical_encoding(df_input.copy())
    except Exception as e:
        print(f"\n  [!] Produção falhou: {e}")
        print("  Encoding de produção requer modelo ativo — rode com --set-active antes.\n")
        return None

    return _compare(df_treino, df_prod,
                    "Encoding — aplicar_encoding_estrategico (treino) vs apply_categorical_encoding (produção)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

AUDITS = {
    'utm':      audit_utm,
    'medium':   audit_medium,
    'fe':       audit_fe,
    'encoding': audit_encoding,
}

def main():
    parser = argparse.ArgumentParser(description='Audit de paridade treino × produção')
    parser.add_argument(
        '--function',
        choices=[*AUDITS.keys(), 'all'],
        default='all',
        help='Função a auditar (default: all)'
    )
    args = parser.parse_args()
    targets = list(AUDITS.keys()) if args.function == 'all' else [args.function]

    resultados = {}
    for nome in targets:
        try:
            resultados[nome] = AUDITS[nome]()
        except FileNotFoundError as e:
            print(f"\n  [SKIP] {nome}: {e}")
            resultados[nome] = None

    print(f"\n{'='*65}")
    print("  RESUMO")
    print(f"{'='*65}")
    for nome, ok in resultados.items():
        status = {True: "OK", False: "DIVERGÊNCIA", None: "SKIP (snapshot ausente)"}.get(ok, "ERRO")
        print(f"  {nome:<12} {status}")
    print()


if __name__ == '__main__':
    main()
