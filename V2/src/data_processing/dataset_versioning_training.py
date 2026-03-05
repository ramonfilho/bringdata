"""
Módulo para criação de versão do dataset por missing rate - PIPELINE DE TREINO.

Reproduz a célula 13 do notebook DevClub.
Detecta automaticamente features com preenchimento tardio (perguntas adicionadas
ao formulário em algum momento do período) e determina o cutoff de data ideal.
"""

from __future__ import annotations

import pandas as pd
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Threshold de missing máximo permitido pós-cutoff (features acima disso são dropadas)
MISSING_MAX_CUTOFF = 0.15       # <= 15% → feature aceita no período pós-cutoff

# Diferença mínima (metade antiga - metade recente) para detectar feature como tardia
DELTA_MINIMO_DETECCAO = 0.40    # >= 40pp → foi adicionada ao formulário durante o período


def _detectar_features_tardias(
    df: pd.DataFrame,
    coluna_data: str = 'Data',
) -> list:
    """
    Detecta features com padrão de preenchimento tardio: missing alto na
    primeira metade dos dados, baixo na segunda.

    Usado apenas para determinar a data de cutoff.

    Returns:
        list of (coluna, miss_antiga, miss_recente)
    """
    if coluna_data not in df.columns:
        return []

    df_sorted = df.sort_values(coluna_data).reset_index(drop=True)
    meio = len(df_sorted) // 2
    df_antiga = df_sorted.iloc[:meio]
    df_recente = df_sorted.iloc[meio:]

    tardias = []
    for col in df.columns:
        if col == coluna_data:
            continue
        miss_antiga = df_antiga[col].isnull().mean()
        miss_recente = df_recente[col].isnull().mean()
        if (miss_antiga - miss_recente) >= DELTA_MINIMO_DETECCAO:
            tardias.append((col, miss_antiga, miss_recente))

    return tardias


def _encontrar_cutoff_otimo(
    df: pd.DataFrame,
    features: list,
    coluna_data: str = 'Data',
) -> Optional[pd.Timestamp]:
    """
    Varre dias em ordem crescente e retorna o primeiro dia em que todas
    as features *viáveis* têm missing rate <= MISSING_MAX_CUTOFF nos registros
    a partir dessa data.

    Features "viáveis" são as que conseguem atingir <= MISSING_MAX_CUTOFF em
    algum ponto do histórico. Features permanentemente acima do threshold são
    ignoradas aqui — serão dropadas no passo de limpeza pós-cutoff.

    Returns:
        Timestamp do cutoff ótimo, ou None se não encontrado.
    """
    if not features or coluna_data not in df.columns:
        return None

    min_registros = max(100, len(df) // 100)
    dias = sorted(df[coluna_data].dropna().dt.normalize().unique())

    # Identificar features que conseguem atingir o threshold em algum ponto
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


def criar_dataset_pos_cutoff(df_medium_producao: pd.DataFrame) -> pd.DataFrame:
    """
    Cria dataset pós-cutoff com detecção automática do ponto de corte.

    Detecta quais features têm missing alto no período antigo e baixo no
    recente (perguntas adicionadas ao formulário), encontra o primeiro dia
    em que todas essas features ficam abaixo do threshold, e filtra o dataset.

    Após o corte, qualquer feature com missing > MISSING_MAX_CUTOFF é dropada.
    """
    df = df_medium_producao.copy()

    if 'Data' in df.columns:
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True)

    n_total = len(df)
    avg_missing_pre = df.drop(columns=['Data'], errors='ignore').isnull().mean().mean() * 100
    logger.info(f"  Input: {n_total:,} registros, missing médio {avg_missing_pre:.1f}%")
    logger.info(f"  Threshold: missing máximo {MISSING_MAX_CUTOFF*100:.0f}%  |  Δ mínimo de detecção {DELTA_MINIMO_DETECCAO*100:.0f}pp")
    logger.info("")

    # 1. Detectar features tardias (usadas apenas para encontrar o cutoff)
    features_tardias = _detectar_features_tardias(df)

    # Separar tardias que melhoram no período recente (usáveis para definir o cutoff)
    # vs tardias que permanecem altas (não podem definir o cutoff — nunca convergiria)
    n_recente = max(200, len(df) // 5)
    df_mais_recente = df.sort_values('Data').tail(n_recente) if 'Data' in df.columns else df.tail(n_recente)

    features_para_cutoff = []
    for col, miss_ant, miss_rec in features_tardias:
        miss_final = df_mais_recente[col].isnull().mean() if col in df_mais_recente.columns else 1.0
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
            flag = '' if col in nomes_para_cutoff else '  → não usada para cutoff (ainda alta)'
            logger.info(f"    {col_display:<{COL}} {miss_ant * 100:>5.0f}%  {miss_rec * 100:>5.0f}%  {delta * 100:>+5.0f}pp{flag}")
        logger.info("")
    else:
        logger.info(f"  Nenhuma feature com preenchimento tardio detectada")
        logger.info(f"    (critério: Δ >= {DELTA_MINIMO_DETECCAO * 100:.0f}pp entre metade antiga e recente)")
        logger.info("")

    # 2. Encontrar cutoff ótimo
    # Primeiro tenta com as features tardias que convergem (mais restritivas e precisas).
    # Se não houver tardias, varre todas as features para encontrar o primeiro dia em que
    # as features viáveis (que conseguem atingir o threshold) ficam abaixo do limite.
    nomes_para_cutoff = [f[0] for f in features_para_cutoff]
    cutoff_date = _encontrar_cutoff_otimo(df, nomes_para_cutoff)

    if cutoff_date:
        logger.info(f"  Cutoff detectado via features tardias: {cutoff_date.strftime('%Y-%m-%d')}")
        logger.info(f"    (primeiro dia em que as {len(nomes_para_cutoff)} feature(s) tardias ficam com missing <= {MISSING_MAX_CUTOFF * 100:.0f}%)")
    else:
        # Sem tardias (ou nenhuma convergiu): varre todas as features
        todas_features = [c for c in df.columns if c != 'Data']
        cutoff_date = _encontrar_cutoff_otimo(df, todas_features)

        if cutoff_date:
            logger.info(f"  Cutoff detectado via todas as features: {cutoff_date.strftime('%Y-%m-%d')}")
            logger.info(f"    (primeiro dia em que todas as features viáveis ficam com missing <= {MISSING_MAX_CUTOFF * 100:.0f}%)")
        else:
            logger.error("  Cutoff automático não encontrado — nenhuma feature consegue atingir o threshold.")
            logger.error("  Verifique os dados ou ajuste MISSING_MAX_CUTOFF.")
            raise ValueError("Cutoff automático não encontrado. Nenhuma feature viável.")

    # 3. Filtrar por cutoff
    df_pos_cutoff = df[df['Data'] >= cutoff_date].copy()

    # 4. Dropar todas as features com missing > threshold pós-cutoff (tardias ou não)
    cols_dropar = [
        col for col in df_pos_cutoff.columns
        if col != 'Data' and df_pos_cutoff[col].isnull().mean() > MISSING_MAX_CUTOFF
    ]
    if cols_dropar:
        df_pos_cutoff = df_pos_cutoff.drop(columns=cols_dropar)

    avg_missing_pos = df_pos_cutoff.drop(columns=['Data'], errors='ignore').isnull().mean().mean() * 100

    logger.info("")
    logger.info(f"  Pré-cutoff:   {n_total:,} leads   missing médio {avg_missing_pre:.1f}%")
    logger.info(f"  Pós-cutoff:   {len(df_pos_cutoff):,} leads   missing médio {avg_missing_pos:.1f}%")
    if cols_dropar:
        logger.info(f"  Dropadas:     {', '.join(cols_dropar)}")
    logger.info("")

    # DEBUG: missing por coluna no pós-cutoff (decrescente)
    missing_sorted = sorted(
        [(col, df_pos_cutoff[col].isnull().mean() * 100)
         for col in df_pos_cutoff.columns if col != 'Data'],
        key=lambda x: -x[1]
    )
    logger.debug("  Missing por coluna pós-cutoff:")
    logger.debug(f"  {'COLUNA':<45} {'% MISSING':>9}")
    logger.debug(f"  {'─' * 45}  {'─' * 9}")
    for col, pct in missing_sorted:
        col_display = col if len(col) <= 45 else col[:42] + '...'
        logger.debug(f"  {col_display:<45} {pct:>8.1f}%")

    return df_pos_cutoff


def disponibilizar_dataset(df_pos_cutoff: pd.DataFrame):
    """Gera relatório final de disponibilização do dataset."""
    logger.debug("")
    logger.debug("DISPONIBILIZAÇÃO DO DATASET")

    data_inicio = None
    if 'Data' in df_pos_cutoff.columns:
        data_inicio = df_pos_cutoff['Data'].min()

    if data_inicio:
        logger.debug(f"  Período: {data_inicio.strftime('%Y-%m-%d')} em diante")
    logger.debug(f"  Registros: {len(df_pos_cutoff):,}")
    logger.debug(f"  Colunas:   {len(df_pos_cutoff.columns)}")
