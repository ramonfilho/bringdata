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

    logger.info(f"📂 Lendo {len(filepaths)} arquivo(s) Excel...")

    all_data = {}

    for filepath in filepaths:
        # Verificar se arquivo existe
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

        filename = Path(filepath).name
        logger.info(f"  Processando: {filename}")

        try:
            # Ler arquivo Excel
            xl_file = pd.ExcelFile(filepath)
            file_data = {}

            # Ler todas as abas
            for sheet_name in xl_file.sheet_names:
                df = pd.read_excel(xl_file, sheet_name=sheet_name)
                file_data[sheet_name] = df
                logger.debug(f"    ✅ Aba '{sheet_name}': {len(df)} linhas, {len(df.columns)} colunas")

            all_data[filename] = file_data
            logger.info(f"    Total: {len(file_data)} aba(s) lida(s)")

        except Exception as e:
            logger.error(f"    ❌ Erro ao ler {filename}: {e}")
            raise

    logger.info(f"✅ Total de arquivos lidos: {len(all_data)}")

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
    logger.info("🔍 Filtrando abas por critérios...")

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
                logger.debug(f"  ✅ {filename} - {sheet_name}: {linhas_original:,} linhas (MANTIDA)")

            else:
                # Aba REMOVIDA
                relatorio.append({
                    'arquivo': filename,
                    'aba': sheet_name,
                    'linhas_original': linhas_original,
                    'status': 'REMOVIDA'
                })
                logger.debug(f"  ❌ {filename} - {sheet_name}: removida pelos critérios")

        # Salvar arquivo se tiver abas válidas
        if abas_filtradas:
            arquivos_filtrados[filename] = abas_filtradas

    abas_mantidas = sum(1 for item in relatorio if item['status'] == 'MANTIDA')
    abas_removidas = len(relatorio) - abas_mantidas

    logger.info(f"  Abas mantidas: {abas_mantidas}")
    logger.info(f"  Abas removidas: {abas_removidas}")

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
    logger.info("🧹 Removendo duplicatas...")

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
    logger.info(f"  Total de duplicatas removidas: {total_duplicatas:,}")

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
    logger.info("🧹 Removendo colunas desnecessárias...")

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
    logger.info(f"  Total de colunas removidas: {total_removidas}")

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
    logger.info("🔗 Consolidando datasets (Pesquisa e Vendas)...")

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

    logger.info(f"  Dataset Pesquisa: {len(df_pesquisa_consolidado):,} registros, {len(df_pesquisa_consolidado.columns)} colunas")
    logger.info(f"  Dataset Vendas: {len(df_vendas_consolidado):,} registros, {len(df_vendas_consolidado.columns)} colunas")

    return df_pesquisa_consolidado, df_vendas_consolidado
