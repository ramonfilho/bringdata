"""
core/dataset_versioning.py — Cutoff e janela de conversão (treino).

Consolida dataset_versioning_training.py e conversion_window.py.
Usado apenas no pipeline de treino (produção não aplica).

Hardcodes migrados:
  #9  MonitoringConfig.conversion_window_days  (janela_dias=20)
  #38 IngestionConfig.dataset_cutoff_date      (None = auto-detectar)

Constantes de detecção de cutoff (não variam por cliente — omitidas do yaml):
  MISSING_MAX_CUTOFF    = 0.15   (15% — threshold de missing pós-cutoff)
  DELTA_MINIMO_DETECCAO = 0.40   (40pp — delta para classificar feature como tardia)
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from .client_config import IngestionConfig, MonitoringConfig

logger = logging.getLogger(__name__)

# Thresholds de detecção de cutoff — constantes de domínio, não variam por cliente
MISSING_MAX_CUTOFF    = 0.15
DELTA_MINIMO_DETECCAO = 0.40


# ---------------------------------------------------------------------------
# Helpers privados (inalterados em relação ao original)
# ---------------------------------------------------------------------------

def _detectar_features_tardias(df: pd.DataFrame, coluna_data: str = 'Data') -> list:
    """Detecta features com missing alto na metade antiga e baixo na recente."""
    if coluna_data not in df.columns:
        return []

    df_sorted = df.sort_values(coluna_data).reset_index(drop=True)
    meio = len(df_sorted) // 2
    df_antiga  = df_sorted.iloc[:meio]
    df_recente = df_sorted.iloc[meio:]

    tardias = []
    for col in df.columns:
        if col == coluna_data:
            continue
        miss_antiga  = df_antiga[col].isnull().mean()
        miss_recente = df_recente[col].isnull().mean()
        if (miss_antiga - miss_recente) >= DELTA_MINIMO_DETECCAO:
            tardias.append((col, miss_antiga, miss_recente))

    return tardias


def _encontrar_cutoff_otimo(
    df: pd.DataFrame,
    features: list,
    coluna_data: str = 'Data',
) -> Optional[pd.Timestamp]:
    """Primeiro dia em que todas as features viáveis ficam abaixo do threshold."""
    if not features or coluna_data not in df.columns:
        return None

    min_registros = max(100, len(df) // 100)
    dias = sorted(df[coluna_data].dropna().dt.normalize().unique())

    features_viaveis = []
    for f in features:
        if f not in df.columns:
            continue
        pode_convergir = any(
            df[df[coluna_data] >= d][f].isnull().mean() <= MISSING_MAX_CUTOFF
            for d in dias
            if len(df[df[coluna_data] >= d]) >= min_registros
        )
        if pode_convergir:
            features_viaveis.append(f)

    if not features_viaveis:
        return None

    for data_candidata in dias:
        df_apos = df[df[coluna_data] >= data_candidata]
        if len(df_apos) < min_registros:
            continue
        features_presentes = [f for f in features_viaveis if f in df_apos.columns]
        if not features_presentes:
            continue
        if all(df_apos[f].isnull().mean() <= MISSING_MAX_CUTOFF for f in features_presentes):
            return data_candidata

    return None


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def criar_dataset_pos_cutoff(
    df: pd.DataFrame,
    config: IngestionConfig,
) -> pd.DataFrame:
    """
    Filtra dataset pelo cutoff de data e descarta features com alto missing.

    Se config.dataset_cutoff_date (#38) estiver definida, usa esse valor fixo.
    Caso contrário, detecta automaticamente o cutoff via padrão de missing
    das features (algoritmo de features tardias).

    Após o corte, descarta qualquer feature com missing > MISSING_MAX_CUTOFF.

    Args:
        df:     DataFrame após unificação de medium + categorias.
        config: IngestionConfig carregado de configs/clients/{client}.yaml.

    Returns:
        DataFrame filtrado pelo cutoff, sem features com alto missing.
    """
    df = df.copy()

    if 'Data' in df.columns:
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True)

    n_total = len(df)
    avg_missing_pre = df.drop(columns=['Data'], errors='ignore').isnull().mean().mean() * 100
    logger.info(f"  Input: {n_total:,} registros, missing médio {avg_missing_pre:.1f}%")
    logger.info(f"  Threshold: missing máximo {MISSING_MAX_CUTOFF*100:.0f}%  |  Δ mínimo {DELTA_MINIMO_DETECCAO*100:.0f}pp")
    logger.info("")

    # 1. Determinar cutoff
    cutoff_date = None

    if config.dataset_cutoff_date:
        # Cutoff fixo via config (#38)
        cutoff_date = pd.Timestamp(config.dataset_cutoff_date)
        logger.info(f"  Cutoff fixo (config): {cutoff_date.strftime('%Y-%m-%d')}")
    else:
        # Auto-detecção via features tardias
        features_tardias = _detectar_features_tardias(df)

        n_recente = max(200, len(df) // 5)
        df_mais_recente = (
            df.sort_values('Data').tail(n_recente)
            if 'Data' in df.columns else df.tail(n_recente)
        )

        features_para_cutoff = []
        for col, miss_ant, miss_rec in features_tardias:
            miss_final = (
                df_mais_recente[col].isnull().mean()
                if col in df_mais_recente.columns else 1.0
            )
            if miss_final <= MISSING_MAX_CUTOFF:
                features_para_cutoff.append((col, miss_ant, miss_rec))

        COL = 44
        if features_tardias:
            logger.info(f"  Features com preenchimento tardio ({len(features_tardias)}):")
            logger.info(f"    {'FEATURE':<{COL}} {'ANTES':>6}  {'DEPOIS':>6}  {'Δ':>7}")
            logger.info(f"    {'─' * COL}  {'─' * 6}  {'─' * 6}  {'─' * 7}")
            nomes_para_cutoff = {f[0] for f in features_para_cutoff}
            for col, miss_ant, miss_rec in sorted(features_tardias, key=lambda x: -(x[1] - x[2])):
                delta = miss_rec - miss_ant
                col_display = col if len(col) <= COL else col[:COL - 3] + '...'
                flag = '' if col in nomes_para_cutoff else '  → não usada (ainda alta)'
                logger.info(f"    {col_display:<{COL}} {miss_ant*100:>5.0f}%  {miss_rec*100:>5.0f}%  {delta*100:>+5.0f}pp{flag}")
            logger.info("")
        else:
            logger.info(f"  Nenhuma feature tardia detectada (Δ >= {DELTA_MINIMO_DETECCAO*100:.0f}pp)")
            logger.info("")

        nomes_para_cutoff = [f[0] for f in features_para_cutoff]
        cutoff_date = _encontrar_cutoff_otimo(df, nomes_para_cutoff)

        if cutoff_date:
            logger.info(f"  Cutoff detectado via features tardias: {cutoff_date.strftime('%Y-%m-%d')}")
        else:
            todas_features = [c for c in df.columns if c != 'Data']
            cutoff_date = _encontrar_cutoff_otimo(df, todas_features)
            if cutoff_date:
                logger.info(f"  Cutoff detectado via todas as features: {cutoff_date.strftime('%Y-%m-%d')}")
            else:
                raise ValueError("Cutoff automático não encontrado. Nenhuma feature viável.")

    # 2. Filtrar por cutoff
    df_pos = df[df['Data'] >= cutoff_date].copy()

    # 3. Descartar features com missing > threshold pós-cutoff
    cols_dropar = [
        col for col in df_pos.columns
        if col != 'Data' and df_pos[col].isnull().mean() > MISSING_MAX_CUTOFF
    ]
    if cols_dropar:
        df_pos = df_pos.drop(columns=cols_dropar)

    avg_missing_pos = df_pos.drop(columns=['Data'], errors='ignore').isnull().mean().mean() * 100
    logger.info(f"  Pré-cutoff:  {n_total:,} leads   missing médio {avg_missing_pre:.1f}%")
    logger.info(f"  Pós-cutoff:  {len(df_pos):,} leads   missing médio {avg_missing_pos:.1f}%")
    if cols_dropar:
        logger.info(f"  Dropadas:    {', '.join(cols_dropar)}")
    logger.info("")

    return df_pos


def aplicar_janela_conversao(
    df_leads: pd.DataFrame,
    df_vendas: pd.DataFrame,
    config: MonitoringConfig,
) -> pd.DataFrame:
    """
    Remove leads que ainda não tiveram tempo suficiente para converter.

    Usa config.conversion_window_days (#9) como janela (ex: 20 dias para DevClub:
    7 dias captação + 6 dias CPL + 7 dias carrinho).

    Args:
        df_leads:  DataFrame de leads com coluna 'target'.
        df_vendas: DataFrame de vendas normalizado (coluna 'data' ou 'Data').
        config:    MonitoringConfig carregado de configs/clients/{client}.yaml.

    Returns:
        DataFrame de leads filtrado — apenas leads cuja janela foi completamente observada.
    """
    janela_dias = config.conversion_window_days or 14

    df = df_leads.copy()

    # 1. Data máxima das vendas
    if 'data' in df_vendas.columns:
        df_vendas = df_vendas.copy()
        df_vendas['data'] = pd.to_datetime(df_vendas['data'], errors='coerce', dayfirst=True)
        data_max_vendas = df_vendas['data'].max()
    elif 'Data' in df_vendas.columns:
        df_vendas = df_vendas.copy()
        df_vendas['Data'] = pd.to_datetime(df_vendas['Data'], errors='coerce', dayfirst=True)
        data_max_vendas = df_vendas['Data'].max()
    else:
        raise ValueError("Coluna de data não encontrada em df_vendas")

    data_limite = data_max_vendas - pd.Timedelta(days=janela_dias)
    logger.info(f"  Janela: {janela_dias} dias — limite: {data_max_vendas.strftime('%Y-%m-%d')} - {janela_dias}d = {data_limite.strftime('%Y-%m-%d')}")

    # 2. Converter data dos leads
    if 'Data' not in df.columns:
        raise ValueError("Coluna 'Data' não encontrada em df_leads")
    df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True)

    total_antes  = len(df)
    target_antes = int(df['target'].sum()) if 'target' in df.columns else 0
    logger.info(f"  Antes:  {total_antes:,} leads, {target_antes:,} target=1 ({target_antes/total_antes*100:.2f}%)")

    # 3. Filtrar — remove TODOS os leads após data_limite (target=0 e target=1)
    df_filtrado = df[df['Data'] <= data_limite].copy()

    total_depois  = len(df_filtrado)
    target_depois = int(df_filtrado['target'].sum()) if 'target' in df_filtrado.columns else 0
    removidos     = total_antes - total_depois

    logger.info(f"  Depois: {total_depois:,} leads, {target_depois:,} target=1 ({target_depois/total_depois*100:.2f}%)")
    logger.info(f"  Removidos: {removidos:,} ({removidos/total_antes*100:.1f}%)")
    logger.info("")

    return df_filtrado
