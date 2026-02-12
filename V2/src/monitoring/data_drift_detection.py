#!/usr/bin/env python3
"""
Análise de Feature Drift: Comparação entre período de treino e produção
Usando dados direto do Google Sheets (produção)
"""
import pandas as pd
import numpy as np
from pathlib import Path
import gspread
from google.auth import default

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

GOOGLE_SHEETS_URL = 'https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo/edit'

# Datas de corte - Comparação: 3 períodos
# Período com D10 NORMAL (9.4%)
PERIODO_D10_NORMAL_INICIO = '2026-01-01'
PERIODO_D10_NORMAL_FIM = '2026-01-07'

# Período com D10 ALTO em DEZEMBRO (30.5%)
PERIODO_D10_ALTO_DEZ_INICIO = '2025-12-09'
PERIODO_D10_ALTO_DEZ_FIM = '2025-12-15'

# Período com D10 ALTO em JANEIRO (31.5%)
PERIODO_D10_ALTO_JAN_INICIO = '2026-01-08'
PERIODO_D10_ALTO_JAN_FIM = '2026-01-14'

# Features para analisar
FEATURES_CATEGORICAS = [
    'O seu gênero:',
    'Qual a sua idade?',
    'O que você faz atualmente?',
    'Atualmente, qual a sua faixa salarial?',
    'Você possui cartão de crédito?',
    'Já estudou programação?',
    'Você já fez/faz/pretende fazer faculdade?',
    'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?',
    'O que mais te chama atenção na profissão de Programador?',
    'O que mais você quer ver no evento?',
    'Source',
    'Medium'
]

# =============================================================================
# FUNÇÕES
# =============================================================================

def buscar_dados_sheets():
    """Busca dados direto do Google Sheets de produção"""
    print("   Conectando ao Google Sheets...")

    scopes = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
    ]

    creds, _ = default(scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_url(GOOGLE_SHEETS_URL)

    # Ler aba principal ([LF] Pesquisa)
    print("   Lendo aba principal...")
    worksheet = spreadsheet.get_worksheet(0)
    valores = worksheet.get_all_values()
    headers = valores[0]
    dados = valores[1:]
    df = pd.DataFrame(dados, columns=headers)

    # Converter coluna Data
    df['Data'] = pd.to_datetime(df['Data'], errors='coerce')

    print(f"    {len(df):,} registros carregados")
    print(f"    {df['Data'].notna().sum():,} datas válidas")

    return df

def calcular_divergencia_kl(dist1, dist2):
    """Calcula divergência KL entre duas distribuições (simplificada)"""
    # Adicionar pequeno epsilon para evitar log(0)
    epsilon = 1e-10
    dist1 = np.array(dist1) + epsilon
    dist2 = np.array(dist2) + epsilon

    # Normalizar
    dist1 = dist1 / dist1.sum()
    dist2 = dist2 / dist2.sum()

    kl = np.sum(dist1 * np.log(dist1 / dist2))
    return kl

def comparar_3_periodos(df_normal, df_alto_dez, df_alto_jan, feature, top_n=None):
    """Compara distribuição de uma feature entre 3 períodos"""

    # Contar valores em cada período
    dist_normal = df_normal[feature].value_counts(normalize=True).sort_index()
    dist_alto_dez = df_alto_dez[feature].value_counts(normalize=True).sort_index()
    dist_alto_jan = df_alto_jan[feature].value_counts(normalize=True).sort_index()

    # Criar DataFrame de comparação
    df_comp = pd.DataFrame({
        'Normal Jan1-7 (%)': (dist_normal * 100).round(2),
        'Alto Dez9-15 (%)': (dist_alto_dez * 100).round(2),
        'Alto Jan8-14 (%)': (dist_alto_jan * 100).round(2)
    })

    # Calcular diferenças em relação ao normal
    df_comp['Diff Dez (pp)'] = (df_comp['Alto Dez9-15 (%)'] - df_comp['Normal Jan1-7 (%)']).round(2)
    df_comp['Diff Jan (pp)'] = (df_comp['Alto Jan8-14 (%)'] - df_comp['Normal Jan1-7 (%)']).round(2)
    df_comp['Diff Dez vs Jan (pp)'] = (df_comp['Alto Jan8-14 (%)'] - df_comp['Alto Dez9-15 (%)']).round(2)

    # Preencher NaN com 0 para valores que não existem em um dos períodos
    df_comp = df_comp.fillna(0)

    # Calcular diferença absoluta máxima para ordenar
    df_comp['Max Diff Abs (pp)'] = df_comp[['Diff Dez (pp)', 'Diff Jan (pp)']].abs().max(axis=1)

    # Ordenar por diferença absoluta
    df_comp = df_comp.sort_values('Max Diff Abs (pp)', ascending=False)

    # Limitar top N se especificado
    if top_n:
        df_comp = df_comp.head(top_n)

    return df_comp

def analisar_feature_drift():
    """Análise completa de feature drift: 3 períodos comparados"""

    print("ANÁLISE DE FEATURE DRIFT: COMPARAÇÃO DE 3 PERÍODOS")

    # Carregar dados
    print(f"\n Carregando dados...")
    df = buscar_dados_sheets()

    print(f"   Total de registros: {len(df):,}")

    # Separar os 3 períodos
    # Converter datas de string para datetime
    d10_normal_inicio = pd.to_datetime(PERIODO_D10_NORMAL_INICIO)
    d10_normal_fim = pd.to_datetime(PERIODO_D10_NORMAL_FIM) + pd.Timedelta(days=1)

    d10_alto_dez_inicio = pd.to_datetime(PERIODO_D10_ALTO_DEZ_INICIO)
    d10_alto_dez_fim = pd.to_datetime(PERIODO_D10_ALTO_DEZ_FIM) + pd.Timedelta(days=1)

    d10_alto_jan_inicio = pd.to_datetime(PERIODO_D10_ALTO_JAN_INICIO)
    d10_alto_jan_fim = pd.to_datetime(PERIODO_D10_ALTO_JAN_FIM) + pd.Timedelta(days=1)

    df_d10_normal = df[
        (df['Data'] >= d10_normal_inicio) &
        (df['Data'] < d10_normal_fim) &
        (df['decil'].notna())
    ].copy()

    df_d10_alto_dez = df[
        (df['Data'] >= d10_alto_dez_inicio) &
        (df['Data'] < d10_alto_dez_fim) &
        (df['decil'].notna())
    ].copy()

    df_d10_alto_jan = df[
        (df['Data'] >= d10_alto_jan_inicio) &
        (df['Data'] < d10_alto_jan_fim) &
        (df['decil'].notna())
    ].copy()

    print(f"\n PERÍODOS COMPARADOS:")
    print(f"\n   [1] D10 NORMAL: {PERIODO_D10_NORMAL_INICIO} a {PERIODO_D10_NORMAL_FIM}")
    print(f"      Total de leads: {len(df_d10_normal):,}")
    if len(df_d10_normal) > 0:
        dist_decil = df_d10_normal['decil'].value_counts(normalize=True).get('D10', 0) * 100
        print(f"      % D10: {dist_decil:.1f}%")

    print(f"\n   [2] D10 ALTO DEZ: {PERIODO_D10_ALTO_DEZ_INICIO} a {PERIODO_D10_ALTO_DEZ_FIM}")
    print(f"      Total de leads: {len(df_d10_alto_dez):,}")
    if len(df_d10_alto_dez) > 0:
        dist_decil = df_d10_alto_dez['decil'].value_counts(normalize=True).get('D10', 0) * 100
        print(f"      % D10: {dist_decil:.1f}%")

    print(f"\n   [3] D10 ALTO JAN: {PERIODO_D10_ALTO_JAN_INICIO} a {PERIODO_D10_ALTO_JAN_FIM}")
    print(f"      Total de leads: {len(df_d10_alto_jan):,}")
    if len(df_d10_alto_jan) > 0:
        dist_decil = df_d10_alto_jan['decil'].value_counts(normalize=True).get('D10', 0) * 100
        print(f"      % D10: {dist_decil:.1f}%")

    # Analisar cada feature
    print("COMPARAÇÃO DE FEATURES: 3 PERÍODOS")

    drift_summary = []

    for feature in FEATURES_CATEGORICAS:
        if feature not in df.columns:
            print(f"\n  Feature '{feature}' não encontrada nos dados")
            continue

        print(f" {feature.upper()}")

        # Comparar distribuições dos 3 períodos
        top_n = 10 if feature in ['Medium', 'Campaign', 'Source'] else None
        df_comp = comparar_3_periodos(df_d10_normal, df_d10_alto_dez, df_d10_alto_jan, feature, top_n=top_n)

        # Imprimir tabela
        print(f"\n{df_comp.to_string()}")

        # Calcular drift scores
        max_drift_dez = df_comp['Diff Dez (pp)'].abs().max()
        max_drift_jan = df_comp['Diff Jan (pp)'].abs().max()
        max_drift_dez_vs_jan = df_comp['Diff Dez vs Jan (pp)'].abs().max()

        drift_summary.append({
            'Feature': feature,
            'Max Drift Dez (pp)': max_drift_dez,
            'Max Drift Jan (pp)': max_drift_jan,
            'Diff Dez vs Jan (pp)': max_drift_dez_vs_jan,
        })

        # Alerta se drift significativo
        print(f"\n   Drift em Dez: ", end="")
        if max_drift_dez > 5:
            print(f" ALTO ({max_drift_dez:.2f}pp)")
        elif max_drift_dez > 2:
            print(f"  MODERADO ({max_drift_dez:.2f}pp)")
        else:
            print(f" BAIXO ({max_drift_dez:.2f}pp)")

        print(f"   Drift em Jan: ", end="")
        if max_drift_jan > 5:
            print(f" ALTO ({max_drift_jan:.2f}pp)")
        elif max_drift_jan > 2:
            print(f"  MODERADO ({max_drift_jan:.2f}pp)")
        else:
            print(f" BAIXO ({max_drift_jan:.2f}pp)")

        print(f"   Diff Dez vs Jan: ", end="")
        if max_drift_dez_vs_jan > 5:
            print(f" MUITO DIFERENTE ({max_drift_dez_vs_jan:.2f}pp)")
        elif max_drift_dez_vs_jan > 2:
            print(f" PARCIALMENTE DIFERENTE ({max_drift_dez_vs_jan:.2f}pp)")
        else:
            print(f" SIMILAR ({max_drift_dez_vs_jan:.2f}pp)")

    # Resumo geral de drift
    print(" RESUMO DE FEATURE DRIFT - 3 PERÍODOS")

    df_drift_summary = pd.DataFrame(drift_summary)
    # Ordenar por maior drift (considerar o máximo entre Dez e Jan)
    df_drift_summary['Max Drift Overall (pp)'] = df_drift_summary[['Max Drift Dez (pp)', 'Max Drift Jan (pp)']].max(axis=1)
    df_drift_summary = df_drift_summary.sort_values('Max Drift Overall (pp)', ascending=False)

    print(f"\n{df_drift_summary.to_string(index=False)}")

    # Análise: Features com drift similar vs diferente
    print(" ANÁLISE: DEZ vs JAN - São os mesmos fatores?")

    features_similares = df_drift_summary[df_drift_summary['Diff Dez vs Jan (pp)'] <= 2]
    features_diferentes = df_drift_summary[df_drift_summary['Diff Dez vs Jan (pp)'] > 2]

    print(f"\n FATORES SIMILARES (Dez e Jan têm o mesmo comportamento):")
    print(f"   Total: {len(features_similares)}")
    if len(features_similares) > 0:
        for _, row in features_similares.iterrows():
            print(f"    {row['Feature']}: Diff = {row['Diff Dez vs Jan (pp)']:.2f}pp")

    print(f"\n FATORES DIFERENTES (Dez e Jan têm comportamentos distintos):")
    print(f"   Total: {len(features_diferentes)}")
    if len(features_diferentes) > 0:
        for _, row in features_diferentes.iterrows():
            print(f"    {row['Feature']}: Diff = {row['Diff Dez vs Jan (pp)']:.2f}pp")

    # Análise de decis por período
    print(" DISTRIBUIÇÃO DE DECIS - 3 PERÍODOS")

    print(f"\n [1] D10 NORMAL ({PERIODO_D10_NORMAL_INICIO} a {PERIODO_D10_NORMAL_FIM}):")
    if len(df_d10_normal) > 0:
        dist_decis_normal = df_d10_normal['decil'].value_counts(normalize=True).sort_index() * 100
        for decil, pct in dist_decis_normal.items():
            emoji = "" if decil == 'D10' and pct > 15 else ""
            print(f"   {decil}: {pct:.2f}% {emoji}")

    print(f"\n [2] D10 ALTO DEZ ({PERIODO_D10_ALTO_DEZ_INICIO} a {PERIODO_D10_ALTO_DEZ_FIM}):")
    if len(df_d10_alto_dez) > 0:
        dist_decis_alto_dez = df_d10_alto_dez['decil'].value_counts(normalize=True).sort_index() * 100
        for decil, pct in dist_decis_alto_dez.items():
            emoji = "" if decil == 'D10' and pct > 15 else ""
            print(f"   {decil}: {pct:.2f}% {emoji}")

    print(f"\n [3] D10 ALTO JAN ({PERIODO_D10_ALTO_JAN_INICIO} a {PERIODO_D10_ALTO_JAN_FIM}):")
    if len(df_d10_alto_jan) > 0:
        dist_decis_alto_jan = df_d10_alto_jan['decil'].value_counts(normalize=True).sort_index() * 100
        for decil, pct in dist_decis_alto_jan.items():
            emoji = "" if decil == 'D10' and pct > 15 else ""
            print(f"   {decil}: {pct:.2f}% {emoji}")


if __name__ == '__main__':
    analisar_feature_drift()
