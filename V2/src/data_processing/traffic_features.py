"""
Módulo para processamento de features de tráfego Meta.

Integra métricas de campanhas Meta (AdSet level) ao dataset de treino.
"""

import pandas as pd
import numpy as np
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def consolidar_relatorios_meta(pasta_trafego: str) -> pd.DataFrame:
    """
    Consolida múltiplos CSVs Meta em um único DataFrame.

    Args:
        pasta_trafego: Caminho para pasta com CSVs de relatórios Meta

    Returns:
        DataFrame consolidado com todas as métricas Meta
    """
    pasta = Path(pasta_trafego)

    if not pasta.exists():
        raise FileNotFoundError(f"Pasta não encontrada: {pasta_trafego}")

    # Encontrar todos os CSVs
    csv_files = list(pasta.glob("*.csv"))

    if not csv_files:
        raise FileNotFoundError(f"Nenhum CSV encontrado em: {pasta_trafego}")

    print(f"\n📂 CONSOLIDANDO RELATÓRIOS META")
    print("=" * 60)
    print(f"Pasta: {pasta_trafego}")
    print(f"CSVs encontrados: {len(csv_files)}")

    dfs = []
    for csv_file in csv_files:
        print(f"\n  Lendo: {csv_file.name}")
        df = pd.read_csv(csv_file)
        print(f"    Linhas: {len(df):,}")
        dfs.append(df)

    # Concatenar todos
    df_consolidado = pd.concat(dfs, ignore_index=True)

    print(f"\n✅ Consolidado: {len(df_consolidado):,} registros")

    return df_consolidado


def renomear_colunas_meta(df_meta: pd.DataFrame) -> pd.DataFrame:
    """
    Renomeia colunas do formato PT (Meta) para formato padrão EN.

    Args:
        df_meta: DataFrame com colunas em português

    Returns:
        DataFrame com colunas renomeadas
    """
    mapeamento = {
        'Início dos relatórios': 'date_start',
        'Término dos relatórios': 'date_stop',
        'Nome do conjunto de anúncios': 'adset_name',
        'Nome da campanha': 'campaign_name',
        'Identificação da campanha': 'campaign_id',
        'Identificação do conjunto de anúncios': 'adset_id',
        'Impressões': 'impressions',
        'CPM (custo por 1.000 impressões) (BRL)': 'cpm',
        'Alcance': 'reach',
        'Frequência': 'frequency',
        'Cliques no link': 'inline_link_clicks',
        'CTR (taxa de cliques no link)': 'ctr',
        'Valor usado (BRL)': 'spend',
        'CPC (todos) (BRL)': 'cpc'
    }

    df_renamed = df_meta.rename(columns=mapeamento)

    print(f"\n📝 RENOMEANDO COLUNAS")
    print("=" * 60)
    print(f"Colunas renomeadas: {len(mapeamento)}")

    # Verificar se todas as colunas esperadas existem
    colunas_faltando = set(mapeamento.values()) - set(df_renamed.columns)
    if colunas_faltando:
        print(f"⚠️  Colunas faltando: {colunas_faltando}")

    return df_renamed


def normalizar_adset_name_para_medium(adset_name: str) -> str:
    """
    Normaliza adset_name para categoria Medium (mesmo tratamento do pipeline).

    Reproduz lógica de:
    - medium_training.py (extrair_publico)
    - medium_production_training.py (aplicar_unificacao_robusta)

    Args:
        adset_name: Nome do adset do relatório Meta

    Returns:
        Categoria Medium normalizada (produção)
    """
    if pd.isna(adset_name):
        return np.nan

    adset_str = str(adset_name).strip()

    # PASSO 1: Extrair público (remover prefixos)
    # Lógica do medium_training.py (linhas 44-71)
    if '|' in adset_str:
        partes = adset_str.split('|')
        if len(partes) >= 2:
            # Se primeira parte é "ADV" ou "Leads DEVLF", pegar segunda parte
            primeiro = partes[0].strip().upper()
            if primeiro in ['ADV', 'ADV ', 'LEADS DEVLF']:
                publico = partes[1].strip()
            else:
                publico = partes[0].strip()
        else:
            publico = adset_str
    else:
        publico = adset_str

    # Se ainda sobrou só "ADV", tentar alternativa
    if publico.upper().strip() == 'ADV':
        if '|' in adset_str:
            publico = adset_str.split('|', 1)[1].strip()

    # PASSO 2: Aplicar mapeamento de produção
    # Lógica do medium_production_training.py (mapping_dict)

    # Categorias válidas de produção (8 categorias)
    categorias_validas = {
        'Aberto',
        'Interesse Programação',
        'Linguagem de programação',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'Lookalike 2% Alunos + Interesse Linguagem de Programação',
        'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Outros',
        'dgen'
    }

    # Mapeamento direto
    mapping_dict = {
        # Válidas (manter)
        'Lookalike 2% Cadastrados - DEV 2.0 + Interesses': 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Aberto': 'Aberto',
        'Linguagem de programação': 'Linguagem de programação',
        'Lookalike 2% Alunos + Interesse Linguagem de Programação': 'Lookalike 2% Alunos + Interesse Linguagem de Programação',
        'dgen': 'dgen',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação': 'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'Interesse Programação': 'Interesse Programação',

        # Variações
        'Interesse Linguagem de programação': 'Linguagem de programação',
        'Lookalike 2% Cadastrados - DEV 2.0   Interesses': 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',

        # Descontinuadas → Outros
        'Lookalike 2% Alunos + Interesse Ciência da Computação': 'Outros',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação': 'Outros',
        'Interesse Python (linguagem de programação)': 'Outros',
        'Interesse Python': 'Outros',
        'Interesse Ciência da computação': 'Outros',
        'Lookalike 3% Alunos + Interesses': 'Outros',
        'Lookalike 3% Cadastrados - DEV 2.0 + Interesses': 'Outros',
        'Lookalike Envolvimento 30D + Salvou 180D + Direct 180D + Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 30D + Salvou 180D + Direct 180D + Interesse Linguagem de Programação': 'Outros',
        'Lookalike Envolvimento 60D + Salvou 365D + Direct 365D + Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 60D + Salvou 365D + Direct 365D + Interesse Linguagem de Programação': 'Outros',
    }

    # Verificar mapeamento direto
    if publico in mapping_dict:
        return mapping_dict[publico]

    # Se é categoria válida mas não está no mapeamento, manter
    if publico in categorias_validas:
        return publico

    # Tudo que não reconhecer → Outros
    return 'Outros'


def agregar_metricas_por_categoria(df_meta: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega métricas Meta por categoria Medium (8 categorias de produção).

    Args:
        df_meta: DataFrame Meta com colunas renomeadas

    Returns:
        DataFrame agregado: 1 linha por categoria Medium
    """
    print(f"\n🔄 NORMALIZANDO ADSET NAMES PARA CATEGORIAS MEDIUM")
    print("=" * 60)

    # Aplicar normalização
    df_meta['medium_categoria'] = df_meta['adset_name'].apply(normalizar_adset_name_para_medium)

    # Mostrar distribuição
    print(f"\nDistribuição por categoria Medium:")
    dist = df_meta['medium_categoria'].value_counts()
    for categoria, count in dist.items():
        pct = count / len(df_meta) * 100
        print(f"  {str(categoria)[:50]:<52} {count:>6,} ({pct:>5.1f}%)")

    print(f"\n📊 AGREGANDO MÉTRICAS POR CATEGORIA")
    print("=" * 60)

    # Agregar métricas (SOMAS primeiro)
    df_agg = df_meta.groupby('medium_categoria').agg({
        # Soma (volumes)
        'impressions': 'sum',
        'reach': 'sum',
        'inline_link_clicks': 'sum',
        'spend': 'sum',

        # Contagem (quantos adsets)
        'adset_id': 'count'
    }).reset_index()

    # Renomear coluna de contagem
    df_agg = df_agg.rename(columns={
        'medium_categoria': 'Medium',
        'adset_id': 'num_adsets'
    })

    # CALCULAR métricas derivadas (CPC, CTR, CPM, Frequency)
    # Método: totais agregados (matematicamente equivalente à média ponderada)
    df_agg['cpc'] = df_agg['spend'] / df_agg['inline_link_clicks']
    df_agg['ctr'] = (df_agg['inline_link_clicks'] / df_agg['impressions']) * 100
    df_agg['cpm'] = (df_agg['spend'] / df_agg['impressions']) * 1000
    df_agg['frequency'] = df_agg['impressions'] / df_agg['reach']

    # Tratar divisões por zero (inf → 0)
    df_agg = df_agg.replace([np.inf, -np.inf], 0)

    # Renomear features com prefixo traffic_
    colunas_metricas = ['impressions', 'reach', 'inline_link_clicks', 'spend', 'cpc', 'ctr', 'cpm', 'frequency', 'num_adsets']
    rename_dict = {col: f'traffic_{col}' for col in colunas_metricas}
    df_agg = df_agg.rename(columns=rename_dict)

    print(f"\nMétricas agregadas: {len(df_agg)} categorias")
    print(f"Colunas criadas: {list(df_agg.columns)}")

    return df_agg


def adicionar_features_trafego_meta(
    df_leads: pd.DataFrame,
    pasta_trafego: str,
    coluna_medium: str = 'Medium'
) -> pd.DataFrame:
    """
    Pipeline completo: carrega relatórios Meta, agrega e faz join com leads.

    Args:
        df_leads: DataFrame de leads (deve ter coluna Medium)
        pasta_trafego: Caminho para pasta com CSVs Meta
        coluna_medium: Nome da coluna Medium no df_leads

    Returns:
        DataFrame de leads enriquecido com features de tráfego
    """
    print(f"\n{'='*80}")
    print(f"ADICIONANDO FEATURES DE TRÁFEGO META")
    print(f"{'='*80}")

    # Validar coluna Medium
    if coluna_medium not in df_leads.columns:
        raise ValueError(f"Coluna '{coluna_medium}' não encontrada no DataFrame de leads")

    print(f"\nDataset de leads:")
    print(f"  Registros: {len(df_leads):,}")
    print(f"  Colunas: {len(df_leads.columns)}")

    # 1. Consolidar relatórios Meta
    df_meta = consolidar_relatorios_meta(pasta_trafego)

    # 2. Renomear colunas
    df_meta = renomear_colunas_meta(df_meta)

    # 3. Agregar por categoria Medium
    df_meta_agg = agregar_metricas_por_categoria(df_meta)

    # 4. Join com leads
    print(f"\n🔗 FAZENDO JOIN COM LEADS")
    print("=" * 60)

    print(f"Leads antes do join: {len(df_leads):,}")
    print(f"Categorias Meta: {len(df_meta_agg)}")

    df_enriquecido = df_leads.merge(
        df_meta_agg,
        on='Medium',
        how='left'
    )

    print(f"Leads após join: {len(df_enriquecido):,}")

    # Verificar % de match
    leads_com_match = df_enriquecido['traffic_impressions'].notna().sum()
    leads_sem_match = df_enriquecido['traffic_impressions'].isna().sum()
    pct_match = leads_com_match / len(df_enriquecido) * 100

    print(f"\n📈 RESULTADO DO MATCH:")
    print(f"  Leads com features de tráfego: {leads_com_match:,} ({pct_match:.1f}%)")
    print(f"  Leads sem features de tráfego: {leads_sem_match:,} ({100-pct_match:.1f}%)")

    if leads_sem_match > 0:
        print(f"\n⚠️  Categorias Medium sem match:")
        categorias_sem_match = df_enriquecido[df_enriquecido['traffic_impressions'].isna()]['Medium'].value_counts()
        for cat, count in categorias_sem_match.head(10).items():
            print(f"    {str(cat)[:40]:<42} {count:>6,}")

    # Preencher NaN com 0 (leads sem match = sem dados de tráfego)
    colunas_traffic = [col for col in df_enriquecido.columns if col.startswith('traffic_')]
    df_enriquecido[colunas_traffic] = df_enriquecido[colunas_traffic].fillna(0)

    print(f"\n✅ FEATURES DE TRÁFEGO ADICIONADAS:")
    print(f"  Novas colunas: {len(colunas_traffic)}")
    for col in colunas_traffic:
        print(f"    - {col}")

    print(f"\nDataset final:")
    print(f"  Registros: {len(df_enriquecido):,}")
    print(f"  Colunas: {len(df_enriquecido.columns)} (+{len(colunas_traffic)} traffic)")

    logger.info(f"✅ Features de tráfego adicionadas: {len(colunas_traffic)} colunas, {pct_match:.1f}% match")

    return df_enriquecido


def adicionar_features_temporais_medium(
    df_leads: pd.DataFrame,
    coluna_data: str = 'Data',
    coluna_medium: str = 'Medium'
) -> pd.DataFrame:
    """
    Adiciona features temporais baseadas na densidade de leads por Medium.

    Não usa dados do Meta - apenas conta leads por período para capturar
    dinâmica temporal das campanhas (proxy de atividade/performance).

    Features criadas:
    - medium_densidade_7d: % de leads com mesmo Medium nos últimos 7 dias
    - medium_densidade_30d: % de leads com mesmo Medium nos últimos 30 dias
    - medium_tendencia: crescendo/decrescendo/estável (comparação 7d vs 30d)
    - medium_rank_7d: ranking do Medium por volume nos últimos 7 dias

    Args:
        df_leads: DataFrame de leads (deve ter colunas Data e Medium)
        coluna_data: Nome da coluna de data
        coluna_medium: Nome da coluna Medium

    Returns:
        DataFrame enriquecido com features temporais
    """
    print(f"\n{'='*80}")
    print(f"ADICIONANDO FEATURES TEMPORAIS DE MEDIUM")
    print(f"{'='*80}")

    # Validar colunas
    if coluna_data not in df_leads.columns:
        raise ValueError(f"Coluna '{coluna_data}' não encontrada")
    if coluna_medium not in df_leads.columns:
        raise ValueError(f"Coluna '{coluna_medium}' não encontrada")

    print(f"\nDataset de leads:")
    print(f"  Registros: {len(df_leads):,}")
    print(f"  Período: {df_leads[coluna_data].min()} a {df_leads[coluna_data].max()}")

    # Garantir que Data é datetime
    df = df_leads.copy()
    df[coluna_data] = pd.to_datetime(df[coluna_data])

    # Ordenar por data
    df = df.sort_values(coluna_data).reset_index(drop=True)

    print(f"\n🔄 CALCULANDO FEATURES TEMPORAIS...")
    print("=" * 60)

    # Inicializar colunas
    df['medium_densidade_7d'] = 0.0
    df['medium_densidade_30d'] = 0.0
    df['medium_rank_7d'] = 0

    # VERSÃO SUPER OTIMIZADA: Agregar por DIA + Medium (reduz de 108k para ~2k cálculos!)
    print(f"  Processando {len(df):,} leads (versão super otimizada)...")

    # Extrair apenas a data (sem hora) para agregação
    df['data_dia'] = df[coluna_data].dt.date

    # Contar leads por dia e Medium
    print(f"  Agregando por dia + Medium...")
    contagem_dia_medium = df.groupby(['data_dia', coluna_medium]).size().reset_index(name='leads_do_dia')

    # Criar dicionário de datas únicas
    datas_unicas = sorted(df['data_dia'].unique())

    print(f"  Calculando densidades para ~{len(datas_unicas)} dias...")

    # Para cada dia + medium, calcular densidade dos últimos 7 e 30 dias
    densidade_cache = {}

    for data in datas_unicas:
        # Converter data para datetime.date se necessário
        if isinstance(data, pd.Timestamp):
            data = data.date()

        # Calcular datas das janelas
        data_7d = data - pd.Timedelta(days=7).to_pytimedelta()
        data_30d = data - pd.Timedelta(days=30).to_pytimedelta()

        # Leads nos últimos 7 dias
        mask_7d = (df['data_dia'] >= data_7d) & (df['data_dia'] < data)
        leads_7d = df[mask_7d]
        total_7d = len(leads_7d)

        # Leads nos últimos 30 dias
        mask_30d = (df['data_dia'] >= data_30d) & (df['data_dia'] < data)
        leads_30d = df[mask_30d]
        total_30d = len(leads_30d)

        # Para cada Medium
        for medium in df[coluna_medium].unique():
            if pd.isna(medium):
                continue

            # Densidade 7d
            if total_7d > 0:
                mesmo_medium_7d = (leads_7d[coluna_medium] == medium).sum()
                densidade_7d = mesmo_medium_7d / total_7d * 100

                # Rank 7d
                contagens = leads_7d[coluna_medium].value_counts()
                if medium in contagens.index:
                    rank = (contagens >= contagens[medium]).sum()
                else:
                    rank = 0
            else:
                densidade_7d = 0.0
                rank = 0

            # Densidade 30d
            if total_30d > 0:
                mesmo_medium_30d = (leads_30d[coluna_medium] == medium).sum()
                densidade_30d = mesmo_medium_30d / total_30d * 100
            else:
                densidade_30d = 0.0

            # Armazenar no cache
            densidade_cache[(data, medium)] = {
                'densidade_7d': densidade_7d,
                'densidade_30d': densidade_30d,
                'rank_7d': rank
            }

    # Aplicar cache aos leads originais
    print(f"  Aplicando resultados aos leads...")
    for idx, row in df.iterrows():
        data_dia = row['data_dia']
        medium = row[coluna_medium]

        if (data_dia, medium) in densidade_cache:
            cache = densidade_cache[(data_dia, medium)]
            df.at[idx, 'medium_densidade_7d'] = cache['densidade_7d']
            df.at[idx, 'medium_densidade_30d'] = cache['densidade_30d']
            df.at[idx, 'medium_rank_7d'] = cache['rank_7d']

    # Remover coluna auxiliar
    df = df.drop(columns=['data_dia'])

    # Calcular tendência (7d vs 30d)
    print(f"\n  Calculando tendências...")
    df['medium_tendencia'] = 'estável'

    # Crescendo: densidade 7d > densidade 30d (com margem de 5%)
    crescendo = df['medium_densidade_7d'] > (df['medium_densidade_30d'] * 1.05)
    df.loc[crescendo, 'medium_tendencia'] = 'crescendo'

    # Decrescendo: densidade 7d < densidade 30d (com margem de 5%)
    decrescendo = df['medium_densidade_7d'] < (df['medium_densidade_30d'] * 0.95)
    df.loc[decrescendo, 'medium_tendencia'] = 'decrescendo'

    print(f"\n✅ FEATURES TEMPORAIS CRIADAS:")
    print(f"  - medium_densidade_7d: % de leads com mesmo Medium nos últimos 7 dias")
    print(f"  - medium_densidade_30d: % de leads com mesmo Medium nos últimos 30 dias")
    print(f"  - medium_tendencia: crescendo/decrescendo/estável")
    print(f"  - medium_rank_7d: ranking do Medium por volume (1=mais leads)")

    # Estatísticas
    print(f"\n📊 ESTATÍSTICAS:")
    print(f"  Densidade 7d  - média: {df['medium_densidade_7d'].mean():.1f}%, std: {df['medium_densidade_7d'].std():.1f}%")
    print(f"  Densidade 30d - média: {df['medium_densidade_30d'].mean():.1f}%, std: {df['medium_densidade_30d'].std():.1f}%")
    print(f"\n  Tendências:")
    print(f"    Crescendo:   {(df['medium_tendencia'] == 'crescendo').sum():,} leads ({(df['medium_tendencia'] == 'crescendo').sum()/len(df)*100:.1f}%)")
    print(f"    Estável:     {(df['medium_tendencia'] == 'estável').sum():,} leads ({(df['medium_tendencia'] == 'estável').sum()/len(df)*100:.1f}%)")
    print(f"    Decrescendo: {(df['medium_tendencia'] == 'decrescendo').sum():,} leads ({(df['medium_tendencia'] == 'decrescendo').sum()/len(df)*100:.1f}%)")

    logger.info(f"✅ Features temporais adicionadas: 4 features, densidade média 7d={df['medium_densidade_7d'].mean():.1f}%")

    return df
