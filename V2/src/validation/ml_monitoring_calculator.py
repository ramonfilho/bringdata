"""
Módulo para Monitoramento de Performance do Modelo ML.

Calcula métricas de performance do modelo em produção e compara
com baseline do test set para detectar degradação.

Métricas incluídas:
- AUC (Area Under Curve)
- Taxa de conversão por decil (real vs esperado)
- Concentração de conversões (top 3, top 5 decis)
- Lift por decil vs baseline
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path
from sklearn.metrics import roc_auc_score
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class MLMonitoringCalculator:
    """
    Calcula métricas de monitoramento do modelo ML.

    Compara performance em produção com baseline do test set
    para identificar degradação ou mudanças no comportamento.
    """

    def __init__(self, model_metadata_path: str):
        """
        Inicializa calculator carregando metadados do test set.

        Args:
            model_metadata_path: Caminho para model_metadata.json
        """
        self.metadata_path = Path(model_metadata_path)
        self.metadata = self._load_test_set_baseline()

        logger.info(f" Metadados do modelo carregados: {self.metadata_path.name}")
        logger.info(f"   AUC Test Set: {self.metadata['auc']:.4f}")
        logger.info(f"   Baseline Conversion Rate: {self.metadata['baseline_conversion_rate']:.4f}")

    def _load_test_set_baseline(self) -> Dict:
        """
        Carrega métricas baseline do test set do arquivo JSON.

        Returns:
            Dict com métricas: auc, decil_analysis, baseline_conversion_rate, etc.

        Raises:
            FileNotFoundError: Se arquivo não existir
            json.JSONDecodeError: Se JSON inválido
        """
        if not self.metadata_path.exists():
            raise FileNotFoundError(f"Metadata não encontrado: {self.metadata_path}")

        with open(self.metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        # Extrair métricas relevantes
        return {
            'auc': metadata['performance_metrics']['auc'],
            'baseline_conversion_rate': metadata['performance_metrics']['baseline_conversion_rate'],
            'top3_concentration': metadata['performance_metrics']['top3_decil_concentration'],
            'top5_concentration': metadata['performance_metrics']['top5_decil_concentration'],
            'lift_maximum': metadata['performance_metrics']['lift_maximum'],
            'decil_analysis': metadata['decil_analysis'],
            'model_name': metadata['model_info']['model_name'],
            'trained_at': metadata['model_info']['trained_at']
        }

    def calculate_auc(self, matched_df: pd.DataFrame) -> Dict:
        """
        Calcula AUC em produção e compara com test set.

        Args:
            matched_df: DataFrame com lead_score e converted

        Returns:
            Dict com auc_production, auc_test_set, delta, delta_pct
        """
        # Filtrar apenas leads com score válido e não-nulo
        valid_df = matched_df[
            matched_df['lead_score'].notna() &
            matched_df['converted'].notna()
        ].copy()

        if len(valid_df) == 0:
            logger.warning(" Nenhum lead com lead_score válido para calcular AUC")
            return {
                'production': np.nan,
                'test_set': self.metadata['auc'],
                'delta': np.nan,
                'delta_pct': np.nan,
                'valid_leads': 0
            }

        # Converter lead_score para float (pode estar como string com vírgula)
        def convert_score(score):
            if pd.isna(score):
                return np.nan
            if isinstance(score, str):
                try:
                    return float(score.replace(',', '.'))
                except (ValueError, AttributeError):
                    return np.nan
            return float(score)

        valid_df['lead_score_float'] = valid_df['lead_score'].apply(convert_score)

        # Remover scores que não puderam ser convertidos
        valid_df = valid_df[valid_df['lead_score_float'].notna()].copy()

        if len(valid_df) == 0:
            logger.warning(" Nenhum lead com lead_score numérico válido para calcular AUC")
            return {
                'production': np.nan,
                'test_set': self.metadata['auc'],
                'delta': np.nan,
                'delta_pct': np.nan,
                'valid_leads': 0
            }

        # Calcular AUC produção
        try:
            auc_production = roc_auc_score(
                y_true=valid_df['converted'].astype(int),
                y_score=valid_df['lead_score_float']
            )
        except Exception as e:
            logger.error(f" Erro ao calcular AUC: {e}")
            return {
                'production': np.nan,
                'test_set': self.metadata['auc'],
                'delta': np.nan,
                'delta_pct': np.nan,
                'valid_leads': len(valid_df)
            }

        auc_test_set = self.metadata['auc']
        delta = auc_production - auc_test_set
        delta_pct = (delta / auc_test_set) * 100 if auc_test_set > 0 else 0

        return {
            'production': auc_production,
            'test_set': auc_test_set,
            'delta': delta,
            'delta_pct': delta_pct,
            'valid_leads': len(valid_df)
        }

    def calculate_decile_performance(self, matched_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula taxa de conversão por decil e compara com esperado.

        IMPORTANTE: Recalcula decis usando percentis (qcut) ao invés de usar thresholds fixos.
        Isso garante distribuição balanceada (10% em cada decil) para comparação justa com test set.

        Args:
            matched_df: DataFrame com lead_score e converted

        Returns:
            DataFrame com colunas:
            - decile: D1-D10
            - leads: Número de leads
            - conversions: Número de conversões
            - conversion_rate_real: Taxa observada (%)
            - conversion_rate_expected: Taxa do test set (%)
            - ratio: real / expected
        """
        # Filtrar apenas leads com score válido
        valid_df = matched_df[matched_df['lead_score'].notna()].copy()

        if len(valid_df) == 0:
            logger.warning(" Nenhum lead com lead_score válido para calcular performance por decil")
            return pd.DataFrame()

        # Converter lead_score para float (pode estar como string com vírgula)
        def convert_score(score):
            if pd.isna(score):
                return np.nan
            if isinstance(score, str):
                try:
                    return float(score.replace(',', '.'))
                except (ValueError, AttributeError):
                    return np.nan
            return float(score)

        valid_df['lead_score_float'] = valid_df['lead_score'].apply(convert_score)

        # Remover scores que não puderam ser convertidos
        valid_df = valid_df[valid_df['lead_score_float'].notna()].copy()

        if len(valid_df) == 0:
            logger.warning(" Nenhum lead com lead_score numérico válido")
            return pd.DataFrame()

        # NOVO: Recalcular decis usando percentis (qcut) para garantir 10% em cada
        # D1 = 10% piores (scores mais baixos)
        # D10 = 10% melhores (scores mais altos)
        try:
            valid_df['decile_percentile'] = pd.qcut(
                valid_df['lead_score_float'],
                q=10,
                labels=['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9', 'D10'],
                duplicates='drop'  # Em caso de ties, agrupa decis
            )
        except ValueError as e:
            # Se qcut falhar (ex: muitos valores duplicados), usar cut com limites fixos
            logger.warning(f" qcut falhou, usando quantis: {e}")
            quantiles = valid_df['lead_score_float'].quantile([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
            valid_df['decile_percentile'] = pd.cut(
                valid_df['lead_score_float'],
                bins=quantiles,
                labels=['D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8', 'D9', 'D10'],
                include_lowest=True,
                duplicates='drop'
            )

        # Agrupar por decil recalculado
        decile_stats = valid_df.groupby('decile_percentile', observed=True).agg({
            'converted': ['count', 'sum']
        }).reset_index()

        decile_stats.columns = ['decile', 'leads', 'conversions']

        # Calcular taxa real
        decile_stats['conversion_rate_real'] = (
            decile_stats['conversions'] / decile_stats['leads'] * 100
        )

        # Buscar taxa esperada do metadata
        expected_rates = []
        for decile in decile_stats['decile']:
            # Metadata usa formato "decil_1", "decil_10", etc.
            decil_num = int(decile[1:]) if isinstance(decile, str) else decile
            decil_key = f'decil_{decil_num}'

            if decil_key in self.metadata['decil_analysis']:
                # Converter de decimal para porcentagem
                rate = self.metadata['decil_analysis'][decil_key]['conversion_rate'] * 100
                expected_rates.append(rate)
            else:
                expected_rates.append(np.nan)

        decile_stats['conversion_rate_expected'] = expected_rates

        # Calcular ratio
        decile_stats['ratio'] = (
            decile_stats['conversion_rate_real'] / decile_stats['conversion_rate_expected']
        )

        # Substituir inf por NaN
        decile_stats['ratio'] = decile_stats['ratio'].replace([np.inf, -np.inf], np.nan)

        # Ordenar por decil numericamente (D1, D2, ..., D10)
        decile_stats['decile_num'] = decile_stats['decile'].str.extract('(\d+)').astype(int)
        decile_stats = decile_stats.sort_values('decile_num').drop('decile_num', axis=1).reset_index(drop=True)

        return decile_stats

    def calculate_concentration_metrics(self, matched_df: pd.DataFrame) -> Dict:
        """
        Calcula concentração de conversões nos top decis.

        Args:
            matched_df: DataFrame com decile e converted

        Returns:
            Dict com top3_production, top3_test_set, top5_production, top5_test_set
        """
        # Contar conversões por decil
        conversions_by_decile = matched_df[matched_df['converted'] == True].groupby('decile').size()
        total_conversions = conversions_by_decile.sum()

        if total_conversions == 0:
            return {
                'top3_production': 0.0,
                'top3_test_set': self.metadata['top3_concentration'],
                'top5_production': 0.0,
                'top5_test_set': self.metadata['top5_concentration']
            }

        # Top 3 decis: D8, D9, D10
        top3_decis = ['D8', 'D9', 'D10']
        top3_conversions = sum(
            conversions_by_decile.get(d, 0) for d in top3_decis
        )
        top3_production = (top3_conversions / total_conversions) * 100

        # Top 5 decis: D6, D7, D8, D9, D10
        top5_decis = ['D6', 'D7', 'D8', 'D9', 'D10']
        top5_conversions = sum(
            conversions_by_decile.get(d, 0) for d in top5_decis
        )
        top5_production = (top5_conversions / total_conversions) * 100

        return {
            'top3_production': top3_production,
            'top3_test_set': self.metadata['top3_concentration'],
            'top5_production': top5_production,
            'top5_test_set': self.metadata['top5_concentration']
        }

    def calculate_lift_by_decile(self, matched_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula lift por decil comparado ao baseline.

        Args:
            matched_df: DataFrame com decile e converted

        Returns:
            DataFrame com:
            - decile: D1-D10
            - conversion_rate: Taxa de conversão (%)
            - baseline_rate: Taxa baseline (%)
            - lift: conversion_rate / baseline_rate
        """
        # Agrupar por decil
        decile_stats = matched_df.groupby('decile').agg({
            'converted': ['count', 'sum']
        }).reset_index()

        decile_stats.columns = ['decile', 'leads', 'conversions']

        # Taxa de conversão
        decile_stats['conversion_rate'] = (
            decile_stats['conversions'] / decile_stats['leads'] * 100
        )

        # Baseline
        baseline_rate = self.metadata['baseline_conversion_rate'] * 100
        decile_stats['baseline_rate'] = baseline_rate

        # Lift
        decile_stats['lift'] = decile_stats['conversion_rate'] / baseline_rate

        # Ordenar por decil numericamente (D1, D2, ..., D10)
        decile_stats['decile_num'] = decile_stats['decile'].str.extract('(\d+)').astype(int)
        decile_stats = decile_stats.sort_values('decile_num').drop('decile_num', axis=1).reset_index(drop=True)

        return decile_stats

    def calculate_temporal_auc_snapshots(
        self,
        matched_df: pd.DataFrame,
        sales_df: pd.DataFrame,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        Calcula AUC dia a dia para análise de degradação temporal.

        Cria snapshots incrementais do AUC à medida que novas vendas surgem,
        permitindo identificar correlação entre aumento de vendas TMB e queda do AUC.

        Args:
            matched_df: DataFrame com leads matched (com lead_score e converted)
            sales_df: DataFrame com todas as vendas (para classificar TMB vs Guru)
            start_date: Data inicial do período de vendas (YYYY-MM-DD)
            end_date: Data final do período de vendas (YYYY-MM-DD)

        Returns:
            DataFrame com colunas:
            - snapshot_date: Data do snapshot
            - cumulative_sales: Vendas acumuladas até a data
            - cumulative_conversions: Conversões matched acumuladas
            - guru_sales: Vendas Guru até a data
            - tmb_sales: Vendas TMB até a data
            - tmb_percentage: % TMB das vendas totais
            - auc: AUC calculado com conversões até a data
            - auc_delta: Diferença vs AUC test set
        """
        from datetime import timedelta

        logger.info(f" Calculando snapshots temporais de AUC ({start_date} a {end_date})...")

        # Fazer cópias profundas para não afetar os originais
        matched_copy = matched_df.copy(deep=True)
        sales_copy = sales_df.copy(deep=True)

        # Garantir que sale_date é datetime
        if 'sale_date' not in sales_copy.columns:
            logger.warning(" Coluna 'sale_date' não encontrada em sales_df")
            return pd.DataFrame()

        sales_copy['sale_date'] = pd.to_datetime(sales_copy['sale_date'])

        # Filtrar apenas vendas do período
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date) + timedelta(days=1) - timedelta(seconds=1)
        sales_copy = sales_copy[
            (sales_copy['sale_date'] >= start_dt) &
            (sales_copy['sale_date'] <= end_dt)
        ].copy()

        if len(sales_copy) == 0:
            logger.warning(" Nenhuma venda no período especificado")
            return pd.DataFrame()

        # Classificar vendas em Guru vs TMB (coluna 'origem' já existe no sales_df)
        if 'origem' not in sales_copy.columns:
            logger.warning(" Coluna 'origem' não encontrada em sales_df")
            return pd.DataFrame()

        # Já temos a coluna 'origem' com valores 'guru' ou 'tmb'
        sales_copy['source'] = sales_copy['origem'].str.upper()  # 'guru' -> 'GURU', 'tmb' -> 'TMB'

        # Criar lista de datas (dias únicos no período)
        date_range = pd.date_range(start=start_dt.date(), end=end_dt.date(), freq='D')

        snapshots = []
        for snapshot_date in date_range:
            # Incluir vendas até o FINAL do dia (23:59:59)
            snapshot_end = pd.Timestamp(snapshot_date) + timedelta(days=1) - timedelta(seconds=1)

            # Filtrar vendas até esta data
            sales_until_date = sales_copy[sales_copy['sale_date'] <= snapshot_end].copy()

            if len(sales_until_date) == 0:
                continue

            # Contar vendas por source
            guru_count = len(sales_until_date[sales_until_date['source'] == 'GURU'])
            tmb_count = len(sales_until_date[sales_until_date['source'] == 'TMB'])
            total_count = len(sales_until_date)
            tmb_pct = (tmb_count / total_count * 100) if total_count > 0 else 0

            # Para calcular AUC: usar TODOS os leads, mas marcar como convertido apenas os que venderam até esta data
            # Criar cópia temporária do matched_df completo
            matched_snapshot = matched_copy.copy()

            # Atualizar coluna 'converted' para refletir conversões até esta data
            emails_converted_until_date = set(sales_until_date['email'].values)
            matched_snapshot['converted'] = matched_snapshot['email'].isin(emails_converted_until_date)

            conversions_count = matched_snapshot['converted'].sum()

            # Calcular AUC com TODOS os leads, mas apenas conversões até esta data
            auc_result = self.calculate_auc(matched_snapshot)

            snapshots.append({
                'snapshot_date': snapshot_date,
                'cumulative_sales': total_count,
                'cumulative_conversions': conversions_count,
                'guru_sales': guru_count,
                'tmb_sales': tmb_count,
                'tmb_percentage': tmb_pct,
                'auc': auc_result['production'],
                'auc_test_set': auc_result['test_set'],
                'auc_delta': auc_result['delta']
            })

        snapshots_df = pd.DataFrame(snapshots)

        if len(snapshots_df) > 0:
            # Calcular correlação entre % TMB e AUC
            if len(snapshots_df) > 1:  # Precisa de pelo menos 2 pontos para correlação
                correlation = snapshots_df[['tmb_percentage', 'auc']].corr().iloc[0, 1]
                logger.info(f"    {len(snapshots_df)} snapshots gerados")
                logger.info(f"    Correlação % TMB vs AUC: {correlation:.3f}")

        return snapshots_df

    def calculate_all_metrics(self, matched_df: pd.DataFrame) -> Dict:
        """
        Calcula métricas de monitoramento do modelo.

        Foca em AUC e métricas de concentração, que são robustas à otimização da Meta
        que altera a distribuição de scores ao longo do tempo.

        Args:
            matched_df: DataFrame com matched leads e conversões

        Returns:
            Dict com métricas de AUC e concentração
        """
        logger.info(" Calculando métricas de monitoramento do modelo...")

        # AUC - Métrica principal de discriminação
        auc_metrics = self.calculate_auc(matched_df)
        logger.info(f"   AUC Produção: {auc_metrics['production']:.4f} "
                   f"(Test Set: {auc_metrics['test_set']:.4f}, Δ: {auc_metrics['delta']:+.4f})")

        # Concentração - Distribuição de conversões nos top decis
        concentration = self.calculate_concentration_metrics(matched_df)
        logger.info(f"   Top 3 Decis: {concentration['top3_production']:.1f}% "
                   f"(Test Set: {concentration['top3_test_set']:.1f}%)")

        return {
            'auc': auc_metrics,
            'concentration': concentration,
            'model_info': {
                'model_name': self.metadata['model_name'],
                'trained_at': self.metadata['trained_at']
            }
        }
