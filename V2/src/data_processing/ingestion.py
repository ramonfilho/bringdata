"""
Módulo de ingestão de dados para lead scoring.

Funções:
- read_excel_files(): Leitura de múltiplos arquivos Excel
- filter_sheets(): Filtragem de abas por critérios configuráveis
- remove_duplicates_per_sheet(): Remoção de duplicatas por aba

Extraído do notebook DevClub e tornado configurável.
"""

import pandas as pd
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def read_excel_files(filepaths: List[str]) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Lê múltiplos arquivos Excel e retorna estrutura organizada.

    Esta função reproduz a lógica das linhas 38-45 do notebook DevClub:
    - Itera sobre múltiplos arquivos Excel
    - Lê todas as abas de cada arquivo
    - Retorna estrutura {filename: {sheet_name: DataFrame}}

    Args:
        filepaths: Lista de caminhos para arquivos Excel (.xlsx ou .xls)

    Returns:
        Dicionário com estrutura:
        {
            'arquivo1.xlsx': {
                'aba1': DataFrame,
                'aba2': DataFrame
            },
            'arquivo2.xlsx': {
                'aba1': DataFrame
            }
        }

    Raises:
        FileNotFoundError: Se algum arquivo não existir
        ValueError: Se a lista de arquivos estiver vazia

    Example:
        >>> files = ['data/LF19.xlsx', 'data/LF20.xlsx']
        >>> data = read_excel_files(files)
        >>> print(data.keys())  # ['LF19.xlsx', 'LF20.xlsx']
    """
    if not filepaths:
        raise ValueError("Lista de arquivos não pode estar vazia")

    # DEBUG: Mensagem de progresso
    logger.debug(f" Lendo {len(filepaths)} arquivo(s) Excel...")

    all_data = {}

    for filepath in filepaths:
        # Verificar se arquivo existe
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

        filename = Path(filepath).name
        logger.debug(f"  Processando: {filename}")

        try:
            # Ler arquivo Excel
            xl_file = pd.ExcelFile(filepath)
            file_data = {}

            # Ler todas as abas
            for sheet_name in xl_file.sheet_names:
                df = pd.read_excel(xl_file, sheet_name=sheet_name)

                # TRATAMENTO ESPECIAL: Arquivo TMB com parcelas (detectar por colunas)
                # Detecta se é o arquivo de contas a receber pela presença de colunas específicas
                is_tmb_parcelas = (
                    'Pedido' in df.columns and
                    'Parcela' in df.columns and
                    'Grau de risco' in df.columns
                )

                if is_tmb_parcelas:
                    logger.debug(f"     Detectado arquivo TMB com parcelas: {filename}")
                    logger.debug(f"       Registros totais (parcelas): {len(df):,}")

                    # Agregar por pedido único
                    if 'Pedido' in df.columns:
                        # ETAPA 1: Filtrar apenas pedidos EFETIVADOS (antes de agregar)
                        # Remove parcelas de pedidos cancelados
                        if 'Status Pedido' in df.columns:
                            total_parcelas_antes = len(df)
                            pedidos_antes = df['Pedido'].nunique()
                            df_efetivado = df[df['Status Pedido'] == 'Efetivado'].copy()
                            parcelas_removidas = total_parcelas_antes - len(df_efetivado)
                            pedidos_cancelados = pedidos_antes - df_efetivado['Pedido'].nunique()

                            if parcelas_removidas > 0:
                                logger.debug(f"         Removidas {parcelas_removidas:,} parcelas de {pedidos_cancelados:,} pedidos cancelados")

                            df = df_efetivado

                        # ETAPA 2: Detectar coluna de risco (variações de nome)
                        coluna_risco = None
                        for possivel_nome in ['Grau de risco', 'Grau de Risco', 'grau de risco', 'risco', 'Risco']:
                            if possivel_nome in df.columns:
                                coluna_risco = possivel_nome
                                logger.debug(f"         Coluna de risco detectada: '{coluna_risco}'")
                                break

                        # ETAPA 3: Agregar por Pedido único (pegar primeira linha de cada pedido)
                        # Todas as parcelas de um pedido têm o mesmo risco, então .first() é suficiente
                        df_agregado = df.groupby('Pedido', as_index=False).first()

                        logger.debug(f"        Agregado: {len(df_agregado):,} pedidos únicos (de {len(df):,} parcelas)")

                        # ETAPA 4: Renomear colunas para formato esperado pelo pipeline
                        rename_map = {
                            'Cliente E-mail': 'Cliente Email',
                            'Ticket': 'Ticket (R$)',
                            'Lançamento': 'nome produto'  # TMB: Lançamento contém nome do produto
                        }
                        df_agregado = df_agregado.rename(columns=rename_map)

                        # ETAPA 5: Verificar e reportar distribuição de risco
                        if coluna_risco and coluna_risco in df_agregado.columns:
                            dist_risco = df_agregado[coluna_risco].value_counts(dropna=False)
                            logger.debug(f"        Distribuição de risco ({len(df_agregado):,} pedidos):")
                            for risco, count in dist_risco.items():
                                pct = (count / len(df_agregado)) * 100
                                risco_display = 'Sem Classificação' if str(risco).strip() == '-' else str(risco)
                                logger.debug(f"          {risco_display}: {count:,} pedidos ({pct:.1f}%)")
                        else:
                            logger.warning(f"        ⚠️  Coluna de risco não encontrada no arquivo TMB!")

                        df = df_agregado
                    else:
                        logger.warning(f"      Coluna 'Pedido' não encontrada, usando dados como estão")

                file_data[sheet_name] = df
                logger.debug(f"     Aba '{sheet_name}': {len(df)} linhas, {len(df.columns)} colunas")

            all_data[filename] = file_data
            logger.debug(f"    Total: {len(file_data)} aba(s) lida(s)")

        except Exception as e:
            logger.error(f"     Erro ao ler {filename}: {e}")
            raise

    # DEBUG: Total já mostrado no train_pipeline.py
    logger.debug(f" Total de arquivos lidos: {len(all_data)}")

    return all_data


def filter_sheets(
    files_data: Dict[str, Dict[str, pd.DataFrame]],
    termos_manter: List[str],
    termos_remover: List[str],
    min_linhas: int
) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], List[Dict]]:
    """
    Filtra abas de múltiplos arquivos Excel baseado em critérios configuráveis.

    Reproduz a lógica de filtragem das linhas 48-59 do notebook DevClub.

    Args:
        files_data: Dicionário {filename: {sheet_name: DataFrame}}
        termos_manter: Lista de termos que as abas devem conter para serem mantidas
        termos_remover: Lista de termos que, se presentes, fazem a aba ser removida
        min_linhas: Número mínimo de linhas para manter uma aba

    Returns:
        Tupla (arquivos_filtrados, relatório):
        - arquivos_filtrados: Dict com abas que passaram nos critérios
        - relatório: Lista de dicts com informações sobre cada aba (mantida ou removida)

    Example:
        >>> filtered, report = filter_sheets(
        ...     data,
        ...     termos_manter=["Pesquisa", "Vendas"],
        ...     termos_remover=["Pontuação", "Lead Score"],
        ...     min_linhas=230
        ... )
    """
    # DEBUG: Mensagem de progresso
    logger.debug(" Filtrando abas por critérios...")

    arquivos_filtrados = {}
    relatorio = []

    for filename, sheets in files_data.items():
        abas_filtradas = {}

        for sheet_name, df in sheets.items():
            linhas_original = len(df)

            # APLICAR CRITÉRIOS DE FILTRAGEM (linhas 48-59 do notebook)
            deve_remover_por_termo = any(termo.lower() in sheet_name.lower() for termo in termos_remover)
            tem_termo_permitido = any(termo.lower() in sheet_name.lower() for termo in termos_manter)
            tem_linhas_suficientes = len(df) >= min_linhas
            nao_esta_vazia = len(df) > 0 and not df.empty

            # Critério específico DevClub: remover abas TMB/Guru de arquivos LF (exceto LF06)
            eh_lf_com_vendas = (
                'LF' in filename and
                any(vendas_termo.lower() in sheet_name.lower() for vendas_termo in ['tmb', 'guru']) and
                'LF06' not in filename
            )

            # Decidir se mantém a aba
            if (nao_esta_vazia and not deve_remover_por_termo and not eh_lf_com_vendas and
                (tem_termo_permitido or tem_linhas_suficientes)):

                # Aba MANTIDA
                abas_filtradas[sheet_name] = df

                relatorio.append({
                    'arquivo': filename,
                    'aba': sheet_name,
                    'linhas_original': linhas_original,
                    'status': 'MANTIDA'
                })
                logger.debug(f"   {filename} - {sheet_name}: {linhas_original:,} linhas (MANTIDA)")

            else:
                # Aba REMOVIDA
                relatorio.append({
                    'arquivo': filename,
                    'aba': sheet_name,
                    'linhas_original': linhas_original,
                    'status': 'REMOVIDA'
                })
                logger.debug(f"   {filename} - {sheet_name}: removida pelos critérios")

        # Salvar arquivo se tiver abas válidas
        if abas_filtradas:
            arquivos_filtrados[filename] = abas_filtradas

    abas_mantidas = sum(1 for item in relatorio if item['status'] == 'MANTIDA')
    abas_removidas = len(relatorio) - abas_mantidas

    # DEBUG: Informações parciais (serão mostradas no resumo final)
    logger.debug(f"  Abas mantidas: {abas_mantidas}")
    logger.debug(f"  Abas removidas: {abas_removidas}")

    return arquivos_filtrados, relatorio


def remove_duplicates_per_sheet(
    files_data: Dict[str, Dict[str, pd.DataFrame]]
) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], Dict[str, Dict[str, int]]]:
    """
    Remove duplicatas de cada aba de cada arquivo.

    Reproduz a lógica da linha 62 do notebook DevClub.

    Args:
        files_data: Dicionário {filename: {sheet_name: DataFrame}}

    Returns:
        Tupla (arquivos_limpos, estatísticas):
        - arquivos_limpos: Dict com DataFrames sem duplicatas
        - estatísticas: Dict {filename: {sheet_name: duplicatas_removidas}}

    Example:
        >>> clean_data, stats = remove_duplicates_per_sheet(data)
    """
    # DEBUG: Mensagem de progresso
    logger.debug(" Removendo duplicatas...")

    arquivos_limpos = {}
    estatisticas = {}

    for filename, sheets in files_data.items():
        abas_limpas = {}
        stats_arquivo = {}

        for sheet_name, df in sheets.items():
            linhas_antes = len(df)

            # REMOVER DUPLICATAS (linha 62 do notebook)
            df_limpo = df.drop_duplicates(keep='first')
            linhas_depois = len(df_limpo)
            duplicatas_removidas = linhas_antes - linhas_depois

            abas_limpas[sheet_name] = df_limpo
            stats_arquivo[sheet_name] = duplicatas_removidas

            if duplicatas_removidas > 0:
                logger.debug(f"  {filename} - {sheet_name}: {duplicatas_removidas} duplicatas removidas")

        arquivos_limpos[filename] = abas_limpas
        estatisticas[filename] = stats_arquivo

    total_duplicatas = sum(sum(stats.values()) for stats in estatisticas.values())
    # DEBUG: Informação parcial (será mostrada no resumo final)
    logger.debug(f"  Total de duplicatas removidas: {total_duplicatas:,}")

    return arquivos_limpos, estatisticas


def remove_unnecessary_columns(
    files_data: Dict[str, Dict[str, pd.DataFrame]],
    colunas_remover: List[str]
) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], List[Dict]]:
    """
    Remove colunas desnecessárias de todos os arquivos.

    Reproduz a lógica da célula 3 do notebook (linhas 174-214 do v3-5).

    Args:
        files_data: Dicionário {filename: {sheet_name: DataFrame}}
        colunas_remover: Lista de nomes de colunas para remover

    Returns:
        Tupla (arquivos_limpos, relatório):
        - arquivos_limpos: Dict com DataFrames sem colunas desnecessárias
        - relatório: Lista de dicts com estatísticas de remoção por aba

    Example:
        >>> clean_data, report = remove_unnecessary_columns(
        ...     data,
        ...     colunas_remover=["CEP", "Bairro", "Status"]
        ... )
    """
    # DEBUG: Mensagem de progresso
    logger.debug(" Removendo colunas desnecessárias...")

    colunas_remover_lower = [col.lower() for col in colunas_remover]

    # Prefixos de colunas de score/faixa que devem ser removidas (incluindo variantes com sufixo)
    score_prefixes = ['score', 'faixa', 'pontuação', 'pontuacao', 'lead_score', 'decil']

    arquivos_limpos = {}
    relatorio = []

    for arquivo, abas_dict in files_data.items():
        abas_limpas = {}

        for aba_nome, df in abas_dict.items():
            colunas_antes = len(df.columns)

            # Identificar colunas para remover (linhas 189-196 do notebook)
            colunas_para_remover = []
            for col in df.columns:
                col_lower = str(col).lower()
                # Remover se está na lista exata
                if col_lower in colunas_remover_lower:
                    colunas_para_remover.append(col)
                # Remover colunas Unnamed
                elif str(col).startswith('Unnamed:'):
                    colunas_para_remover.append(col)
                # Remover qualquer coluna que comece com prefixos de score/faixa
                elif any(col_lower.startswith(prefix) for prefix in score_prefixes):
                    colunas_para_remover.append(col)
                # NÃO remover colunas vazias aqui - será feito na célula 8
                # Mantendo compatibilidade com notebook

            # Aplicar remoção (linha 199)
            df_limpo = df.drop(columns=colunas_para_remover) if colunas_para_remover else df.copy()
            abas_limpas[aba_nome] = df_limpo

            # Relatório (linhas 202-210)
            colunas_depois = len(df_limpo.columns)
            relatorio.append({
                'arquivo': arquivo,
                'aba': aba_nome,
                'colunas_antes': colunas_antes,
                'colunas_depois': colunas_depois,
                'removidas': len(colunas_para_remover)
            })

            if colunas_para_remover:
                logger.debug(f"  {arquivo} - {aba_nome}: {len(colunas_para_remover)} colunas removidas")

        arquivos_limpos[arquivo] = abas_limpas

    total_removidas = sum(item['removidas'] for item in relatorio)
    # DEBUG: Informação parcial (será mostrada no resumo final)
    logger.debug(f"  Total de colunas removidas: {total_removidas}")

    return arquivos_limpos, relatorio


def consolidate_datasets(
    files_data: Dict[str, Dict[str, pd.DataFrame]],
    pesquisa_keywords: List[str],
    vendas_keywords: List[str]
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Consolida arquivos separando em datasets de pesquisa e vendas.

    Reproduz a lógica da célula 4 do notebook (linhas 258-281 do v3-5).

    Args:
        files_data: Dicionário {filename: {sheet_name: DataFrame}}
        pesquisa_keywords: Termos que identificam abas de pesquisa
        vendas_keywords: Termos que identificam abas de vendas

    Returns:
        Tupla (df_pesquisa_consolidado, df_vendas_consolidado):
        - df_pesquisa: DataFrame consolidado de pesquisa
        - df_vendas: DataFrame consolidado de vendas
        
        Ambos incluem colunas 'arquivo_origem' e 'aba_origem'

    Example:
        >>> df_pesq, df_vend = consolidate_datasets(
        ...     data,
        ...     pesquisa_keywords=["pesquisa"],
        ...     vendas_keywords=["vendas", "sheet1"]
        ... )
    """
    # DEBUG: Mensagem de progresso
    logger.debug(" Consolidando datasets (Pesquisa e Vendas)...")

    dados_pesquisa = []
    dados_vendas = []

    # Classificar e adicionar metadata (linhas 265-275 do notebook)
    for arquivo, abas_dict in files_data.items():
        for aba_nome, df in abas_dict.items():
            df_copia = df.copy()
            df_copia['arquivo_origem'] = arquivo
            df_copia['aba_origem'] = aba_nome

            # Classificar por tipo
            if any(termo in aba_nome.lower() for termo in pesquisa_keywords):
                dados_pesquisa.append(df_copia)
            elif any(termo in aba_nome.lower() for termo in vendas_keywords):
                dados_vendas.append(df_copia)

    # Consolidar em DataFrames únicos (linhas 278-279)
    df_pesquisa_consolidado = pd.concat(dados_pesquisa, ignore_index=True) if dados_pesquisa else pd.DataFrame()
    df_vendas_consolidado = pd.concat(dados_vendas, ignore_index=True) if dados_vendas else pd.DataFrame()

    # DEBUG: Informações parciais (serão mostradas no resumo final)
    logger.debug(f"  Dataset Pesquisa: {len(df_pesquisa_consolidado):,} registros, {len(df_pesquisa_consolidado.columns)} colunas")
    logger.debug(f"  Dataset Vendas: {len(df_vendas_consolidado):,} registros, {len(df_vendas_consolidado.columns)} colunas")

    return df_pesquisa_consolidado, df_vendas_consolidado


def read_all_training_sources(
    filepaths: List[str],
    include_api_data: bool = False,
    api_start_date: str = None,
    api_end_date: str = None,
    num_sheets_api: int = 1
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Lê dados de treino de TODAS as fontes: arquivos locais + API/Sheets (opcional).

    Esta função é usada pelo pipeline de retreino para combinar dados históricos
    (arquivos Excel locais) com dados novos (Google Sheets + API Guru).

    Fluxo:
    1. Lê arquivos Excel locais (sempre)
    2. Se include_api_data=True:
       - Busca leads do Google Sheets (apenas aba 0 para retreino)
       - Busca vendas da API Guru
       - Converte para formato dict e adiciona aos dados locais

    Args:
        filepaths: Lista de caminhos para arquivos Excel locais
        include_api_data: Se True, busca dados adicionais de API/Sheets
        api_start_date: Data início para buscar dados da API (formato: YYYY-MM-DD)
        api_end_date: Data fim para buscar dados da API (formato: YYYY-MM-DD)
        num_sheets_api: Número de abas do Sheets para carregar (default: 1 para retreino)

    Returns:
        Dicionário no mesmo formato que read_excel_files():
        {
            'arquivo1.xlsx': {'aba1': DataFrame, ...},
            '[API] Leads Google Sheets': {'Pesquisa': DataFrame},
            '[API] Vendas Guru': {'Vendas': DataFrame}
        }

    Example:
        >>> # Treino normal (só arquivos locais)
        >>> data = read_all_training_sources(filepaths)

        >>> # Retreino (arquivos + API)
        >>> data = read_all_training_sources(
        ...     filepaths,
        ...     include_api_data=True,
        ...     api_start_date='2025-12-01',
        ...     api_end_date='2026-01-28'
        ... )
    """
    # 1. LER ARQUIVOS LOCAIS (comportamento padrão)
    logger.debug(" INGESTÃO DE DADOS DE TREINO")

    local_data = read_excel_files(filepaths)

    # 2. SE RETREINO, BUSCAR DADOS DA API
    if not include_api_data:
        return local_data

    # DEBUG: Buscando dados adicionais
    logger.debug("")
    logger.debug(" BUSCANDO DADOS ADICIONAIS (API/Sheets)")
    logger.debug("-" * 60)

    if not api_start_date or not api_end_date:
        logger.warning("  Datas da API não fornecidas, pulando ingestão API")
        return local_data

    try:
        # Importar loaders
        from src.validation.data_loader import LeadDataLoader, SalesDataLoader

        api_data = {}

        # === LEADS DO GOOGLE SHEETS ===
        logger.info("\n 1/2: Leads do Google Sheets")
        try:
            lead_loader = LeadDataLoader()
            sheets_df = lead_loader.load_leads_from_sheets(
                sheets_url=None,  # Usa default ou env var
                start_date=api_start_date,
                end_date=api_end_date,
                use_cache=False,  # Sempre buscar dados frescos no retreino
                num_sheets=num_sheets_api  # Retreino: apenas aba 0
            )

            if not sheets_df.empty:
                # Converter para formato esperado: {filename: {sheetname: DataFrame}}
                # Renomear colunas para formato do notebook
                sheets_formatted = pd.DataFrame()
                sheets_formatted['E-mail'] = sheets_df['email']
                sheets_formatted['Nome Completo'] = sheets_df.get('nome', '')
                sheets_formatted['Telefone'] = sheets_df.get('telefone', '')
                sheets_formatted['Data'] = sheets_df['data_captura']
                sheets_formatted['Campaign'] = sheets_df['campaign']
                sheets_formatted['Source'] = sheets_df.get('source', '')
                sheets_formatted['Medium'] = sheets_df.get('medium', '')
                sheets_formatted['Term'] = sheets_df.get('term', '')
                sheets_formatted['Content'] = sheets_df.get('content', '')
                sheets_formatted['lead_score'] = sheets_df.get('lead_score', None)

                # Colunas demográficas (perguntas do formulário)
                sheets_formatted['O seu gênero:'] = sheets_df.get('genero', None)
                sheets_formatted['Qual a sua idade?'] = sheets_df.get('idade', None)
                sheets_formatted['O que você faz atualmente?'] = sheets_df.get('ocupacao', None)
                sheets_formatted['Atualmente, qual a sua faixa salar'] = sheets_df.get('faixa_salarial', None)
                sheets_formatted['Você possui cartão de crédito?'] = sheets_df.get('cartao_credito', None)
                sheets_formatted['O que mais você quer ver no evento?'] = sheets_df.get('interesse_evento', None)
                sheets_formatted['Tem computador/notebook?'] = sheets_df.get('tem_computador', None)
                sheets_formatted['Já estudou programação?'] = sheets_df.get('estudou_programacao', None)
                sheets_formatted['Você já fez/faz/pretende fazer faculdade?'] = sheets_df.get('pretende_faculdade', None)
                # Usar nomes completos para ser consistente com arquivos locais (column_unification.py fará a unificação)
                sheets_formatted['Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?'] = sheets_df.get('investiu_curso_online', None)
                sheets_formatted['O que mais te chama atenção na profissão de Programador?'] = sheets_df.get('interesse_programacao', None)

                api_data['[API] Leads Google Sheets'] = {
                    '[LF] Pesquisa - API': sheets_formatted
                }
                # Resumo já mostrado por load_leads_from_sheets()
            else:
                logger.warning("     Nenhum lead encontrado no Sheets")

        except Exception as e:
            logger.error(f"    Erro ao buscar leads do Sheets: {e}")

        # === VENDAS DA API GURU ===
        logger.info("\n 2/2: Vendas da API Guru")
        try:
            sales_loader = SalesDataLoader()
            guru_df = sales_loader.load_guru_sales_from_api(
                start_date=api_start_date,
                end_date=api_end_date,
                save_excel=False
            )

            if not guru_df.empty:
                # Converter para formato esperado
                guru_formatted = pd.DataFrame()
                guru_formatted['email'] = guru_df['email']
                guru_formatted['nome'] = guru_df.get('nome', '')
                guru_formatted['telefone'] = guru_df.get('telefone', '')
                guru_formatted['data'] = guru_df['sale_date']
                guru_formatted['valor'] = guru_df['sale_value']
                guru_formatted['utm_campaign'] = guru_df.get('utm_campaign', '')
                guru_formatted['produto'] = 'DevClub'  # Produto padrão
                guru_formatted['status'] = guru_df.get('status', 'Aprovada')  # Status para filtro (já pré-filtrado pela API)
                guru_formatted['arquivo_origem'] = '[API] Guru'

                api_data['[API] Vendas Guru'] = {
                    'Sheet1': guru_formatted
                }
                # Resumo já mostrado por load_guru_sales_from_api() com detalhes de filtros
            else:
                logger.warning("     Nenhuma venda encontrada na API Guru")

        except Exception as e:
            logger.error(f"    Erro ao buscar vendas da API Guru: {e}")

        # 3. COMBINAR DADOS LOCAIS + API
        if api_data:
            logger.info("\n COMBINANDO DADOS")
            logger.info("-" * 60)
            logger.info(f"   Arquivos locais: {len(local_data)}")
            logger.info(f"   Fontes API: {len(api_data)}")

            combined_data = {**local_data, **api_data}

            logger.info(f"    Total combinado: {len(combined_data)} fontes de dados")

            return combined_data
        else:
            logger.warning("\n  Nenhum dado da API foi carregado")
            logger.info("   Usando apenas arquivos locais")
            return local_data

    except Exception as e:
        logger.error(f"\n Erro ao buscar dados da API: {e}")
        logger.info("   Fallback: usando apenas arquivos locais")
        return local_data
