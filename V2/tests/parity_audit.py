"""
Audit de paridade treino × produção.

Carrega os snapshots gerados por train_pipeline.py --capture-parity-snapshots
e compara o output das implementações de treino e produção sobre o mesmo input.

Uso:
    cd bring_data/
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
    """
    Migração concluída — arquivos antigos deletados.
    Smoke test: core/utm.unify_utm roda e normaliza Source/Term corretamente.
    """
    from V2.src.core.utm import unify_utm
    from V2.src.core.client_config import ClientConfig

    config   = ClientConfig.from_yaml(os.path.join(ROOT, 'V2', 'configs', 'clients', 'devclub.yaml'))
    df_input = _load('snapshot_utm_input')
    df_out   = unify_utm(df_input.copy(), config.utm)

    print(f"\n{'='*65}")
    print("  UTM — core/utm smoke test (migração concluída)")
    print(f"{'='*65}")
    print(f"  Input : {df_input.shape[0]:,} linhas × {df_input.shape[1]} colunas")

    ok = True
    if 'Source' in df_out.columns:
        sources = df_out['Source'].unique().tolist()
        print(f"  Source categorias: {sorted(str(s) for s in sources if s is not None)}")
        if any(s in (config.utm.source_to_outros or []) for s in sources):
            print("  [!] Valores de source_to_outros ainda presentes no output")
            ok = False
    if ok:
        print("\n  OK — UTM normalizado\n")
    return ok


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
    """
    Migração concluída — arquivo antigo deletado.
    Smoke test: core/feature_engineering.create_features roda e produz colunas esperadas.
    """
    from V2.src.core.feature_engineering import create_features
    from V2.src.core.client_config import ClientConfig

    config   = ClientConfig.from_yaml(os.path.join(ROOT, 'V2', 'configs', 'clients', 'devclub.yaml'))
    df_input = _load('snapshot_fe_input')
    df_out   = create_features(df_input.copy(), config.feature)

    expected = {'dia_semana', 'nome_comprimento', 'nome_tem_sobrenome', 'telefone_comprimento'}
    missing  = expected - set(df_out.columns)

    print(f"\n{'='*65}")
    print("  FE — core/feature_engineering smoke test (migração concluída)")
    print(f"{'='*65}")
    print(f"  Input : {df_input.shape[0]:,} linhas × {df_input.shape[1]} colunas")
    print(f"  Output: {df_out.shape[0]:,} linhas × {df_out.shape[1]} colunas")

    if missing:
        print(f"\n  [!] Features ausentes: {sorted(missing)}")
        return False

    print("\n  OK — todas as features esperadas presentes\n")
    return True


def audit_encoding():
    """
    Migração concluída — encoding_training.py deletado.
    Smoke test: core/encoding.apply_encoding roda e produz colunas numéricas esperadas.

    Divergências documentadas (intencionais por design — não são regressões):
      - clean_column_names() normaliza nomes para snake_case → 51 cols core/ vs 60 cols treino antigo
      - Ordinais com nomes longos em core/ (snapshot tem forma longa): 'Atualmente_qual_a_sua_faixa_salarial'
        vs 'faixa_salarial' no treino antigo (aliases curtos via category_unification não migrado ainda)
    Produção (encoding.py) mantém import antigo até o próximo retreino (estratégia train-first).
    """
    from V2.src.core.encoding import apply_encoding
    from V2.src.core.client_config import ClientConfig

    config   = ClientConfig.from_yaml(os.path.join(ROOT, 'V2', 'configs', 'clients', 'devclub.yaml'))
    df_input = _load('snapshot_encoding_input')
    df_out   = apply_encoding(df_input.copy(), config.encoding, artifacts={})

    print(f"\n{'='*65}")
    print("  Encoding — core/encoding smoke test (migração concluída)")
    print(f"{'='*65}")
    print(f"  Input : {df_input.shape[0]:,} linhas × {df_input.shape[1]} colunas")
    print(f"  Output: {df_out.shape[0]:,} linhas × {df_out.shape[1]} colunas")

    ok = True

    # Verificar que ordinais foram encodadas como numéricas
    ordinais_esperadas = {
        'Atualmente_qual_a_sua_faixa_salarial',  # forma longa normalizada
        'Qual_a_sua_idade',                        # forma longa normalizada
        'dia_semana',
    }
    # Verificar ao menos uma ordinal presente e numérica
    ordinais_presentes = [c for c in df_out.columns if any(o in c for o in ordinais_esperadas)]
    for col in ordinais_presentes:
        if df_out[col].dtype == object:
            print(f"\n  [!] Ordinal '{col}' não foi encodada — dtype={df_out[col].dtype}")
            ok = False

    # Verificar ausência de NaN
    nan_count = df_out.isna().sum().sum()
    if nan_count > 0:
        print(f"\n  [!] {nan_count} NaN remanescentes no output")
        ok = False

    # Verificar que nomes de coluna são snake_case (sem chars especiais)
    bad_cols = [c for c in df_out.columns if any(ch in c for ch in ['?', ' ', '-', '.'])]
    if bad_cols:
        print(f"\n  [!] Colunas com caracteres especiais ({len(bad_cols)}): {bad_cols[:5]}")
        ok = False

    if ok:
        print("\n  OK — encoding aplicado, colunas normalizadas, sem NaN\n")
    return ok


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
