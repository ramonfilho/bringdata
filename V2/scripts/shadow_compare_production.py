#!/usr/bin/env python3
"""
shadow_compare_production.py

Compara o pipeline de produção ANTIGO (pré-migração) com o pipeline NOVO
(usando core/) na mesma entrada de dados.

Propósito: validar paridade antes de substituir os componentes antigos por core/.

Fontes de dados:
  --file leads.xlsx          Arquivo local (Excel ou CSV)
  --source sheets            Google Sheets de produção (via LeadDataLoader)

Uso:
    # Comparar com Sheets de produção (padrão quando --file não é informado):
    python scripts/shadow_compare_production.py --source sheets

    # Comparar com arquivo local:
    python scripts/shadow_compare_production.py --file caminho/leads.xlsx

    # Componente específico (medium | category | encoding | all):
    python scripts/shadow_compare_production.py --source sheets --component medium

    # Modo verbose — imprime amostras de diferenças:
    python scripts/shadow_compare_production.py --source sheets --verbose

Saída:
    - Resumo por componente: quantas colunas/linhas divergem
    - Para cada coluna divergente: % de linhas diferentes + amostra
    - Exit code 0 se paridade OK, 1 se há divergências
"""

from __future__ import annotations

import argparse
import os
import sys
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT.parent))

logging.basicConfig(level=logging.WARNING, format='%(levelname)s — %(name)s — %(message)s')
logger = logging.getLogger('shadow_compare')

# ---------------------------------------------------------------------------
# Import OLD components (pré-migração)
# ---------------------------------------------------------------------------
from V2.src.data_processing.medium_unification import unify_medium_columns as _old_unify_medium
from V2.src.data_processing.category_unification import unificar_categorias_completo as _old_unify_categories
from V2.src.features.encoding import apply_categorical_encoding as _old_apply_encoding
from V2.src.data_processing.preprocessing import (
    remove_duplicates, clean_columns, remove_campaign_features,
    remove_technical_fields, rename_long_column_names,
)

# ---------------------------------------------------------------------------
# Import NEW core/ components
# ---------------------------------------------------------------------------
from V2.src.core.medium import unify_medium as _new_unify_medium
from V2.src.core.category_unification import unify_categories as _new_unify_categories
from V2.src.core.encoding import apply_encoding as _new_apply_encoding
from V2.src.core.preprocessing import preprocess as _new_preprocess
from V2.src.core.client_config import ClientConfig

# ---------------------------------------------------------------------------
# Shared components (idênticos nos dois pipelines)
# ---------------------------------------------------------------------------
from V2.src.core.utm import unify_utm
from V2.src.core.feature_engineering import create_features as _create_features

CONFIG_PATH = ROOT / 'configs' / 'clients' / 'devclub.yaml'


# ---------------------------------------------------------------------------
# Carregamento de dados
# ---------------------------------------------------------------------------

def _load_client_config() -> ClientConfig:
    return ClientConfig.from_yaml(str(CONFIG_PATH))


def _get_model_artifacts() -> Dict:
    """Lê mlflow_run_id do active_model.yaml sem instanciar o pipeline completo."""
    import yaml
    active_model_path = ROOT / 'configs' / 'active_model.yaml'
    with open(active_model_path) as f:
        data = yaml.safe_load(f)
    mlflow_run_id = data.get('active_model', {}).get('mlflow_run_id')
    return {'mlflow_run_id': mlflow_run_id, 'model_path': None}


def _load_from_file(filepath: str) -> pd.DataFrame:
    """Carrega leads de um arquivo Excel ou CSV (formato bruto de produção)."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

    if filepath.lower().endswith('.csv'):
        df = pd.read_csv(filepath)
    else:
        df = pd.read_excel(filepath)

    print(f"  Arquivo: {path.name} — {len(df):,} linhas")
    return df


def _load_from_sheets() -> pd.DataFrame:
    """
    Carrega leads do Google Sheets de produção via LeadDataLoader.

    Usa training_mode=True para que as colunas demográficas cheguem com
    os nomes originais do formulário — mesmo formato que os arquivos Excel
    de produção.  Em seguida, mapeia para os nomes canônicos usados pelo
    production_pipeline (E-mail, Data, Nome Completo, …).
    """
    from V2.src.validation.data_loader import LeadDataLoader

    print("  Baixando leads do Google Sheets…")
    loader = LeadDataLoader()
    sheets_df = loader.load_leads_from_sheets(
        sheets_url=None,       # usa GOOGLE_SHEETS_URL ou padrão
        start_date=None,       # sem filtro de data — todos os leads
        end_date=None,
        use_cache=False,       # sempre dados frescos
        num_sheets=1,          # aba de produção
        include_secondary=False,
        training_mode=True,    # colunas demográficas com nomes originais
    )

    if sheets_df.empty:
        raise RuntimeError("Google Sheets retornou DataFrame vazio")

    # Mapear snake_case → formato canônico do production_pipeline
    # (mesmo mapeamento feito por ingestion.py em read_all_training_sources)
    raw = pd.DataFrame()
    raw['E-mail']         = sheets_df.get('email', pd.NA)
    raw['Nome Completo']  = sheets_df.get('nome', pd.NA)
    raw['Telefone']       = sheets_df.get('telefone', pd.NA)
    raw['Data']           = sheets_df.get('data_captura', pd.NA)
    raw['Campaign']       = sheets_df.get('campaign', pd.NA)
    raw['Source']         = sheets_df.get('source', pd.NA)
    raw['Medium']         = sheets_df.get('medium', pd.NA)
    raw['Term']           = sheets_df.get('term', pd.NA)
    raw['Content']        = sheets_df.get('content', pd.NA)

    # Colunas demográficas restantes (nomes originais do formulário)
    cols_consumidas = {'email', 'nome', 'telefone', 'data_captura',
                       'campaign', 'source', 'medium', 'term', 'content',
                       'lead_score', 'decile'}
    for col in sheets_df.columns:
        if col not in cols_consumidas and col not in raw.columns:
            raw[col] = sheets_df[col]

    print(f"  Google Sheets — {len(raw):,} leads carregados")
    return raw


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _pipeline_old(df: pd.DataFrame, config: ClientConfig, artifacts: Dict) -> pd.DataFrame:
    """Pipeline antigo — funções individuais de data_processing/."""
    df = remove_duplicates(df)
    df = clean_columns(df)
    df = remove_campaign_features(df)
    df = unify_utm(df, config.utm)
    df = _old_unify_medium(df)
    df = rename_long_column_names(df)
    df = _old_unify_categories(df)
    df = remove_technical_fields(df)
    df = _create_features(df, config.feature)
    df = _old_apply_encoding(
        df,
        versao='v1',
        medium_strategy='binary_top3',
        mlflow_run_id=artifacts.get('mlflow_run_id'),
        model_path=artifacts.get('model_path'),
    )
    return df


def _pipeline_new(df: pd.DataFrame, config: ClientConfig, artifacts: Dict) -> pd.DataFrame:
    """Pipeline novo — 100% core/. Espelho exato de production_pipeline.py."""
    df = _new_preprocess(df, config.ingestion, config.feature)
    df = unify_utm(df, config.utm)
    df = _new_unify_medium(
        df,
        config.medium,
        artifacts if (artifacts.get('mlflow_run_id') or artifacts.get('model_path')) else None,
    )
    df = _new_unify_categories(df, config.category)
    df = _create_features(df, config.feature)
    df = _new_apply_encoding(df, config.encoding, artifacts)
    return df


# ---------------------------------------------------------------------------
# Comparação
# ---------------------------------------------------------------------------

def compare_dataframes(old: pd.DataFrame, new: pd.DataFrame, component: str, verbose: bool) -> dict:
    result = {
        'component': component,
        'ok': True,
        'row_diff': 0,
        'col_old_only': [],
        'col_new_only': [],
        'divergent_cols': {},
    }

    if len(old) != len(new):
        result['ok'] = False
        result['row_diff'] = len(new) - len(old)
        return result

    cols_old = set(old.columns)
    cols_new = set(new.columns)
    result['col_old_only'] = sorted(cols_old - cols_new)
    result['col_new_only'] = sorted(cols_new - cols_old)
    if result['col_old_only'] or result['col_new_only']:
        result['ok'] = False

    common_cols = sorted(cols_old & cols_new)
    for col in common_cols:
        s_old = old[col].reset_index(drop=True)
        s_new = new[col].reset_index(drop=True)

        if pd.api.types.is_numeric_dtype(s_old) and pd.api.types.is_numeric_dtype(s_new):
            diff = (s_old - s_new).abs()
            pct = float((diff > 1e-9).mean())
            if pct > 0:
                result['divergent_cols'][col] = {
                    'type': 'numeric',
                    'max_diff': float(diff.max()),
                    'pct_rows_differ': pct,
                }
        else:
            mismatch = (s_old.astype(str) != s_new.astype(str))
            pct = float(mismatch.mean())
            if pct > 0:
                result['divergent_cols'][col] = {
                    'type': 'categorical',
                    'pct_rows_differ': pct,
                    'sample_old': s_old[mismatch].head(3).tolist(),
                    'sample_new': s_new[mismatch].head(3).tolist(),
                }

    if result['divergent_cols']:
        result['ok'] = False

    return result


# ---------------------------------------------------------------------------
# Componentes isolados
# ---------------------------------------------------------------------------

def compare_medium(df_raw: pd.DataFrame, config: ClientConfig, artifacts: Dict, verbose: bool) -> dict:
    base = _new_preprocess(df_raw.copy(), config.ingestion, config.feature)
    base = unify_utm(base, config.utm)
    old = _old_unify_medium(base.copy())
    new = _new_unify_medium(
        base.copy(),
        config.medium,
        artifacts if (artifacts.get('mlflow_run_id') or artifacts.get('model_path')) else None,
    )

    divergent = {}
    if 'Medium' in old.columns and 'Medium' in new.columns:
        mismatch = (old['Medium'].astype(str) != new['Medium'].astype(str))
        pct = float(mismatch.mean())
        if pct > 0:
            divergent['Medium'] = {
                'type': 'categorical',
                'pct_rows_differ': pct,
                'sample_old': old['Medium'][mismatch].head(5).tolist(),
                'sample_new': new['Medium'][mismatch].head(5).tolist(),
            }

    return {
        'component': 'medium',
        'ok': len(divergent) == 0,
        'row_diff': 0,
        'col_old_only': [],
        'col_new_only': [],
        'divergent_cols': divergent,
    }


def compare_category(df_raw: pd.DataFrame, config: ClientConfig, artifacts: Dict, verbose: bool) -> dict:
    base = _new_preprocess(df_raw.copy(), config.ingestion, config.feature)
    base = unify_utm(base, config.utm)
    base = _old_unify_medium(base)   # mesmo medium nos dois ramos
    old = _old_unify_categories(base.copy())
    new = _new_unify_categories(base.copy(), config.category)
    return compare_dataframes(old, new, 'category', verbose)


def compare_encoding(df_raw: pd.DataFrame, config: ClientConfig, artifacts: Dict, verbose: bool) -> dict:
    # Aplicar todos os passos anteriores identicamente
    base = _new_preprocess(df_raw.copy(), config.ingestion, config.feature)
    base = unify_utm(base, config.utm)
    base = _old_unify_medium(base)
    base = _old_unify_categories(base)
    base = _create_features(base, config.feature)
    old = _old_apply_encoding(
        base.copy(),
        versao='v1',
        medium_strategy='binary_top3',
        mlflow_run_id=artifacts.get('mlflow_run_id'),
        model_path=artifacts.get('model_path'),
    )
    new = _new_apply_encoding(base.copy(), config.encoding, artifacts)
    return compare_dataframes(old, new, 'encoding', verbose)


def compare_all(df_raw: pd.DataFrame, config: ClientConfig, artifacts: Dict, verbose: bool) -> dict:
    old = _pipeline_old(df_raw.copy(), config, artifacts)
    new = _pipeline_new(df_raw.copy(), config, artifacts)
    return compare_dataframes(old, new, 'full_pipeline', verbose)


# ---------------------------------------------------------------------------
# Predições
# ---------------------------------------------------------------------------

def _load_predictor():
    """Carrega LeadScoringPredictor com o modelo ativo (sem instanciar LeadScoringPipeline)."""
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from V2.src.model.prediction import LeadScoringPredictor
    predictor = LeadScoringPredictor(use_active_model=True)
    predictor.load_model()
    return predictor


def compare_predictions(df_raw: pd.DataFrame, config: ClientConfig, artifacts: Dict, verbose: bool) -> dict:
    """
    Roda modelo de produção sobre o output de cada pipeline e compara scores.

    Validação mais forte: garante que features idênticas → modelo retorna
    exatamente os mesmos scores (float64 bit-a-bit).
    """
    predictor = _load_predictor()

    df_old = _pipeline_old(df_raw.copy(), config, artifacts)
    df_new = _pipeline_new(df_raw.copy(), config, artifacts)

    X_old = predictor.prepare_features(df_old)
    X_new = predictor.prepare_features(df_new)

    scores_old = predictor.model.predict_proba(X_old)[:, 1]
    scores_new = predictor.model.predict_proba(X_new)[:, 1]

    diff = np.abs(scores_old - scores_new)
    max_diff   = float(diff.max())
    mean_diff  = float(diff.mean())
    pct_differ = float((diff > 1e-9).mean())

    ok = pct_differ == 0.0

    result = {
        'component': 'predictions (lead_score)',
        'ok': ok,
        'row_diff': 0,
        'col_old_only': [],
        'col_new_only': [],
        'divergent_cols': {},
        '_scores_old': scores_old,
        '_scores_new': scores_new,
        '_max_diff': max_diff,
        '_mean_diff': mean_diff,
        '_pct_differ': pct_differ,
        '_n_leads': len(scores_old),
    }

    return result


def _print_prediction_result(r: dict, verbose: bool):
    comp = r['component']
    status = "OK" if r['ok'] else "DIVERGÊNCIA"
    print(f"\n[{comp}] {status}")
    print(f"  Leads avaliados: {r['_n_leads']:,}")
    print(f"  Score OLD — min={r['_scores_old'].min():.6f}  max={r['_scores_old'].max():.6f}  mean={r['_scores_old'].mean():.6f}")
    print(f"  Score NEW — min={r['_scores_new'].min():.6f}  max={r['_scores_new'].max():.6f}  mean={r['_scores_new'].mean():.6f}")
    if r['ok']:
        print("  Scores bit-a-bit idênticos ✓")
    else:
        pct = r['_pct_differ'] * 100
        print(f"  {pct:.2f}% dos leads têm score diferente")
        print(f"  max_diff={r['_max_diff']:.2e}  mean_diff={r['_mean_diff']:.2e}")
        if verbose:
            idx_diff = np.where(np.abs(r['_scores_old'] - r['_scores_new']) > 1e-9)[0][:5]
            for i in idx_diff:
                print(f"    lead {i}: old={r['_scores_old'][i]:.8f}  new={r['_scores_new'][i]:.8f}")


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------

def print_report(results: list, verbose: bool) -> bool:
    all_ok = True
    print("\n" + "=" * 60)
    print("SHADOW COMPARE — RELATÓRIO")
    print("=" * 60)

    for r in results:
        comp = r['component']
        status = "OK" if r['ok'] else "DIVERGÊNCIA"
        print(f"\n[{comp}] {status}")

        if r['row_diff'] != 0:
            print(f"  Linhas: {r['row_diff']:+d}")
        if r['col_old_only']:
            print(f"  Colunas só no OLD ({len(r['col_old_only'])}): {r['col_old_only']}")
        if r['col_new_only']:
            print(f"  Colunas só no NEW ({len(r['col_new_only'])}): {r['col_new_only']}")

        if r['divergent_cols']:
            all_ok = False
            print(f"  Colunas divergentes: {len(r['divergent_cols'])}")
            for col, info in r['divergent_cols'].items():
                pct = info['pct_rows_differ'] * 100
                if info['type'] == 'numeric':
                    print(f"    {col}: {pct:.1f}% linhas diferem, max_diff={info['max_diff']:.8f}")
                else:
                    print(f"    {col}: {pct:.1f}% linhas diferem")
                    if verbose:
                        print(f"      OLD: {info['sample_old']}")
                        print(f"      NEW: {info['sample_new']}")
        elif r['ok']:
            print("  Paridade perfeita ✓")
        else:
            all_ok = False

    print("\n" + "=" * 60)
    if all_ok:
        print("RESULTADO: PARIDADE OK — migração aprovada")
    else:
        print("RESULTADO: DIVERGÊNCIAS ENCONTRADAS — NÃO migrar ainda")
    print("=" * 60 + "\n")
    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Shadow compare: old vs new production pipeline')

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--file', help='Arquivo de leads (.xlsx ou .csv)')
    source_group.add_argument('--source', choices=['sheets'], help='Fonte de dados: sheets (Google Sheets de produção)')

    parser.add_argument(
        '--component',
        choices=['medium', 'category', 'encoding', 'all'],
        default='all',
        help='Componente a comparar (default: all)',
    )
    parser.add_argument('--predict', action='store_true', help='Também rodar modelo de produção e comparar scores')
    parser.add_argument('--verbose', action='store_true', help='Imprimir amostras de diferenças')
    args = parser.parse_args()

    config = _load_client_config()

    print(f"\nCarregando modelo ativo…")
    artifacts = _get_model_artifacts()
    print(f"  mlflow_run_id: {artifacts.get('mlflow_run_id')}")
    print(f"  model_path:    {artifacts.get('model_path')}")

    print(f"\nCarregando leads…")
    if args.file:
        df_raw = _load_from_file(args.file)
    else:  # --source sheets
        df_raw = _load_from_sheets()

    results = []

    if args.component in ('medium', 'all'):
        print("\nComparando: medium…")
        results.append(compare_medium(df_raw, config, artifacts, args.verbose))

    if args.component in ('category', 'all'):
        print("Comparando: category…")
        results.append(compare_category(df_raw, config, artifacts, args.verbose))

    if args.component in ('encoding', 'all'):
        print("Comparando: encoding…")
        results.append(compare_encoding(df_raw, config, artifacts, args.verbose))

    if args.component == 'all':
        print("Comparando: pipeline completo…")
        results.append(compare_all(df_raw, config, artifacts, args.verbose))

    pred_result = None
    if args.predict:
        print("Comparando: scores do modelo de produção…")
        pred_result = compare_predictions(df_raw, config, artifacts, args.verbose)

    ok = print_report(results, args.verbose)

    if pred_result is not None:
        _print_prediction_result(pred_result, args.verbose)
        if not pred_result['ok']:
            ok = False

    print()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
