"""
Módulo para comparação fair control em nível de ADSETS e ADS.

Compara campanhas Champion vs Challenger no nível de conjuntos de anúncios e anúncios individuais.
Foco em métricas de negócio: ROAS, CPA, Margem de Contribuição, Taxa de Conversão.

Princípio: "Maçãs com Maçãs"
- Compara MESMOS adsets (mesmo targeting/público)
- Compara MESMOS ads (mesmo criativo)
- Filtro de gasto mínimo: R$ 200 por adset/ad
"""

import os
import sys
import logging
from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime
from pathlib import Path
import pandas as pd

# Adicionar path para imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Importar ajuste TMB
from src.validation.tmb_adjuster import adjust_revenue_for_tmb, FATOR_TMB_MEDIO

# Meta Ads API
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad

# Token fixo do projeto
from api.meta_config import META_CONFIG

logger = logging.getLogger(__name__)


# ============================================================================
# HELPER: CRIAR MAPEAMENTO REFINADO DE CAMPANHAS
# ============================================================================

def create_refined_campaign_map(
    campaigns_df: pd.DataFrame,
    ml_campaign_ids: List[str],
    control_campaign_ids: List[str]
) -> Dict[str, str]:
    """
    Cria mapeamento refinado: campaign_id  comparison_group.

    Distingue entre:
    - 'Champion': Campanhas ML que usam eventos CAPI customizados (LeadQualified/LQHQ)
    - 'Otimização ML': Campanhas ML que NÃO usam eventos customizados
    - 'Challenger': Campanhas sem ML

    Args:
        campaigns_df: DataFrame com campanhas (deve ter optimization_goal)
        ml_campaign_ids: Lista de IDs de campanhas ML
        control_campaign_ids: Lista de IDs de campanhas Controle

    Returns:
        Dict mapping campaign_id  comparison_group ('Champion', 'Otimização ML', ou 'Challenger')
    """
    refined_map = {}

    # DEBUG: Mostrar colunas disponíveis
    logger.info(f"    DEBUG create_refined_campaign_map:")
    logger.info(f"      Colunas disponíveis: {list(campaigns_df.columns)[:10]}")
    logger.info(f"      Total de linhas: {len(campaigns_df)}")

    # Criar lookup de campaign_id  optimization_goal e campaign_name
    if 'campaign_id' in campaigns_df.columns:
        # Limpar campaign_id (primeiros 15 dígitos)
        campaigns_df['campaign_id_clean'] = campaigns_df['campaign_id'].astype(str).str[:15]

        opt_goal_map = {}
        campaign_name_map = {}

        for idx, row in campaigns_df.iterrows():
            cid = str(row['campaign_id_clean'])
            opt_goal = str(row.get('optimization_goal', ''))
            campaign_name = str(row.get('campaign_name', ''))

            opt_goal_map[cid] = opt_goal
            campaign_name_map[cid] = campaign_name
    else:
        opt_goal_map = {}
        campaign_name_map = {}

    # Classificar campanhas ML
    # Champion ML  = LEADQUALIFIED (tag UTM) ou MACHINE LEARNING (legado) ou opt_goal LeadQualified
    # Challenger ML = LEADHQLB/HQLB (tag UTM do A/B abr28 — novo braço ML)
    # Otimização ML = outras campanhas ML sem CAPI custom
    for cid in ml_campaign_ids:
        cid_clean = str(cid)[:15]
        opt_goal = opt_goal_map.get(cid_clean, '')
        campaign_name = campaign_name_map.get(cid_clean, '')
        name_lower = campaign_name.lower()

        # PRIORIDADE 1: Challenger ML — LEADHQLB no nome ou HQLB no opt_goal
        if 'leadhqlb' in name_lower or 'hqlb' in name_lower or 'HQLB' in opt_goal:
            refined_map[cid_clean] = 'Challenger'
            logger.info(f"    Champion classificada como Challenger ML (LEADHQLB): {cid_clean}")
            continue

        # PRIORIDADE 2: Champion ML — MACHINE LEARNING (legado)
        if 'machine learning' in name_lower:
            refined_map[cid_clean] = 'Champion'
            logger.info(f"    Campanha classificada como Champion ML (nome contém MACHINE LEARNING): {cid_clean}")
            continue

        # PRIORIDADE 3: Champion ML — LEADQUALIFIED no nome
        if 'leadqualified' in name_lower:
            refined_map[cid_clean] = 'Champion'
            continue

        # PRIORIDADE 4: opt_goal LeadQualified custom event
        uses_custom_events = any(custom in opt_goal for custom in ['LeadQualified', 'LeadQualifiedHighQuality'])
        if uses_custom_events:
            refined_map[cid_clean] = 'Champion'
        else:
            refined_map[cid_clean] = 'Otimização ML'

    # Classificar campanhas Controle puro (DEVLF sem sufixo ML)
    logger.info(f"    DEBUG - Classificando {len(control_campaign_ids)} campanhas Controle:")
    for cid in control_campaign_ids:
        cid_clean = str(cid)[:15]
        refined_map[cid_clean] = 'Controle'
        logger.info(f"       {cid_clean}  Controle")

    logger.info(f"    Mapeamento refinado criado:")
    eventos_ml = sum(1 for v in refined_map.values() if v == 'Champion')
    challenger_ml = sum(1 for v in refined_map.values() if v == 'Challenger')
    otimiz_ml = sum(1 for v in refined_map.values() if v == 'Otimização ML')
    controle = sum(1 for v in refined_map.values() if v == 'Controle')
    logger.info(f"      Champion ML: {eventos_ml}, Challenger ML: {challenger_ml}, Otimização ML: {otimiz_ml}, Controle: {controle}")

    return refined_map


# ============================================================================
# HELPER: NORMALIZAR WHITESPACE EM ADSET NAMES
# ============================================================================

def normalize_whitespace(text: str) -> str:
    """
    Normaliza espaços em branco em nomes de adsets para matching consistente.

    - Colapsa múltiplos espaços em um único espaço
    - Remove espaços no início e fim

    Args:
        text: Texto a normalizar

    Returns:
        Texto normalizado
    """
    import re
    if pd.isna(text):
        return text
    # Colapsar múltiplos espaços em um único
    normalized = re.sub(r'\s+', ' ', str(text))
    # Remover espaços no início e fim
    return normalized.strip()


# ============================================================================
# CONFIGURAÇÃO: ADSETS E ADS MATCHED
# ============================================================================

# Definição dos matched adsets (aparecem em ML E Controle)
# IMPORTANTE: Espaçamento será normalizado automaticamente (múltiplos espaços  1 espaço)
MATCHED_ADSETS = [
    'ABERTO | AD0022',
    'ABERTO | AD0027',
    'ADV | Linguagem de programação',
    'ADV | Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
    'ADV | Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
]

# Normalizar MATCHED_ADSETS ao carregar o módulo
MATCHED_ADSETS = [normalize_whitespace(adset) for adset in MATCHED_ADSETS]

# Definição dos matched ads (aparecem em ML E Controle)
MATCHED_ADS = [
    'AD0013', 'AD0014', 'AD0017', 'AD0018', 'AD0022', 'AD0027', 'AD0033'
]

# Gasto mínimo para incluir adset/ad na comparação (R$)
MIN_SPEND = 0.0


# ============================================================================
# FUNÇÕES DE IDENTIFICAÇÃO DE MATCHED PAIRS
# ============================================================================

def identify_matched_adset_pairs(
    adsets_df: pd.DataFrame,
    ml_campaign_ids: List[str],
    control_campaign_ids: List[str],
    min_spend: float = MIN_SPEND,
    use_dynamic_matching: bool = False
) -> Tuple[List[str], pd.DataFrame]:
    """
    Identifica adsets que aparecem tanto em campanhas ML quanto controle.

    Args:
        adsets_df: DataFrame com adsets e suas métricas
        ml_campaign_ids: IDs das campanhas ML
        control_campaign_ids: IDs das campanhas controle
        min_spend: Gasto mínimo para incluir adset (default: R$ 200)
        use_dynamic_matching: Se True, usa TODOS os adsets identificados dinamicamente.
                              Se False (padrão), usa apenas MATCHED_ADSETS pré-definidos.

    Returns:
        Tuple (matched_adsets, adsets_metrics_df)
        - matched_adsets: Lista de nomes de adsets matched
        - adsets_metrics_df: DataFrame com métricas por adset
    """
    logger.info(" Identificando matched pairs de adsets...")

    # CRÍTICO: Normalizar whitespace em adset_name para matching consistente
    adsets_df = adsets_df.copy()
    adsets_df['adset_name'] = adsets_df['adset_name'].apply(normalize_whitespace)

    # Adsets em campanhas ML - AGREGAR primeiro, DEPOIS filtrar
    ml_adsets_all = adsets_df[adsets_df['campaign_id'].isin(ml_campaign_ids)]
    if not ml_adsets_all.empty:
        # MUDANÇA: Usar 'total_spend' (histórico) em vez de 'spend' (filtrado por período)
        # Isso permite identificar matched adsets que têm gasto histórico, mesmo que não no período atual
        spend_col = 'total_spend' if 'total_spend' in ml_adsets_all.columns else 'spend'
        # Agregar spend por adset_name
        ml_adsets_agg = ml_adsets_all.groupby('adset_name')[spend_col].sum().reset_index()
        # Filtrar por gasto mínimo agregado
        ml_adsets_filtered = ml_adsets_agg[ml_adsets_agg[spend_col] >= min_spend]
        ml_adsets = set(ml_adsets_filtered['adset_name'].dropna().unique().tolist())
        total_spend_sum = ml_adsets_agg[spend_col].sum()
        logger.info(f"    ML: {len(ml_adsets)} adsets com {spend_col} >= R$ {min_spend:.0f}")
        logger.info(f"      Total {spend_col}: R$ {total_spend_sum:.2f}")
    else:
        ml_adsets = set()

    # Adsets em campanhas controle - AGREGAR primeiro, DEPOIS filtrar
    ctrl_adsets_all = adsets_df[adsets_df['campaign_id'].isin(control_campaign_ids)]
    if not ctrl_adsets_all.empty:
        # MUDANÇA: Usar 'total_spend' (histórico) em vez de 'spend' (filtrado por período)
        spend_col = 'total_spend' if 'total_spend' in ctrl_adsets_all.columns else 'spend'
        # Agregar spend por adset_name
        ctrl_adsets_agg = ctrl_adsets_all.groupby('adset_name')[spend_col].sum().reset_index()
        # Filtrar por gasto mínimo agregado
        ctrl_adsets_filtered = ctrl_adsets_agg[ctrl_adsets_agg[spend_col] >= min_spend]
        control_adsets = set(ctrl_adsets_filtered['adset_name'].dropna().unique().tolist())
        logger.info(f"    Controle: {len(control_adsets)} adsets com {spend_col} >= R$ {min_spend:.0f}")
    else:
        control_adsets = set()

    # Matched pairs (interseção)
    matched = list(ml_adsets.intersection(control_adsets))

    # DEBUG: Mostrar adsets matched
    logger.info(f"    DEBUG - Adsets matched (interseção dinâmica): {len(matched)}")
    for adset in sorted(matched):
        logger.info(f"       {repr(adset)}")

    # DECISÃO: Usar identificação dinâmica OU lista pré-definida
    if use_dynamic_matching:
        logger.info(f"    Modo: DINÂMICO - usando todos os {len(matched)} adsets identificados")
        matched_final = matched
    else:
        logger.info(f"    Modo: MANUAL - usando apenas MATCHED_ADSETS pré-definidos")
        # Filtrar apenas adsets que estão na lista MATCHED_ADSETS
        matched_final = [adset for adset in matched if adset in MATCHED_ADSETS]

        # DEBUG: Mostrar comparação com lista esperada
        in_list = matched_final
        not_in_list = [adset for adset in matched if adset not in MATCHED_ADSETS]
        missing_from_intersection = [adset for adset in MATCHED_ADSETS if adset not in matched]

        if in_list:
            logger.info(f"    {len(in_list)} adsets matched encontrados na interseção:")
            for adset in sorted(in_list):
                logger.info(f"       {repr(adset)}")

        if not_in_list:
            logger.info(f"     {len(not_in_list)} adsets matched NÃO estão na lista MATCHED_ADSETS (ignorados):")
            for adset in sorted(not_in_list)[:5]:
                logger.info(f"       {repr(adset)}")
            if len(not_in_list) > 5:
                logger.info(f"      ... e mais {len(not_in_list) - 5}")

        if missing_from_intersection:
            logger.warning(f"     {len(missing_from_intersection)} adsets de MATCHED_ADSETS NÃO encontrados na interseção:")
            for adset in sorted(missing_from_intersection):
                logger.warning(f"       {repr(adset)}")

    logger.info(f"    {len(matched_final)} adsets matched selecionados (Eventos Champion vs Challenger)")
    logger.info(f"      ML adsets (total): {len(ml_adsets)}, Controle adsets (total): {len(control_adsets)}")

    # Criar DataFrame com métricas por adset
    adsets_metrics = adsets_df[adsets_df['adset_name'].isin(matched_final)].copy()

    # DEBUG: Verificar quais colunas existem
    logger.info(f"    DEBUG - Tem 'leads_standard'? {'leads_standard' in adsets_df.columns}")
    logger.info(f"    DEBUG - Tem 'leads'? {'leads' in adsets_df.columns}")

    # Criar coluna 'leads' a partir dos relatórios Meta
    if 'leads_standard' in adsets_metrics.columns:
        adsets_metrics['leads'] = adsets_metrics['leads_standard']
        logger.info(f"    Criado coluna 'leads' a partir de 'leads_standard' ({adsets_metrics['leads'].sum():.0f} leads)")

        # NOTA: Não preencher com LeadQualified aqui para edge case
        # A lógica de leads artificiais será aplicada depois em compare_adset_performance
    elif 'leads' not in adsets_metrics.columns:
        logger.warning(f"    'leads_standard' não encontrado em adsets_df, criando coluna 'leads' com 0")
        adsets_metrics['leads'] = 0

    return matched_final, adsets_metrics


def identify_matched_ad_pairs(
    ads_df: pd.DataFrame,
    ml_campaign_ids: List[str],
    control_campaign_ids: List[str],
    min_spend: float = MIN_SPEND
) -> Tuple[List[str], pd.DataFrame]:
    """
    Identifica anúncios que aparecem tanto em campanhas ML quanto controle.

    Args:
        ads_df: DataFrame com ads e suas métricas
        ml_campaign_ids: IDs das campanhas ML
        control_campaign_ids: IDs das campanhas controle
        min_spend: Gasto mínimo para incluir ad (default: R$ 200)

    Returns:
        Tuple (matched_ads, ads_metrics_df)
        - matched_ads: Lista de AD codes matched
        - ads_metrics_df: DataFrame com métricas por ad
    """
    logger.info(" Identificando matched pairs de anúncios...")

    # Anúncios em campanhas ML - AGREGAR primeiro, DEPOIS filtrar
    ml_ads_all = ads_df[ads_df['campaign_id'].isin(ml_campaign_ids)]
    if not ml_ads_all.empty:
        # Agregar spend por ad_code
        ml_ads_agg = ml_ads_all.groupby('ad_code')['spend'].sum().reset_index()
        # Filtrar por gasto mínimo agregado
        ml_ads_filtered = ml_ads_agg[ml_ads_agg['spend'] >= min_spend]
        ml_ads = set(ml_ads_filtered['ad_code'].dropna().unique().tolist())
    else:
        ml_ads = set()

    # Anúncios em campanhas controle - AGREGAR primeiro, DEPOIS filtrar
    ctrl_ads_all = ads_df[ads_df['campaign_id'].isin(control_campaign_ids)]
    if not ctrl_ads_all.empty:
        # Agregar spend por ad_code
        ctrl_ads_agg = ctrl_ads_all.groupby('ad_code')['spend'].sum().reset_index()
        # Filtrar por gasto mínimo agregado
        ctrl_ads_filtered = ctrl_ads_agg[ctrl_ads_agg['spend'] >= min_spend]
        control_ads = set(ctrl_ads_filtered['ad_code'].dropna().unique().tolist())
    else:
        control_ads = set()

    # Matched pairs (interseção)
    matched = list(ml_ads.intersection(control_ads))

    # Filtrar apenas ads na lista MATCHED_ADS
    matched_final = [ad for ad in matched if ad in MATCHED_ADS]

    logger.info(f"    {len(matched_final)} anúncios matched (de {len(MATCHED_ADS)} esperados)")
    logger.info(f"      ML ads: {len(ml_ads)}, Controle ads: {len(control_ads)}")

    # Criar DataFrame com métricas por ad
    ads_metrics = ads_df[ads_df['ad_code'].isin(matched_final)].copy()

    return matched_final, ads_metrics


def identify_matched_adsets_faixa_a(
    adsets_df: pd.DataFrame,
    campaign_metrics: pd.DataFrame,
    eventos_ml_campaign_ids: List[str],
    matched_df: Optional[pd.DataFrame] = None
) -> Tuple[List[str], pd.DataFrame]:
    """
    Identifica adsets que aparecem tanto em campanhas Eventos ML quanto em campanhas Faixa A.
    Usa arquivos mapeados manualmente em adsets_analysis/faixa/.

    Args:
        adsets_df: DataFrame com adsets e suas métricas
        campaign_metrics: DataFrame com métricas de campanhas (para identificar quais têm Faixa A)
        eventos_ml_campaign_ids: IDs das campanhas Eventos ML
        matched_df: DataFrame com conversões matched (leadsvendas) - OPCIONAL

    Returns:
        Tuple (matched_adsets, adsets_metrics_df)
        - matched_adsets: Lista de nomes de adsets matched
        - adsets_metrics_df: DataFrame com métricas agregadas por grupo
    """
    logger.info(" Identificando matched pairs de adsets (Eventos ML vs Faixa A)...")

    # Carregar arquivos de mapeamento da pasta faixa
    from pathlib import Path
    import glob

    base_path = Path("files/validation/meta_reports/adsets_analysis/faixa")
    csv_files = glob.glob(str(base_path / "*.csv"))

    if not csv_files:
        logger.warning("    Nenhum arquivo CSV encontrado em adsets_analysis/faixa/")
        return [], pd.DataFrame()

    logger.info(f"    Carregando {len(csv_files)} arquivos de mapeamento...")

    # Carregar e combinar todos os arquivos
    faixa_dfs = []
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            faixa_dfs.append(df)
        except Exception as e:
            logger.warning(f"    Erro ao ler {Path(csv_file).name}: {e}")

    if not faixa_dfs:
        logger.warning("    Nenhum arquivo válido carregado")
        return [], pd.DataFrame()

    # Combinar todos os DataFrames
    faixa_mapping = pd.concat(faixa_dfs, ignore_index=True)

    # Identificar colunas de Eventos ML
    evento_ml_cols = []
    for col in faixa_mapping.columns:
        if 'evento ml' in col.lower():
            evento_ml_cols.append(col)

    if not evento_ml_cols:
        logger.warning("    Colunas 'Evento ML' não encontradas nos arquivos de mapeamento")
        return [], pd.DataFrame()

    logger.info(f"    Colunas de Eventos ML encontradas: {evento_ml_cols}")

    # Normalizar nome do adset
    faixa_mapping['adset_name_normalized'] = faixa_mapping['Nome do conjunto de anúncios'].apply(normalize_whitespace)

    # Identificar adsets matched: aqueles que têm valor > 0 em qualquer coluna de Eventos ML
    matched_mask = faixa_mapping[evento_ml_cols].fillna(0).sum(axis=1) > 0
    matched_adsets_df = faixa_mapping[matched_mask].copy()

    if matched_adsets_df.empty:
        logger.info("   ℹ Nenhum adset matched encontrado nos arquivos de mapeamento")
        return [], pd.DataFrame()

    # Lista de adsets matched (nomes normalizados)
    matched_adset_names = matched_adsets_df['adset_name_normalized'].unique().tolist()

    logger.info(f"    {len(matched_adset_names)} adsets matched identificados nos arquivos")

    # DEBUG: Mostrar adsets matched
    if matched_adset_names:
        logger.info(f"    Adsets matched:")
        for adset in sorted(matched_adset_names)[:10]:  # Mostrar apenas os primeiros 10
            logger.info(f"       {repr(adset)}")
        if len(matched_adset_names) > 10:
            logger.info(f"      ... e mais {len(matched_adset_names) - 10} adsets")

    # CRÍTICO: Normalizar whitespace em adsets_df para matching consistente
    adsets_df = adsets_df.copy()
    adsets_df['adset_name'] = adsets_df['adset_name'].apply(normalize_whitespace)

    # Extrair IDs das campanhas Faixa A diretamente dos arquivos de mapeamento
    faixa_a_campaign_ids = []
    if 'Identificação da campanha' in faixa_mapping.columns:
        # Usar apenas os primeiros 15 dígitos do campaign_id para matching
        campaign_ids_raw = faixa_mapping['Identificação da campanha'].dropna().unique()
        for cid in campaign_ids_raw:
            cid_str = str(cid).strip()
            # Extrair apenas os primeiros 15 dígitos
            if len(cid_str) >= 15:
                faixa_a_campaign_ids.append(cid_str[:15])

    logger.info(f"    {len(faixa_a_campaign_ids)} campanhas Faixa A identificadas dos arquivos")
    logger.info(f"    {len(eventos_ml_campaign_ids)} campanhas Eventos ML")

    # Filtrar adsets_df para incluir apenas matched adsets
    matched_adsets_data = adsets_df[adsets_df['adset_name'].isin(matched_adset_names)].copy()

    if matched_adsets_data.empty:
        logger.warning("    Nenhum dado encontrado para adsets matched")
        return matched_adset_names, pd.DataFrame()

    # Criar coluna com primeiros 15 dígitos do campaign_id para matching
    matched_adsets_data['campaign_id_15'] = matched_adsets_data['campaign_id'].astype(str).str[:15]

    # Filtrar para incluir APENAS campanhas Eventos ML ou Faixa A (excluir Controle e outras)
    eventos_ml_ids_15 = [str(cid)[:15] for cid in eventos_ml_campaign_ids]
    all_relevant_campaign_ids_15 = set(eventos_ml_ids_15 + faixa_a_campaign_ids)
    matched_adsets_data = matched_adsets_data[matched_adsets_data['campaign_id_15'].isin(all_relevant_campaign_ids_15)].copy()

    if matched_adsets_data.empty:
        logger.warning("    Nenhum dado encontrado para campanhas Eventos ML ou Faixa A")
        return matched_adset_names, pd.DataFrame()

    # Criar coluna 'leads' a partir dos relatórios Meta
    if 'leads_standard' in matched_adsets_data.columns:
        matched_adsets_data['leads'] = matched_adsets_data['leads_standard']
    elif 'leads' not in matched_adsets_data.columns:
        matched_adsets_data['leads'] = 0

    # Classificar cada linha por grupo (Eventos ML ou Faixa A)
    matched_adsets_data['comparison_group'] = matched_adsets_data['campaign_id_15'].apply(
        lambda cid: 'Champion' if cid in eventos_ml_ids_15 else 'Faixa A'
    )

    # Agregar leads e spend dos relatórios Meta
    spend_metrics = matched_adsets_data.groupby('comparison_group').agg({
        'leads': 'sum',
        'spend': 'sum'
    }).reset_index()

    # Adicionar conversões do matched_df (se fornecido)
    if matched_df is not None and not matched_df.empty:
        # Normalizar whitespace em medium (adset_name)
        if 'medium' in matched_df.columns:
            matched_df_copy = matched_df.copy()
            matched_df_copy['medium_norm'] = matched_df_copy['medium'].apply(normalize_whitespace)

            # Filtrar apenas matched adsets
            matched_conversions = matched_df_copy[matched_df_copy['medium_norm'].isin(matched_adset_names)].copy()

            if not matched_conversions.empty:
                # Criar campaign_id_15 para classificação
                matched_conversions['campaign_id_15'] = matched_conversions['campaign_id'].astype(str).str[:15]

                # Filtrar apenas campanhas relevantes (Eventos ML ou Faixa A)
                matched_conversions = matched_conversions[
                    matched_conversions['campaign_id_15'].isin(all_relevant_campaign_ids_15)
                ].copy()

                # Classificar por grupo
                matched_conversions['comparison_group'] = matched_conversions['campaign_id_15'].apply(
                    lambda cid: 'Champion' if cid in eventos_ml_ids_15 else 'Faixa A'
                )

                # Contar conversões por grupo
                if 'converted' in matched_conversions.columns:
                    converted = matched_conversions[matched_conversions['converted'] == True]

                    conversion_metrics = converted.groupby('comparison_group').agg({
                        'email': 'nunique',  # Conversões únicas
                        'sale_value': 'sum'   # Receita total
                    }).reset_index()

                    conversion_metrics.columns = ['comparison_group', 'conversions', 'revenue']

                    # Merge com spend_metrics
                    aggregated = spend_metrics.merge(
                        conversion_metrics,
                        on='comparison_group',
                        how='left'
                    )

                    # Preencher NaN com 0
                    aggregated['conversions'] = aggregated['conversions'].fillna(0)
                    aggregated['revenue'] = aggregated['revenue'].fillna(0)

                    logger.info(f"    Conversões identificadas no matched_df:")
                    for _, row in aggregated.iterrows():
                        logger.info(f"      {row['comparison_group']}: {row['conversions']:.0f} conversões, R$ {row['revenue']:.2f}")
                else:
                    aggregated = spend_metrics.copy()
                    aggregated['conversions'] = 0
                    aggregated['revenue'] = 0
            else:
                aggregated = spend_metrics.copy()
                aggregated['conversions'] = 0
                aggregated['revenue'] = 0
        else:
            aggregated = spend_metrics.copy()
            aggregated['conversions'] = 0
            aggregated['revenue'] = 0
    else:
        aggregated = spend_metrics.copy()
        aggregated['conversions'] = 0
        aggregated['revenue'] = 0

    # Renomear colunas para português
    aggregated = aggregated.rename(columns={
        'leads': 'Leads',
        'conversions': 'Vendas',
        'spend': 'Valor gasto',
        'revenue': 'Receita Total'
    })

    # Calcular métricas derivadas
    aggregated['Taxa de conversão'] = (aggregated['Vendas'] / aggregated['Leads']) * 100
    aggregated['CPL'] = aggregated['Valor gasto'] / aggregated['Leads']
    aggregated['ROAS'] = aggregated['Receita Total'] / aggregated['Valor gasto']

    # Calcular margem de contribuição (Receita - Gasto)
    aggregated['Margem de contribuição'] = aggregated['Receita Total'] - aggregated['Valor gasto']

    # Substituir NaN/Inf por 0
    aggregated = aggregated.fillna(0)
    aggregated = aggregated.replace([float('inf'), float('-inf')], 0)

    logger.info(f"    Métricas agregadas por grupo:")
    for _, row in aggregated.iterrows():
        logger.info(f"      {row['comparison_group']}: {row['Leads']:.0f} leads, {row['Vendas']:.0f} vendas")

    return matched_adset_names, aggregated


def get_faixa_a_instances_detail(
    eventos_ml_campaign_ids: List[str],
    matched_df: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Retorna detalhes de CADA INSTÂNCIA de adset matched entre Eventos ML e Faixa A.

    Cada linha do DataFrame retornado representa uma linha dos CSVs de Faixa A que foi
    marcada como matched (tem valor em colunas 'Evento ML').

    Args:
        eventos_ml_campaign_ids: IDs das campanhas Eventos ML
        matched_df: DataFrame com conversões matched (leadsvendas) - OPCIONAL

    Returns:
        DataFrame com colunas:
        - adset_name: Nome do adset
        - campaign_name: Nome da campanha
        - campaign_id: ID da campanha
        - comparison_group: 'Champion' ou 'Faixa A'
        - spend: Valor gasto
        - leads: Número de leads
        - conversions: Número de vendas
        - revenue: Receita total
        - roas: ROAS (receita / gasto)
    """
    from pathlib import Path
    import glob

    logger.info(" Carregando detalhes de instâncias de adsets matched (Faixa A)...")

    # Carregar CSVs de Faixa A (mesmos arquivos de mapeamento)
    base_path = Path("files/validation/meta_reports/adsets_analysis/faixa")
    csv_files = glob.glob(str(base_path / "*.csv"))

    if not csv_files:
        logger.warning("    Nenhum arquivo CSV encontrado em adsets_analysis/faixa/")
        return pd.DataFrame()

    # Carregar CSVs de Eventos ML (para pegar spend/leads de Eventos ML)
    eventos_ml_path = Path("files/validation/meta_reports/adsets_analysis/eventos_ml")
    eventos_ml_csv_files = glob.glob(str(eventos_ml_path / "*.csv"))

    # Combinar CSVs Faixa A
    faixa_dfs = []
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            faixa_dfs.append(df)
        except Exception as e:
            logger.warning(f"    Erro ao ler {Path(csv_file).name}: {e}")

    # Combinar CSVs Eventos ML
    eventos_ml_dfs = []
    for csv_file in eventos_ml_csv_files:
        try:
            df = pd.read_csv(csv_file)
            eventos_ml_dfs.append(df)
        except Exception as e:
            logger.warning(f"    Erro ao ler {Path(csv_file).name}: {e}")

    if not faixa_dfs:
        logger.warning("    Nenhum arquivo Faixa A válido carregado")
        return pd.DataFrame()

    faixa_mapping = pd.concat(faixa_dfs, ignore_index=True)
    eventos_ml_mapping = pd.concat(eventos_ml_dfs, ignore_index=True) if eventos_ml_dfs else pd.DataFrame()

    # Identificar colunas de Eventos ML
    evento_ml_cols = [col for col in faixa_mapping.columns if 'evento ml' in col.lower()]

    if not evento_ml_cols:
        logger.warning("    Colunas 'Evento ML' não encontradas")
        return pd.DataFrame()

    # Normalizar nomes de adsets
    faixa_mapping['adset_name_normalized'] = faixa_mapping['Nome do conjunto de anúncios'].apply(normalize_whitespace)
    if not eventos_ml_mapping.empty and 'Nome do conjunto de anúncios' in eventos_ml_mapping.columns:
        eventos_ml_mapping['adset_name_normalized'] = eventos_ml_mapping['Nome do conjunto de anúncios'].apply(normalize_whitespace)

    # Filtrar apenas linhas matched (têm marcação Eventos ML)
    matched_mask = faixa_mapping[evento_ml_cols].fillna(0).sum(axis=1) > 0
    matched_rows = faixa_mapping[matched_mask].copy()

    if matched_rows.empty:
        logger.info("   ℹ Nenhuma instância matched encontrada")
        return pd.DataFrame()

    logger.info(f"    {len(matched_rows)} instâncias matched encontradas nos CSVs Faixa A")

    # Preparar lista de resultados
    results = []

    # IDs de campanhas Eventos ML (primeiros 15 dígitos)
    eventos_ml_ids_15 = [str(cid)[:15] for cid in eventos_ml_campaign_ids]

    # PASSO 1: Processar TODAS as linhas de Faixa A matched
    for idx, row in matched_rows.iterrows():
        adset_name = row['adset_name_normalized']
        campaign_name = row.get('Nome da campanha', '')
        campaign_id = str(row.get('Identificação da campanha', ''))[:15]
        spend = row.get('Valor usado (BRL)', 0)
        leads = row.get('Leads', 0)

        # Criar registro Faixa A
        faixa_record = {
            'adset_name': adset_name,
            'campaign_name': campaign_name,
            'campaign_id': campaign_id,
            'comparison_group': 'Faixa A',
            'spend': spend if pd.notna(spend) else 0,
            'leads': leads if pd.notna(leads) else 0,
            'conversions': 0,  # Será preenchido depois
            'revenue': 0,      # Será preenchido depois
            'roas': 0          # Será calculado depois
        }
        results.append(faixa_record)

    # PASSO 2: Processar TODAS as instâncias de Eventos ML (independentemente)
    # Coletar adsets únicos que foram matched
    matched_adset_names = matched_rows['adset_name_normalized'].unique()

    if not eventos_ml_mapping.empty:
        # Filtrar apenas instâncias de Eventos ML que correspondem a adsets matched
        eventos_ml_matched = eventos_ml_mapping[
            eventos_ml_mapping['adset_name_normalized'].isin(matched_adset_names)
        ]

        for _, ml_row in eventos_ml_matched.iterrows():
            adset_name = ml_row['adset_name_normalized']
            ml_campaign_name = ml_row.get('Nome da campanha', '')
            ml_campaign_id = str(ml_row.get('Identificação da campanha', ''))[:15]
            ml_spend = ml_row.get('Valor usado (BRL)', 0)
            ml_leads = ml_row.get('Leads', 0)

            ml_record = {
                'adset_name': adset_name,
                'campaign_name': ml_campaign_name,
                'campaign_id': ml_campaign_id,
                'comparison_group': 'Champion',
                'spend': ml_spend if pd.notna(ml_spend) else 0,
                'leads': ml_leads if pd.notna(ml_leads) else 0,
                'conversions': 0,
                'revenue': 0,
                'roas': 0
            }
            results.append(ml_record)

    if not results:
        logger.warning("    Nenhum resultado processado")
        return pd.DataFrame()

    # Criar DataFrame
    instances_df = pd.DataFrame(results)

    # Adicionar conversões do matched_df
    if matched_df is not None and not matched_df.empty and 'medium' in matched_df.columns:
        logger.info("    Adicionando conversões do matched_df...")

        matched_df_copy = matched_df.copy()
        matched_df_copy['medium_norm'] = matched_df_copy['medium'].apply(normalize_whitespace)
        matched_df_copy['campaign_id_15'] = matched_df_copy['campaign_id'].astype(str).str[:15]

        # Para cada instância, contar conversões
        for idx, row in instances_df.iterrows():
            adset_name = row['adset_name']
            campaign_id = row['campaign_id']

            # Filtrar conversões para este adset + campanha
            instance_conversions = matched_df_copy[
                (matched_df_copy['medium_norm'] == adset_name) &
                (matched_df_copy['campaign_id_15'] == campaign_id) &
                (matched_df_copy['converted'] == True)
            ]

            if not instance_conversions.empty:
                conversions = len(instance_conversions['email'].unique())  # Conversões únicas
                revenue = instance_conversions['sale_value'].sum()

                instances_df.at[idx, 'conversions'] = conversions
                instances_df.at[idx, 'revenue'] = revenue

    # Calcular ROAS
    instances_df['roas'] = instances_df.apply(
        lambda row: row['revenue'] / row['spend'] if row['spend'] > 0 else 0,
        axis=1
    )

    logger.info(f"    {len(instances_df)} instâncias processadas com conversões")
    logger.info(f"      Eventos ML: {len(instances_df[instances_df['comparison_group'] == 'Champion'])} instâncias")
    logger.info(f"      Faixa A: {len(instances_df[instances_df['comparison_group'] == 'Faixa A'])} instâncias")

    return instances_df


# ============================================================================
# FUNÇÕES DE COMPARAÇÃO DE PERFORMANCE
# ============================================================================

def compare_all_adsets_performance(
    adsets_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    comparison_group_map: Dict[str, str],
    product_value: float = 2000.0,
    min_spend: float = 0.0,
    config: Optional[Dict] = None
) -> pd.DataFrame:
    """
    Compara performance de TODOS os adsets (Eventos Champion vs Challenger), sem filtrar por matched pairs.

    Args:
        adsets_df: DataFrame com TODOS os adsets do Excel (sem filtro de matched pairs)
        matched_df: DataFrame com conversões matched (leadsvendas)
        comparison_group_map: Mapeamento campaign_id  comparison_group
        product_value: Valor do produto em R$
        min_spend: Gasto mínimo para incluir adset (default: R$ 0)

    Returns:
        DataFrame agregado com métricas por grupo (Eventos Champion vs Challenger)
    """
    logger.info(" Comparando performance de TODOS os adsets (Eventos Champion vs Challenger)...")

    # CRÍTICO: Contar LEADS (todos) e CONVERSÕES por CAMPAIGN + ADSET + COMPARISON_GROUP do matched_df
    # Isso garante consistência com a Tabela 1 (Comparação por Campanhas)
    # IMPORTANTE: Incluir comparison_group no agrupamento para manter a mesma classificação
    if 'medium' in matched_df.columns and 'campaign' in matched_df.columns and 'comparison_group' in matched_df.columns:
        # PASSO 1: Contar TODOS os leads por campanha + adset + comparison_group
        leads_by_campaign_adset = matched_df.groupby(
            ['campaign', 'medium', 'comparison_group']
        ).size().reset_index(name='leads_count')

        leads_by_campaign_adset.columns = ['campaign_name', 'adset_name', 'comparison_group', 'leads_count']

        # PASSO 2: Contar conversões e receita (apenas convertidos)
        if 'converted' in matched_df.columns:
            converted_leads = matched_df[matched_df['converted'] == True].copy()

            # Aplicar ajuste TMB
            converted_leads = adjust_revenue_for_tmb(converted_leads, fator=FATOR_TMB_MEDIO)

            conversions_by_campaign_adset = converted_leads.groupby(
                ['campaign', 'medium', 'comparison_group']
            ).agg({
                'email': 'nunique',  # Conversões únicas
                'sale_value': 'sum',   # Receita nominal
                'sale_value_adjusted': 'sum'  # Receita ajustada TMB
            }).reset_index()

            conversions_by_campaign_adset.columns = ['campaign_name', 'adset_name', 'comparison_group', 'conversions', 'revenue', 'revenue_adjusted']

            # Merge leads + conversões
            metrics_by_campaign_adset = leads_by_campaign_adset.merge(
                conversions_by_campaign_adset,
                on=['campaign_name', 'adset_name', 'comparison_group'],
                how='left'
            )
            metrics_by_campaign_adset['conversions'] = metrics_by_campaign_adset['conversions'].fillna(0)
            metrics_by_campaign_adset['revenue'] = metrics_by_campaign_adset['revenue'].fillna(0)
            metrics_by_campaign_adset['revenue_adjusted'] = metrics_by_campaign_adset['revenue_adjusted'].fillna(0)
        else:
            # Se não tem conversões, usar apenas leads
            metrics_by_campaign_adset = leads_by_campaign_adset.copy()
            metrics_by_campaign_adset['conversions'] = 0
            metrics_by_campaign_adset['revenue'] = 0
            metrics_by_campaign_adset['revenue_adjusted'] = 0

        # Extrair Campaign ID do final do nome
        def extract_campaign_id(campaign_name):
            if pd.isna(campaign_name):
                return None
            parts = str(campaign_name).split('|')
            if len(parts) >= 2:
                campaign_id = parts[-1].strip()
                if campaign_id.isdigit() and len(campaign_id) >= 15:
                    return campaign_id[:15]
            return None

        metrics_by_campaign_adset['campaign_id_from_utm'] = metrics_by_campaign_adset['campaign_name'].apply(extract_campaign_id)

        # Verificar se há IDs extraídos
        total_leads = metrics_by_campaign_adset['leads_count'].sum()
        total_convs = metrics_by_campaign_adset['conversions'].sum()
        total_revenue = metrics_by_campaign_adset['revenue'].sum()
        combinations_with_id = metrics_by_campaign_adset['campaign_id_from_utm'].notna().sum()
        logger.info(f"    Leads, conversões e receita calculadas por campanha + adset + comparison_group")
        logger.info(f"   Total de combinações: {len(metrics_by_campaign_adset)}")
        logger.info(f"   Campaign IDs extraídos dos UTMs: {combinations_with_id}/{len(metrics_by_campaign_adset)}")
        logger.info(f"   Leads totais: {total_leads}")
        logger.info(f"   Conversões totais: {total_convs:.0f}")
        logger.info(f"   Receita total real: R$ {total_revenue:,.2f}")

        # DEBUG: Verificar se há (campaign, adset) que aparecem em múltiplos comparison_groups
        duplicates = metrics_by_campaign_adset.groupby(['campaign_name', 'adset_name']).size()
        multi_group = duplicates[duplicates > 1]
        if len(multi_group) > 0:
            logger.warning(f"     {len(multi_group)} pares (campaign, adset) aparecem em MÚLTIPLOS comparison_groups:")
            for (camp, adset), count in multi_group.head(5).items():
                logger.warning(f"       {adset[:40]} (campaign {camp[-20:]}): {count} grupos")
                # Mostrar quais grupos
                groups = metrics_by_campaign_adset[
                    (metrics_by_campaign_adset['campaign_name'] == camp) &
                    (metrics_by_campaign_adset['adset_name'] == adset)
                ]['comparison_group'].tolist()
                leads_per_group = metrics_by_campaign_adset[
                    (metrics_by_campaign_adset['campaign_name'] == camp) &
                    (metrics_by_campaign_adset['adset_name'] == adset)
                ]['leads_count'].tolist()
                for g, l in zip(groups, leads_per_group):
                    logger.warning(f"         - {g}: {l} leads")
    else:
        metrics_by_campaign_adset = pd.DataFrame(columns=['campaign_name', 'adset_name', 'leads_count', 'conversions', 'revenue'])

    # Preparar campaign_id para merge (primeiros 15 dígitos)
    adsets_df['campaign_id_clean'] = adsets_df['campaign_id'].astype(str).str[:15]
    metrics_by_campaign_adset['campaign_id_clean'] = metrics_by_campaign_adset['campaign_id_from_utm'].astype(str).str[:15]

    # CRÍTICO: Normalizar adset_name em AMBOS DataFrames antes do merge
    # Isso resolve problemas de espaçamento ("ABERTO |  AD0065" vs "ABERTO | AD0065")
    if 'adset_name' in adsets_df.columns:
        adsets_df['adset_name'] = adsets_df['adset_name'].apply(normalize_whitespace)
    metrics_by_campaign_adset['adset_name'] = metrics_by_campaign_adset['adset_name'].apply(normalize_whitespace)

    # CRÍTICO: Deduplicar adsets_df ANTES do merge para evitar duplicação de leads!
    # O adsets_df pode ter múltiplas linhas para o mesmo adset (diferentes períodos)
    # IMPORTANTE: Deduplicar por (campaign_id_clean, adset_name) que são as chaves do merge!
    logger.info(f"    Deduplicando adsets_df antes do merge...")
    adsets_df_before = len(adsets_df)
    adsets_df = adsets_df.groupby(['campaign_id_clean', 'adset_name'], as_index=False).agg({
        'campaign_id': 'first',  # Pegar primeiro campaign_id completo
        'adset_id': 'first',     # Pegar primeiro adset_id completo
        'campaign_name': 'first' if 'campaign_name' in adsets_df.columns else lambda x: None,
        'spend': 'sum',  # SOMAR spend de todos os períodos
        'leads_standard': 'sum' if 'leads_standard' in adsets_df.columns else lambda x: 0,
        'lead_qualified': 'sum' if 'lead_qualified' in adsets_df.columns else lambda x: 0,
        'lead_qualified_hq': 'sum' if 'lead_qualified_hq' in adsets_df.columns else lambda x: 0,
        'faixa_a': 'sum' if 'faixa_a' in adsets_df.columns else lambda x: 0,
    })
    logger.info(f"      {adsets_df_before} rows  {len(adsets_df)} rows (removidas {adsets_df_before - len(adsets_df)} duplicatas)")

    # Merge leads, conversões e receita (do matched_df) com dados de spend do Excel
    adsets_full = adsets_df.merge(
        metrics_by_campaign_adset,
        on=['campaign_id_clean', 'adset_name'],
        how='left',
        suffixes=('', '_matched')
    )

    # Preencher valores ausentes (adsets sem leads no matched_df)
    adsets_full['leads_count'] = adsets_full['leads_count'].fillna(0)
    adsets_full['conversions'] = adsets_full['conversions'].fillna(0)
    adsets_full['revenue'] = adsets_full['revenue'].fillna(0)  # Receita real do matched_df
    if 'revenue_adjusted' in adsets_full.columns:
        adsets_full['revenue_adjusted'] = adsets_full['revenue_adjusted'].fillna(0)  # Receita ajustada TMB

    # CRÍTICO: Usar APENAS comparison_group do matched_df - NÃO preencher com mapeamento!
    # Isso garante que a classificação seja EXATAMENTE a mesma que na Tabela 1
    if 'comparison_group' not in adsets_full.columns:
        # Se não tem comparison_group, criar vazio (será filtrado depois)
        adsets_full['comparison_group'] = None
        logger.warning(f"     comparison_group não veio do matched_df - adsets sem leads")

    # DEBUG: Verificar quantos NaN temos
    nan_count = adsets_full['comparison_group'].isna().sum()
    if nan_count > 0:
        logger.info(f"   ℹ  {nan_count} adsets sem comparison_group (sem leads no matched_df)")

    # IMPORTANTE: NÃO preencher NaN com mapeamento!
    # Leads com comparison_group=NaN não estão no matched_df, então não devem ser contados
    logger.info(f"    comparison_group preservado EXATAMENTE como no matched_df (sem preenchimento)")

    # DEBUG: Verificar total de leads ANTES da agregação
    total_leads_before_agg = adsets_full['leads_count'].sum()
    rows_before_agg = len(adsets_full)
    logger.info(f"    DEBUG - ANTES agregação:")
    logger.info(f"      Total rows: {rows_before_agg}")
    logger.info(f"      Total leads: {total_leads_before_agg:.0f}")

    # CRÍTICO: Agregar duplicatas por (campaign_id, adset_id) SOMANDO o spend
    # Pode haver duplicatas no adsets_df devido a múltiplos relatórios ou períodos
    # IMPORTANTE: Somar spend garante que tenhamos o gasto total mesmo após filtro de período
    before_dedup = len(adsets_full)
    convs_before_dedup = adsets_full['conversions'].sum()
    spend_before_dedup = adsets_full['spend'].sum()

    # DEBUG: Verificar leads ANTES da agregação por grupo
    logger.info(f"    DEBUG - Leads ANTES da agregação por grupo (do matched_df):")
    adsets_full_temp = adsets_full.copy()
    adsets_full_temp['comparison_group_temp'] = adsets_full_temp['campaign_id_clean'].map(comparison_group_map)
    for group in ['Champion', 'Challenger']:
        group_rows = adsets_full_temp[adsets_full_temp['comparison_group_temp'] == group]
        if 'leads_count' in group_rows.columns:
            total_leads = group_rows['leads_count'].sum()
            logger.info(f"      {group}: {len(group_rows)} linhas, {total_leads:.0f} leads (matched_df)")
        else:
            logger.info(f"      {group}: {len(group_rows)} linhas, coluna leads_count não encontrada")

    # CRÍTICO: Agregar por (campaign_id, adset_id, comparison_group) para preservar breakdown
    # Isso evita misturar leads de diferentes grupos no mesmo adset
    agg_dict = {
        'campaign_id_clean': 'first',
        'adset_name': 'first',
        'spend': 'sum',  # SOMAR spend de todos os períodos
        'leads_count': 'max',  # Leads do matched_df não duplicam (já agregados por campaign+adset+group)
        'conversions': 'max',  # Conversões não duplicam (vem do matched_df)
        'revenue': 'max',  # Revenue não duplica (vem do matched_df)
    }

    # Adicionar colunas opcionais se existirem
    if 'campaign_name' in adsets_full.columns:
        agg_dict['campaign_name'] = 'first'
    # IMPORTANTE: Incluir leads_standard dos relatórios Meta
    if 'leads_standard' in adsets_full.columns:
        agg_dict['leads_standard'] = 'sum'  # Somar leads de diferentes períodos
    if 'lead_qualified' in adsets_full.columns:
        agg_dict['lead_qualified'] = 'sum'
    if 'lead_qualified_hq' in adsets_full.columns:
        agg_dict['lead_qualified_hq'] = 'sum'
    if 'faixa_a' in adsets_full.columns:
        agg_dict['faixa_a'] = 'sum'

    # IMPORTANTE: Incluir comparison_group no groupby para preservar breakdown por grupo
    group_cols = ['campaign_id', 'adset_id']
    if 'comparison_group' in adsets_full.columns:
        group_cols.append('comparison_group')

    adsets_full = adsets_full.groupby(group_cols, as_index=False).agg(agg_dict)

    after_dedup = len(adsets_full)
    convs_after_dedup = adsets_full['conversions'].sum()
    spend_after_dedup = adsets_full['spend'].sum()

    # DEBUG: Verificar total de leads DEPOIS da agregação
    total_leads_after_agg = adsets_full['leads_count'].sum()
    logger.info(f"    DEBUG - DEPOIS agregação:")
    logger.info(f"      Total rows: {after_dedup}")
    logger.info(f"      Total leads: {total_leads_after_agg:.0f}")
    if total_leads_before_agg != total_leads_after_agg:
        logger.warning(f"       Leads mudaram na agregação: {total_leads_before_agg:.0f}  {total_leads_after_agg:.0f} ({total_leads_after_agg - total_leads_before_agg:+.0f})")

    # DEBUG: Verificar leads DEPOIS da agregação por grupo
    logger.info(f"    DEBUG - Leads DEPOIS da agregação por grupo (do matched_df):")
    adsets_full_temp2 = adsets_full.copy()
    adsets_full_temp2['comparison_group_temp'] = adsets_full_temp2['campaign_id_clean'].map(comparison_group_map)
    for group in ['Champion', 'Challenger']:
        group_rows = adsets_full_temp2[adsets_full_temp2['comparison_group_temp'] == group]
        if 'leads_count' in group_rows.columns:
            total_leads = group_rows['leads_count'].sum()
            logger.info(f"      {group}: {len(group_rows)} linhas, {total_leads:.0f} leads (matched_df)")
        else:
            logger.info(f"      {group}: {len(group_rows)} linhas, coluna leads_count não encontrada")

    if before_dedup != after_dedup:
        logger.info(f"    Agregadas {before_dedup - after_dedup} linhas duplicadas (mesmo campaign_id + adset_id)")
        logger.info(f"      Spend: R$ {spend_before_dedup:,.2f}  R$ {spend_after_dedup:,.2f}")
        if convs_before_dedup != convs_after_dedup:
            logger.warning(f"       Conversões afetadas: {convs_before_dedup:.0f}  {convs_after_dedup:.0f} (-{convs_before_dedup - convs_after_dedup:.0f})")

    # Criar coluna 'leads' a partir dos relatórios Meta
    # Usar 'leads_standard' como fonte oficial de leads
    if 'leads_standard' in adsets_full.columns:
        adsets_full['leads'] = adsets_full['leads_standard']
        logger.info(f"    Criado coluna 'leads' a partir de 'leads_standard' ({adsets_full['leads'].sum():.0f} leads)")

        # NOTA: Não preencher com LeadQualified aqui para edge case
        # A lógica de leads artificiais será aplicada depois (linhas 681-712)
    elif 'leads' not in adsets_full.columns:
        logger.warning("    Coluna 'leads' e 'leads_standard' não encontradas, usando 0")
        adsets_full['leads'] = 0

    # CRÍTICO: Remover adsets "fantasma" (0 leads E 0 gasto) DEPOIS do merge e renomeação
    # Esses adsets causam duplicação de conversões quando têm o mesmo nome que adsets ativos
    # Exemplo: "ABERTO |  AD0027" (espaço duplo, 0 leads) duplica conversões de "ABERTO | AD0027" (ativo)
    before_filter = len(adsets_full)

    # DEBUG: Verificar leads ANTES do filtro de fantasma por grupo
    logger.info(f"    DEBUG - Leads ANTES do filtro de adsets fantasma (do matched_df):")
    adsets_full_temp3 = adsets_full.copy()
    adsets_full_temp3['comparison_group_temp'] = adsets_full_temp3['campaign_id_clean'].map(comparison_group_map)
    for group in ['Champion', 'Challenger']:
        group_rows = adsets_full_temp3[adsets_full_temp3['comparison_group_temp'] == group]
        total_leads = group_rows['leads'].sum()
        logger.info(f"      {group}: {len(group_rows)} linhas, {total_leads:.0f} leads (matched_df)")

    adsets_full = adsets_full[~((adsets_full['leads'] == 0) & (adsets_full['spend'] == 0))]
    after_filter = len(adsets_full)

    # DEBUG: Verificar leads DEPOIS do filtro de fantasma por grupo
    logger.info(f"    DEBUG - Leads DEPOIS do filtro de adsets fantasma (do matched_df):")
    adsets_full_temp4 = adsets_full.copy()
    adsets_full_temp4['comparison_group_temp'] = adsets_full_temp4['campaign_id_clean'].map(comparison_group_map)
    for group in ['Champion', 'Challenger']:
        group_rows = adsets_full_temp4[adsets_full_temp4['comparison_group_temp'] == group]
        total_leads = group_rows['leads'].sum()
        logger.info(f"      {group}: {len(group_rows)} linhas, {total_leads:.0f} leads (matched_df)")

    if before_filter != after_filter:
        logger.info(f"    Removidos {before_filter - after_filter} adsets fantasma (0 leads E 0 gasto)")

    # AJUSTE ESPECIAL: Adsets da campanha edge case que não dispara evento Lead
    # Aplicar mesma lógica de "forjar" leads que foi feita no nível de campanha
    campaign_special_id_prefix = '120234062599950'

    # Verificar se há coluna LeadQualified
    if 'lead_qualified' in adsets_full.columns or 'LeadQualified' in adsets_full.columns:
        lq_col = 'lead_qualified' if 'lead_qualified' in adsets_full.columns else 'LeadQualified'

        # Calcular proporção média LQ/Leads USANDO A MESMA PROPORÇÃO DA CAMPANHA
        # IMPORTANTE: Usar fator fixo de 1.906 (671/352) calculado pela campanha edge case
        # Isso garante CONSISTÊNCIA entre campanha e adsets

        # Proporção fixa baseada no cálculo de metrics_calculator para a campanha
        # 671 leads / 352 LQ = 1.906 (ou seja, avg_ratio = 352/671 = 0.5244)
        avg_ratio = 0.5244  # 52.44% - mesma proporção usada pelas campanhas
        logger.info(f"    Usando proporção fixa da campanha edge case: {avg_ratio:.2%}")
        logger.info(f"      Fator de multiplicação: {1/avg_ratio:.3f}x (LQ  Leads)")

        if True:  # Sempre aplicar
            # Ajustar adsets da campanha especial
            for idx in adsets_full.index:
                camp_id = str(adsets_full.at[idx, 'campaign_id_clean'])
                if camp_id.startswith(campaign_special_id_prefix):
                    lq = adsets_full.at[idx, lq_col]
                    current_leads = adsets_full.at[idx, 'leads']

                    # Se tem LQ mas não tem leads, calcular leads artificiais
                    if pd.notna(lq) and lq > 0 and (pd.isna(current_leads) or current_leads == 0):
                        leads_artificial = int(lq / avg_ratio)
                        adsets_full.at[idx, 'leads'] = leads_artificial
                        logger.info(f"    Adset especial ajustado: {adsets_full.at[idx, 'adset_name'][:50]}")
                        logger.info(f"      LeadQualified: {lq:.0f}  Leads artificial: {leads_artificial} (proporção {avg_ratio:.2%})")

    # DEBUG: Mostrar distribuição de leads por comparison_group ANTES do filtro
    logger.info(f"    DEBUG - Leads por comparison_group ANTES do filtro:")
    for group in adsets_full['comparison_group'].unique():
        if pd.notna(group):
            group_leads = adsets_full[adsets_full['comparison_group'] == group]['leads'].sum()
            group_count = len(adsets_full[adsets_full['comparison_group'] == group])
            logger.info(f"      {group}: {group_count} adsets, {group_leads:.0f} leads")

    # Se configurado, agrupar "Otimização ML" com "Challenger"
    if config and config.get('merge_otimizacao_ml_with_controle', False):
        logger.info("    Agrupando 'Otimização ML' com 'Challenger' (merge_otimizacao_ml_with_controle=true)")
        adsets_full.loc[
            adsets_full['comparison_group'] == 'Otimização ML',
            'comparison_group'
        ] = 'Challenger'

    # Filtrar apenas Eventos ML e Controle (remover Otimização ML e outros)
    # IMPORTANTE: Mostrar TODOS os adsets, independente de gasto, leads ou conversões
    # Isso garante que os totais batam com a tabela de Campanhas
    adsets_filtered = adsets_full[adsets_full['comparison_group'].isin(['Champion', 'Challenger'])].copy()

    logger.info(f"    Todos os adsets das campanhas Eventos ML + Controle: {len(adsets_filtered)}")

    # DEBUG: Mostrar distribuição de leads por comparison_group DEPOIS do filtro
    logger.info(f"    DEBUG - Leads por comparison_group DEPOIS do filtro:")
    for group in ['Champion', 'Challenger']:
        group_leads = adsets_filtered[adsets_filtered['comparison_group'] == group]['leads'].sum()
        group_count = len(adsets_filtered[adsets_filtered['comparison_group'] == group])
        logger.info(f"      {group}: {group_count} adsets, {group_leads:.0f} leads")

    # DEBUG: Verificar spend e leads por grupo
    logger.info(f"    DEBUG - Spend e Leads por grupo (leads do matched_df):")
    for group in ['Champion', 'Challenger']:
        group_adsets = adsets_filtered[adsets_filtered['comparison_group'] == group]
        total_spend = group_adsets['spend'].sum()
        total_leads = group_adsets['leads'].sum()
        adsets_with_spend = group_adsets[group_adsets['spend'] > 0]
        logger.info(f"      {group}: {len(adsets_with_spend)}/{len(group_adsets)} adsets com spend > 0")
        logger.info(f"         Spend: R$ {total_spend:,.2f}, Leads: {total_leads:.0f} (matched_df)")

    # Calcular métricas de negócio
    # NOTA: 'revenue' já vem do matched_df com valores reais de venda, não usar product_value fixo
    # adsets_filtered['revenue'] já foi preenchida no merge acima
    adsets_filtered['cpl'] = adsets_filtered['spend'] / adsets_filtered['leads'].replace(0, 1)  # Evitar divisão por zero
    adsets_filtered['roas'] = adsets_filtered['revenue'] / adsets_filtered['spend'].replace(0, 1)  # Evitar divisão por zero
    adsets_filtered['margin'] = adsets_filtered['revenue'] - adsets_filtered['spend']
    adsets_filtered['conversion_rate'] = adsets_filtered['conversions'] / adsets_filtered['leads'].replace(0, 1)  # Evitar divisão por zero

    # DEBUG: Verificar se há duplicação de conversões por comparison_group
    logger.info(f"\n    DEBUG - Verificando conversões únicas por grupo:")
    for group in ['Champion', 'Challenger']:
        group_adsets = adsets_filtered[adsets_filtered['comparison_group'] == group]
        total_convs = group_adsets['conversions'].sum()

        # Verificar se há adsets com conversões duplicadas
        adsets_with_convs = group_adsets[group_adsets['conversions'] > 0]
        logger.info(f"      {group}: {len(adsets_with_convs)} adsets com conversões, total: {total_convs:.0f}")

        # Mostrar top 5 adsets por conversões
        if len(adsets_with_convs) > 0:
            top5 = adsets_with_convs.nlargest(5, 'conversions')[['adset_name', 'campaign_id_clean', 'adset_id', 'conversions']]
            for idx, row in top5.iterrows():
                adset_id_short = str(row['adset_id'])[:18] if pd.notna(row.get('adset_id')) else 'NO_ID'
                logger.info(f"          {row['adset_name'][:40]} (campaign {row['campaign_id_clean']}, adset {adset_id_short}): {row['conversions']:.0f}")

    # DEBUG ESPECÍFICO: Investigar "ABERTO | AD0027" duplicado
    logger.info(f"\n    DEBUG - Investigando 'ABERTO | AD0027' duplicado:")
    ad0027_adsets = adsets_filtered[adsets_filtered['adset_name'] == 'ABERTO | AD0027']
    if len(ad0027_adsets) > 0:
        logger.info(f"      Total de linhas com 'ABERTO | AD0027': {len(ad0027_adsets)}")
        for idx, row in ad0027_adsets.iterrows():
            logger.info(f"          campaign_id: {row.get('campaign_id_clean', 'N/A')}")
            logger.info(f"           adset_id: {row.get('adset_id', 'N/A')}")
            logger.info(f"           comparison_group: {row.get('comparison_group', 'N/A')}")
            logger.info(f"           conversions: {row.get('conversions', 0):.0f}")
            logger.info(f"           leads: {row.get('leads', 0):.0f}")
            logger.info(f"           spend: R$ {row.get('spend', 0):.2f}")
            logger.info(f"           ---")

            # DEBUG: Mostrar emails das conversões desse adset
            if row.get('conversions', 0) > 0:
                try:
                    adset_id = row.get('adset_id')
                    campaign_id = str(row.get('campaign_id_clean', ''))

                    logger.info(f"            Procurando conversões para campaign {campaign_id}, adset {adset_id}")

                    # Filtrar conversões desse adset específico
                    converted_leads = matched_df[matched_df['converted'] == True].copy()
                    logger.info(f"              Total de conversões: {len(converted_leads)}")

                    # Extrair ID da campanha do formato "NOME|ID"
                    # O campo campaign está no formato: "DEVLF | CAP | FRIO | ... |120220370119870390"
                    if 'campaign' in converted_leads.columns:
                        # Extrair ID da campanha (após o último pipe, primeiros 15 dígitos)
                        converted_leads['campaign_id_extracted'] = converted_leads['campaign'].astype(str).str.split('|').str[-1].str[:15]

                        # Filtrar por campanha
                        converted_leads = converted_leads[converted_leads['campaign_id_extracted'] == campaign_id]
                        logger.info(f"              Conversões dessa campanha: {len(converted_leads)}")

                    # Normalizar medium para comparação
                    if len(converted_leads) > 0 and 'medium' in converted_leads.columns:
                        converted_leads['medium_norm'] = converted_leads['medium'].apply(normalize_whitespace)
                        converted_leads_adset = converted_leads[converted_leads['medium_norm'] == 'ABERTO | AD0027']

                        logger.info(f"              Conversões do adset 'ABERTO | AD0027': {len(converted_leads_adset)}")

                        if len(converted_leads_adset) > 0:
                            logger.info(f"            Emails das conversões ({len(converted_leads_adset)}):")
                            for idx, conv_row in converted_leads_adset.head(5).iterrows():
                                email = conv_row.get('email', 'N/A')
                                medium_orig = conv_row.get('medium', 'N/A')
                                logger.info(f"              - {email} (medium original: '{medium_orig}')")
                except Exception as e:
                    logger.error(f"            Erro ao buscar emails: {e}")

    # Garantir que revenue_adjusted existe antes da agregação
    if 'revenue_adjusted' not in adsets_filtered.columns:
        adsets_filtered['revenue_adjusted'] = 0

    # Agregar por comparison_group
    aggregated = adsets_filtered.groupby('comparison_group').agg({
        'leads': 'sum',
        'conversions': 'sum',
        'spend': 'sum',
        'revenue': 'sum',
        'revenue_adjusted': 'sum',
        'margin': 'sum'
    }).reset_index()

    # Recalcular métricas agregadas
    aggregated['conversion_rate'] = aggregated['conversions'] / aggregated['leads']
    aggregated['cpl'] = aggregated['spend'] / aggregated['leads']
    aggregated['roas'] = aggregated['revenue'] / aggregated['spend']

    # Calcular ROAS Ajustado TMB e Margem Ajustada se disponível
    if 'revenue_adjusted' in aggregated.columns:
        aggregated['roas_adjusted'] = aggregated['revenue_adjusted'] / aggregated['spend']
        aggregated['margin_adjusted'] = aggregated['revenue_adjusted'] - aggregated['spend']

    logger.info(f"    Comparação completa de adsets calculada")
    logger.info(f"      Eventos ML: {aggregated[aggregated['comparison_group']=='Champion']['conversions'].sum():.0f} conversões")
    logger.info(f"      Controle: {aggregated[aggregated['comparison_group']=='Challenger']['conversions'].sum():.0f} conversões")

    return aggregated


def compare_adset_performance(
    adsets_metrics_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    ml_type_map: Dict[str, str],
    product_value: float = 2000.0,
    comparison_group_map: Optional[Dict[str, str]] = None
) -> Dict[str, pd.DataFrame]:
    """
    Compara performance de adsets entre ML e Controle.

    Args:
        adsets_metrics_df: DataFrame com métricas de adsets (da Meta API)
        matched_df: DataFrame com conversões matched (leadsvendas)
        ml_type_map: Mapeamento campaign_id  ml_type (DEPRECATED - usar comparison_group_map)
        product_value: Valor do produto em R$
        comparison_group_map: Mapeamento campaign_id  comparison_group ('Champion', 'Otimização ML', 'Challenger')

    Returns:
        Dict com DataFrames:
        - 'aggregated': Agregação Champion vs Challenger
        - 'detailed': Detalhamento adset-a-adset (CADA CAMPANHA SEPARADA)
    """
    logger.info(" Comparando performance de adsets...")

    # CRÍTICO: Normalizar adset_name no DataFrame de métricas do Excel
    # Isso resolve problemas de espaçamento ("ABERTO |  AD0065" vs "ABERTO | AD0065")
    if 'adset_name' in adsets_metrics_df.columns:
        adsets_metrics_df['adset_name'] = adsets_metrics_df['adset_name'].apply(normalize_whitespace)

    # Adicionar ml_type aos adsets (para compatibilidade)
    adsets_metrics_df['ml_type'] = adsets_metrics_df['campaign_id'].map(ml_type_map)

    # Se temos comparison_group_map, usar ele diretamente (novo comportamento)
    if comparison_group_map:
        adsets_metrics_df['comparison_group_from_campaign'] = adsets_metrics_df['campaign_id'].map(comparison_group_map)

    # NOVO: Calcular conversões E RECEITA REAL por CAMPAIGN + ADSET usando 'campaign' e 'medium' do matched_df
    # A coluna 'medium' contém o NOME DO ADSET que gerou o lead
    # A coluna 'campaign' contém o NOME DA CAMPANHA
    # IMPORTANTE: Precisamos das DUAS para matching preciso!
    if 'converted' in matched_df.columns and 'medium' in matched_df.columns and 'campaign' in matched_df.columns:
        # Conversões e receita real por campanha + adset (usando campaign + medium)
        # CRÍTICO: Contar emails únicos, não agregação de linhas (evita duplicatas)
        converted_leads = matched_df[matched_df['converted'] == True].copy()

        # Aplicar ajuste TMB
        converted_leads = adjust_revenue_for_tmb(converted_leads, fator=FATOR_TMB_MEDIO)

        conversions_by_campaign_adset = converted_leads.groupby(
            ['campaign', 'medium']  # campaign + medium = identificação única
        ).agg({
            'email': 'nunique',  # Conversões únicas
            'sale_value': 'sum',   # Receita nominal
            'sale_value_adjusted': 'sum'  # Receita ajustada TMB
        }).reset_index()

        conversions_by_campaign_adset.columns = ['campaign_name', 'adset_name', 'conversions', 'revenue', 'revenue_adjusted']

        # NOVO: Calcular LEADS (todos, não só convertidos) por campanha + adset
        # IMPORTANTE: Usar TODOS os leads do matched_df para garantir consistência
        leads_by_campaign_adset = matched_df.groupby(
            ['campaign', 'medium']
        ).size().reset_index(name='leads_matched_df')

        leads_by_campaign_adset.columns = ['campaign_name', 'adset_name', 'leads_matched_df']

        # CRÍTICO: Normalizar whitespace em adset_name (UTMs podem ter espaçamento inconsistente)
        conversions_by_campaign_adset['adset_name'] = conversions_by_campaign_adset['adset_name'].apply(normalize_whitespace)
        leads_by_campaign_adset['adset_name'] = leads_by_campaign_adset['adset_name'].apply(normalize_whitespace)

        # IMPORTANTE: Extrair Campaign ID do final do nome para fazer matching preciso
        # Exemplo: "CAMPAIGN | 2025-04-15|120220370119870390"  ID = "120220370119870390"
        def extract_campaign_id(campaign_name):
            """Extrai o Campaign ID do final do nome da campanha"""
            if pd.isna(campaign_name):
                return None
            parts = str(campaign_name).split('|')
            if len(parts) > 1:
                last_part = parts[-1].strip()
                # Se último elemento é numérico e tem 18+ dígitos, é um Campaign ID
                if last_part.isdigit() and len(last_part) >= 18:
                    return last_part
            return None

        conversions_by_campaign_adset['campaign_id_from_utm'] = conversions_by_campaign_adset['campaign_name'].apply(extract_campaign_id)
        leads_by_campaign_adset['campaign_id_from_utm'] = leads_by_campaign_adset['campaign_name'].apply(extract_campaign_id)

        # DEBUG: Verificar quantos IDs foram extraídos
        ids_extracted = conversions_by_campaign_adset['campaign_id_from_utm'].notna().sum()
        logger.info(f"    Conversões calculadas por campanha + adset (via 'campaign' + 'medium')")
        logger.info(f"   Total de combinações campanha+adset com conversões: {len(conversions_by_campaign_adset)}")
        logger.info(f"   Campaign IDs extraídos dos UTMs: {ids_extracted}/{len(conversions_by_campaign_adset)}")
        logger.info(f"    Leads calculados por campanha + adset (via 'campaign' + 'medium')")
        logger.info(f"   Total de combinações campanha+adset com leads: {len(leads_by_campaign_adset)}")

        if ids_extracted < len(conversions_by_campaign_adset):
            logger.warning(f"    {len(conversions_by_campaign_adset) - ids_extracted} conversões SEM Campaign ID no UTM")
            # Mostrar exemplos
            sem_id = conversions_by_campaign_adset[conversions_by_campaign_adset['campaign_id_from_utm'].isna()]
            for idx, row in sem_id.head(3).iterrows():
                logger.warning(f"       Campaign: {row['campaign_name'][:70]}")
                logger.warning(f"        Adset: {row['adset_name'][:50]}")
    else:
        conversions_by_campaign_adset = pd.DataFrame(columns=['campaign_name', 'adset_name', 'conversions', 'revenue'])
        leads_by_campaign_adset = pd.DataFrame(columns=['campaign_name', 'adset_name', 'leads_matched_df'])
        if 'medium' not in matched_df.columns:
            logger.warning("    Coluna 'medium' não encontrada em matched_df - conversões não podem ser atribuídas aos adsets!")

    # Merge conversões por campanha + adset
    # IMPORTANTE: Usar Campaign ID + Adset Name para matching preciso
    # (evita ambiguidade quando há múltiplas campanhas com mesmo nome)

    # NOVO: Usar campaign_id COMPLETO para evitar colisões entre contas
    # Apenas truncar quando necessário para compatibilidade
    # Estratégia: primeiro tentar match completo, depois truncado se necessário

    # Preservar IDs completos e criar versão truncada apenas para fallback
    adsets_metrics_df['campaign_id_full'] = adsets_metrics_df['campaign_id'].astype(str)
    adsets_metrics_df['campaign_id_clean'] = adsets_metrics_df['campaign_id'].astype(str).str[:15]

    conversions_by_campaign_adset['campaign_id_full'] = conversions_by_campaign_adset['campaign_id_from_utm'].astype(str)
    conversions_by_campaign_adset['campaign_id_clean'] = conversions_by_campaign_adset['campaign_id_from_utm'].astype(str).str[:15]

    leads_by_campaign_adset['campaign_id_full'] = leads_by_campaign_adset['campaign_id_from_utm'].astype(str)
    leads_by_campaign_adset['campaign_id_clean'] = leads_by_campaign_adset['campaign_id_from_utm'].astype(str).str[:15]

    # CRÍTICO: Detectar se há colisões (múltiplas contas com mesmo campaign_id_clean)
    # Se houver, precisamos usar campaign_id_full para evitar mapeamento incorreto
    collision_check = adsets_metrics_df.groupby('campaign_id_clean')['_account_name'].nunique()
    collisions = collision_check[collision_check > 1]

    if len(collisions) > 0:
        logger.warning(f"\n    DETECTADAS {len(collisions)} COLISÕES DE CAMPAIGN_ID (mesmo ID, contas diferentes):")
        for campaign_id_clean in collisions.index[:5]:  # Mostrar primeiros 5
            accounts = adsets_metrics_df[adsets_metrics_df['campaign_id_clean'] == campaign_id_clean]['_account_name'].unique()
            full_ids = adsets_metrics_df[adsets_metrics_df['campaign_id_clean'] == campaign_id_clean]['campaign_id_full'].unique()
            logger.warning(f"       ID truncado: {campaign_id_clean}")
            logger.warning(f"        Contas: {', '.join(accounts)}")
            logger.warning(f"        IDs completos: {', '.join(full_ids[:3])}")
        logger.warning(f"    Usando IDs COMPLETOS para merge para evitar mapeamento incorreto")
        use_full_id = True
    else:
        logger.info(f"    Sem colisões de campaign_id detectadas - usando IDs truncados (compatibilidade)")
        use_full_id = False

    # Definir coluna de merge baseado em detecção de colisões
    merge_id_col = 'campaign_id_full' if use_full_id else 'campaign_id_clean'

    # DEBUG: Verificar matching antes do merge
    logger.info(f"\n    DEBUG - Preparando merge:")
    logger.info(f"      IDs únicos no Excel: {adsets_metrics_df['campaign_id_clean'].nunique()}")
    logger.info(f"      IDs únicos nas conversões: {conversions_by_campaign_adset['campaign_id_clean'].nunique()}")

    # Verificar se há algum match possível
    ids_excel = set(adsets_metrics_df['campaign_id_clean'].unique())
    ids_conversions = set(conversions_by_campaign_adset['campaign_id_clean'].dropna().unique())
    matching_ids = ids_excel & ids_conversions
    logger.info(f"      IDs que fazem match: {len(matching_ids)}")

    if len(matching_ids) == 0:
        logger.warning(f"       NENHUM ID FAZ MATCH! Vamos comparar:")
        logger.warning(f"         Excel (primeiros 3): {list(ids_excel)[:3]}")
        logger.warning(f"         Conversões (primeiros 3): {list(ids_conversions)[:3]}")

    # DEBUG: Identificar conversões que NÃO fazem match com Excel
    # Fazer merge inverso: quais conversões não encontram adset no Excel?
    # NOVO: Usar mesmo merge_id_col definido acima
    conversions_not_in_excel = conversions_by_campaign_adset.merge(
        adsets_metrics_df[[merge_id_col, 'adset_name']].drop_duplicates(),
        on=[merge_id_col, 'adset_name'],
        how='left',
        indicator=True
    )
    unmatched_conversions = conversions_not_in_excel[conversions_not_in_excel['_merge'] == 'left_only']

    if len(unmatched_conversions) > 0:
        total_unmatched_convs = unmatched_conversions['conversions'].sum()
        logger.warning(f"\n    CONVERSÕES NÃO ENCONTRADAS NO EXCEL META:")
        logger.warning(f"      Total de adsets não encontrados: {len(unmatched_conversions)}")
        logger.warning(f"      Total de conversões perdidas: {total_unmatched_convs:.0f}")
        logger.warning(f"\n      Detalhes dos adsets não encontrados:")

        # Para cada adset não encontrado, buscar os emails correspondentes em matched_df
        for idx, row in unmatched_conversions.iterrows():
            logger.warning(f"       Campaign: {row['campaign_name'][:60]}")
            logger.warning(f"        Adset: {row['adset_name'][:50]}")
            logger.warning(f"        Campaign ID (15): {row['campaign_id_clean']}")
            logger.warning(f"        Conversões: {row['conversions']:.0f}")

            # Buscar emails específicos deste adset em matched_df
            if 'campaign' in matched_df.columns and 'medium' in matched_df.columns:
                matching_rows = matched_df[
                    (matched_df['campaign'] == row['campaign_name']) &
                    (matched_df['medium'] == row['adset_name']) &
                    (matched_df['converted'] == True)
                ]
                if len(matching_rows) > 0:
                    emails = matching_rows['email'].unique()
                    logger.warning(f"        Emails: {', '.join(emails[:3])}{' ...' if len(emails) > 3 else ''}")
                    # Verificar comparison_group destes leads
                    if 'comparison_group' in matching_rows.columns:
                        groups = matching_rows['comparison_group'].unique()
                        logger.warning(f"        Grupos: {', '.join(groups)}")
        logger.warning("")

    # MELHORADO: Merge com matching mais flexível de nomes
    # 1. Tentar merge exato primeiro
    # NOVO: Usar ID completo ou truncado baseado em detecção de colisões (definido acima)

    # DEBUG: Verificar spend ANTES do merge
    if 'spend' in adsets_metrics_df.columns:
        logger.info(f"    DEBUG - ANTES do merge:")
        logger.info(f"      adsets_metrics_df spend sum: R$ {adsets_metrics_df['spend'].sum():,.2f}")
        if 'total_spend' in adsets_metrics_df.columns:
            logger.info(f"      adsets_metrics_df total_spend sum: R$ {adsets_metrics_df['total_spend'].sum():,.2f}")

    adsets_full = adsets_metrics_df.merge(
        conversions_by_campaign_adset,
        on=[merge_id_col, 'adset_name'],
        how='left',
        suffixes=('', '_conv')
    )


    # CRÍTICO: Agregar duplicatas por (campaign_id, adset_id)
    # Pode haver duplicatas no adsets_metrics_df devido a múltiplos relatórios ou períodos
    # IMPORTANTE: SOMAR spend de linhas duplicadas, não descartar!
    before_dedup = len(adsets_full)

    # DEBUG: Verificar se 'leads' existe ANTES da agregação
    logger.info(f"    DEBUG - ANTES da agregação:")
    logger.info(f"      'leads' in columns? {'leads' in adsets_full.columns}")
    if 'leads' in adsets_full.columns:
        logger.info(f"      'leads' sum: {adsets_full['leads'].sum():.0f}")

    # CRÍTICO: Definir como agregar cada tipo de coluna
    # - spend/total_spend/leads_standard: SOMAR (representa diferentes períodos ou adsets)
    # - conversions/revenue: MAX ou FIRST (vêm do matched_df, já contabilizados)
    #   Se há duplicatas do mesmo adset, esses valores são REPLICADOS pelo merge, não somados
    numeric_cols_to_sum = ['spend']
    if 'total_spend' in adsets_full.columns:
        numeric_cols_to_sum.append('total_spend')

    # IMPORTANTE: 'leads' vem dos relatórios Meta (leads_standard), deve ser SOMADO
    # Apenas conversions/revenue vêm do matched_df e devem usar MAX
    if 'leads_standard' in adsets_full.columns:
        numeric_cols_to_sum.append('leads_standard')
    if 'leads' in adsets_full.columns:
        numeric_cols_to_sum.append('leads')
    if 'lead_qualified' in adsets_full.columns:
        numeric_cols_to_sum.append('lead_qualified')
    if 'lead_qualified_hq' in adsets_full.columns:
        numeric_cols_to_sum.append('lead_qualified_hq')

    # Colunas que vêm do matched_df - NÃO somar (usar max para pegar maior valor)
    numeric_cols_to_max = ['conversions', 'revenue', 'revenue_adjusted', 'leads_matched_df']

    # Colunas de identificação para agrupar
    group_cols = ['campaign_id', 'adset_id']

    # Preparar dicionário de agregação
    agg_dict = {}

    # Para cada coluna, definir função de agregação apropriada
    for col in adsets_full.columns:
        if col in group_cols:
            continue  # Estas são as chaves de agrupamento
        elif col in numeric_cols_to_sum:
            agg_dict[col] = 'sum'  # Somar spend (representa períodos diferentes)
        elif col in numeric_cols_to_max:
            agg_dict[col] = 'max'  # MAX para evitar somar valores replicados pelo merge
        else:
            agg_dict[col] = 'first'  # Manter primeiro valor para outras colunas

    # Agregar linhas duplicadas
    adsets_full = adsets_full.groupby(group_cols, as_index=False).agg(agg_dict)
    after_dedup = len(adsets_full)

    if before_dedup != after_dedup:
        logger.info(f"    Agregadas {before_dedup - after_dedup} linhas duplicadas (mesmo campaign_id + adset_id)")
        logger.info(f"      Spend foi SOMADO para duplicatas (não descartado)")

    # REMOVIDO: Não substituir leads do Meta com matched_df
    # Os relatórios Meta são a fonte oficial de leads
    # matched_df é usado apenas para identificar conversões (vendas)
    #
    # NOTA: Para campanha edge case 120234062599950, os leads são calculados
    # separadamente e já estão presentes nos relatórios Meta

    # Manter leads do Meta como estão (não fazer merge com leads_matched_df)
    logger.info(f"   ℹ  Mantendo leads dos relatórios Meta (não substituído por matched_df)")
    if 'leads' in adsets_full.columns:
        logger.info(f"      Total de leads (Meta): {adsets_full['leads'].sum():.0f}")

    # 2. Para conversões que não tiveram match exato, tentar matching flexível
    # (útil quando nomes no UTM são truncados)
    if len(unmatched_conversions) > 0:
        logger.info(f"    Tentando matching flexível para {len(unmatched_conversions)} conversões não encontradas...")
        matches_found = 0

        # Para cada conversão que não encontrou adset no Excel
        for conv_idx, conv_row in unmatched_conversions.iterrows():
            utm_name = str(conv_row['adset_name']).strip()
            utm_campaign_id = str(conv_row['campaign_id_clean'])

            # Normalizar nome do UTM (remover espaços extras, lowercase)
            utm_name_normalized = ' '.join(utm_name.split()).lower()

            # DEBUG: Log do adset que estamos tentando encontrar
            logger.info(f"       Buscando adset: '{utm_name}' (campanha {utm_campaign_id})")

            # Procurar adsets da mesma campanha no Excel
            same_campaign_excel = adsets_metrics_df[
                adsets_metrics_df['campaign_id_clean'] == utm_campaign_id
            ]

            logger.info(f"         Encontrados {len(same_campaign_excel)} adsets da mesma campanha no Excel")

            # Tentar matching por substring/similaridade
            for excel_idx, excel_row in same_campaign_excel.iterrows():
                excel_name = str(excel_row['adset_name']).strip()
                excel_name_normalized = ' '.join(excel_name.split()).lower()

                # DEBUG: Comparar nomes
                logger.info(f"         Comparando com: '{excel_name}'")
                logger.info(f"            UTM norm: '{utm_name_normalized}'")
                logger.info(f"            Excel norm: '{excel_name_normalized}'")
                logger.info(f"            Exato match: {utm_name_normalized == excel_name_normalized}")

                # Estratégia 1: Match exato (redundante mas útil para debug)
                if utm_name_normalized == excel_name_normalized:
                    # Encontrar a linha correspondente em adsets_full
                    match_mask = (
                        (adsets_full['campaign_id_clean'] == utm_campaign_id) &
                        (adsets_full['adset_name'] == excel_name)
                    )
                    if match_mask.any():
                        adsets_full.loc[match_mask, 'conversions'] = conv_row['conversions']
                        matches_found += 1
                        logger.info(f"       Match EXATO encontrado: '{utm_name[:50]}'  '{excel_name[:50]}'")
                        break

                # Estratégia 2: Substring/similaridade (70% dos caracteres)
                min_len = min(len(utm_name_normalized), len(excel_name_normalized))

                if min_len >= 20:  # Só tentar se os nomes forem razoavelmente longos
                    # Verificar se os primeiros 70% dos caracteres são iguais
                    check_len = int(min_len * 0.7)
                    if utm_name_normalized[:check_len] == excel_name_normalized[:check_len]:
                        # Encontrar a linha correspondente em adsets_full
                        match_mask = (
                            (adsets_full['campaign_id_clean'] == utm_campaign_id) &
                            (adsets_full['adset_name'] == excel_name)
                        )
                        if match_mask.any():
                            adsets_full.loc[match_mask, 'conversions'] = conv_row['conversions']
                            matches_found += 1
                            logger.info(f"       Match flexível ({check_len} chars): '{utm_name[:50]}'  '{excel_name[:50]}'")
                            break

        if matches_found > 0:
            logger.info(f"    Recuperadas {matches_found} conversões via matching flexível!")
        else:
            logger.info(f"    Nenhum match flexível encontrado")

    # CRÍTICO: Deduplic novamente após matching flexível (pode ter criado duplicatas)
    before_dedup2 = len(adsets_full)
    adsets_full = adsets_full.drop_duplicates(subset=['campaign_id', 'adset_id'], keep='first')
    after_dedup2 = len(adsets_full)

    if before_dedup2 != after_dedup2:
        logger.info(f"    Removidas {before_dedup2 - after_dedup2} linhas duplicadas após matching flexível")

    adsets_full['conversions'] = adsets_full['conversions'].fillna(0)
    adsets_full['revenue'] = adsets_full['revenue'].fillna(0)  # Receita real do matched_df

    # Preencher revenue_adjusted (TMB) se disponível
    if 'revenue_adjusted' in adsets_full.columns:
        adsets_full['revenue_adjusted'] = adsets_full['revenue_adjusted'].fillna(0)
        logger.info(f"    revenue_adjusted preenchida com zeros onde necessário")

    # Remover colunas temporárias
    adsets_full = adsets_full.drop(columns=['campaign_id_clean', 'campaign_id_from_utm', 'campaign_name_conv'], errors='ignore')

    # Calcular métricas de negócio
    # IMPORTANTE: NÃO sobrescrever 'leads' - o valor já vem correto do Excel!
    # Apenas garantir que leads esteja preenchido (fallback para casos sem dados)
    logger.info(f"    DEBUG - Verificando coluna 'leads' após aggregation:")
    logger.info(f"      'leads' in columns? {'leads' in adsets_full.columns}")
    if 'leads' in adsets_full.columns:
        logger.info(f"      'leads' sum: {adsets_full['leads'].sum():.0f}")
        logger.info(f"      'leads' isna().all()? {adsets_full['leads'].isna().all()}")
        logger.info(f"      'leads' count non-zero: {(adsets_full['leads'] > 0).sum()}")

    if 'leads' not in adsets_full.columns or adsets_full['leads'].isna().all():
        logger.warning("    Coluna 'leads' não encontrada ou vazia, usando count como fallback")
        adsets_full['leads'] = adsets_full.groupby(['campaign_id', 'adset_name'])['adset_id'].transform('count')
    else:
        # Preencher NaN com 0
        adsets_full['leads'] = adsets_full['leads'].fillna(0)

    # DEBUG: Verificar adsets com conversões mas sem leads
    weird_adsets = adsets_full[
        (adsets_full['conversions'] > 0) &
        (adsets_full['leads'] == 0)
    ]

    if len(weird_adsets) > 0:
        logger.warning(f"\n    ATENÇÃO: {len(weird_adsets)} adset(s) com conversões mas 0 leads:")
        for idx, row in weird_adsets.iterrows():
            logger.warning(f"       {row['campaign_name'][:60]}")
            logger.warning(f"        Adset: {row['adset_name'][:50]}")
            logger.warning(f"        Conversões: {row['conversions']:.0f} | Leads (Excel): {row['leads']:.0f}")
            logger.warning(f"        Isso indica discrepância entre dados CAPI/CSV e relatório Meta")
        logger.warning("")

    # AJUSTE ESPECIAL: Adsets da campanha edge case que não dispara evento Lead
    # Aplicar mesma lógica de "forjar" leads que foi feita no nível de campanha
    campaign_special_id_prefix = '120234062599950'

    # Verificar se há coluna LeadQualified
    if 'lead_qualified' in adsets_full.columns or 'LeadQualified' in adsets_full.columns:
        lq_col = 'lead_qualified' if 'lead_qualified' in adsets_full.columns else 'LeadQualified'

        # Calcular proporção média LQ/Leads USANDO A MESMA PROPORÇÃO DA CAMPANHA
        # IMPORTANTE: Usar fator fixo de 1.906 (671/352) calculado pela campanha edge case
        # Isso garante CONSISTÊNCIA entre campanha e adsets

        # Proporção fixa baseada no cálculo de metrics_calculator para a campanha
        # 671 leads / 352 LQ = 1.906 (ou seja, avg_ratio = 352/671 = 0.5244)
        avg_ratio = 0.5244  # 52.44% - mesma proporção usada pelas campanhas
        logger.info(f"    Usando proporção fixa da campanha edge case (Matched): {avg_ratio:.2%}")
        logger.info(f"      Fator de multiplicação: {1/avg_ratio:.3f}x (LQ  Leads)")

        if True:  # Sempre aplicar
            # Ajustar adsets da campanha especial
            for idx in adsets_full.index:
                camp_id = str(adsets_full.at[idx, 'campaign_id'])
                if camp_id.startswith(campaign_special_id_prefix):
                    lq = adsets_full.at[idx, lq_col]
                    current_leads = adsets_full.at[idx, 'leads']

                    # Se tem LQ mas não tem leads, calcular leads artificiais
                    if pd.notna(lq) and lq > 0 and (pd.isna(current_leads) or current_leads == 0):
                        leads_artificial = int(lq / avg_ratio)
                        adsets_full.at[idx, 'leads'] = leads_artificial
                        logger.info(f"    Adset especial ajustado (Matched): {adsets_full.at[idx, 'adset_name'][:50]}")
                        logger.info(f"      LeadQualified: {lq:.0f}  Leads artificial: {leads_artificial} (proporção {avg_ratio:.2%})")

    # Filtrar adsets com gasto 0 E leads 0 (sem atividade)
    # IMPORTANTE: Manter adsets com conversões mesmo if spend/leads = 0
    adsets_full = adsets_full[
        (adsets_full['spend'] > 0) |
        (adsets_full['leads'] > 0) |
        (adsets_full['conversions'] > 0)
    ].copy()

    logger.info(f"    Adsets após filtro (removidos com spend=0 e leads=0): {len(adsets_full)}")

    adsets_full['cpl'] = adsets_full['spend'] / adsets_full['leads'].replace(0, 1)
    adsets_full['cpa'] = adsets_full['spend'] / adsets_full['conversions'].replace(0, 1)
    adsets_full['conversion_rate'] = (adsets_full['conversions'] / adsets_full['leads'].replace(0, 1)) * 100
    # NOTA: 'revenue' já vem do matched_df com valores reais de venda, não usar product_value fixo
    # adsets_full['revenue'] já foi preenchida no merge acima
    adsets_full['roas'] = adsets_full['revenue'] / adsets_full['spend'].replace(0, 1)
    adsets_full['margin'] = adsets_full['revenue'] - adsets_full['spend']
    adsets_full['margin_pct'] = (adsets_full['margin'] / adsets_full['revenue'].replace(0, 1)) * 100

    # Calcular ROAS Ajustado TMB se disponível
    if 'revenue_adjusted' in adsets_full.columns:
        adsets_full['roas_adjusted'] = adsets_full['revenue_adjusted'] / adsets_full['spend'].replace(0, 1)
        logger.info(f"    ROAS Ajustado TMB calculado para adsets_full")
    else:
        logger.warning(f"    'revenue_adjusted' NÃO encontrado em adsets_full")
        logger.warning(f"    Colunas em adsets_full: {adsets_full.columns.tolist()}")

    # Agregação Champion vs Challenger
    agg_dict_ml = {
        'adset_name': 'nunique',
        'spend': 'sum',
        'leads': 'sum',
        'conversions': 'sum',
        'cpl': 'mean',
        'cpa': 'mean',
        'conversion_rate': 'mean',
        'roas': 'mean',
        'margin': 'sum',
        'margin_pct': 'mean'
    }

    # Adicionar revenue e revenue_adjusted se disponíveis
    if 'revenue' in adsets_full.columns:
        agg_dict_ml['revenue'] = 'sum'
    if 'revenue_adjusted' in adsets_full.columns:
        agg_dict_ml['revenue_adjusted'] = 'sum'

    aggregated = adsets_full.groupby('ml_type').agg(agg_dict_ml).reset_index()

    # Recalcular ROAS e ROAS Ajustado TMB após agregação
    if 'revenue' in aggregated.columns:
        aggregated['roas'] = aggregated['revenue'] / aggregated['spend'].replace(0, 1)
    if 'revenue_adjusted' in aggregated.columns:
        aggregated['roas_adjusted'] = aggregated['revenue_adjusted'] / aggregated['spend'].replace(0, 1)
        aggregated['margin_adjusted'] = aggregated['revenue_adjusted'] - aggregated['spend']

    # Detalhamento adset-a-adset (CADA CAMPANHA SEPARADA - NÃO AGREGAR)
    # MUDANÇA IMPORTANTE: Não agrupar por adset_name
    # Cada linha representa um adset de uma campanha específica
    # Exemplo: "ADV | Lookalike 1%" na campanha A é diferente de "ADV | Lookalike 1%" na campanha B

    # CRÍTICO: Incluir total_spend se disponível (para matched pairs)
    detail_columns = ['campaign_name', 'campaign_id', 'adset_name', 'adset_id', 'ml_type',
                      'spend', 'leads', 'conversions', 'cpl', 'cpa',
                      'conversion_rate', 'roas', 'revenue', 'margin', 'margin_pct']

    if 'total_spend' in adsets_full.columns:
        detail_columns.append('total_spend')

    # Adicionar colunas ajustadas TMB se disponíveis
    if 'revenue_adjusted' in adsets_full.columns:
        detail_columns.append('revenue_adjusted')
    if 'roas_adjusted' in adsets_full.columns:
        detail_columns.append('roas_adjusted')

    detailed = adsets_full[detail_columns].copy()

    # Adicionar account_id baseado no adset_id + campaign_id
    # O account_name vem do MetaReportsLoader (extraído do nome do arquivo Excel)
    # CRÍTICO: Usar campaign_id + adset_id como chave composta para evitar ambiguidade
    # quando o mesmo adset aparece em múltiplos relatórios/períodos
    if '_account_name' in adsets_metrics_df.columns:
        # Criar chave composta: campaign_id + "|" + adset_id
        adset_account_map_df = adsets_metrics_df[['campaign_id', 'adset_id', '_account_name']].drop_duplicates()
        adset_account_map_df['map_key'] = adset_account_map_df['campaign_id'].astype(str) + "|" + adset_account_map_df['adset_id'].astype(str)

        # Verificar se há duplicatas com a chave composta
        duplicate_keys = adset_account_map_df[adset_account_map_df.duplicated(subset=['map_key'], keep=False)]
        if len(duplicate_keys) > 0:
            logger.warning(f"    {len(duplicate_keys)} duplicatas com mesma chave (campaign_id|adset_id) mas contas diferentes!")
            for key in duplicate_keys['map_key'].unique()[:3]:
                accounts = duplicate_keys[duplicate_keys['map_key'] == key]['_account_name'].unique()
                logger.warning(f"       {key}: {', '.join(accounts)}")

        # Criar mapa usando chave composta
        account_map = adset_account_map_df.set_index('map_key')['_account_name'].to_dict()

        # Aplicar mapa ao detailed (que também precisa da chave composta)
        detailed['map_key'] = detailed['campaign_id'].astype(str) + "|" + detailed['adset_id'].astype(str)
        detailed['account_id'] = detailed['map_key'].map(account_map)
        detailed = detailed.drop(columns=['map_key'])  # Remover coluna temporária
    elif 'account_id' in adsets_metrics_df.columns:
        account_map = adsets_metrics_df[['adset_id', 'account_id']].drop_duplicates().set_index('adset_id')['account_id'].to_dict()
        detailed['account_id'] = detailed['adset_id'].map(account_map)
    else:
        detailed['account_id'] = None

    # IMPORTANTE: Adsets herdam a classificação da CAMPANHA PAI
    # Não reclassificamos por optimization_goal do adset para manter consistência
    # A classificação já foi feita no nível de campanha considerando optimization_goal

    # Buscar optimization_goal apenas para referência (não para reclassificar)
    if 'optimization_goal' in adsets_metrics_df.columns:
        optimization_map = adsets_metrics_df[['adset_id', 'optimization_goal']].drop_duplicates().set_index('adset_id')['optimization_goal'].to_dict()
        detailed['optimization_goal'] = detailed['adset_id'].map(optimization_map)
    else:
        detailed['optimization_goal'] = None

    # Adicionar comparison_group HERDADO da campanha
    if comparison_group_map:
        # NOVO: Usar mapeamento refinado direto (já distingue Eventos ML vs Otimização ML)
        # IMPORTANTE: Usar primeiros 15 dígitos para matching (mesma lógica do comparison_group_map)
        detailed['campaign_id_15'] = detailed['campaign_id'].astype(str).str[:15]

        # DEBUG: Verificar mapeamento antes de aplicar
        logger.info(f"\n    DEBUG ADSETS - Verificando mapeamento comparison_group:")
        logger.info(f"      Total de IDs no mapa: {len(comparison_group_map)}")
        logger.info(f"      Total de adsets: {len(detailed)}")
        logger.info(f"      IDs únicos nos adsets (15 dig): {detailed['campaign_id_15'].nunique()}")

        # DEBUG: Mostrar mapeamento das campanhas ML
        logger.info(f"\n      Mapeamento de campanhas ML:")
        for id_15, group in comparison_group_map.items():
            if 'ML' in group or group == 'Champion':
                logger.info(f"         {id_15}  {group}")

        # Verificar se há IDs que não fazem match
        ids_in_detailed = set(detailed['campaign_id_15'].unique())
        ids_in_map = set(comparison_group_map.keys())
        ids_not_in_map = ids_in_detailed - ids_in_map
        if ids_not_in_map:
            logger.warning(f"       {len(ids_not_in_map)} IDs de adsets NÃO encontrados no mapa:")
            for id_val in list(ids_not_in_map)[:5]:
                # Mostrar o nome da campanha correspondente
                sample_adset = detailed[detailed['campaign_id_15'] == id_val].iloc[0]
                logger.warning(f"          ID 15: {id_val}  {sample_adset['campaign_name'][:50]}")

        detailed['comparison_group'] = detailed['campaign_id_15'].map(comparison_group_map)

        # DEBUG: Verificar se há NaN após mapeamento
        unmapped_count = detailed['comparison_group'].isna().sum()
        if unmapped_count > 0:
            logger.warning(f"       {unmapped_count} adsets sem grupo após mapeamento (NaN)")

        logger.info("    Usando mapeamento refinado (Eventos ML / Otimização ML / Controle)")
    else:
        # LEGACY: Converter ml_type para comparison_group (sem distinção Eventos/Otimização)
        def classify_comparison_group_from_ml_type(row):
            """Conversão legacy: ml_type  comparison_group (sem refinamento)"""
            ml_type = row['ml_type']
            if ml_type == 'COM_ML':
                return 'Champion'  # Assume todos ML são Eventos (não ideal)
            elif ml_type == 'SEM_ML':
                return 'Challenger'
            else:
                return 'Outro'

        detailed['comparison_group'] = detailed.apply(classify_comparison_group_from_ml_type, axis=1)
        logger.warning("    Usando mapeamento legacy (sem distinção Eventos ML vs Otimização ML)")

    # Filtrar apenas "Champion" vs "Challenger" (excluir "Otimização ML" e "Outro")
    before_filter = len(detailed)
    conversions_before_filter = detailed['conversions'].sum()

    # DEBUG: Verificar quais conversões serão removidas pelo filtro
    removed_by_filter = detailed[~detailed['comparison_group'].isin(['Champion', 'Challenger'])].copy()
    if len(removed_by_filter) > 0:
        convs_removed = removed_by_filter['conversions'].sum()
        logger.warning(f"\n    CONVERSÕES REMOVIDAS PELO FILTRO (Otimização ML / Outro):")
        logger.warning(f"      Adsets removidos: {len(removed_by_filter)}")
        logger.warning(f"      Conversões removidas: {convs_removed:.0f}")

        # Mostrar breakdown por comparison_group
        by_group = removed_by_filter.groupby('comparison_group').agg({
            'adset_name': 'count',
            'conversions': 'sum'
        }).reset_index()
        by_group.columns = ['Grupo', 'Adsets', 'Conversões']
        logger.warning(f"\n      Breakdown por grupo:")
        for _, row in by_group.iterrows():
            logger.warning(f"         {row['Grupo']}: {row['Adsets']} adsets, {row['Conversões']:.0f} conversões")

        # Mostrar detalhes de cada adset removido
        logger.warning(f"\n      Detalhes dos adsets removidos:")
        for idx, row in removed_by_filter.iterrows():
            logger.warning(f"       [{row['comparison_group']}] {row['campaign_name'][:60]}")
            logger.warning(f"        Adset: {row['adset_name'][:60]}")
            logger.warning(f"        Conversões: {row['conversions']:.0f}")
            logger.warning(f"        Campaign ID (completo): {row['campaign_id']}")
            logger.warning(f"        Campaign ID (15 dígitos): {str(row['campaign_id'])[:15]}")

            # Buscar emails específicos deste adset em matched_df
            if 'campaign' in matched_df.columns and 'medium' in matched_df.columns:
                # Construir o nome completo da campanha como aparece no matched_df
                campaign_variations = [
                    row['campaign_name'],
                    f"{row['campaign_name']}|{row['campaign_id']}",
                    f"{row['campaign_name'].rstrip('|')}|{row['campaign_id']}"
                ]

                matching_rows = pd.DataFrame()
                for camp_var in campaign_variations:
                    matches = matched_df[
                        (matched_df['campaign'] == camp_var) &
                        (matched_df['medium'] == row['adset_name']) &
                        (matched_df['converted'] == True)
                    ]
                    if len(matches) > 0:
                        matching_rows = matches
                        break

                if len(matching_rows) > 0:
                    emails = matching_rows['email'].unique()
                    logger.warning(f"        Emails ({len(emails)}): {', '.join(emails[:5])}{' ...' if len(emails) > 5 else ''}")
                else:
                    logger.warning(f"          Não encontrei os emails correspondentes em matched_df")
        logger.warning("")

    detailed = detailed[detailed['comparison_group'].isin(['Champion', 'Challenger'])].copy()
    after_filter = len(detailed)
    conversions_after_filter = detailed['conversions'].sum()

    if before_filter != after_filter:
        logger.info(f"    Filtrados {before_filter - after_filter} adsets (Otimização ML ou Outro)")
        logger.info(f"    Conversões: {conversions_before_filter:.0f}  {conversions_after_filter:.0f} ({conversions_before_filter - conversions_after_filter:.0f} removidas)")

    logger.info("    Comparações de adsets calculadas")
    logger.info(f"      Adsets após filtro (Eventos ML + Controle): {len(detailed)}")

    # CRÍTICO: Para matched pairs, agregar por (campaign_id, adset_id, comparison_group)
    # Detectamos matched pairs quando há poucos adset_names únicos (<< total de linhas)
    unique_adset_names = detailed['adset_name'].nunique()
    is_matched_pairs = unique_adset_names < 20 and len(detailed) > unique_adset_names * 2

    if is_matched_pairs:
        logger.info(f"\n    MATCHED PAIRS detectado ({unique_adset_names} adsets únicos, {len(detailed)} linhas)")
        logger.info(f"    Agregando por (campaign_id, adset_id, comparison_group) para preservar instâncias por campanha...")

        # CRÍTICO: Para matched pairs, usar SEMPRE 'spend' (período filtrado)
        # NÃO usar total_spend porque queremos apenas o gasto do período de análise
        spend_column = 'spend'

        # Agregar métricas por (campaign_id, adset_id, comparison_group)
        # IMPORTANTE: Isso preserva cada combinação única de campanha+adset
        # Exemplo: mesmo adset em campanhas diferentes = linhas separadas
        agg_dict = {
            'leads': 'sum',
            'conversions': 'sum',
            spend_column: 'sum',  # Usar total_spend se disponível
            'revenue': 'sum',
            'campaign_name': 'first',  # Manter nome de campanha
            'adset_name': 'first',      # Manter nome de adset
            'account_id': 'first'       # CRÍTICO: Preservar account_id durante agregação!
        }

        # Adicionar revenue_adjusted se disponível
        if 'revenue_adjusted' in detailed.columns:
            agg_dict['revenue_adjusted'] = 'sum'

        detailed_aggregated = detailed.groupby(['campaign_id', 'adset_id', 'comparison_group'], as_index=False).agg(agg_dict)

        # Renomear spend_column para 'spend' para compatibilidade
        if spend_column != 'spend':
            detailed_aggregated['spend'] = detailed_aggregated[spend_column]
            detailed_aggregated = detailed_aggregated.drop(columns=[spend_column])
            logger.info(f"    Usando {spend_column} (histórico) para matched pairs")

        # Recalcular métricas derivadas
        detailed_aggregated['cpl'] = detailed_aggregated['spend'] / detailed_aggregated['leads'].replace(0, 1)
        detailed_aggregated['cpa'] = detailed_aggregated['spend'] / detailed_aggregated['conversions'].replace(0, 1)
        detailed_aggregated['conversion_rate'] = (detailed_aggregated['conversions'] / detailed_aggregated['leads'].replace(0, 1)) * 100
        detailed_aggregated['roas'] = detailed_aggregated['revenue'] / detailed_aggregated['spend'].replace(0, 1)
        detailed_aggregated['margin'] = detailed_aggregated['revenue'] - detailed_aggregated['spend']
        detailed_aggregated['margin_pct'] = (detailed_aggregated['margin'] / detailed_aggregated['revenue'].replace(0, 1)) * 100

        # Calcular ROAS Ajustado TMB se disponível
        if 'revenue_adjusted' in detailed_aggregated.columns:
            detailed_aggregated['roas_adjusted'] = detailed_aggregated['revenue_adjusted'] / detailed_aggregated['spend'].replace(0, 1)

        # Preservar colunas opcionais se existirem
        # NOTA: account_id JÁ foi preservado na agregação (agg_dict linha 1472)
        # NÃO re-mapear por adset_name pois o mesmo adset pode estar em múltiplas contas!

        if 'optimization_goal' in detailed.columns:
            opt_map = detailed.groupby('adset_name')['optimization_goal'].first().to_dict()
            detailed_aggregated['optimization_goal'] = detailed_aggregated['adset_name'].map(opt_map)

        if 'ml_type' in detailed.columns:
            ml_map = detailed.groupby('adset_name')['ml_type'].first().to_dict()
            detailed_aggregated['ml_type'] = detailed_aggregated['adset_name'].map(ml_map)

        logger.info(f"    Agregação completa: {len(detailed)} linhas  {len(detailed_aggregated)} linhas")
        logger.info(f"      Leads: {detailed['leads'].sum():.0f}  {detailed_aggregated['leads'].sum():.0f}")
        logger.info(f"      Conversões: {detailed['conversions'].sum():.0f}  {detailed_aggregated['conversions'].sum():.0f}")
        logger.info(f"      Spend: R$ {detailed['spend'].sum():.2f}  R$ {detailed_aggregated['spend'].sum():.2f}")

        detailed = detailed_aggregated

    return {
        'aggregated': aggregated,
        'detailed': detailed
    }


def compare_ad_performance(
    ad_metrics_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    ml_type_map: Dict[str, str],
    product_value: float = 2000.0,
    comparison_group_map: Optional[Dict[str, str]] = None
) -> Dict[str, pd.DataFrame]:
    """
    Compara performance de anúncios entre ML e Controle.

    IMPORTANTE: Usa matching preciso por (Campaign ID + ad_code).
    Mesma lógica dos adsets, mas usando utm_content em vez de utm_medium.

    Args:
        ad_metrics_df: DataFrame com métricas de anúncios (da Meta API)
        matched_df: DataFrame com conversões matched (leadsvendas)
        ml_type_map: Mapeamento campaign_id  ml_type (DEPRECATED - usar comparison_group_map)
        product_value: Valor do produto em R$
        comparison_group_map: Mapeamento campaign_id  comparison_group ('Champion', 'Otimização ML', 'Challenger')

    Returns:
        Dict com DataFrames:
        - 'aggregated': Agregação Champion vs Challenger
        - 'detailed': Detalhamento anúncio-a-anúncio
    """
    logger.info(" Comparando performance de anúncios...")

    # Adicionar ml_type aos anúncios (para compatibilidade)
    ad_metrics_df['ml_type'] = ad_metrics_df['campaign_id'].map(ml_type_map)

    # Se temos comparison_group_map, usar ele diretamente (novo comportamento)
    if comparison_group_map:
        ad_metrics_df['comparison_group_from_campaign'] = ad_metrics_df['campaign_id'].map(comparison_group_map)

    # Criar coluna account_id se não existir (pode vir como _account_name)
    if 'account_id' not in ad_metrics_df.columns and '_account_name' in ad_metrics_df.columns:
        ad_metrics_df['account_id'] = ad_metrics_df['_account_name']

    # =========================================================================
    # MATCHING PRECISO DE ANÚNCIOS (mesma lógica dos adsets)
    # =========================================================================

    # Função para extrair Campaign ID (reutilizar a mesma dos adsets)
    def extract_campaign_id(campaign_name):
        """Extrai o Campaign ID do final do nome da campanha"""
        if pd.isna(campaign_name):
            return None
        parts = str(campaign_name).split('|')
        if len(parts) > 1:
            last_part = parts[-1].strip()
            if last_part.isdigit() and len(last_part) >= 18:
                return last_part
        return None

    # Calcular conversões por ANÚNCIO (matching preciso!)
    if 'converted' in matched_df.columns:
        conversions_df = matched_df[matched_df['converted'] == True].copy()

        # 1. Extrair Campaign ID do utm_campaign
        conversions_df['campaign_id_from_utm'] = conversions_df['campaign'].apply(extract_campaign_id)

        # 2. Extrair ad_code do utm_content (padrão: AD0\d+)
        conversions_df['ad_code_from_utm'] = conversions_df['content'].str.extract(r'(AD0\d+)', expand=False)

        # DEBUG
        content_filled = conversions_df['content'].notna().sum()
        ad_code_extracted = conversions_df['ad_code_from_utm'].notna().sum()
        logger.info(f"\n    Extração de ad_code das conversões:")
        logger.info(f"      Total conversões: {len(conversions_df)}")
        logger.info(f"      utm_content preenchido: {content_filled} ({content_filled/len(conversions_df)*100:.1f}%)")
        logger.info(f"      ad_code extraído: {ad_code_extracted} ({ad_code_extracted/len(conversions_df)*100:.1f}%)")

        # 3. Preparar campaign_id_clean (primeiros 15 dígitos)
        conversions_df['campaign_id_clean'] = conversions_df['campaign_id_from_utm'].astype(str).str[:15]

        # 4. Agrupar por (campaign_id_clean, ad_code) - MATCHING PRECISO E calcular RECEITA REAL
        # CRÍTICO: Contar emails únicos para conversões, somar sale_value para receita
        conversions_by_campaign_ad = conversions_df.groupby(
            ['campaign_id_clean', 'ad_code_from_utm']
        ).agg({
            'email': 'nunique',  # Conversões únicas
            'sale_value': 'sum'   # Receita real total
        }).reset_index()
        conversions_by_campaign_ad.columns = ['campaign_id_clean', 'ad_code_from_utm', 'conversions', 'revenue']

        logger.info(f"      Agrupadas por (Campaign ID + ad_code): {len(conversions_by_campaign_ad)}")

        # 5. Calcular LEADS por anúncio (usar TODO o matched_df, não só conversões)
        logger.info(f"\n    Calculando leads por anúncio:")

        # Extrair ad_code de TODOS os leads
        all_leads_df = matched_df.copy()
        all_leads_df['campaign_id_from_utm'] = all_leads_df['campaign'].apply(extract_campaign_id)
        all_leads_df['ad_code_from_utm'] = all_leads_df['content'].str.extract(r'(AD0\d+)', expand=False)
        all_leads_df['campaign_id_clean'] = all_leads_df['campaign_id_from_utm'].astype(str).str[:15]

        # Agrupar por (campaign_id_clean, ad_code) para contar leads
        leads_by_campaign_ad = all_leads_df[all_leads_df['ad_code_from_utm'].notna()].groupby(
            ['campaign_id_clean', 'ad_code_from_utm']
        ).size().reset_index(name='leads')

        logger.info(f"      Total de leads com ad_code: {leads_by_campaign_ad['leads'].sum()}")
        logger.info(f"      Combinações únicas (Campaign ID + ad_code): {len(leads_by_campaign_ad)}")

        # 6. Preparar ad_metrics_df para merge
        ad_metrics_df['campaign_id_clean'] = ad_metrics_df['campaign_id'].astype(str).str[:15]

        # 7. AGREGAÇÃO: Consolidar anúncios com mesmo (campaign_id, ad_code)
        #    Mesmo ad_code pode ter múltiplos ad_ids no Excel  somar spend
        logger.info(f"\n    Agregando anúncios com mesmo (Campaign ID + ad_code):")
        logger.info(f"      Total de linhas no Excel: {len(ad_metrics_df)}")

        ad_metrics_aggregated = ad_metrics_df.groupby(['campaign_id_clean', 'ad_code', 'ml_type'], dropna=False).agg({
            'spend': 'sum',
            'campaign_id': 'first',  # Manter ID original
            'campaign_name': 'first',  # Manter nome
            'ad_name': 'first',  # Manter nome do primeiro ad
            'adset_name': 'first',  # Nome do adset
            'account_id': 'first'  # Account ID
        }).reset_index()

        logger.info(f"      Total após agregação: {len(ad_metrics_aggregated)}")
        logger.info(f"      Anúncios consolidados: {len(ad_metrics_df) - len(ad_metrics_aggregated)}")

        # 8. Merge LEADS por (campaign_id_clean, ad_code)
        ad_full = ad_metrics_aggregated.merge(
            leads_by_campaign_ad,
            left_on=['campaign_id_clean', 'ad_code'],
            right_on=['campaign_id_clean', 'ad_code_from_utm'],
            how='left',
            suffixes=('', '_leads')
        )

        ad_full['leads'] = ad_full['leads'].fillna(0)

        # 9. Merge CONVERSÕES E RECEITA REAL por (campaign_id_clean, ad_code)
        ad_full = ad_full.merge(
            conversions_by_campaign_ad,
            left_on=['campaign_id_clean', 'ad_code'],
            right_on=['campaign_id_clean', 'ad_code_from_utm'],
            how='left',
            suffixes=('', '_conv')
        )

        ad_full['conversions'] = ad_full['conversions'].fillna(0)
        ad_full['revenue'] = ad_full['revenue'].fillna(0)  # Receita real do matched_df

        logger.info(f"    Anúncios com leads: {(ad_full['leads'] > 0).sum()}")
        logger.info(f"    Anúncios com conversões: {(ad_full['conversions'] > 0).sum()}")
        logger.info(f"    Total leads: {ad_full['leads'].sum():.0f}")
        logger.info(f"    Total conversões atribuídas: {ad_full['conversions'].sum():.0f}")

    else:
        ad_metrics_df['campaign_id_clean'] = ad_metrics_df['campaign_id'].astype(str).str[:15]
        ad_full = ad_metrics_df.copy()
        ad_full['conversions'] = 0
        ad_full['leads'] = 0
        ad_full['revenue'] = 0

    # =========================================================================
    # CALCULAR MÉTRICAS DE NEGÓCIO
    # =========================================================================

    # Calcular métricas
    ad_full['cpl'] = ad_full['spend'] / ad_full['leads'].replace(0, 1)
    ad_full['cpa'] = ad_full['spend'] / ad_full['conversions'].replace(0, 1)
    ad_full['conversion_rate'] = (ad_full['conversions'] / ad_full['leads'].replace(0, 1)) * 100
    # NOTA: 'revenue' já vem do matched_df com valores reais de venda, não usar product_value fixo
    # ad_full['revenue'] já foi preenchida no merge acima
    ad_full['roas'] = ad_full['revenue'] / ad_full['spend'].replace(0, 1)
    ad_full['margin'] = ad_full['revenue'] - ad_full['spend']
    ad_full['margin_pct'] = (ad_full['margin'] / ad_full['revenue'].replace(0, 1)) * 100

    # CORREÇÃO: Adicionar comparison_group ANTES de criar agregações
    # Preparar campaign_id_15 para matching
    ad_full['campaign_id_15'] = ad_full['campaign_id'].astype(str).str[:15]

    # Aplicar comparison_group_map
    if comparison_group_map:
        ad_full['comparison_group'] = ad_full['campaign_id_15'].map(comparison_group_map)
        logger.info("    Usando mapeamento refinado (Eventos ML / Otimização ML / Controle)")
    else:
        # Fallback para ml_type
        ad_full['comparison_group'] = ad_full['ml_type'].map({
            'COM_ML': 'Champion',
            'SEM_ML': 'Challenger'
        })
        logger.warning("    comparison_group_map não disponível, usando classificação simples")

    # FILTRAR antes de agregar: apenas Eventos ML e Controle
    before_filter_count = len(ad_full)
    ad_full_filtered = ad_full[ad_full['comparison_group'].isin(['Champion', 'Challenger'])].copy()
    after_filter_count = len(ad_full_filtered)

    if before_filter_count != after_filter_count:
        logger.info(f"    Filtrados {before_filter_count - after_filter_count} ads (Otimização ML ou Outro) ANTES da agregação")

    # Agregação por comparison_group (NÃO ml_type)
    aggregated = ad_full_filtered.groupby('comparison_group').agg({
        'ad_code': 'nunique',
        'spend': 'sum',
        'leads': 'sum',
        'conversions': 'sum',
        'cpl': 'mean',
        'cpa': 'mean',
        'conversion_rate': 'mean',
        'roas': 'mean',
        'margin': 'sum',
        'margin_pct': 'mean'
    }).reset_index()

    # Detalhamento anúncio-a-anúncio (incluir informações contextuais)
    # USAR ad_full_filtered para garantir que apenas Eventos ML e Controle sejam incluídos
    detailed = ad_full_filtered.groupby(['ad_code', 'comparison_group']).agg({
        'campaign_name': 'first',  # Nome da campanha
        'campaign_id': 'first',  # ID da campanha (para buscar optimization_goal)
        'account_id': 'first',  # Account ID
        'adset_name': 'first',  # Nome do adset
        'ad_name': 'first',  # Nome do anúncio
        'ml_type': 'first',  # Manter ml_type para compatibilidade
        'spend': 'sum',
        'leads': 'sum',
        'conversions': 'sum',
        'cpl': 'mean',
        'cpa': 'mean',
        'conversion_rate': 'mean',
        'roas': 'mean',
        'revenue': 'sum',
        'margin': 'sum',
        'margin_pct': 'mean'
    }).reset_index()

    # IMPORTANTE: Ads herdam a classificação da CAMPANHA PAI
    # Não reclassificamos por optimization_goal do ad para manter consistência
    # A classificação já foi feita no nível de campanha considerando optimization_goal

    # Buscar optimization_goal apenas para referência (não para reclassificar)
    if 'optimization_goal' in ad_metrics_df.columns:
        optimization_map = ad_metrics_df[['campaign_id', 'optimization_goal']].drop_duplicates().set_index('campaign_id')['optimization_goal'].to_dict()
        detailed['optimization_goal'] = detailed['campaign_id'].map(optimization_map)
    else:
        detailed['optimization_goal'] = None

    # NOTA: comparison_group já foi adicionado ao ad_full nas linhas 1086-1095 e
    # o DataFrame foi filtrado (apenas Eventos ML e Controle) nas linhas 1097-1099.
    # O 'detailed' foi criado a partir do ad_full_filtered já filtrado (linhas 1118-1137),
    # então não é necessário adicionar comparison_group ou filtrar novamente aqui.

    logger.info(f"    Comparações de anúncios calculadas")
    logger.info(f"      Anúncios após filtro (Eventos ML + Controle): {len(detailed)}")

    return {
        'aggregated': aggregated,
        'detailed': detailed
    }


def compare_ads_in_matched_adsets(
    ad_metrics_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    ml_type_map: Dict[str, str],
    product_value: float = 2000.0,
    comparison_group_map: Optional[Dict[str, str]] = None,
    filtered_matched_adsets: Optional[List[str]] = None
) -> Dict[str, pd.DataFrame]:
    """
    Compara performance de anúncios que pertencem APENAS aos adsets matched.

    DIFERENÇA vs compare_ad_performance:
    - compare_ad_performance: todos os ads da lista MATCHED_ADS
    - compare_ads_in_matched_adsets: apenas ads cujo adset pai está em MATCHED_ADSETS

    Args:
        ad_metrics_df: DataFrame com métricas de anúncios (da Meta API)
        matched_df: DataFrame com conversões matched (leadsvendas)
        ml_type_map: Mapeamento campaign_id  ml_type
        product_value: Valor do produto em R$
        comparison_group_map: Mapeamento campaign_id  comparison_group
        filtered_matched_adsets: Lista de adsets matched que passaram nos filtros (comparison_group).
                                 Se None, usa a lista hardcoded MATCHED_ADSETS.

    Returns:
        Dict com DataFrames:
        - 'aggregated': Agregação Champion vs Challenger
        - 'detailed': Detalhamento anúncio-a-anúncio
    """
    logger.info(" Comparando performance de anúncios EM adsets matched...")

    # CORREÇÃO: Usar lista filtrada de adsets em vez da hardcoded
    # Isso garante que apenas ads de adsets "Champion" e "Challenger" sejam incluídos
    # (excluindo "Otimização ML" e outros)
    adsets_to_use = filtered_matched_adsets if filtered_matched_adsets is not None else MATCHED_ADSETS

    logger.info(f"    Usando {len(adsets_to_use)} adsets matched (filtrados por comparison_group)")

    # Filtrar apenas ads cujo adset pai está na lista filtrada
    ads_in_matched_adsets = ad_metrics_df[
        ad_metrics_df['adset_name'].isin(adsets_to_use)
    ].copy()

    logger.info(f"    Ads em adsets matched: {len(ads_in_matched_adsets)}")
    logger.info(f"    Ad codes únicos: {ads_in_matched_adsets['ad_name'].nunique()}")

    if len(ads_in_matched_adsets) == 0:
        logger.warning("    Nenhum ad encontrado nos adsets matched!")
        return {
            'aggregated': pd.DataFrame(),
            'detailed': pd.DataFrame()
        }

    # Usar a mesma lógica de compare_ad_performance, mas com o DataFrame filtrado
    return compare_ad_performance(
        ads_in_matched_adsets,
        matched_df,
        ml_type_map,
        product_value,
        comparison_group_map
    )


def compare_matched_ads_in_matched_adsets(
    ad_metrics_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    ml_type_map: Dict[str, str],
    product_value: float = 2000.0,
    comparison_group_map: Optional[Dict[str, str]] = None,
    filtered_matched_adsets: Optional[List[str]] = None
) -> Dict[str, pd.DataFrame]:
    """
    Compara performance de anúncios MATCHED que pertencem APENAS aos adsets matched.

    Combina dois filtros:
    1. Apenas adsets matched (aparecem em ML e Controle)
    2. Dentro desses adsets, apenas ads matched (ad_code aparece em ML e Controle)

    Args:
        ad_metrics_df: DataFrame com métricas de anúncios
        matched_df: DataFrame com dados de matching leads-vendas
        ml_type_map: Dict mapeando campaign_id para ml_type (COM_ML/SEM_ML)
        product_value: Valor do produto para cálculo de receita
        comparison_group_map: Dict mapeando campaign_id (15 dígitos) para grupo de comparação
        filtered_matched_adsets: Lista de adsets matched que passaram nos filtros

    Returns:
        Dict com 'aggregated' e 'detailed' DataFrames
    """
    logger.info(" Comparando ads MATCHED em adsets MATCHED...")

    # PASSO 1: Filtrar apenas ads dos adsets matched
    adsets_to_use = filtered_matched_adsets if filtered_matched_adsets is not None else MATCHED_ADSETS

    logger.info(f"    Usando {len(adsets_to_use)} adsets matched (filtrados por comparison_group)")

    ads_in_matched_adsets = ad_metrics_df[
        ad_metrics_df['adset_name'].isin(adsets_to_use)
    ].copy()

    logger.info(f"    Ads em adsets matched: {len(ads_in_matched_adsets)}")

    if len(ads_in_matched_adsets) == 0:
        logger.warning("    Nenhum ad encontrado nos adsets matched!")
        return {
            'aggregated': pd.DataFrame(),
            'detailed': pd.DataFrame()
        }

    # PASSO 2: Identificar ad_codes matched (aparecem em ML E Controle)
    # Preparar campaign_id_15 e comparison_group
    ads_in_matched_adsets['campaign_id_15'] = ads_in_matched_adsets['campaign_id'].astype(str).str[:15]

    if comparison_group_map:
        ads_in_matched_adsets['comparison_group'] = ads_in_matched_adsets['campaign_id_15'].map(comparison_group_map)
    else:
        ads_in_matched_adsets['comparison_group'] = ads_in_matched_adsets['campaign_id'].map(ml_type_map).map({
            'COM_ML': 'Champion',
            'SEM_ML': 'Challenger'
        })

    # Filtrar apenas Eventos ML e Controle
    ads_filtered = ads_in_matched_adsets[
        ads_in_matched_adsets['comparison_group'].isin(['Champion', 'Challenger'])
    ].copy()

    logger.info(f"    Ads após filtro de comparison_group: {len(ads_filtered)}")

    # Identificar quais ad_codes aparecem em AMBOS os grupos
    ad_codes_by_group = ads_filtered.groupby('comparison_group')['ad_code'].unique()

    if 'Champion' not in ad_codes_by_group or 'Challenger' not in ad_codes_by_group:
        logger.warning("    Não há ad_codes em ambos os grupos!")
        return {
            'aggregated': pd.DataFrame(),
            'detailed': pd.DataFrame()
        }

    eventos_ml_codes = set(ad_codes_by_group['Champion'])
    controle_codes = set(ad_codes_by_group['Challenger'])
    matched_ad_codes = eventos_ml_codes & controle_codes

    logger.info(f"    Ad codes matched (aparecem em ML E Controle): {len(matched_ad_codes)}")
    logger.info(f"      Eventos ML: {len(eventos_ml_codes)} códigos")
    logger.info(f"      Controle: {len(controle_codes)} códigos")
    logger.info(f"      Interseção: {len(matched_ad_codes)} códigos")

    if len(matched_ad_codes) == 0:
        logger.warning("    Nenhum ad_code matched encontrado!")
        return {
            'aggregated': pd.DataFrame(),
            'detailed': pd.DataFrame()
        }

    # PASSO 3: Filtrar apenas ads com ad_codes matched
    matched_ads_only = ads_filtered[
        ads_filtered['ad_code'].isin(matched_ad_codes)
    ].copy()

    logger.info(f"    Ads finais (matched em adsets matched): {len(matched_ads_only)}")

    # PASSO 4: Calcular métricas usando a mesma lógica de compare_ad_performance
    return compare_ad_performance(
        matched_ads_only,
        matched_df,
        ml_type_map,
        product_value,
        comparison_group_map
    )


# ============================================================================
# FUNÇÕES DE FORMATAÇÃO PARA EXCEL
# ============================================================================

def prepare_adset_comparison_for_excel(
    comparisons: Dict[str, pd.DataFrame]
) -> Dict[str, pd.DataFrame]:
    """
    Prepara DataFrames de comparação por adset para Excel.
    Formato similar à aba "Comparação por Campanhas".

    Args:
        comparisons: Dict com 'aggregated' e 'detailed'

    Returns:
        Dict com DataFrames formatados para Excel
    """
    logger.info(" Preparando comparações por adset para Excel...")

    excel_dfs = {}

    # Usar apenas 'detailed' com formato similar à aba Campanhas
    if not comparisons['detailed'].empty:
        df = comparisons['detailed'].copy()

        # DEBUG: Ver quais colunas existem
        logger.info(f"    DEBUG - Colunas em adsets detailed: {df.columns.tolist()}")

        # Renomear e reordenar colunas para formato similar à aba Campanhas
        column_mapping = {
            'account_id': 'Conta',
            'comparison_group': 'Grupo',
            'campaign_name': 'Campanha',
            'campaign_id': 'Campaign ID',
            'adset_name': 'Adset',
            'adset_id': 'Adset ID',
            'leads': 'Leads',
            'conversions': 'Vendas',
            'conversion_rate': 'Taxa de conversão',
            'spend': 'Valor gasto',
            'cpl': 'CPL',
            'roas': 'ROAS',
            'revenue': 'Receita Total',
            'margin': 'Margem de contribuição'
        }

        # Adicionar mapeamentos de TMB ajustado se existirem
        if 'revenue_adjusted' in df.columns:
            column_mapping['revenue_adjusted'] = 'Receita Ajustada TMB'
        if 'roas_adjusted' in df.columns:
            column_mapping['roas_adjusted'] = 'ROAS Ajustado TMB'

        df = df.rename(columns=column_mapping)

        # Mapear account_id para nomes amigáveis
        if 'Conta' in df.columns:
            def clean_account_name(x):
                if pd.isna(x):
                    return 'N/A'
                x = str(x)
                # Se é um ID de conta
                if x.startswith('act_'):
                    account_ids = {
                        'act_188005769808959': 'Rodolfo Mori',
                        'act_786790755803474': 'Gestor de IA'
                    }
                    return account_ids.get(x, x)
                # Se é nome de arquivo, extrair nome da conta
                if 'Rodolfo Mori' in x:
                    return 'Rodolfo Mori'
                elif 'Gestor de IA' in x:
                    return 'Gestor de IA'
                return x

            df['Conta'] = df['Conta'].apply(clean_account_name)

        # Calcular receita total se não existir
        if 'Receita Total' not in df.columns and 'Vendas' in df.columns:
            df['Receita Total'] = df['Vendas'] * 2000.0  # product_value

        # Selecionar e ordenar colunas (similar à aba Campanhas, com Conta primeiro)
        columns_order = [
            'Conta', 'Campanha', 'Campaign ID', 'Adset', 'Adset ID', 'Grupo', 'Leads', 'Vendas',
            'Taxa de conversão', 'Valor gasto', 'CPL', 'ROAS',
            'Receita Total', 'Margem de contribuição'
        ]

        # Adicionar colunas ajustadas TMB se existirem
        if 'Receita Ajustada TMB' in df.columns:
            columns_order.append('Receita Ajustada TMB')
        if 'ROAS Ajustado TMB' in df.columns:
            columns_order.append('ROAS Ajustado TMB')
        if 'Margem Ajustada TMB' in df.columns:
            columns_order.append('Margem Ajustada TMB')

        # Incluir apenas colunas que existem
        available_columns = [col for col in columns_order if col in df.columns]
        df = df[available_columns]

        # Ordenar por ROAS descendente
        if 'ROAS' in df.columns:
            df = df.sort_values('ROAS', ascending=False)

        excel_dfs['comparacao_adsets'] = df

    logger.info(f"    {len(excel_dfs)} abas preparadas para Excel")

    return excel_dfs


def prepare_ad_comparison_for_excel(
    comparisons: Dict[str, pd.DataFrame]
) -> Dict[str, pd.DataFrame]:
    """
    Prepara DataFrames de comparação por anúncio para Excel.
    Formato similar à aba "Comparação por Adsets".

    Args:
        comparisons: Dict com 'aggregated' e 'detailed'

    Returns:
        Dict com DataFrames formatados para Excel
    """
    logger.info(" Preparando comparações por anúncio para Excel...")

    excel_dfs = {}

    # Usar 'detailed' com formato similar à aba Adsets
    if 'detailed' in comparisons and not comparisons['detailed'].empty:
        df = comparisons['detailed'].copy()

        # Renomear colunas (adicionar IDs de campanha e adset)
        df = df.rename(columns={
            'comparison_group': 'Grupo',
            'campaign_id': 'Campaign ID',
            'adset_id': 'Adset ID',
            'ad_code': 'Ad Code',
            'ad_name': 'Nome do Anúncio',
            'leads': 'Leads',
            'conversions': 'Vendas',
            'conversion_rate': 'Taxa de conversão',
            'spend': 'Valor gasto',
            'cpl': 'CPL',
            'roas': 'ROAS',
            'revenue': 'Receita Total',
            'margin': 'Margem de contribuição'
        })

        # Calcular receita total se não existir
        if 'Receita Total' not in df.columns and 'Vendas' in df.columns:
            df['Receita Total'] = df['Vendas'] * 2000.0  # product_value

        # Selecionar e ordenar colunas (incluir IDs)
        columns_order = [
            'Campaign ID', 'Adset ID', 'Ad Code', 'Nome do Anúncio', 'Grupo',
            'Leads', 'Vendas', 'Taxa de conversão', 'Valor gasto', 'CPL', 'ROAS',
            'Receita Total', 'Margem de contribuição'
        ]

        # Incluir apenas colunas que existem
        available_columns = [col for col in columns_order if col in df.columns]
        df = df[available_columns]

        # Ordenar por ROAS descendente
        if 'ROAS' in df.columns:
            df = df.sort_values('ROAS', ascending=False)

        excel_dfs['comparacao_ads'] = df

    logger.info(f"    {len(excel_dfs)} abas preparadas para Excel")

    return excel_dfs

# ============================================================================
# CÓDIGO DE COMPATIBILIDADE COM VALIDATE_ML_PERFORMANCE.PY
# ============================================================================
# As seções abaixo foram adicionadas para manter compatibilidade com o script
# principal (validate_ml_performance.py) que foi mantido na versão do dia 16/12.
# TODO: Refatorar o script principal para usar as funções modernas acima.
# ============================================================================

# ============================================================================
# CONFIGURAÇÃO: NÍVEIS DE COMPARAÇÃO - EVENTO ML
# ============================================================================

# NÍVEL 1: Evento ML (adsets iguais)
# Comparação rigorosa: mesma estrutura de adsets, budget similar
ADSETS_IGUAIS_CONFIG = {
    'name': 'Evento ML (adsets iguais)',
    'ml_campaigns': [
        '120236428684840390',  # ADV ML - CBO R$ 300/dia
        '120236428684850390',  # ADV ML - CBO R$ 300/dia
    ],
    'control_campaigns': [
        '120224064762630390',  # ADV Controle - CBO R$ 390/dia
        '120224064761980390',  # ADV Controle - CBO R$ 390/dia
    ],
    'matched_ads': [
        'AD0013', 'AD0014', 'AD0017', 'AD0018', 'AD0022', 'AD0033'
    ],
    'adset_names': [
        'ADV | Linguagem de programação',
        'ADV | Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'ADV | Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'ADV | Lookalike 2% Alunos + Interesse Linguagem de Programação',
    ],
    'filter_by_adset': True,
    'budget_tolerance': 0.30,  # 30%
}

# NÍVEL 2: Evento ML (todos)
# Comparação geral: todas campanhas Evento ML, estruturas variadas
TODOS_CONFIG = {
    'name': 'Evento ML (todos)',
    'ml_campaigns': [
        '120236428684090390',  # ABERTO ML - CBO R$ 550/dia
        '120236428684840390',  # ADV ML - CBO R$ 300/dia
        '120236428684850390',  # ADV ML - CBO R$ 300/dia
    ],
    'control_campaigns': [
        '120220370119870390',  # ABERTO Controle - ABO
        '120224064762630390',  # ADV Controle - CBO R$ 390/dia
        '120224064761980390',  # ADV Controle - CBO R$ 390/dia
        '120224064762010390',  # ADV Controle
        '120224064762600390',  # ADV Controle
        '120228073033890390',  # ADV Controle
        '120230454190910390',  # ADV Controle
    ],
    'matched_ads': [
        'AD0004', 'AD0013', 'AD0014', 'AD0017', 'AD0018', 'AD0022', 'AD0027', 'AD0033'
    ],
    'filter_by_adset': False,
    'budget_tolerance': None,  # Sem restrição
}


def get_comparison_config(comparison_level: str = 'adsets_iguais') -> Dict:
    """
    Retorna configuração do nível de comparação desejado.
    
    Args:
        comparison_level: 'adsets_iguais' ou 'todos'
    
    Returns:
        Dict com configuração do nível
    """
    if comparison_level == 'adsets_iguais':
        return ADSETS_IGUAIS_CONFIG
    elif comparison_level == 'todos':
        return TODOS_CONFIG
    else:
        raise ValueError(f"Nível desconhecido: {comparison_level}. Use 'adsets_iguais' ou 'todos'")
def filter_campaigns_by_level(
    campaigns_df: pd.DataFrame,
    ml_type: str,
    comparison_level: str = 'ultra_fair'
) -> pd.DataFrame:
    """
    Filtra campanhas de acordo com o nível de comparação.

    Args:
        campaigns_df: DataFrame com todas as campanhas
        ml_type: 'eventos_ml' ou 'controle'
        comparison_level: 'ultra_fair' ou 'fair'

    Returns:
        DataFrame filtrado
    """
    config = get_comparison_config(comparison_level)

    if ml_type == 'eventos_ml':
        campaign_ids = config['ml_campaigns']
    elif ml_type == 'controle':
        campaign_ids = config['control_campaigns']
    else:
        raise ValueError(f"ml_type inválido: {ml_type}. Use 'eventos_ml' ou 'controle'")

    # Filtrar campanhas
    filtered = campaigns_df[campaigns_df['campaign_id'].isin(campaign_ids)].copy()

    logger.info(
        f"Filtro {config['name']} ({ml_type}): "
        f"{len(filtered)} de {len(campaigns_df)} campanhas"
    )

    return filtered


def filter_ads_by_level(
    ads_df: pd.DataFrame,
    comparison_level: str = 'ultra_fair'
) -> pd.DataFrame:
    """
    Filtra anúncios de acordo com o nível de comparação.

    Para Ultra Fair: apenas matched ads do nível
    Para Fair: todos matched ads

    Args:
        ads_df: DataFrame com todos os anúncios
        comparison_level: 'ultra_fair' ou 'fair'

    Returns:
        DataFrame filtrado
    """
    config = get_comparison_config(comparison_level)
    matched_ads = config['matched_ads']

    # Filtrar por ad_code
    if 'ad_code' in ads_df.columns:
        filtered = ads_df[ads_df['ad_code'].isin(matched_ads)].copy()
    else:
        logger.warning("Coluna 'ad_code' não encontrada. Retornando DataFrame original.")
        return ads_df

    logger.info(
        f"Filtro {config['name']}: "
        f"{len(filtered)} de {len(ads_df)} anúncios matched"
    )

    return filtered


def filter_ads_by_adset(
    ads_df: pd.DataFrame,
    comparison_level: str = 'ultra_fair'
) -> pd.DataFrame:
    """
    Filtra anúncios que aparecem nos mesmos adsets (apenas para Ultra Fair).

    Args:
        ads_df: DataFrame com anúncios (deve ter colunas 'adset_name' e 'ml_type')
        comparison_level: 'ultra_fair' ou 'fair'

    Returns:
        DataFrame filtrado
    """
    config = get_comparison_config(comparison_level)

    # Se não filtrar por adset, retornar tudo
    if not config.get('filter_by_adset', False):
        return ads_df

    # Verificar colunas necessárias
    required_cols = ['adset_name', 'ml_type', 'ad_code']
    missing_cols = [col for col in required_cols if col not in ads_df.columns]
    if missing_cols:
        logger.warning(f"Colunas faltando para filtro de adset: {missing_cols}")
        return ads_df

    # Adsets válidos
    valid_adsets = config.get('adset_names', [])
class FairCampaignMatcher:
    """
    Encontra campanhas de controle justo para comparação com campanhas ML.

    Usa Meta Ads API para identificar campanhas não-ML que sejam comparáveis
    às campanhas ML em termos de spend, criativos e período.
    """

    def __init__(self, account_id: str):
        """
        Inicializa o matcher com credenciais Meta API.

        Args:
            account_id: Meta Ads account ID (e.g., 'act_188005769808959')
        """
        self.account_id = account_id if account_id.startswith('act_') else f'act_{account_id}'
        self.access_token = META_CONFIG['access_token']

        # Cache para targeting (evitar chamadas repetidas à API)
        self._targeting_cache = {}
        self._api_calls_count = 0
        self._cache_hits_count = 0

        try:
            FacebookAdsApi.init(access_token=self.access_token)
            self.account = AdAccount(self.account_id)
            self.api_available = True
            logger.info(f" Meta API inicializada: {self.account_id}")
        except Exception as e:
            logger.error(f" Erro ao inicializar Meta API: {e}")
            self.api_available = False

    def get_ml_campaign_metadata(
        self,
        start_date: str,
        end_date: str
    ) -> Dict[str, Dict]:
        """
        Obtém metadata das campanhas ML (referência para comparação).

        Args:
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)

        Returns:
            Dict com campaign_id  {name, spend, creative_ids, impressions, ...}
        """
        if not self.api_available:
            logger.warning(" Meta API não disponível")
            return {}

        logger.info(f" Buscando campanhas ML ({start_date} a {end_date})...")

        try:
            params = {
                'time_range': {'since': start_date, 'until': end_date},
                'level': 'campaign',
                'fields': [
                    'campaign_id',
                    'campaign_name',
                    'spend',
                    'impressions',
                    'clicks',
                    'actions',
                ],
                'filtering': [
                    {
                        'field': 'campaign.name',
                        'operator': 'CONTAIN',
                        'value': 'MACHINE LEARNING'
                    }
                ]
            }

            insights = self.account.get_insights(params=params)

            ml_campaigns = {}
            for insight in insights:
                campaign_id = insight.get('campaign_id')
                campaign_name = insight.get('campaign_name')

                # Verificar se é realmente ML (MACHINE LEARNING ou | ML |)
                if not ('MACHINE LEARNING' in campaign_name.upper() or '| ML |' in campaign_name.upper()):
                    continue

                # Buscar budget e creative IDs desta campanha
                campaign_obj = Campaign(campaign_id)
                campaign_data = campaign_obj.api_get(fields=[
                    Campaign.Field.daily_budget,
                    Campaign.Field.lifetime_budget,
                    Campaign.Field.name
                ])

                # Pegar budget (priorizar daily, senão lifetime)
                # Meta API retorna em centavos - converter para reais
                budget_cents = float(campaign_data.get('daily_budget', 0) or campaign_data.get('lifetime_budget', 0) or 0)
                budget = budget_cents / 100 if budget_cents > 0 else 0

                # Se budget é 0, tentar buscar dos ad sets (CBO)
                if budget == 0:
                    try:
                        adsets = campaign_obj.get_ad_sets(fields=[
                            AdSet.Field.daily_budget,
                            AdSet.Field.lifetime_budget
                        ])
                        adset_budgets = []
                        for adset in adsets:
                            # Meta API retorna em centavos - converter para reais
                            adset_budget_cents = float(adset.get('daily_budget', 0) or adset.get('lifetime_budget', 0) or 0)
                            adset_budget = adset_budget_cents / 100 if adset_budget_cents > 0 else 0
                            if adset_budget > 0:
                                adset_budgets.append(adset_budget)

                        # Somar budgets dos ad sets
                        if adset_budgets:
                            budget = sum(adset_budgets)
                            logger.debug(f"Budget da campanha {campaign_id} obtido dos ad sets: R$ {budget:.2f}")
                    except Exception as e:
                        logger.debug(f"Erro ao buscar budget dos ad sets: {e}")

                # Buscar creative IDs desta campanha
                creative_ids = self._get_campaign_creative_ids(campaign_id, start_date, end_date)

                ml_campaigns[campaign_id] = {
                    'name': campaign_name,
                    'spend': float(insight.get('spend', 0)),
                    'budget': budget,
                    'impressions': int(insight.get('impressions', 0)),
                    'clicks': int(insight.get('clicks', 0)),
                    'creative_ids': creative_ids,
                }

            logger.info(f"    {len(ml_campaigns)} campanhas ML encontradas")
            for cid, data in ml_campaigns.items():
                logger.info(f"      {data['name']}: Budget R$ {data['budget']:.2f}, Spend R$ {data['spend']:.2f}, {len(data['creative_ids'])} criativos")

            return ml_campaigns

        except Exception as e:
            logger.error(f" Erro ao buscar campanhas ML: {e}")
            return {}

    def find_fair_control_campaigns(
        self,
        ml_campaign_metadata: Dict[str, Dict],
        min_creative_overlap: float = 0.8,
        budget_tolerance: float = 0.30,
        start_date: str = None,
        end_date: str = None
    ) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
        """
        Encontra campanhas de controle com características similares.

        CRITÉRIOS REFINADOS (após análise manual):
        - Budget: ±30% tolerância (não precisa ser exato)
        - Criativos: 80%+ overlap (mínimo)
        - Targeting: NÃO verificado (evita rate limits, não essencial)

        Args:
            ml_campaign_metadata: Metadata das campanhas ML (de get_ml_campaign_metadata)
            min_creative_overlap: Sobreposição mínima de criativos (0.8 = 80%+)
            budget_tolerance: Tolerância de budget (0.30 = ±30%)
            start_date: Data início (YYYY-MM-DD)
            end_date: Data fim (YYYY-MM-DD)

        Returns:
            Tuple de (fair_control_map, control_id_to_name):
            - fair_control_map: Dict com ml_campaign_id  [fair_control_campaign_ids]
            - control_id_to_name: Dict com campaign_id  campaign_name (para controles)
        """
        if not self.api_available or not ml_campaign_metadata:
            return {}, {}

        logger.info(f" Buscando campanhas de controle justo (critérios: Budget ±{budget_tolerance*100:.0f}%, Criativos {min_creative_overlap*100:.0f}%+ iguais)...")

        fair_matches = {}
        control_id_to_name = {}

        try:
            # Buscar TODAS as campanhas do período (não apenas ML)
            params = {
                'time_range': {'since': start_date, 'until': end_date},
                'level': 'campaign',
                'fields': ['campaign_id', 'campaign_name', 'spend'],
            }

            all_insights = self.account.get_insights(params=params)

            # Converter para dict - extrair campanhas não-ML
            all_campaigns = {}
            for insight in all_insights:
                campaign_id = insight.get('campaign_id')
                campaign_name = insight.get('campaign_name')

                # Excluir campanhas ML
                if 'MACHINE LEARNING' in campaign_name.upper() or '| ML |' in campaign_name.upper():
                    continue

                # Buscar budget e criativos
                budget = self._get_campaign_budget(campaign_id)
                creative_ids = self._get_campaign_creative_ids(campaign_id, start_date, end_date)

                all_campaigns[campaign_id] = {
                    'name': campaign_name,
                    'spend': float(insight.get('spend', 0)),
                    'budget': budget,
                    'creative_ids': creative_ids,
                }

            logger.info(f"    {len(all_campaigns)} campanhas não-ML encontradas para comparação")

            # Para cada campanha ML, encontrar matches usando critérios refinados
            for ml_id, ml_data in ml_campaign_metadata.items():
                ml_budget = ml_data.get('budget', 0)
                ml_creatives = set(ml_data['creative_ids'])
                ml_name = ml_data['name']

                logger.info(f"\n    Analisando ML: {ml_name[:80]}...")
                logger.info(f"      Budget: R$ {ml_budget:.2f}, {len(ml_creatives)} criativos")

                matches = []
                rejected_budget = 0
                rejected_creatives = 0

                for ctrl_id, ctrl_data in all_campaigns.items():
                    ctrl_budget = ctrl_data.get('budget', 0)
                    ctrl_creatives = set(ctrl_data['creative_ids'])
                    ctrl_name = ctrl_data['name']

                    # Critério 1: Budget dentro da tolerância (±30%)
                    if ml_budget > 0:
                        budget_diff = abs(ml_budget - ctrl_budget) / ml_budget
                        if budget_diff > budget_tolerance:
                            rejected_budget += 1
                            if rejected_budget <= 3:  # Mostrar primeiras 3
                                logger.info(f"       Budget: {ctrl_name[:60]} (R$ {ctrl_budget:.2f}, diff {budget_diff*100:.0f}% > {budget_tolerance*100:.0f}%)")
                            continue

                    # Critério 2: Sobreposição de criativos (80%+)
                    if len(ml_creatives) == 0 or len(ctrl_creatives) == 0:
                        rejected_creatives += 1
                        continue

                    overlap = len(ml_creatives & ctrl_creatives)
                    overlap_pct_ml = overlap / len(ml_creatives)
                    overlap_pct_ctrl = overlap / len(ctrl_creatives)
                    min_overlap_pct = min(overlap_pct_ml, overlap_pct_ctrl)

                    if min_overlap_pct < min_creative_overlap:
                        rejected_creatives += 1
                        if rejected_creatives <= 3:  # Mostrar primeiras 3
                            logger.info(f"       Criativos: {ctrl_name[:60]} ({min_overlap_pct*100:.0f}% < {min_creative_overlap*100:.0f}%)")
                        continue

                    #  MATCH ENCONTRADO! Budget ±30% e Criativos 80%+
                    logger.info(f"       MATCH: {ctrl_name[:60]}")
                    logger.info(f"         Budget: R$ {ctrl_budget:.2f} (diff {budget_diff*100:.0f}%), Criativos: {overlap}/{len(ml_creatives)} ({min_overlap_pct*100:.0f}%)")

                    match_info = {
                        'id': ctrl_id,
                        'name': ctrl_data['name'],
                        'spend': ctrl_data['spend'],
                        'budget': ctrl_budget,
                        'creative_overlap': overlap,
                        'creative_overlap_pct': min_overlap_pct * 100,
                        'match_score': (1 - budget_diff) * min_overlap_pct  # Score combinado
                    }

                    matches.append(match_info)

                # Mostrar resumo de filtros
                total_checked = rejected_budget + rejected_creatives + len(matches)
                logger.info(f"\n       Resumo de filtros para esta ML:")
                logger.info(f"         Total verificadas: {total_checked}")
                logger.info(f"          Rejeitadas por Budget: {rejected_budget}")
                logger.info(f"          Rejeitadas por Criativos: {rejected_creatives}")
                logger.info(f"          Aprovadas (Fair Control): {len(matches)}")

                # Ordenar por match score (melhor combinação de budget + criativos)
                matches.sort(key=lambda x: -x['match_score'])

                fair_matches[ml_id] = [m['id'] for m in matches]

                # Adicionar ao mapeamento id  name
                for m in matches:
                    control_id_to_name[m['id']] = m['name']

                if matches:
                    logger.info(f"\n    {ml_name}:")
                    logger.info(f"       Encontradas {len(matches)} campanhas Fair Control:")
                    for m in matches[:3]:  # Top 3
                        logger.info(f"          {m['name'][:60]}")
                        logger.info(f"           Budget: R$ {m['budget']:.2f}, Criativos: {m['creative_overlap']} ({m['creative_overlap_pct']:.0f}%), Score: {m['match_score']:.2f}")
                else:
                    logger.warning(f"    Nenhuma campanha Fair Control encontrada")

            return fair_matches, control_id_to_name

        except Exception as e:
            logger.error(f" Erro ao buscar campanhas de controle: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {}, {}

    def _get_campaign_budget(self, campaign_id: str) -> float:
        """
        Extrai budget de uma campanha (daily ou lifetime).

        Args:
            campaign_id: ID da campanha

        Returns:
            Budget em R$ (convertido de centavos)
        """
        try:
            campaign_obj = Campaign(campaign_id)
            campaign_data = campaign_obj.api_get(fields=[
                Campaign.Field.daily_budget,
                Campaign.Field.lifetime_budget
            ])
            # Meta API retorna em centavos - converter para reais
            budget_cents = float(campaign_data.get('daily_budget', 0) or campaign_data.get('lifetime_budget', 0) or 0)
            budget = budget_cents / 100 if budget_cents > 0 else 0

            # Se budget é 0, tentar buscar dos ad sets (CBO)
            if budget == 0:
                try:
                    adsets = campaign_obj.get_ad_sets(fields=[
                        AdSet.Field.daily_budget,
                        AdSet.Field.lifetime_budget
                    ])
                    adset_budgets = []
                    for adset in adsets:
                        adset_budget_cents = float(adset.get('daily_budget', 0) or adset.get('lifetime_budget', 0) or 0)
                        adset_budget = adset_budget_cents / 100 if adset_budget_cents > 0 else 0
                        if adset_budget > 0:
                            adset_budgets.append(adset_budget)

                    if adset_budgets:
                        budget = sum(adset_budgets)
                        logger.debug(f"Budget da campanha {campaign_id} obtido dos ad sets: R$ {budget:.2f}")
                except Exception as e_adset:
                    logger.debug(f"Erro ao buscar budget dos ad sets: {e_adset}")

            return budget

        except Exception as e:
            logger.debug(f"Erro ao buscar budget da campanha {campaign_id}: {e}")
            return 0.0

    def _get_campaign_creative_ids(
        self,
        campaign_id: str,
        start_date: str,
        end_date: str
    ) -> List[str]:
        """
        Extrai creative IDs de uma campanha.

        Args:
            campaign_id: ID da campanha
            start_date: Data início
            end_date: Data fim

        Returns:
            Lista de creative IDs únicos
        """
        try:
            campaign = Campaign(campaign_id)

            # Buscar ads da campanha (sem filtro de time_range, buscar todos)
            ads = campaign.get_ads(
                fields=[Ad.Field.creative, Ad.Field.name, Ad.Field.status],
                params={
                    'effective_status': ['ACTIVE', 'PAUSED', 'ARCHIVED'],
                }
            )

            creative_ids = set()
            ad_count = 0
            for ad in ads:
                ad_count += 1
                creative = ad.get(Ad.Field.creative)

                if creative:
                    # Pode vir como dict ou como objeto AdCreative
                    if isinstance(creative, dict):
                        creative_id = creative.get('id')
                    else:
                        # É um objeto AdCreative, pegar o ID dele
                        creative_id = getattr(creative, 'get_id', lambda: None)() or creative.get('id', None)

                    if creative_id:
                        creative_ids.add(str(creative_id))

            logger.debug(f"Campanha {campaign_id}: {ad_count} ads encontrados, {len(creative_ids)} criativos únicos")
            return list(creative_ids)

        except Exception as e:
            logger.debug(f"Erro ao buscar criativos da campanha {campaign_id}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []

    def create_comparison_groups(
        self,
        leads_df: pd.DataFrame,
        ml_campaign_metadata: Dict[str, Dict],
        fair_control_map: Dict[str, List[str]],
        control_id_to_name: Dict[str, str],
        campaign_hierarchy: Dict[str, Dict] = None,
        campaigns_with_custom_events: Set[str] = None
    ) -> pd.DataFrame:
        """
        Adiciona coluna 'comparison_group' aos leads baseado nos matches.

        Args:
            leads_df: DataFrame de leads com coluna 'campaign'
            ml_campaign_metadata: Metadata das campanhas ML (com nomes)
            fair_control_map: Mapeamento ML campaign_id  [control campaign_ids]
            control_id_to_name: Mapeamento control campaign_id  campaign_name
            campaign_hierarchy: Hierarquia de campanhas com optimization_goal (opcional)
            campaigns_with_custom_events: Set de campaign_ids que usam eventos customizados

        Returns:
            DataFrame com coluna 'comparison_group' adicionada:
            - 'Champion': Campanha com eventos customizados
            - 'Otimização ML': Campanha com ML mas eventos padrão
            - 'Challenger': Campanha de controle justo
            - 'Outro': Outras campanhas
        """
        df = leads_df.copy()

        # Debug: verificar colunas disponíveis
        has_lq = 'LeadQualified' in df.columns
        has_lqhq = 'LeadQualifiedHighQuality' in df.columns
        logger.info(f"    Colunas de eventos customizados: LeadQualified={has_lq}, LeadQualifiedHighQuality={has_lqhq}")
        if has_lq:
            lq_sum = df['LeadQualified'].sum()
            lq_campaigns = df[df['LeadQualified'] > 0]['campaign'].unique()
            logger.info(f"    Total LeadQualified: {lq_sum} em {len(lq_campaigns)} campanhas")
            if len(lq_campaigns) > 0:
                logger.info(f"    Campanhas com LeadQualified: {lq_campaigns[:3]}")

        # Criar set de nomes COMPLETOS de campanhas de controle justo (incluindo ID)
        fair_control_names = set(control_id_to_name.values())

        # Enriquecer com optimization_goal se não existir
        if 'optimization_goal' not in df.columns:
            # Criar mapeamento campaign_id  optimization_goal da hierarquia
            if campaign_hierarchy:
                logger.info(f"    Enriquecendo leads com optimization_goal ({len(campaign_hierarchy)} campanhas na hierarquia)")
                opt_goal_map = {}
                for campaign_id, campaign_data in campaign_hierarchy.items():
                    # Verificar TODOS os adsets para detectar eventos customizados
                    # Se qualquer adset usa evento customizado, a campanha é "Champion"
                    adsets = campaign_data.get('adsets', {})
                    optimization_goals = []
                    for adset_id, adset_data in adsets.items():
                        opt_goal = adset_data.get('optimization_goal', 'Lead')
                        optimization_goals.append(opt_goal)

                    # Se qualquer adset usa LeadQualified ou LeadQualifiedHighQuality, usar isso
                    if 'LeadQualified' in optimization_goals:
                        opt_goal_map[campaign_id] = 'LeadQualified'
                    elif 'LeadQualifiedHighQuality' in optimization_goals:
                        opt_goal_map[campaign_id] = 'LeadQualifiedHighQuality'
                    else:
                        # Usar o primeiro adset como antes
                        opt_goal_map[campaign_id] = optimization_goals[0] if optimization_goals else 'Lead'

                logger.info(f"    Mapeamento criado para {len(opt_goal_map)} campanhas")

                # Extrair campaign_id da coluna campaign (formato: "nome|campaign_id")
                def get_campaign_id(campaign_str):
                    if pd.isna(campaign_str) or not isinstance(campaign_str, str):
                        return None
                    if '|' in campaign_str:
                        parts = campaign_str.rsplit('|', 1)
                        if len(parts) == 2 and parts[1].strip().isdigit():
                            return parts[1].strip()
                    return None

                df['_campaign_id'] = df['campaign'].apply(get_campaign_id)
                df['optimization_goal'] = df['_campaign_id'].map(opt_goal_map).fillna('Lead')
                df = df.drop(columns=['_campaign_id'])

                # Log de campanhas COM_ML e seus optimization_goals
                com_ml_campaigns = df[df['ml_type'] == 'COM_ML']['campaign'].unique()
                if len(com_ml_campaigns) > 0:
                    logger.info(f"    Campanhas COM_ML e seus eventos:")
                    for camp in com_ml_campaigns[:5]:  # Primeiras 5
                        camp_rows = df[df['campaign'] == camp]
                        if len(camp_rows) > 0:
                            opt_goal = camp_rows.iloc[0]['optimization_goal']
                            logger.info(f"       {camp[:60]}: {opt_goal}")
            else:
                logger.warning("    Hierarquia de campanhas não fornecida - usando 'Lead' padrão")

        # Classificar
        def classify_group(row):
            campaign_name = row.get('campaign', '')
            optimization_goal = row.get('optimization_goal', '')

            # Normalizar: remover sufixo |campaign_id se presente
            campaign_name_base = campaign_name
            campaign_id = None
            if '|' in campaign_name:
                parts = campaign_name.rsplit('|', 1)
                if len(parts) == 2 and parts[1].strip().isdigit():
                    campaign_name_base = parts[0].strip()
                    campaign_id = parts[1].strip()

            # Critério 1: Eventos ML (COM_ML + usa eventos customizados)
            if row.get('ml_type') == 'COM_ML':
                # Verificar se usa eventos customizados através de múltiplas fontes:
                # 1. Optimization goal da hierarquia
                # 2. Set explícito de campanhas com eventos customizados
                # 3. Heurística por data: campanhas criadas a partir de 25/11 usam eventos customizados
                uses_custom_events_by_goal = optimization_goal in ['LeadQualified', 'LeadQualifiedHighQuality']
                uses_custom_events_by_set = campaigns_with_custom_events and campaign_id in campaigns_with_custom_events

                # Heurística por data: extrair data do nome da campanha (formato: | YYYY-MM-DD)
                uses_custom_events_by_date = False
                import re
                date_match = re.search(r'\| (\d{4})-(\d{2})-(\d{2})', campaign_name)
                if date_match:
                    year, month, day = date_match.groups()
                    campaign_date = f"{year}-{month}-{day}"
                    # Campanhas Eventos ML foram criadas a partir de 2025-11-25 (conta 1880)
                    # ou 2025-11-11 (conta 7867 - teste com LeadQualified)
                    if campaign_date >= "2025-11-11":
                        uses_custom_events_by_date = True

                if uses_custom_events_by_goal or uses_custom_events_by_set or uses_custom_events_by_date:
                    return 'Champion'
                else:
                    return 'Otimização ML'

            # Critério 2: É campanha de controle justo?
            # Check both full name and base name (without ID suffix)
            elif row.get('ml_type') == 'SEM_ML' and (
                campaign_name in fair_control_names or
                campaign_name_base in fair_control_names
            ):
                return 'Challenger'

            # Outras campanhas
            else:
                return 'Outro'

        df['comparison_group'] = df.apply(classify_group, axis=1)

        # Log da distribuição
        logger.info(f"\n    Distribuição de grupos de comparação:")
        for group in ['Champion', 'Otimização ML', 'Challenger', 'Outro']:
            count = len(df[df['comparison_group'] == group])
            pct = count / len(df) * 100 if len(df) > 0 else 0
            logger.info(f"      {group}: {count} leads ({pct:.1f}%)")

        return df


