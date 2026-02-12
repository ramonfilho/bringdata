"""
Módulo para geração de visualizações de validação de performance ML.

Gera 5 gráficos PNG:
1. Comparação de Taxa de Conversão (COM ML vs SEM ML)
2. Comparação de ROAS (COM ML vs SEM ML)
3. Performance por Decil (Real vs Esperado)
4. Receita Acumulada por Decil
5. Margem de Contribuição por Campanha
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Configurar estilo seaborn
sns.set_style("whitegrid")
sns.set_palette("husl")


class ValidationVisualizer:
    """
    Gera visualizações para validação de performance ML.

    Usa matplotlib + seaborn para criar gráficos profissionais
    salvos em PNG de alta resolução.
    """

    def __init__(self, dpi: int = 300):
        """
        Inicializa visualizador.

        Args:
            dpi: Resolução dos gráficos PNG (default: 300)
        """
        self.dpi = dpi
        self.figsize = (12, 6)

        # Cores padrão
        self.color_com_ml = '#70AD47'  # Verde
        self.color_sem_ml = '#E74C3C'  # Vermelho
        self.color_expected = '#95A5A6'  # Cinza
        self.color_real = '#3498DB'  # Azul

    def generate_all_charts(
        self,
        campaign_metrics: pd.DataFrame,
        decile_metrics: pd.DataFrame,
        ml_comparison: Dict,
        output_dir: str
    ) -> dict:
        """
        Gera todos os 5 gráficos PNG.

        Args:
            campaign_metrics: DataFrame de CampaignMetricsCalculator
            decile_metrics: DataFrame de DecileMetricsCalculator
            ml_comparison: Dict de compare_ml_vs_non_ml()
            output_dir: Diretório para salvar PNGs

        Returns:
            Dicionário com caminhos dos arquivos gerados
        """
        logger.info(" Gerando visualizações...")

        # Criar diretório se não existir
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        output_files = {}

        # 1. Comparação Taxa de Conversão
        logger.info("   Gerando: conversion_rate_comparison.png")
        output_files['conversion_rate'] = self.plot_conversion_rate_comparison(
            ml_comparison, output_dir
        )

        # 2. Comparação ROAS
        logger.info("   Gerando: roas_comparison.png")
        output_files['roas'] = self.plot_roas_comparison(
            ml_comparison, output_dir
        )

        # 3. Performance por Decil
        logger.info("   Gerando: decile_performance.png")
        output_files['decile_performance'] = self.plot_decile_performance(
            decile_metrics, output_dir
        )

        # 4. Receita Acumulada
        logger.info("   Gerando: cumulative_revenue_by_decile.png")
        output_files['cumulative_revenue'] = self.plot_cumulative_revenue(
            decile_metrics, output_dir
        )

        # 5. Margem por Campanha
        logger.info("   Gerando: contribution_margin_by_campaign.png")
        output_files['contribution_margin'] = self.plot_contribution_margin(
            campaign_metrics, output_dir
        )

        logger.info(f"    5 gráficos PNG salvos em: {output_dir}/")

        return output_files

    def plot_conversion_rate_comparison(
        self,
        ml_comparison: Dict,
        output_dir: str
    ) -> str:
        """
        Gráfico de barras: Taxa de conversão COM ML vs SEM ML.

        Args:
            ml_comparison: Dict de compare_ml_vs_non_ml()
            output_dir: Diretório de saída

        Returns:
            Caminho do arquivo PNG gerado
        """
        com_ml = ml_comparison.get('com_ml', {})
        sem_ml = ml_comparison.get('sem_ml', {})

        # Dados
        categories = ['COM ML', 'SEM ML']
        values = [
            com_ml.get('conversion_rate', 0),
            sem_ml.get('conversion_rate', 0)
        ]

        # Criar figura
        fig, ax = plt.subplots(figsize=self.figsize)

        # Barras
        bars = ax.bar(
            categories,
            values,
            color=[self.color_com_ml, self.color_sem_ml],
            alpha=0.8,
            edgecolor='black',
            linewidth=1.2
        )

        # Adicionar valores nas barras
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height + 0.1,
                f'{height:.2f}%',
                ha='center',
                va='bottom',
                fontsize=12,
                fontweight='bold'
            )

        # Títulos e labels
        ax.set_title(
            'Taxa de Conversão: COM ML vs SEM ML',
            fontsize=16,
            fontweight='bold',
            pad=20
        )
        ax.set_ylabel('Taxa de Conversão (%)', fontsize=12, fontweight='bold')
        ax.set_ylim(0, max(values) * 1.3)

        # Grid
        ax.grid(axis='y', alpha=0.3, linestyle='--')
        ax.set_axisbelow(True)

        plt.tight_layout()

        # Salvar
        output_path = str(Path(output_dir) / 'conversion_rate_comparison.png')
        plt.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
        plt.close()

        return output_path

    def plot_roas_comparison(
        self,
        ml_comparison: Dict,
        output_dir: str
    ) -> str:
        """
        Gráfico de barras: ROAS COM ML vs SEM ML com linha de breakeven.

        Args:
            ml_comparison: Dict de compare_ml_vs_non_ml()
            output_dir: Diretório de saída

        Returns:
            Caminho do arquivo PNG gerado
        """
        com_ml = ml_comparison.get('com_ml', {})
        sem_ml = ml_comparison.get('sem_ml', {})

        # Dados
        categories = ['COM ML', 'SEM ML']
        values = [
            com_ml.get('roas', 0),
            sem_ml.get('roas', 0)
        ]

        # Criar figura
        fig, ax = plt.subplots(figsize=self.figsize)

        # Barras
        bars = ax.bar(
            categories,
            values,
            color=[self.color_com_ml, self.color_sem_ml],
            alpha=0.8,
            edgecolor='black',
            linewidth=1.2
        )

        # Linha de breakeven em ROAS = 1.0
        ax.axhline(
            y=1.0,
            color='red',
            linestyle='--',
            linewidth=2,
            label='Breakeven (ROAS = 1.0)',
            alpha=0.7
        )

        # Adicionar valores nas barras
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height + 0.1,
                f'{height:.2f}x',
                ha='center',
                va='bottom',
                fontsize=12,
                fontweight='bold'
            )

        # Títulos e labels
        ax.set_title(
            'ROAS (Return on Ad Spend): COM ML vs SEM ML',
            fontsize=16,
            fontweight='bold',
            pad=20
        )
        ax.set_ylabel('ROAS (x)', fontsize=12, fontweight='bold')
        ax.set_ylim(0, max(values) * 1.3)

        # Legenda
        ax.legend(loc='upper right', fontsize=10)

        # Grid
        ax.grid(axis='y', alpha=0.3, linestyle='--')
        ax.set_axisbelow(True)

        plt.tight_layout()

        # Salvar
        output_path = str(Path(output_dir) / 'roas_comparison.png')
        plt.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
        plt.close()

        return output_path

    def plot_decile_performance(
        self,
        decile_metrics: pd.DataFrame,
        output_dir: str
    ) -> str:
        """
        Gráfico de barras agrupadas: Conversão Real vs Esperada por Decil.

        Mostra taxa real (Guru+TMB) vs taxa esperada do modelo para D1-D10.

        Args:
            decile_metrics: DataFrame de DecileMetricsCalculator
            output_dir: Diretório de saída

        Returns:
            Caminho do arquivo PNG gerado
        """
        if decile_metrics.empty:
            logger.warning("    Nenhuma métrica de decil para plotar")
            # Criar gráfico vazio com mensagem
            fig, ax = plt.subplots(figsize=self.figsize)
            ax.text(0.5, 0.5, 'Sem dados de decil disponíveis',
                   ha='center', va='center', fontsize=14)
            output_path = str(Path(output_dir) / 'decile_performance.png')
            plt.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
            plt.close()
            return output_path

        # Dados
        deciles = decile_metrics['decile'].tolist()
        real_rates = decile_metrics['conversion_rate_total'].tolist()  # Guru+TMB
        expected_rates = decile_metrics['expected_conversion_rate'].tolist()

        # Criar figura
        fig, ax = plt.subplots(figsize=(14, 6))

        # Posições das barras
        x = range(len(deciles))
        width = 0.35

        # Barras agrupadas
        bars1 = ax.bar(
            [i - width/2 for i in x],
            real_rates,
            width,
            label='Taxa Real (Guru+TMB)',
            color=self.color_real,
            alpha=0.8,
            edgecolor='black',
            linewidth=1
        )

        bars2 = ax.bar(
            [i + width/2 for i in x],
            expected_rates,
            width,
            label='Taxa Esperada (Modelo)',
            color=self.color_expected,
            alpha=0.8,
            edgecolor='black',
            linewidth=1
        )

        # Adicionar valores nas barras
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        height + 0.05,
                        f'{height:.2f}%',
                        ha='center',
                        va='bottom',
                        fontsize=9
                    )

        # Títulos e labels
        ax.set_title(
            'Performance por Decil: Taxa de Conversão Real vs Esperada',
            fontsize=16,
            fontweight='bold',
            pad=20
        )
        ax.set_xlabel('Decil', fontsize=12, fontweight='bold')
        ax.set_ylabel('Taxa de Conversão (%)', fontsize=12, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(deciles)

        # Legenda
        ax.legend(loc='upper left', fontsize=11)

        # Grid
        ax.grid(axis='y', alpha=0.3, linestyle='--')
        ax.set_axisbelow(True)

        plt.tight_layout()

        # Salvar
        output_path = str(Path(output_dir) / 'decile_performance.png')
        plt.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
        plt.close()

        return output_path

    def plot_cumulative_revenue(
        self,
        decile_metrics: pd.DataFrame,
        output_dir: str
    ) -> str:
        """
        Gráfico de linha: Receita acumulada por Decil.

        Mostra que decis superiores (D9-D10) geram maior receita.

        Args:
            decile_metrics: DataFrame de DecileMetricsCalculator
            output_dir: Diretório de saída

        Returns:
            Caminho do arquivo PNG gerado
        """
        if decile_metrics.empty:
            logger.warning("    Nenhuma métrica de decil para plotar")
            fig, ax = plt.subplots(figsize=self.figsize)
            ax.text(0.5, 0.5, 'Sem dados de decil disponíveis',
                   ha='center', va='center', fontsize=14)
            output_path = str(Path(output_dir) / 'cumulative_revenue_by_decile.png')
            plt.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
            plt.close()
            return output_path

        # Calcular receita acumulada
        decile_metrics_sorted = decile_metrics.sort_values('decile')
        cumulative_revenue = decile_metrics_sorted['revenue_total'].cumsum()

        # Criar figura
        fig, ax = plt.subplots(figsize=(14, 6))

        # Linha principal
        ax.plot(
            range(len(cumulative_revenue)),
            cumulative_revenue / 1000,  # Converter para milhares
            marker='o',
            linewidth=3,
            markersize=8,
            color=self.color_real,
            label='Receita Acumulada'
        )

        # Área preenchida
        ax.fill_between(
            range(len(cumulative_revenue)),
            0,
            cumulative_revenue / 1000,
            alpha=0.3,
            color=self.color_real
        )

        # Adicionar valores nos pontos
        for i, value in enumerate(cumulative_revenue):
            ax.text(
                i,
                value / 1000 + (cumulative_revenue.max() / 1000 * 0.02),
                f'R$ {value/1000:.1f}k',
                ha='center',
                va='bottom',
                fontsize=9
            )

        # Títulos e labels
        ax.set_title(
            'Receita Acumulada por Decil (D1  D10)',
            fontsize=16,
            fontweight='bold',
            pad=20
        )
        ax.set_xlabel('Decil', fontsize=12, fontweight='bold')
        ax.set_ylabel('Receita Acumulada (R$ mil)', fontsize=12, fontweight='bold')
        ax.set_xticks(range(len(decile_metrics_sorted)))
        ax.set_xticklabels(decile_metrics_sorted['decile'].tolist())

        # Legenda
        ax.legend(loc='upper left', fontsize=11)

        # Grid
        ax.grid(axis='both', alpha=0.3, linestyle='--')
        ax.set_axisbelow(True)

        plt.tight_layout()

        # Salvar
        output_path = str(Path(output_dir) / 'cumulative_revenue_by_decile.png')
        plt.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
        plt.close()

        return output_path

    def plot_contribution_margin(
        self,
        campaign_metrics: pd.DataFrame,
        output_dir: str,
        top_n: int = 15
    ) -> str:
        """
        Gráfico de barras: Margem de Contribuição por Campanha.

        Ordenado do maior para o menor, com cores:
        - Verde: Margem positiva
        - Vermelho: Margem negativa

        Args:
            campaign_metrics: DataFrame de CampaignMetricsCalculator
            output_dir: Diretório de saída
            top_n: Número de campanhas a exibir (padrão: 15)

        Returns:
            Caminho do arquivo PNG gerado
        """
        if campaign_metrics.empty:
            logger.warning("    Nenhuma métrica de campanha para plotar")
            fig, ax = plt.subplots(figsize=self.figsize)
            ax.text(0.5, 0.5, 'Sem dados de campanha disponíveis',
                   ha='center', va='center', fontsize=14)
            output_path = str(Path(output_dir) / 'contribution_margin_by_campaign.png')
            plt.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
            plt.close()
            return output_path

        # Ordenar por margem (maior para menor) e pegar top_n
        df_sorted = campaign_metrics.sort_values('contribution_margin', ascending=True).tail(top_n)

        # Truncar nomes de campanhas para visualização
        df_sorted['campaign_short'] = df_sorted['campaign'].apply(
            lambda x: x[:50] + '...' if len(str(x)) > 50 else x
        )

        # Cores baseadas em positivo/negativo
        colors = [self.color_com_ml if x >= 0 else self.color_sem_ml
                 for x in df_sorted['contribution_margin']]

        # Criar figura
        fig, ax = plt.subplots(figsize=(12, max(8, len(df_sorted) * 0.5)))

        # Barras horizontais
        bars = ax.barh(
            df_sorted['campaign_short'],
            df_sorted['contribution_margin'] / 1000,  # Converter para milhares
            color=colors,
            alpha=0.8,
            edgecolor='black',
            linewidth=1
        )

        # Linha vertical em zero
        ax.axvline(x=0, color='black', linestyle='-', linewidth=1.5, alpha=0.7)

        # Adicionar valores nas barras
        for i, (bar, value) in enumerate(zip(bars, df_sorted['contribution_margin'])):
            width = bar.get_width()
            label_x = width + (1 if width >= 0 else -1)
            ax.text(
                label_x,
                bar.get_y() + bar.get_height() / 2,
                f'R$ {value/1000:.1f}k',
                ha='left' if width >= 0 else 'right',
                va='center',
                fontsize=9,
                fontweight='bold'
            )

        # Títulos e labels
        ax.set_title(
            f'Margem de Contribuição por Campanha (Top {len(df_sorted)})',
            fontsize=16,
            fontweight='bold',
            pad=20
        )
        ax.set_xlabel('Margem de Contribuição (R$ mil)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Campanha', fontsize=12, fontweight='bold')

        # Grid
        ax.grid(axis='x', alpha=0.3, linestyle='--')
        ax.set_axisbelow(True)

        plt.tight_layout()

        # Salvar
        output_path = str(Path(output_dir) / 'contribution_margin_by_campaign.png')
        plt.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
        plt.close()

        return output_path
