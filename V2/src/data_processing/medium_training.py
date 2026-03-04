"""
Módulo para unificação de UTM Medium com extração de públicos - PIPELINE DE TREINO.

Reproduz a célula 11 do notebook DevClub.
NÃO confundir com medium_unification.py (pipeline de produção).
"""

import pandas as pd
import re
import logging

logger = logging.getLogger(__name__)


def extrair_publico_medium(df_pesquisa: pd.DataFrame):
    """
    Extrai e unifica tipos de público da coluna Medium.

    Reproduz a lógica da célula 11 do notebook DevClub.

    Args:
        df_pesquisa: DataFrame de pesquisa

    Returns:
        Tuple (df, n_apos_extracao): DataFrame com Medium unificado e
        número de valores únicos após extração (antes da normalização de escrita)
    """
    df = df_pesquisa.copy()

    if 'Medium' not in df.columns:
        logger.info("Coluna 'Medium' não encontrada")
        return df, 0

    n_bruto = df['Medium'].nunique()

    # DEBUG: exemplos antes da extração
    logger.debug("")
    logger.debug("Exemplos antes da extração:")
    exemplos_antes = df['Medium'].value_counts().head(10)
    for valor, count in exemplos_antes.items():
        if pd.notna(valor):
            logger.debug(f"  {str(valor)[:70]:<72} ({count:,})")

    # Função para extrair público (remove prefixo 'ADV |')
    def extrair_publico(medium_value):
        if pd.isna(medium_value):
            return medium_value

        medium_str = str(medium_value).strip()

        if '|' in medium_str:
            partes = medium_str.split('|')
            if len(partes) >= 2:
                if partes[0].strip().upper() in ['ADV', 'ADV ']:
                    publico = partes[1].strip()
                else:
                    publico = partes[0].strip()
            else:
                publico = medium_str
        else:
            publico = medium_str

        if publico.upper().strip() == 'ADV':
            if '|' in medium_str:
                publico = medium_str.split('|', 1)[1].strip()

        return publico

    # Passo 1 — Extração
    logger.info(f"  Passo 1 — Extração do nome do público (remoção de prefixo 'ADV |')")
    df['Medium'] = df['Medium'].apply(extrair_publico)
    n_apos_extracao = df['Medium'].nunique()
    logger.info(f"    {n_bruto} → {n_apos_extracao} valores únicos")

    # DEBUG: distribuição após extração
    logger.debug("")
    logger.debug("Distribuição após extração inicial (top 15):")
    medium_apos_extracao_vc = df['Medium'].value_counts(dropna=False)
    for i, (valor, count) in enumerate(medium_apos_extracao_vc.head(15).items(), 1):
        pct = count / len(df) * 100
        valor_str = str(valor) if pd.notna(valor) else 'nan'
        logger.debug(f"{i:2d}. {valor_str[:60]:<62} {count:>6,} ({pct:>5.1f}%)")

    # Passo 2 — Normalização de variantes de escrita
    logger.info(f"  Passo 2 — Normalização de variantes de escrita")
    logger.debug("")
    logger.debug("Identificando públicos similares para unificação...")

    valores_medium = df['Medium'].dropna().unique()
    grupos_similares = {}
    processados = set()

    def normalizar_para_comparacao(texto):
        if pd.isna(texto):
            return ""
        texto_norm = str(texto).lower().strip()
        texto_norm = re.sub(r'\s+', ' ', texto_norm)
        texto_norm = texto_norm.rstrip('.')
        return texto_norm

    for valor in valores_medium:
        if valor in processados:
            continue
        valor_norm = normalizar_para_comparacao(valor)
        grupo = [valor]
        for outro_valor in valores_medium:
            if outro_valor != valor and outro_valor not in processados:
                outro_norm = normalizar_para_comparacao(outro_valor)
                if valor_norm == outro_norm:
                    grupo.append(outro_valor)
                    processados.add(outro_valor)
        if len(grupo) > 1:
            contagens = [(v, (df['Medium'] == v).sum()) for v in grupo]
            representante = max(contagens, key=lambda x: x[1])[0]
            grupos_similares[representante] = grupo
        processados.add(valor)

    if grupos_similares:
        logger.debug("")
        logger.debug("Grupos similares encontrados para unificação:")
        for representante, grupo in grupos_similares.items():
            if len(grupo) > 1:
                count_total = sum((df['Medium'] == v).sum() for v in grupo)
                logger.debug(f"\nUnificando em: '{representante}' ({count_total:,} registros)")
                for valor in grupo:
                    if valor != representante:
                        count_individual = (df['Medium'] == valor).sum()
                        logger.debug(f"  '{valor}' ({count_individual:,})")
                        df.loc[df['Medium'] == valor, 'Medium'] = representante
    else:
        logger.debug("Nenhum grupo similar detectado automaticamente")

    unificacoes_manuais = {
        'ABERTO': 'Aberto',
        'MIX QUENTE': 'Mix Quente',
    }

    unificacoes_aplicadas = []
    for original, unificado in unificacoes_manuais.items():
        if original in df['Medium'].values:
            count = (df['Medium'] == original).sum()
            df.loc[df['Medium'] == original, 'Medium'] = unificado
            unificacoes_aplicadas.append(f"'{original}' → '{unificado}' ({count:,})")
            logger.debug(f"  '{original}' → '{unificado}' ({count:,} registros)")

    n_apos_norm = df['Medium'].nunique()
    logger.info(f"    {n_apos_extracao} → {n_apos_norm} valores únicos")
    if unificacoes_aplicadas:
        logger.info(f"    Unificações: {', '.join(unificacoes_aplicadas)}")

    # Relatório detalhado dos 58 públicos (apenas no nível debug)
    relatorio_final_medium(df)

    return df, n_apos_extracao


def relatorio_final_medium(df: pd.DataFrame):
    """
    Gera relatório final da coluna Medium após unificação.

    Args:
        df: DataFrame com Medium unificado
    """
    # DEBUG: Relatório detalhado completo
    logger.debug("")
    logger.debug("RELATÓRIO FINAL - MEDIUM (PÚBLICOS)")

    if 'Medium' not in df.columns:
        logger.debug("Coluna Medium não encontrada")
        return

    total_registros = len(df)
    medium_validos = df['Medium'].notna().sum()
    medium_nulos = df['Medium'].isna().sum()
    valores_unicos = df['Medium'].nunique()

    logger.debug(f"Total de registros: {total_registros:,}")
    logger.debug(f"Medium válidos: {medium_validos:,} ({medium_validos/total_registros*100:.1f}%)")
    logger.debug(f"Medium nulos: {medium_nulos:,} ({medium_nulos/total_registros*100:.1f}%)")
    logger.debug(f"Públicos únicos: {valores_unicos}")

    logger.debug("")
    logger.debug("Distribuição final dos públicos:")
    logger.debug("-" * 80)
    logger.debug(f"{'#':<3} {'PÚBLICO':<55} {'COUNT':<8} {'%':<6}")
    logger.debug("-" * 80)

    medium_final = df['Medium'].value_counts(dropna=False)

    for i, (valor, count) in enumerate(medium_final.items(), 1):
        pct = count / total_registros * 100
        valor_str = str(valor) if pd.notna(valor) else 'nan'

        # Truncar se muito longo
        if len(valor_str) > 52:
            valor_display = valor_str[:49] + '...'
        else:
            valor_display = valor_str

        logger.debug(f"{i:<3} {valor_display:<55} {count:<8,} {pct:<6.1f}%")



def exportar_categorias_medium(df: pd.DataFrame, arquivo_csv: str = 'categorias_medium_publicos.csv'):
    """
    Exporta categorias Medium para CSV.

    Args:
        df: DataFrame com Medium unificado
        arquivo_csv: Nome do arquivo CSV de saída
    """
    # DEBUG: Exportação é detalhe técnico
    logger.debug("")
    logger.debug("EXPORTAÇÃO DAS CATEGORIAS MEDIUM")

    # Criar DataFrame com todas as categorias e suas estatísticas
    medium_stats = df['Medium'].value_counts(dropna=False)
    total_registros = len(df)

    categorias_data = []
    for i, (categoria, count) in enumerate(medium_stats.items(), 1):
        pct = (count / total_registros) * 100
        categoria_str = str(categoria) if pd.notna(categoria) else 'NaN'

        categorias_data.append({
            'rank': i,
            'categoria_medium': categoria_str,
            'quantidade': count,
            'percentual': round(pct, 2)
        })

    # Converter para DataFrame
    df_categorias = pd.DataFrame(categorias_data)

    try:
        # Exportar para CSV
        df_categorias.to_csv(arquivo_csv, index=False, encoding='utf-8')

        logger.debug("Arquivo exportado com sucesso:")
        logger.debug(f"  Nome: {arquivo_csv}")
        logger.debug(f"  Total de categorias: {len(df_categorias)}")
        logger.debug(f"  Colunas: rank, categoria_medium, quantidade, percentual")

        # Mostrar prévia do arquivo
        logger.debug("")
        logger.debug("Prévia do arquivo CSV (primeiras 10 linhas):")
        logger.debug("-" * 70)
        logger.debug(f"{'RANK':<5} {'CATEGORIA':<35} {'QTD':<8} {'%':<6}")
        logger.debug("-" * 70)

        for _, row in df_categorias.head(10).iterrows():
            categoria_display = row['categoria_medium'][:32] + '...' if len(str(row['categoria_medium'])) > 32 else row['categoria_medium']
            logger.debug(f"{row['rank']:<5} {categoria_display:<35} {row['quantidade']:<8} {row['percentual']:<6}%")

        if len(df_categorias) > 10:
            logger.debug(f"... e mais {len(df_categorias) - 10} categorias no arquivo")

    except Exception as e:
        logger.debug(f"Erro ao exportar arquivo CSV: {e}")
        logger.debug("Verifique permissões de escrita no diretório atual")
