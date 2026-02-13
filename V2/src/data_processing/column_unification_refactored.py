"""
Módulo para unificação de colunas duplicadas - REFATORADO.

Separa a lógica da célula 5 original em 5 sub-células:
- CÉLULA 5: Unificação de colunas duplicadas
- CÉLULA 5.1: Filtro temporal
- CÉLULA 5.2: Remoção de colunas UTM com alta % ausentes
- CÉLULA 5.3: Filtro de status e risco
- CÉLULA 5.4: Filtro de produtos DevClub
"""

import pandas as pd
from typing import Tuple, List
import logging

logger = logging.getLogger(__name__)


def identificar_colunas_duplicadas_pesquisa(df: pd.DataFrame) -> List[Tuple[str, str]]:
    """
    Identifica todas as colunas duplicadas no dataset de pesquisa.

    Args:
        df: DataFrame de pesquisa

    Returns:
        Lista de tuplas (col1, col2) de colunas duplicadas
    """
    colunas = df.columns.tolist()
    duplicadas = []

    # Verificar padrões de duplicação
    for i, col1 in enumerate(colunas):
        for j, col2 in enumerate(colunas[i+1:], i+1):
            # Comparar início das strings (truncadas podem ser iguais)
            if col1[:30] == col2[:30] and col1 != col2:
                duplicadas.append((col1, col2))

    return duplicadas


def unificar_colunas_pesquisa(df_pesquisa: pd.DataFrame) -> pd.DataFrame:
    """
    CÉLULA 5 - Parte 1: Unifica colunas duplicadas no dataset de PESQUISA.

    Args:
        df_pesquisa: DataFrame de pesquisa

    Returns:
        DataFrame de pesquisa com colunas unificadas
    """
    df_pesquisa_unificado = df_pesquisa.copy()
    colunas_antes = len(df_pesquisa_unificado.columns)

    # DEBUG: Lista completa de colunas duplicadas
    duplicadas_pesquisa = identificar_colunas_duplicadas_pesquisa(df_pesquisa_unificado)
    logger.debug("PESQUISA - Colunas duplicadas identificadas:")
    for col1, col2 in duplicadas_pesquisa:
        logger.debug(f"  {col1}")
        logger.debug(f"  {col2}")
        logger.debug("")

    # Unificar colunas duplicadas de pesquisa (OPERAÇÃO VETORIZADA)
    colunas_investiu = [
        'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?',
        'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro? '
    ]

    if all(col in df_pesquisa_unificado.columns for col in colunas_investiu):
        df_pesquisa_unificado['investiu_curso_online'] = (
            df_pesquisa_unificado[colunas_investiu[0]]
            .fillna(df_pesquisa_unificado[colunas_investiu[1]])
        )
        df_pesquisa_unificado = df_pesquisa_unificado.drop(columns=colunas_investiu)

    colunas_atencao = [
        'O que mais te chama atenção na profissão de Programador?',
        'O que mais te chama atenção na profissão de Programador? '
    ]

    if all(col in df_pesquisa_unificado.columns for col in colunas_atencao):
        df_pesquisa_unificado['interesse_programacao'] = (
            df_pesquisa_unificado[colunas_atencao[0]]
            .fillna(df_pesquisa_unificado[colunas_atencao[1]])
        )
        df_pesquisa_unificado = df_pesquisa_unificado.drop(columns=colunas_atencao)

    # Unificar colunas de faixa salarial (nome truncado da API vs nome completo dos arquivos locais)
    colunas_faixa_salarial = [
        'Atualmente, qual a sua faixa salarial?',  # Arquivos locais (nome completo)
        'Atualmente, qual a sua faixa salar'        # API (nome truncado)
    ]

    if all(col in df_pesquisa_unificado.columns for col in colunas_faixa_salarial):
        df_pesquisa_unificado['Atualmente, qual a sua faixa salarial?'] = (
            df_pesquisa_unificado[colunas_faixa_salarial[0]]
            .fillna(df_pesquisa_unificado[colunas_faixa_salarial[1]])
        )
        df_pesquisa_unificado = df_pesquisa_unificado.drop(columns=[colunas_faixa_salarial[1]])

    # NORMAL: Resumo com colunas antes/depois
    colunas_depois = len(df_pesquisa_unificado.columns)
    colunas_unificadas = colunas_antes - colunas_depois

    logger.info(f"  Pesquisa - Colunas antes: {colunas_antes}, depois: {colunas_depois} (unificadas: {colunas_unificadas})")

    return df_pesquisa_unificado


def unificar_colunas_vendas(df_vendas: pd.DataFrame) -> pd.DataFrame:
    """
    CÉLULA 5 - Parte 2: Unifica colunas duplicadas no dataset de VENDAS.

    Args:
        df_vendas: DataFrame de vendas

    Returns:
        DataFrame de vendas com colunas unificadas
    """
    df_vendas_unificado = df_vendas.copy()
    colunas_antes = len(df_vendas_unificado.columns)

    # DEBUG: Detalhes de cada unificação
    logger.debug("VENDAS - Unificando colunas:")

    # Unificar valor
    if 'Ticket (R$)' in df_vendas_unificado.columns and 'valor produtos' in df_vendas_unificado.columns:
        df_vendas_unificado['valor'] = df_vendas_unificado['Ticket (R$)'].fillna(df_vendas_unificado['valor produtos'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Ticket (R$)', 'valor produtos'])
        logger.debug("  Ticket (R$) + valor produtos  valor")
    elif 'Ticket (R$)' in df_vendas_unificado.columns:
        df_vendas_unificado['valor'] = df_vendas_unificado['Ticket (R$)']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Ticket (R$)'])
        logger.debug("  Ticket (R$)  valor")
    elif 'valor produtos' in df_vendas_unificado.columns:
        df_vendas_unificado['valor'] = df_vendas_unificado['valor produtos']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['valor produtos'])
        logger.debug("  valor produtos  valor")

    # Unificar produto (hierarquia: Produto [Guru] > Lançamento [TMB] > nome produto [fallback])
    colunas_produto_disponiveis = []
    if 'Produto' in df_vendas_unificado.columns:
        colunas_produto_disponiveis.append('Produto')
    if 'Lançamento' in df_vendas_unificado.columns:
        colunas_produto_disponiveis.append('Lançamento')
    if 'nome produto' in df_vendas_unificado.columns:
        colunas_produto_disponiveis.append('nome produto')

    if colunas_produto_disponiveis:
        # Unificar com hierarquia: pegar primeira coluna não-nula
        df_vendas_unificado['produto'] = df_vendas_unificado[colunas_produto_disponiveis[0]]
        for col in colunas_produto_disponiveis[1:]:
            df_vendas_unificado['produto'] = df_vendas_unificado['produto'].fillna(df_vendas_unificado[col])

        # Remover colunas originais
        df_vendas_unificado = df_vendas_unificado.drop(columns=colunas_produto_disponiveis)

        # Log de quais colunas foram unificadas
        if len(colunas_produto_disponiveis) > 1:
            logger.debug(f"  {' + '.join(colunas_produto_disponiveis)}  produto")
        else:
            logger.debug(f"  {colunas_produto_disponiveis[0]}  produto")

    # Unificar nome
    if 'Cliente Nome' in df_vendas_unificado.columns and 'nome contato' in df_vendas_unificado.columns:
        df_vendas_unificado['nome'] = df_vendas_unificado['Cliente Nome'].fillna(df_vendas_unificado['nome contato'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Cliente Nome', 'nome contato'])
        logger.debug("  Cliente Nome + nome contato  nome")
    elif 'Cliente Nome' in df_vendas_unificado.columns:
        df_vendas_unificado['nome'] = df_vendas_unificado['Cliente Nome']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Cliente Nome'])
        logger.debug("  Cliente Nome  nome")
    elif 'nome contato' in df_vendas_unificado.columns:
        df_vendas_unificado['nome'] = df_vendas_unificado['nome contato']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['nome contato'])
        logger.debug("  nome contato  nome")

    # Unificar email
    if 'Cliente Email' in df_vendas_unificado.columns and 'email contato' in df_vendas_unificado.columns:
        df_vendas_unificado['email'] = df_vendas_unificado['Cliente Email'].fillna(df_vendas_unificado['email contato'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Cliente Email', 'email contato'])
        logger.debug("  Cliente Email + email contato  email")
    elif 'Cliente Email' in df_vendas_unificado.columns:
        df_vendas_unificado['email'] = df_vendas_unificado['Cliente Email']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Cliente Email'])
        logger.debug("  Cliente Email  email")
    elif 'email contato' in df_vendas_unificado.columns:
        df_vendas_unificado['email'] = df_vendas_unificado['email contato']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['email contato'])
        logger.debug("  email contato  email")

    # Unificar data
    def fix_datetime_format(col):
        """Converte datetime para string DD/MM/YYYY HH:MM:SS ou mantém NaT"""
        return col.apply(lambda x: x.strftime('%d/%m/%Y %H:%M:%S') if pd.notna(x) and hasattr(x, 'strftime') else x)

    date_format = '%d/%m/%Y %H:%M:%S'

    if 'Criado Em' in df_vendas_unificado.columns and 'data aprovacao' in df_vendas_unificado.columns and 'Data Efetivado' in df_vendas_unificado.columns:
        df_vendas_unificado['Criado Em'] = fix_datetime_format(df_vendas_unificado['Criado Em'])
        df_vendas_unificado['data aprovacao'] = fix_datetime_format(df_vendas_unificado['data aprovacao'])
        df_vendas_unificado['Data Efetivado'] = fix_datetime_format(df_vendas_unificado['Data Efetivado'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Criado Em'], format=date_format, errors='coerce').fillna(
            pd.to_datetime(df_vendas_unificado['data aprovacao'], format=date_format, errors='coerce')).fillna(
            pd.to_datetime(df_vendas_unificado['Data Efetivado'], format=date_format, errors='coerce'))
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Criado Em', 'data aprovacao', 'Data Efetivado'])
        logger.debug("  Criado Em + data aprovacao + Data Efetivado  data (formato BR corrigido)")
    elif 'Criado Em' in df_vendas_unificado.columns and 'data aprovacao' in df_vendas_unificado.columns:
        df_vendas_unificado['Criado Em'] = fix_datetime_format(df_vendas_unificado['Criado Em'])
        df_vendas_unificado['data aprovacao'] = fix_datetime_format(df_vendas_unificado['data aprovacao'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Criado Em'], format=date_format, errors='coerce').fillna(
            pd.to_datetime(df_vendas_unificado['data aprovacao'], format=date_format, errors='coerce'))
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Criado Em', 'data aprovacao'])
        logger.debug("  Criado Em + data aprovacao  data (formato BR corrigido)")
    elif 'Criado Em' in df_vendas_unificado.columns and 'Data Efetivado' in df_vendas_unificado.columns:
        df_vendas_unificado['Criado Em'] = fix_datetime_format(df_vendas_unificado['Criado Em'])
        df_vendas_unificado['Data Efetivado'] = fix_datetime_format(df_vendas_unificado['Data Efetivado'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Criado Em'], format=date_format, errors='coerce').fillna(
            pd.to_datetime(df_vendas_unificado['Data Efetivado'], format=date_format, errors='coerce'))
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Criado Em', 'Data Efetivado'])
        logger.debug("  Criado Em + Data Efetivado  data (formato BR corrigido)")
    elif 'data aprovacao' in df_vendas_unificado.columns and 'Data Efetivado' in df_vendas_unificado.columns:
        df_vendas_unificado['data aprovacao'] = fix_datetime_format(df_vendas_unificado['data aprovacao'])
        df_vendas_unificado['Data Efetivado'] = fix_datetime_format(df_vendas_unificado['Data Efetivado'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['data aprovacao'], format=date_format, errors='coerce').fillna(
            pd.to_datetime(df_vendas_unificado['Data Efetivado'], format=date_format, errors='coerce'))
        df_vendas_unificado = df_vendas_unificado.drop(columns=['data aprovacao', 'Data Efetivado'])
        logger.debug("  data aprovacao + Data Efetivado  data (formato BR corrigido)")
    elif 'Criado Em' in df_vendas_unificado.columns:
        df_vendas_unificado['Criado Em'] = fix_datetime_format(df_vendas_unificado['Criado Em'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Criado Em'], format=date_format, errors='coerce')
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Criado Em'])
        logger.debug("  Criado Em  data (formato BR corrigido)")
    elif 'data aprovacao' in df_vendas_unificado.columns:
        df_vendas_unificado['data aprovacao'] = fix_datetime_format(df_vendas_unificado['data aprovacao'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['data aprovacao'], format=date_format, errors='coerce')
        df_vendas_unificado = df_vendas_unificado.drop(columns=['data aprovacao'])
        logger.debug("  data aprovacao  data (formato BR corrigido)")
    elif 'Data Efetivado' in df_vendas_unificado.columns:
        df_vendas_unificado['Data Efetivado'] = fix_datetime_format(df_vendas_unificado['Data Efetivado'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Data Efetivado'], errors='coerce', dayfirst=True)
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Data Efetivado'])
        logger.debug("  Data Efetivado  data (formato BR corrigido)")

    # Unificar telefone
    if 'Telefone' in df_vendas_unificado.columns and 'telefone contato' in df_vendas_unificado.columns:
        df_vendas_unificado['telefone'] = df_vendas_unificado['Telefone'].fillna(df_vendas_unificado['telefone contato'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Telefone', 'telefone contato'])
        logger.debug("  Telefone + telefone contato  telefone")
    elif 'Telefone' in df_vendas_unificado.columns:
        df_vendas_unificado['telefone'] = df_vendas_unificado['Telefone']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Telefone'])
        logger.debug("  Telefone  telefone")
    elif 'telefone contato' in df_vendas_unificado.columns:
        df_vendas_unificado['telefone'] = df_vendas_unificado['telefone contato']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['telefone contato'])
        logger.debug("  telefone contato  telefone")

    # Unificar UTMs (manter as versões 'last' quando disponíveis)
    utms_map = [
        ('utm_last_source', 'utm_source', 'source'),
        ('utm_last_medium', 'utm_medium', 'medium'),
        ('utm_last_campaign', 'utm_campaign', 'campaign'),
        ('utm_last_content', 'utm_content', 'content')
    ]

    for utm_last, utm_regular, utm_final in utms_map:
        if utm_last in df_vendas_unificado.columns and utm_regular in df_vendas_unificado.columns:
            df_vendas_unificado[utm_final] = df_vendas_unificado[utm_last].fillna(df_vendas_unificado[utm_regular])
            df_vendas_unificado = df_vendas_unificado.drop(columns=[utm_last, utm_regular])
            logger.debug(f"  {utm_last} + {utm_regular}  {utm_final}")

    # NORMAL: Resumo com colunas antes/depois
    colunas_depois = len(df_vendas_unificado.columns)
    colunas_unificadas = colunas_antes - colunas_depois

    logger.info(f"  Vendas - Colunas antes: {colunas_antes}, depois: {colunas_depois} (unificadas: {colunas_unificadas})")
    logger.info("")

    return df_vendas_unificado


def aplicar_filtro_temporal(
    df_vendas: pd.DataFrame,
    df_pesquisa: pd.DataFrame
) -> pd.DataFrame:
    """
    CÉLULA 5.1: Filtra vendas para incluir apenas até a data máxima dos leads.

    Args:
        df_vendas: DataFrame de vendas
        df_pesquisa: DataFrame de pesquisa (para calcular data máxima)

    Returns:
        DataFrame de vendas filtrado
    """
    df_vendas_filtrado = df_vendas.copy()

    if 'data' in df_vendas_filtrado.columns and 'Data' in df_pesquisa.columns:
        vendas_antes = len(df_vendas_filtrado)

        # Calcular data máxima REAL dos leads (não hardcoded!)
        df_pesquisa_temp = df_pesquisa.copy()
        df_pesquisa_temp['Data'] = pd.to_datetime(df_pesquisa_temp['Data'], errors='coerce')
        data_max_leads = df_pesquisa_temp['Data'].max()

        # Se não conseguiu calcular, usar data de hoje como fallback
        if pd.isna(data_max_leads):
            data_max_leads = pd.Timestamp.now()
            logger.info(f"  Não foi possível calcular data máxima dos leads, usando hoje: {data_max_leads.strftime('%Y-%m-%d')}")

        df_vendas_filtrado = df_vendas_filtrado[
            (df_vendas_filtrado['data'].isna()) | (df_vendas_filtrado['data'] <= data_max_leads)
        ].copy()
        vendas_depois = len(df_vendas_filtrado)
        vendas_removidas = vendas_antes - vendas_depois

        # DEBUG: Detalhes do filtro temporal
        if vendas_removidas > 0:
            logger.debug("")
            logger.debug(f"Filtro temporal (até {data_max_leads.strftime('%Y-%m-%d')}):")
            logger.debug(f"  Vendas antes: {vendas_antes:,}")
            logger.debug(f"  Vendas após: {vendas_depois:,}")
            logger.debug(f"  Vendas futuras removidas: {vendas_removidas:,}")
            logger.debug(f"  (Data calculada dinamicamente dos leads)")
        else:
            logger.debug("Nenhuma venda futura encontrada (todas dentro do período dos leads)")
    else:
        logger.debug("Filtro temporal não aplicado (colunas de data não encontradas)")

    # NORMAL: Data do filtro e vendas antes/depois
    logger.info(f"  Filtro temporal aplicado: até {data_max_leads.strftime('%Y-%m-%d')}")
    logger.info(f"  Vendas antes: {vendas_antes:,} | Vendas após: {vendas_depois:,}")
    logger.info("")

    return df_vendas_filtrado


def remover_colunas_utm_ausentes(df_vendas: pd.DataFrame) -> pd.DataFrame:
    """
    CÉLULA 5.2: Remove colunas UTM com alta porcentagem de ausentes.

    Args:
        df_vendas: DataFrame de vendas

    Returns:
        DataFrame sem colunas UTM
    """
    df_vendas_sem_utm = df_vendas.copy()
    colunas_antes = len(df_vendas_sem_utm.columns)

    colunas_utm_remover = ['source', 'medium', 'campaign', 'content']
    colunas_existentes_utm = [col for col in colunas_utm_remover if col in df_vendas_sem_utm.columns]

    if colunas_existentes_utm:
        # Calcular % de ausentes de cada coluna ANTES de remover
        missing_info = {}
        for col in colunas_existentes_utm:
            missing_pct = (df_vendas_sem_utm[col].isna().sum() / len(df_vendas_sem_utm)) * 100
            missing_info[col] = missing_pct

        df_vendas_sem_utm = df_vendas_sem_utm.drop(columns=colunas_existentes_utm)

        # NORMAL: Lista de colunas removidas com % ausentes
        logger.info(f"  Colunas removidas (alta % ausentes):")
        for col in colunas_existentes_utm:
            logger.info(f"    - {col}: {missing_info[col]:.1f}% ausentes")
    else:
        logger.info("  Nenhuma coluna UTM encontrada para remover")

    # NORMAL: Colunas antes/depois e resultado final
    colunas_depois = len(df_vendas_sem_utm.columns)
    colunas_removidas = colunas_antes - colunas_depois

    logger.info(f"  Colunas antes: {colunas_antes} | Colunas depois: {colunas_depois} (removidas: {colunas_removidas})")
    logger.info(f"  Vendas: {len(df_vendas_sem_utm)} registros, {colunas_depois} colunas")
    logger.info("")

    return df_vendas_sem_utm


def aplicar_filtro_status_risco(
    df_vendas: pd.DataFrame,
    tmb_risk_filter: str = 'all'
) -> pd.DataFrame:
    """
    CÉLULA 5.3: Filtra vendas por status (Guru) e risco (TMB).

    Args:
        df_vendas: DataFrame de vendas
        tmb_risk_filter: Filtro de risco para alunos TMB
            - 'all': Todos alunos TMB (padrão)
            - 'none': Nenhum aluno TMB (só Guru)
            - 'low': Apenas baixo risco
            - 'low_medium': Baixo + médio risco

    Returns:
        DataFrame de vendas filtrado
    """
    df_vendas_filtrado = df_vendas.copy()

    if 'arquivo_origem' not in df_vendas_filtrado.columns:
        logger.info("Coluna 'arquivo_origem' não encontrada - filtro não aplicado")
        return df_vendas_filtrado

    before = len(df_vendas_filtrado)

    # Identificar vendas Guru e TMB
    is_guru = df_vendas_filtrado['arquivo_origem'].str.lower().str.contains('guru', na=False)
    is_tmb = ~is_guru

    # === FILTRO GURU: Apenas vendas aprovadas ===
    if 'status' in df_vendas_filtrado.columns:
        mask_guru = (is_guru & (df_vendas_filtrado['status'] == 'Aprovada'))
    else:
        mask_guru = is_guru

    # === FILTRO TMB: Por grau de risco ===
    mask_tmb = pd.Series([False] * len(df_vendas_filtrado), index=df_vendas_filtrado.index)

    if tmb_risk_filter == 'none':
        pass  # mask_tmb permanece False
    elif tmb_risk_filter == 'all':
        mask_tmb = is_tmb
    elif 'Grau de risco' in df_vendas_filtrado.columns:
        if tmb_risk_filter == 'low':
            mask_tmb = (is_tmb & (df_vendas_filtrado['Grau de risco'] == 'Baixo'))
        elif tmb_risk_filter == 'low_medium':
            mask_tmb = (is_tmb & df_vendas_filtrado['Grau de risco'].isin(['Baixo', 'Médio']))
        else:
            logger.warning(f"  tmb_risk_filter '{tmb_risk_filter}' inválido, usando 'all'")
            mask_tmb = is_tmb
    else:
        if tmb_risk_filter in ['low', 'low_medium']:
            logger.warning(f"  Coluna 'Grau de risco' não encontrada, mantendo todos TMB")
        mask_tmb = is_tmb

    # Aplicar filtros combinados
    df_vendas_filtrado = df_vendas_filtrado[mask_guru | mask_tmb].copy()
    after = len(df_vendas_filtrado)

    # Calcular estatísticas
    vendas_guru_total = is_guru.sum()
    vendas_guru_mantidas = mask_guru.sum()
    vendas_tmb_total = is_tmb.sum()
    vendas_tmb_mantidas = mask_tmb.sum()

    # NORMAL: Resumo consolidado
    logger.info(f"  GURU: {vendas_guru_mantidas:,} aprovadas (de {vendas_guru_total:,} total)")
    if tmb_risk_filter == 'none':
        logger.info(f"  TMB: 0 mantidas (filtro: nenhum TMB)")
    elif tmb_risk_filter == 'all':
        logger.info(f"  TMB: {vendas_tmb_mantidas:,} mantidas (filtro: todos)")
    else:
        logger.info(f"  TMB: {vendas_tmb_mantidas:,} mantidas (filtro: {tmb_risk_filter.replace('_', ' + ')})")

    # DEBUG: Detalhes completos
    logger.debug("")
    logger.debug(f"Filtro de status e risco (tmb_risk_filter='{tmb_risk_filter}')")
    logger.debug(f"GURU:")
    logger.debug(f"  Total: {vendas_guru_total:,}")
    logger.debug(f"  Aprovadas mantidas: {vendas_guru_mantidas:,}")
    logger.debug(f"  Não aprovadas excluídas: {vendas_guru_total - vendas_guru_mantidas:,}")
    logger.debug("")
    logger.debug(f"TMB:")
    logger.debug(f"  Total: {vendas_tmb_total:,}")

    if tmb_risk_filter == 'none':
        logger.debug(f"  Filtro: NENHUM aluno TMB (só Guru)")
        logger.debug(f"  Mantidas: 0")
        logger.debug(f"  Removidas: {vendas_tmb_total:,}")
    elif tmb_risk_filter == 'all':
        logger.debug(f"  Filtro: TODOS alunos TMB")
        logger.debug(f"  Mantidas: {vendas_tmb_mantidas:,}")
    else:
        logger.debug(f"  Filtro: {tmb_risk_filter.upper().replace('_', ' + ')}")
        if 'Grau de risco' in df_vendas_filtrado.columns:
            df_tmb_subset = df_vendas_filtrado[mask_tmb]
            dist_risco = df_tmb_subset['Grau de risco'].value_counts()
            logger.debug(f"  Mantidas: {vendas_tmb_mantidas:,}")
            logger.debug(f"  Distribuição mantida:")
            for risco, count in dist_risco.items():
                logger.debug(f"    - {risco}: {count:,}")
            logger.debug(f"  Removidas: {vendas_tmb_total - vendas_tmb_mantidas:,}")
        else:
            logger.debug(f"  Mantidas: {vendas_tmb_mantidas:,}")

    logger.info(f"  TOTAL FINAL: {after:,} vendas")
    logger.info("")

    return df_vendas_filtrado


def filtrar_vendas_devclub(df_vendas: pd.DataFrame) -> pd.DataFrame:
    """
    CÉLULA 5.4: Filtra vendas para manter apenas produtos DevClub.

    Args:
        df_vendas: DataFrame de vendas

    Returns:
        DataFrame de vendas filtrado (apenas DevClub)
    """
    df_vendas_devclub = df_vendas.copy()

    if 'produto' not in df_vendas_devclub.columns:
        logger.warning("  Coluna 'produto' não encontrada - filtro não aplicado")
        return df_vendas_devclub

    vendas_antes = len(df_vendas_devclub)

    # Filtrar apenas produtos que contêm "devclub" (case-insensitive)
    mask_devclub = df_vendas_devclub['produto'].fillna('').str.lower().str.contains('devclub', na=False)
    df_vendas_devclub = df_vendas_devclub[mask_devclub].copy()

    vendas_depois = len(df_vendas_devclub)
    vendas_removidas = vendas_antes - vendas_depois

    # Contar produtos únicos DevClub
    produtos_devclub = df_vendas_devclub['produto'].value_counts()

    # NORMAL: Resumo do filtro
    logger.info(f"  Vendas antes: {vendas_antes:,}")
    logger.info(f"  Vendas DevClub: {vendas_depois:,}")
    logger.info(f"  Vendas removidas (outros produtos): {vendas_removidas:,}")
    logger.info(f"  Produtos DevClub únicos: {len(produtos_devclub)}")

    # DEBUG: Top 20 produtos ANTES do filtro (para ver o que tem em TMB)
    logger.debug("")
    logger.debug("TOP 20 PRODUTOS - ANTES DO FILTRO DEVCLUB:")
    logger.debug("-" * 80)
    produtos_antes = df_vendas['produto'].value_counts().head(20)
    for produto, count in produtos_antes.items():
        pct = (count / vendas_antes) * 100
        is_devclub = 'devclub' in str(produto).lower()
        marca = "[DevClub]" if is_devclub else "[Outros] "
        logger.debug(f"  {marca} {str(produto)[:55]:<57} {count:>5,} ({pct:>5.1f}%)")
    logger.debug("-" * 80)

    # DEBUG: Lista de produtos DevClub
    logger.debug("")
    logger.debug("Produtos DevClub encontrados:")
    for produto, count in produtos_devclub.items():
        logger.debug(f"  {produto}: {count:,} vendas")

    # DEBUG: Distribuição por arquivo de origem (ANTES do filtro)
    if 'arquivo_origem' in df_vendas.columns:
        logger.debug("")
        logger.debug("DISTRIBUIÇÃO POR ARQUIVO - ANTES DO FILTRO DEVCLUB:")
        logger.debug("-" * 80)
        vendas_por_arquivo_antes = df_vendas['arquivo_origem'].value_counts()
        for arquivo, count in vendas_por_arquivo_antes.items():
            pct = (count / vendas_antes) * 100
            logger.debug(f"  {arquivo:<50} {count:>6,} vendas ({pct:>5.1f}%)")
        logger.debug("-" * 80)
        logger.debug(f"  TOTAL: {vendas_antes:,} vendas")

    # DEBUG: Distribuição por arquivo de origem (DEPOIS do filtro - apenas DevClub)
    if 'arquivo_origem' in df_vendas_devclub.columns:
        logger.debug("")
        logger.debug("DISTRIBUIÇÃO POR ARQUIVO - VENDAS DEVCLUB:")
        logger.debug("-" * 80)
        vendas_por_arquivo_devclub = df_vendas_devclub['arquivo_origem'].value_counts()
        for arquivo, count in vendas_por_arquivo_devclub.items():
            pct = (count / vendas_depois) * 100
            logger.debug(f"  {arquivo:<50} {count:>6,} vendas ({pct:>5.1f}%)")
        logger.debug("-" * 80)
        logger.debug(f"  TOTAL DEVCLUB: {vendas_depois:,} vendas")
        logger.debug("")

        # Mostrar conversão (quantos % de cada arquivo viraram DevClub)
        logger.debug("TAXA DE CONVERSÃO DEVCLUB POR ARQUIVO:")
        logger.debug("-" * 80)
        for arquivo in vendas_por_arquivo_antes.index:
            antes = vendas_por_arquivo_antes.get(arquivo, 0)
            depois = vendas_por_arquivo_devclub.get(arquivo, 0)
            taxa = (depois / antes * 100) if antes > 0 else 0
            logger.debug(f"  {arquivo:<50} {depois:>6,}/{antes:>6,} ({taxa:>5.1f}%)")
        logger.debug("-" * 80)

    logger.info("")

    return df_vendas_devclub
