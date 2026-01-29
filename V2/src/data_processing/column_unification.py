"""
Módulo para unificação de colunas duplicadas.

Reproduz a célula 5 do notebook DevClub.
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


def unificar_colunas_datasets(
    df_pesquisa: pd.DataFrame,
    df_vendas: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Unifica colunas duplicadas nos datasets de pesquisa e vendas.

    Reproduz a lógica da célula 5 do notebook DevClub.

    Args:
        df_pesquisa: DataFrame de pesquisa
        df_vendas: DataFrame de vendas

    Returns:
        Tupla (df_pesquisa_unificado, df_vendas_unificado)
    """
    # DATASET PESQUISA
    df_pesquisa_unificado = df_pesquisa.copy()

    print("PESQUISA - Colunas duplicadas identificadas:")
    duplicadas_pesquisa = identificar_colunas_duplicadas_pesquisa(df_pesquisa_unificado)

    for col1, col2 in duplicadas_pesquisa:
        print(f"  {col1}")
        print(f"  {col2}")
        print()

    # Unificar colunas duplicadas de pesquisa
    colunas_investiu = [
        'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?',
        'Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro? '
    ]

    if all(col in df_pesquisa_unificado.columns for col in colunas_investiu):
        for i, row_idx in enumerate(df_pesquisa_unificado.index):
            valor_final = None
            for col in colunas_investiu:
                valor = df_pesquisa_unificado.loc[row_idx, col]
                if pd.notna(valor) and valor_final is None:
                    valor_final = valor
            df_pesquisa_unificado.loc[row_idx, 'investiu_curso_online'] = valor_final

        df_pesquisa_unificado = df_pesquisa_unificado.drop(columns=colunas_investiu)

    colunas_atencao = [
        'O que mais te chama atenção na profissão de Programador?',
        'O que mais te chama atenção na profissão de Programador? '
    ]

    if all(col in df_pesquisa_unificado.columns for col in colunas_atencao):
        for i, row_idx in enumerate(df_pesquisa_unificado.index):
            valor_final = None
            for col in colunas_atencao:
                valor = df_pesquisa_unificado.loc[row_idx, col]
                if pd.notna(valor) and valor_final is None:
                    valor_final = valor
            df_pesquisa_unificado.loc[row_idx, 'interesse_programacao'] = valor_final

        df_pesquisa_unificado = df_pesquisa_unificado.drop(columns=colunas_atencao)

    # DATASET VENDAS
    df_vendas_unificado = df_vendas.copy()

    print("VENDAS - Unificando colunas:")

    # Unificar valor
    if 'Ticket (R$)' in df_vendas_unificado.columns and 'valor produtos' in df_vendas_unificado.columns:
        df_vendas_unificado['valor'] = df_vendas_unificado['Ticket (R$)'].fillna(df_vendas_unificado['valor produtos'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Ticket (R$)', 'valor produtos'])
        print("  Ticket (R$) + valor produtos → valor")
    elif 'Ticket (R$)' in df_vendas_unificado.columns:
        df_vendas_unificado['valor'] = df_vendas_unificado['Ticket (R$)']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Ticket (R$)'])
        print("  Ticket (R$) → valor")
    elif 'valor produtos' in df_vendas_unificado.columns:
        df_vendas_unificado['valor'] = df_vendas_unificado['valor produtos']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['valor produtos'])
        print("  valor produtos → valor")

    # Unificar produto
    if 'Produto' in df_vendas_unificado.columns and 'nome produto' in df_vendas_unificado.columns:
        df_vendas_unificado['produto'] = df_vendas_unificado['Produto'].fillna(df_vendas_unificado['nome produto'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Produto', 'nome produto'])
        print("  Produto + nome produto → produto")
    elif 'Produto' in df_vendas_unificado.columns:
        df_vendas_unificado['produto'] = df_vendas_unificado['Produto']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Produto'])
        print("  Produto → produto")
    elif 'nome produto' in df_vendas_unificado.columns:
        df_vendas_unificado['produto'] = df_vendas_unificado['nome produto']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['nome produto'])
        print("  nome produto → produto")

    # Unificar nome
    if 'Cliente Nome' in df_vendas_unificado.columns and 'nome contato' in df_vendas_unificado.columns:
        df_vendas_unificado['nome'] = df_vendas_unificado['Cliente Nome'].fillna(df_vendas_unificado['nome contato'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Cliente Nome', 'nome contato'])
        print("  Cliente Nome + nome contato → nome")
    elif 'Cliente Nome' in df_vendas_unificado.columns:
        df_vendas_unificado['nome'] = df_vendas_unificado['Cliente Nome']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Cliente Nome'])
        print("  Cliente Nome → nome")
    elif 'nome contato' in df_vendas_unificado.columns:
        df_vendas_unificado['nome'] = df_vendas_unificado['nome contato']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['nome contato'])
        print("  nome contato → nome")

    # Unificar email
    if 'Cliente Email' in df_vendas_unificado.columns and 'email contato' in df_vendas_unificado.columns:
        df_vendas_unificado['email'] = df_vendas_unificado['Cliente Email'].fillna(df_vendas_unificado['email contato'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Cliente Email', 'email contato'])
        print("  Cliente Email + email contato → email")
    elif 'Cliente Email' in df_vendas_unificado.columns:
        df_vendas_unificado['email'] = df_vendas_unificado['Cliente Email']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Cliente Email'])
        print("  Cliente Email → email")
    elif 'email contato' in df_vendas_unificado.columns:
        df_vendas_unificado['email'] = df_vendas_unificado['email contato']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['email contato'])
        print("  email contato → email")

    # Unificar data
    # IMPORTANTE: Converter datetime para string formato DD/MM/YYYY e depois re-parsear com dayfirst=True
    # porque pandas lê Excel com formato US por padrão (01/08/2026 vira 01-Aug-2026 ao invés de 08-Jan-2026)
    def fix_datetime_format(col):
        """Converte datetime para string DD/MM/YYYY HH:MM:SS ou mantém NaT"""
        return col.apply(lambda x: x.strftime('%d/%m/%Y %H:%M:%S') if pd.notna(x) and hasattr(x, 'strftime') else x)

    if 'Criado Em' in df_vendas_unificado.columns and 'data aprovacao' in df_vendas_unificado.columns and 'Data Efetivado' in df_vendas_unificado.columns:
        df_vendas_unificado['Criado Em'] = fix_datetime_format(df_vendas_unificado['Criado Em'])
        df_vendas_unificado['data aprovacao'] = fix_datetime_format(df_vendas_unificado['data aprovacao'])
        df_vendas_unificado['Data Efetivado'] = fix_datetime_format(df_vendas_unificado['Data Efetivado'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Criado Em'], errors='coerce', dayfirst=True).fillna(
            pd.to_datetime(df_vendas_unificado['data aprovacao'], errors='coerce', dayfirst=True)).fillna(
            pd.to_datetime(df_vendas_unificado['Data Efetivado'], errors='coerce', dayfirst=True))
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Criado Em', 'data aprovacao', 'Data Efetivado'])
        print("  Criado Em + data aprovacao + Data Efetivado → data (formato BR corrigido)")
    elif 'Criado Em' in df_vendas_unificado.columns and 'data aprovacao' in df_vendas_unificado.columns:
        df_vendas_unificado['Criado Em'] = fix_datetime_format(df_vendas_unificado['Criado Em'])
        df_vendas_unificado['data aprovacao'] = fix_datetime_format(df_vendas_unificado['data aprovacao'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Criado Em'], errors='coerce', dayfirst=True).fillna(
            pd.to_datetime(df_vendas_unificado['data aprovacao'], errors='coerce', dayfirst=True))
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Criado Em', 'data aprovacao'])
        print("  Criado Em + data aprovacao → data (formato BR corrigido)")
    elif 'Criado Em' in df_vendas_unificado.columns and 'Data Efetivado' in df_vendas_unificado.columns:
        df_vendas_unificado['Criado Em'] = fix_datetime_format(df_vendas_unificado['Criado Em'])
        df_vendas_unificado['Data Efetivado'] = fix_datetime_format(df_vendas_unificado['Data Efetivado'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Criado Em'], errors='coerce', dayfirst=True).fillna(
            pd.to_datetime(df_vendas_unificado['Data Efetivado'], errors='coerce', dayfirst=True))
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Criado Em', 'Data Efetivado'])
        print("  Criado Em + Data Efetivado → data (formato BR corrigido)")
    elif 'data aprovacao' in df_vendas_unificado.columns and 'Data Efetivado' in df_vendas_unificado.columns:
        df_vendas_unificado['data aprovacao'] = fix_datetime_format(df_vendas_unificado['data aprovacao'])
        df_vendas_unificado['Data Efetivado'] = fix_datetime_format(df_vendas_unificado['Data Efetivado'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['data aprovacao'], errors='coerce', dayfirst=True).fillna(
            pd.to_datetime(df_vendas_unificado['Data Efetivado'], errors='coerce', dayfirst=True))
        df_vendas_unificado = df_vendas_unificado.drop(columns=['data aprovacao', 'Data Efetivado'])
        print("  data aprovacao + Data Efetivado → data (formato BR corrigido)")
    elif 'Criado Em' in df_vendas_unificado.columns:
        df_vendas_unificado['Criado Em'] = fix_datetime_format(df_vendas_unificado['Criado Em'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Criado Em'], errors='coerce', dayfirst=True)
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Criado Em'])
        print("  Criado Em → data (formato BR corrigido)")
    elif 'data aprovacao' in df_vendas_unificado.columns:
        df_vendas_unificado['data aprovacao'] = fix_datetime_format(df_vendas_unificado['data aprovacao'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['data aprovacao'], errors='coerce', dayfirst=True)
        df_vendas_unificado = df_vendas_unificado.drop(columns=['data aprovacao'])
        print("  data aprovacao → data (formato BR corrigido)")
    elif 'Data Efetivado' in df_vendas_unificado.columns:
        df_vendas_unificado['Data Efetivado'] = fix_datetime_format(df_vendas_unificado['Data Efetivado'])
        df_vendas_unificado['data'] = pd.to_datetime(df_vendas_unificado['Data Efetivado'], errors='coerce', dayfirst=True)
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Data Efetivado'])
        print("  Data Efetivado → data (formato BR corrigido)")

    # Filtrar vendas para incluir apenas até a data máxima dos leads
    # Isso garante que a janela de conversão funcione corretamente
    # IMPORTANTE: Calcular dinamicamente do dataset de pesquisa ao invés de hardcoded
    if 'data' in df_vendas_unificado.columns and 'Data' in df_pesquisa_unificado.columns:
        vendas_antes = len(df_vendas_unificado)

        # Calcular data máxima REAL dos leads (não hardcoded!)
        df_pesquisa_unificado['Data'] = pd.to_datetime(df_pesquisa_unificado['Data'], errors='coerce')
        data_max_leads = df_pesquisa_unificado['Data'].max()

        # Se não conseguiu calcular, usar data de hoje como fallback
        if pd.isna(data_max_leads):
            data_max_leads = pd.Timestamp.now()
            print(f"  ⚠️  Não foi possível calcular data máxima dos leads, usando hoje: {data_max_leads.strftime('%Y-%m-%d')}")

        df_vendas_unificado = df_vendas_unificado[
            (df_vendas_unificado['data'].isna()) | (df_vendas_unificado['data'] <= data_max_leads)
        ].copy()
        vendas_depois = len(df_vendas_unificado)
        vendas_removidas = vendas_antes - vendas_depois
        if vendas_removidas > 0:
            print(f"\nVENDAS - Filtro temporal (até {data_max_leads.strftime('%Y-%m-%d')}):")
            print(f"  Vendas antes do filtro: {vendas_antes:,}")
            print(f"  Vendas após filtro: {vendas_depois:,}")
            print(f"  Vendas futuras removidas: {vendas_removidas:,}")
            print(f"  (Data calculada dinamicamente dos leads carregados)")

    # Unificar telefone
    if 'Telefone' in df_vendas_unificado.columns and 'telefone contato' in df_vendas_unificado.columns:
        df_vendas_unificado['telefone'] = df_vendas_unificado['Telefone'].fillna(df_vendas_unificado['telefone contato'])
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Telefone', 'telefone contato'])
        print("  Telefone + telefone contato → telefone")
    elif 'Telefone' in df_vendas_unificado.columns:
        df_vendas_unificado['telefone'] = df_vendas_unificado['Telefone']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['Telefone'])
        print("  Telefone → telefone")
    elif 'telefone contato' in df_vendas_unificado.columns:
        df_vendas_unificado['telefone'] = df_vendas_unificado['telefone contato']
        df_vendas_unificado = df_vendas_unificado.drop(columns=['telefone contato'])
        print("  telefone contato → telefone")

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
            print(f"  {utm_last} + {utm_regular} → {utm_final}")

    # Remover colunas UTM unificadas com alta porcentagem de ausentes
    print("\nVENDAS - Removendo colunas UTM com alta porcentagem de ausentes:")
    colunas_utm_remover = ['source', 'medium', 'campaign', 'content']
    colunas_existentes_utm = [col for col in colunas_utm_remover if col in df_vendas_unificado.columns]

    if colunas_existentes_utm:
        df_vendas_unificado = df_vendas_unificado.drop(columns=colunas_existentes_utm)
        for col in colunas_existentes_utm:
            print(f"  Removida: {col}")

    # Filtrar apenas vendas GURU aprovadas (TMB não tem coluna status)
    # Excluir vendas canceladas, expiradas, reembolsadas, etc. APENAS dos arquivos Guru
    if 'status' in df_vendas_unificado.columns and 'arquivo_origem' in df_vendas_unificado.columns:
        before = len(df_vendas_unificado)

        # Identificar vendas Guru (têm coluna status) e TMB (não têm)
        is_guru = df_vendas_unificado['arquivo_origem'].str.lower().str.contains('guru', na=False)

        # Filtrar status APENAS das vendas Guru
        mask_guru_aprovada = (is_guru & (df_vendas_unificado['status'] == 'Aprovada'))
        mask_tmb = ~is_guru  # Manter todas as vendas TMB

        df_vendas_unificado = df_vendas_unificado[mask_guru_aprovada | mask_tmb].copy()
        after = len(df_vendas_unificado)

        vendas_guru_antes = is_guru.sum()
        vendas_guru_depois = (mask_guru_aprovada).sum()
        vendas_tmb = mask_tmb.sum()

        if before != after:
            print(f"\nVENDAS - Filtro de status (APENAS Guru):")
            print(f"  Vendas Guru antes do filtro: {vendas_guru_antes:,}")
            print(f"  Vendas Guru aprovadas mantidas: {vendas_guru_depois:,}")
            print(f"  Vendas Guru não aprovadas excluídas: {vendas_guru_antes - vendas_guru_depois:,}")
            print(f"  Vendas TMB mantidas (sem filtro): {vendas_tmb:,}")
            print(f"  Total após filtro: {after:,}")

    logger.info(f"  Pesquisa: {len(df_pesquisa_unificado)} registros, {len(df_pesquisa_unificado.columns)} colunas")
    logger.info(f"  Vendas: {len(df_vendas_unificado)} registros, {len(df_vendas_unificado.columns)} colunas")

    return df_pesquisa_unificado, df_vendas_unificado
