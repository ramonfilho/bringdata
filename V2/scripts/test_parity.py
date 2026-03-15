"""
Teste de paridade treino × produção.

Carrega dados brutos do Google Sheets para um período recente, processa pelos
dois pipelines (treino e produção) com os MESMOS dados de entrada e compara
as features coluna a coluna.

Uso:
    cd V2/
    python scripts/test_parity.py
    python scripts/test_parity.py --periodo LF45
    python scripts/test_parity.py --start 2026-02-03 --end 2026-02-23 --sample 200
"""

import sys
import os
import argparse
import tempfile
import logging
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── Períodos conhecidos ────────────────────────────────────────────────────────
PERIODOS = {
    'LF40':  ('2025-11-25', '2025-12-02'),
    'LF41':  ('2025-12-02', '2025-12-09'),
    'LF42':  ('2025-12-09', '2025-12-16'),
    'DEV19': ('2025-12-16', '2026-01-14'),
    'LF43':  ('2026-01-13', '2026-01-26'),
    'LF44':  ('2026-01-27', '2026-02-03'),
    'LF45':  ('2026-02-03', '2026-02-23'),
}

MLFLOW_RUN_ID = 'b58e2b98fb4242c1a77ec7427dde8b52'

PRODUCAO_SHEETS_URL = 'https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo'
BACKUP_SHEETS_URL   = 'https://docs.google.com/spreadsheets/d/1OqNYA5zU9ix1uf52ovRYIdLhcugzwgfKOheKxE_zgvE'


# ── Carregar dados brutos do Sheets ───────────────────────────────────────────

def load_raw_sheets(start: str, end: str) -> pd.DataFrame:
    """
    Carrega dados brutos do Google Sheets (planilha de produção + backup).
    Retorna DataFrame com colunas originais (Data, Nome Completo, etc.).
    """
    import subprocess, re, gspread
    from google.auth import default as gauth_default

    scopes = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly',
    ]
    creds, _ = gauth_default(scopes=scopes)
    gc = gspread.authorize(creds)

    dfs = []
    for url in [PRODUCAO_SHEETS_URL, BACKUP_SHEETS_URL]:
        sheet_id = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url).group(1)
        spreadsheet = gc.open_by_url(url)
        for ws in spreadsheet.worksheets()[:2]:
            csv_url = (
                f"https://docs.google.com/spreadsheets/d/{sheet_id}"
                f"/export?format=csv&gid={ws.id}"
            )
            with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp:
                r = subprocess.run(
                    ['curl', '-sL', '--max-time', '30', csv_url, '-o', tmp.name],
                    capture_output=True, timeout=35,
                )
                if r.returncode != 0:
                    continue
                try:
                    df_aba = pd.read_csv(tmp.name, low_memory=False)
                    df_aba = df_aba.loc[:, ~df_aba.columns.duplicated(keep='first')]
                    if 'Data' in df_aba.columns:
                        df_aba['Data'] = pd.to_datetime(df_aba['Data'], errors='coerce')
                    dfs.append(df_aba)
                except Exception:
                    pass
                finally:
                    os.unlink(tmp.name)

    if not dfs:
        raise RuntimeError("Não foi possível carregar dados do Google Sheets.")

    df = pd.concat(dfs, ignore_index=True, sort=False)
    df = df.loc[:, ~df.columns.duplicated(keep='first')]

    if 'Data' in df.columns:
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
        df = df[(df['Data'] >= start) & (df['Data'] <= end + ' 23:59:59')]

    if 'E-mail' in df.columns:
        df = df.drop_duplicates(subset='E-mail', keep='first')

    return df.reset_index(drop=True)


# ── Pipeline de treino (inline, todos os passos) ──────────────────────────────

def process_train_pipeline(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Processa leads pelo pipeline de treino até o encoding.

    Inclui TODOS os passos de preprocessing (os mesmos que a produção usa
    de src.data_processing.preprocessing) mais as funções específicas de treino
    para UTM, Medium, FE e encoding.
    """
    # Imports de preprocessing — mesmos que produção
    from src.data_processing.preprocessing import (
        remove_duplicates, clean_columns, remove_campaign_features,
        remove_technical_fields, rename_long_column_names,
    )
    # Imports específicos de treino
    from src.data_processing.utm_training import unificar_utm_source_term
    from src.data_processing.medium_production_training import unificar_medium_para_producao
    from src.data_processing.medium_training import extrair_publico_medium
    from src.data_processing.category_unification import unificar_categorias_completo
    from src.features.feature_engineering_training import criar_features_derivadas
    from src.features.encoding_training import aplicar_encoding_estrategico

    emails_norm = (
        df_raw['E-mail'].str.strip().str.lower()
        if 'E-mail' in df_raw.columns else None
    )

    df = df_raw.copy()

    # target dummy — feature_engineering_training requer coluna target
    if 'target' not in df.columns:
        df['target'] = 0

    # Preprocessing compartilhado (igual produção)
    df = remove_duplicates(df)
    df = clean_columns(df)
    df = remove_campaign_features(df)

    # UTM (versão treino)
    df = unificar_utm_source_term(df)

    # Medium (versão treino)
    if 'Medium' in df.columns:
        df, n_apos_extracao = extrair_publico_medium(df)
        n_bruto = df['Medium'].nunique()
        n_apos_norm = df['Medium'].nunique()
        df = unificar_medium_para_producao(
            df,
            n_bruto=n_bruto,
            n_apos_extracao=n_apos_extracao,
            n_apos_norm=n_apos_norm,
        )

    # Preprocessing compartilhado (continuação)
    df = rename_long_column_names(df)
    df = unificar_categorias_completo(df)
    df = remove_technical_fields(df)

    # Feature engineering (versão treino)
    df = criar_features_derivadas(df)

    # Encoding (versão treino)
    df_enc = aplicar_encoding_estrategico(df, medium_strategy='full')

    # Sanitizar nomes de colunas para bater com a produção
    # (encoding.py aplica str.replace('[^A-Za-z0-9_]', '_'); encoding_training.py não aplica)
    df_enc.columns = (
        df_enc.columns
        .str.replace('[^A-Za-z0-9_]', '_', regex=True)
        .str.replace('__+', '_', regex=True)
        .str.strip('_')
    )

    # Alinhar ao feature registry do modelo
    import json
    mlruns_path = (
        ROOT / 'mlruns' / '1' / MLFLOW_RUN_ID / 'artifacts' / 'feature_registry.json'
    )
    with open(mlruns_path) as f:
        reg = json.load(f)
    features_esperadas = reg['model_input_features']['ordered_list']
    for col in features_esperadas:
        if col not in df_enc.columns:
            df_enc[col] = 0
    df_enc = df_enc[[c for c in features_esperadas if c in df_enc.columns]]

    # Email como índice para alinhamento
    if emails_norm is not None:
        n = min(len(emails_norm), len(df_enc))
        df_enc.index = pd.Index(emails_norm.values[:n], name='email')

    return df_enc


# ── Pipeline de produção (real) ────────────────────────────────────────────────

def process_prod_pipeline(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Roda o pipeline de produção real (LeadScoringPipeline) no mesmo DataFrame bruto.
    """
    from src.production_pipeline import LeadScoringPipeline

    emails_norm = (
        df_raw['E-mail'].str.strip().str.lower()
        if 'E-mail' in df_raw.columns else None
    )

    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp:
        tmp_path = tmp.name
        df_raw.to_csv(tmp_path, index=False)

    try:
        pipeline = LeadScoringPipeline()
        pipeline.load_data(tmp_path)
        pipeline.preprocess()
        df_enc = pipeline.data.copy()
    finally:
        os.unlink(tmp_path)

    if emails_norm is not None:
        n = min(len(emails_norm), len(df_enc))
        df_enc.index = pd.Index(emails_norm.values[:n], name='email')

    return df_enc


# ── Comparação ─────────────────────────────────────────────────────────────────

def compare_dataframes(
    df_train: pd.DataFrame,
    df_prod: pd.DataFrame,
    threshold: float = 0.001,
):
    """Compara dois DataFrames encodados coluna a coluna."""

    print('\n' + '=' * 70)
    print('RESULTADO DO TESTE DE PARIDADE TREINO × PRODUÇÃO')
    print('=' * 70)

    idx_common = df_train.index.intersection(df_prod.index)
    print(f'\nLeads comparados: {len(idx_common)}')

    if len(idx_common) == 0:
        print('  ERRO: Nenhum lead em comum para comparar.')
        print(f'  Treino index amostra: {list(df_train.index[:5])}')
        print(f'  Prod  index amostra:  {list(df_prod.index[:5])}')
        return

    t = df_train.loc[idx_common]
    p = df_prod.loc[idx_common]

    import json
    mlruns_path = (
        ROOT / 'mlruns' / '1' / MLFLOW_RUN_ID / 'artifacts' / 'feature_registry.json'
    )
    with open(mlruns_path) as f:
        reg = json.load(f)
    features_modelo = reg['model_input_features']['ordered_list']

    print(f'Features esperadas pelo modelo: {len(features_modelo)}')
    print(f'Features no pipeline treino:    {len(t.columns)}')
    print(f'Features no pipeline produção:  {len(p.columns)}')

    ausentes_treino = [f for f in features_modelo if f not in t.columns]
    ausentes_prod   = [f for f in features_modelo if f not in p.columns]

    if ausentes_treino:
        print(f'\n⚠️  Features AUSENTES no treino ({len(ausentes_treino)}):')
        for f in ausentes_treino:
            print(f'    - {f}')

    if ausentes_prod:
        print(f'\n⚠️  Features AUSENTES na produção ({len(ausentes_prod)}):')
        for f in ausentes_prod:
            print(f'    - {f}')

    features_comparar = [f for f in features_modelo if f in t.columns and f in p.columns]
    print(f'\nFeatures comparadas: {len(features_comparar)}')

    divergencias = []
    for col in features_comparar:
        t_col = pd.to_numeric(t[col], errors='coerce').fillna(0)
        p_col = pd.to_numeric(p[col], errors='coerce').fillna(0)
        diff = (t_col - p_col).abs()
        max_diff = diff.max()
        leads_divergem = (diff > threshold).sum()

        if leads_divergem > 0:
            divergencias.append({
                'feature': col,
                'leads_divergem': leads_divergem,
                'pct': leads_divergem / len(idx_common) * 100,
                'max_diff': max_diff,
            })

    if not divergencias:
        print(
            f'\n✅  PARIDADE CONFIRMADA — todas as {len(features_comparar)} '
            f'features dentro do threshold {threshold}'
        )
    else:
        print(f'\n❌  {len(divergencias)} FEATURES COM DIVERGÊNCIA (threshold={threshold}):\n')
        print(f"  {'Feature':<55} {'Leads':>6} {'%':>6} {'MaxDiff':>9}")
        print('  ' + '-' * 80)
        for d in sorted(divergencias, key=lambda x: -x['leads_divergem']):
            print(
                f"  {d['feature']:<55} {d['leads_divergem']:>6} "
                f"{d['pct']:>5.1f}% {d['max_diff']:>9.4f}"
            )

    print('\n' + '=' * 70)
    return divergencias


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Teste de paridade treino × produção')
    parser.add_argument(
        '--periodo', choices=list(PERIODOS.keys()), default='LF45',
        help='Período a usar (padrão: LF45)',
    )
    parser.add_argument('--start', help='Data início (YYYY-MM-DD) — sobrescreve --periodo')
    parser.add_argument('--end',   help='Data fim   (YYYY-MM-DD) — sobrescreve --periodo')
    parser.add_argument(
        '--sample', type=int, default=300,
        help='Número de leads a amostrar (padrão: 300)',
    )
    parser.add_argument(
        '--threshold', type=float, default=0.001,
        help='Tolerância numérica por feature (padrão: 0.001)',
    )
    args = parser.parse_args()

    if args.start and args.end:
        start, end = args.start, args.end
        label = f'{start} → {end}'
    else:
        start, end = PERIODOS[args.periodo]
        label = args.periodo

    print(f'\nTeste de paridade — período: {label}')
    print(f'Sample: {args.sample} leads | Threshold: {args.threshold}')

    # 1. Carregar dados brutos do Sheets
    print('\n[1/4] Carregando dados brutos do Google Sheets...')
    df_periodo = load_raw_sheets(start, end)
    print(f'  {len(df_periodo)} leads no período')

    if len(df_periodo) == 0:
        print('  ERRO: Nenhum lead encontrado no período.')
        sys.exit(1)

    # Amostrar
    n = min(args.sample, len(df_periodo))
    df_sample = df_periodo.sample(n=n, random_state=42).reset_index(drop=True)
    print(f'  Amostra: {n} leads')

    # 2. Pipeline de treino
    print('\n[2/4] Processando pelo pipeline de TREINO...')
    try:
        df_train_enc = process_train_pipeline(df_sample.copy())
        print(f'  OK — {len(df_train_enc)} leads, {len(df_train_enc.columns)} features')
    except Exception as e:
        print(f'  ERRO: {e}')
        import traceback; traceback.print_exc()
        sys.exit(1)

    # 3. Pipeline de produção
    print('\n[3/4] Processando pelo pipeline de PRODUÇÃO...')
    try:
        df_prod_enc = process_prod_pipeline(df_sample.copy())
        print(f'  OK — {len(df_prod_enc)} leads, {len(df_prod_enc.columns)} features')
    except Exception as e:
        print(f'  ERRO: {e}')
        import traceback; traceback.print_exc()
        sys.exit(1)

    # 4. Comparar
    print('\n[4/4] Comparando pipelines...')
    compare_dataframes(df_train_enc, df_prod_enc, threshold=args.threshold)


if __name__ == '__main__':
    main()
