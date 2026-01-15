"""
Módulo de unificação de categorias Medium.
Mantém a lógica EXATA do notebook original para garantir reprodutibilidade.
"""

import pandas as pd
import re
import logging

logger = logging.getLogger(__name__)
from typing import Dict, List, Tuple


def extract_medium_audience(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extrai tipos de público da coluna Medium (primeira célula da Seção 11).

    Segue lógica EXATA da primeira célula do notebook original:
    - Remove prefixos "ADV |" e "ABERTO |"
    - Normaliza valores similares

    Args:
        df: DataFrame com coluna Medium

    Returns:
        DataFrame com Medium com públicos extraídos
    """
    df_extracted = df.copy()

    if 'Medium' not in df_extracted.columns:
        return df_extracted

    def extrair_publico(medium_value):
        """Função EXATA copiada do notebook original."""
        if pd.isna(medium_value):
            return medium_value

        medium_str = str(medium_value).strip()

        # Se tem |, pegar parte depois do último |, não antes
        if '|' in medium_str:
            partes = medium_str.split('|')
            if len(partes) >= 2:
                # Se primeira parte é só "ADV", pegar a segunda parte
                if partes[0].strip().upper() in ['ADV', 'ADV ']:
                    publico = partes[1].strip()
                else:
                    publico = partes[0].strip()
            else:
                publico = medium_str
        else:
            publico = medium_str

        # Se ainda sobrou só "ADV", tentar extrair de outra forma
        if publico.upper().strip() == 'ADV':
            # Voltar ao valor original e tentar alternativa
            if '|' in medium_str:
                # Pegar tudo depois do primeiro |
                publico = medium_str.split('|', 1)[1].strip()

        return publico

    # Aplicar extração
    df_extracted['Medium'] = df_extracted['Medium'].apply(extrair_publico)

    # Normalizar casos específicos (como no notebook)
    def normalizar_para_comparacao(texto):
        """Normaliza texto para comparação."""
        if pd.isna(texto):
            return ""

        texto_norm = str(texto).lower().strip()
        # Remover espaços extras
        texto_norm = re.sub(r'\s+', ' ', texto_norm)
        # Remover pontuação final
        texto_norm = texto_norm.rstrip('.')

        return texto_norm

    # Identificar e unificar duplicatas similares
    valores_medium = df_extracted['Medium'].dropna().unique()
    grupos_similares = {}
    processados = set()

    # Agrupar públicos idênticos (após normalização)
    for valor in valores_medium:
        if valor in processados:
            continue

        valor_norm = normalizar_para_comparacao(valor)
        grupo = [valor]

        # Buscar valores similares
        for outro_valor in valores_medium:
            if outro_valor != valor and outro_valor not in processados:
                outro_norm = normalizar_para_comparacao(outro_valor)

                # Critérios de similaridade
                if valor_norm == outro_norm:
                    grupo.append(outro_valor)
                    processados.add(outro_valor)

        if len(grupo) > 1:
            # Escolher representante (o mais comum)
            contagens = [(v, (df_extracted['Medium'] == v).sum()) for v in grupo]
            representante = max(contagens, key=lambda x: x[1])[0]
            grupos_similares[representante] = grupo

        processados.add(valor)

    # Aplicar unificações
    for representante, grupo in grupos_similares.items():
        if len(grupo) > 1:
            for valor in grupo:
                if valor != representante:
                    df_extracted.loc[df_extracted['Medium'] == valor, 'Medium'] = representante

    # Unificações manuais específicas (como no notebook)
    unificacoes_manuais = {
        'ABERTO': 'Aberto',  # Case sensitivity
    }

    for original, unificado in unificacoes_manuais.items():
        if original in df_extracted['Medium'].values:
            df_extracted.loc[df_extracted['Medium'] == original, 'Medium'] = unificado

    return df_extracted


def unify_medium_by_actions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica categorias Medium baseado no mapeamento de actions (segunda célula da Seção 11).

    Segue lógica EXATA da segunda célula do notebook original:
    - Aplica mapeamento específico baseado em análise de actions
    - Agrupa categorias similares

    Args:
        df: DataFrame com coluna Medium já com públicos extraídos

    Returns:
        DataFrame com Medium unificado por actions
    """
    df_unified = df.copy()

    if 'Medium' not in df_unified.columns:
        return df_unified

    # DEFINIR CATEGORIAS VÁLIDAS PARA PRODUÇÃO (baseado na análise temporal)
    # Removido 'Interesse Programação' - terminou em set/2025, não está em produção
    categorias_validas_producao = {
        'Aberto',
        'Linguagem de programação',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'Lookalike 2% Alunos + Interesse Linguagem de Programação',
        'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Outros',
        'dgen'
    }

    # Mapeamento atualizado baseado na análise temporal
    mapping_dict = {
        # MANTER - Categorias válidas para produção (7 categorias)
        'Lookalike 2% Cadastrados - DEV 2.0 + Interesses': 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Aberto': 'Aberto',
        'Linguagem de programação': 'Linguagem de programação',
        'Lookalike 2% Alunos + Interesse Linguagem de Programação': 'Lookalike 2% Alunos + Interesse Linguagem de Programação',
        'dgen': 'dgen',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação': 'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'nan': 'nan',

        # DESCONTINUADAS - Direcionar para 'Outros' (5 categorias)
        'Interesse Programação': 'Outros',  # Terminou set/2025
        'Lookalike 2% Alunos + Interesse Ciência da Computação': 'Outros',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação': 'Outros',
        'Interesse Python (linguagem de programação)': 'Outros',
        'Interesse Ciência da computação': 'Outros',

        # OUTRAS CATEGORIAS HISTÓRICAS - Direcionar para 'Outros'
        '{{adset.name}}': 'Outros',
        'paid': 'Outros',
        'Interesses': 'Outros',
        'search': 'Outros',
        'pmax': 'Outros',
        'Desenvolvimento profissional': 'Outros',
        'Funcionários de médias empresas B2B (200 a 500 funcionários)': 'Outros',
        'Funcionários de pequenas empresas B2B (10 a 200 funcionários)': 'Outros',
        'Funcionários de grandes empresas B2B (mais de 500 funcionários) — Cópia': 'Outros',
        'Lookalike 2% Alunos   Interesse Linguagem de Programação': 'Outros',
        'Lookalike 1% Cadastrados - DEV 2.0   Interesse Ciência da Computação': 'Outros',
        'Aberto++AD08-1002': 'Outros',
        'Lookalike 1% Cadastrados - DEV 2.0 Interesse Linguagem de Programação': 'Outros',
        'Lookalike 2% Alunos Interesse Ciência da Computação': 'Outros',
        'ADV+%7C+Lookalike+2%25+Cadastrados+-+DEV+2.0+%2B+Interesses': 'Outros',
        'Lookalike Envolvimento 30D Salvou 180D Direct 180D Interesse Ciência da Computação': 'Outros',
        'Lookalike% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação': 'Outros',
        'teste': 'Outros',
        '[field id="utm_medium"]': 'Outros',
        'ADV %7C Linguagem de programação': 'Outros',
        'gdn': 'Outros',
        'Lookalike 3% Alunos Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 30D   Salvou 180D   Direct 180D   Interesse Linguagem de Programação': 'Outros',
        'Lookalike Envolvimento 30D + Salvou80D + Direct80D + Interesse Linguagem de Programação': 'Outros',
        'Lookalike Envolvimento 60D Salvou 365D Direct 365D Interesse Ciência da Computação': 'Outros',
        'Lookalike 2% Cadastrados - DEV 2.0   Interesses': 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Lookalike 3% Alunos + Interesses': 'Outros',
        'Lookalike 3% Alunos + Interesse Ciência da Computação': 'Outros',
        'Lookalike 3% Alunos + Interesse Linguagem de Programação': 'Outros',
        'Interesse Python': 'Outros',
        'Lookalike 3% Cadastrados - DEV 2.0 + Interesses': 'Outros',
        'Lookalike 3% Cadastrados - DEV 2.0 + Interesse Ciência da Computação': 'Outros',
        'Lookalike 3% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação': 'Outros',
        'Lookalike Envolvimento 30D + Salvou 180D + Direct 180D + Interesse Linguagem de Programação': 'Outros',
        'Lookalike Envolvimento 30D + Salvou 180D + Direct 180D + Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 60D + Salvou 365D + Direct 365D + Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 60D + Salvou 365D + Direct 365D + Interesse Linguagem de Programação': 'Outros',
        'Interesse Linguagem de programação': 'Linguagem de programação'
    }

    # RASTREAR CONVERSÕES PARA 'OUTROS'
    conversoes_para_outros = []
    valores_nao_mapeados = []

    # FUNÇÃO DE UNIFICAÇÃO COM TRATAMENTO DE VALORES NÃO VISTOS
    def aplicar_unificacao_robusta(medium_value):
        """Aplica unificação com tratamento robusto para valores não vistos"""

        if pd.isna(medium_value):
            return medium_value

        medium_str = str(medium_value)

        # 1. VERIFICAR MAPEAMENTO DIRETO
        if medium_str in mapping_dict:
            resultado = mapping_dict[medium_str]
            # Rastrear se virou 'Outros'
            if resultado == 'Outros' and medium_str != 'Outros':
                if medium_str not in [c[0] for c in conversoes_para_outros]:
                    count = (df_unified['Medium'] == medium_str).sum()
                    conversoes_para_outros.append((medium_str, count))
            return resultado

        # 2. TRATAMENTO PARA VALORES NÃO VISTOS
        # Se não encontrou no mapeamento, verificar se é uma categoria válida para produção
        if medium_str in categorias_validas_producao:
            return medium_str

        # 3. VALORES COMPLETAMENTE NOVOS → 'Outros'
        if medium_str not in [v[0] for v in valores_nao_mapeados]:
            count = (df_unified['Medium'] == medium_str).sum()
            valores_nao_mapeados.append((medium_str, count))
        return 'Outros'

    # Aplicar a função de unificação robusta
    df_unified['Medium'] = df_unified['Medium'].apply(aplicar_unificacao_robusta)

    # LOGAR CONVERSÕES
    if conversoes_para_outros:
        logger.info(f"   📌 Medium convertidas para 'Outros' (mapeamento):")
        # Ordenar por contagem decrescente
        conversoes_para_outros.sort(key=lambda x: x[1], reverse=True)
        for valor, count in conversoes_para_outros[:10]:
            logger.info(f"      - '{valor}': {count} leads")
        if len(conversoes_para_outros) > 10:
            total_resto = sum(c[1] for c in conversoes_para_outros[10:])
            logger.info(f"      ... e mais {len(conversoes_para_outros)-10} categorias ({total_resto} leads)")

    if valores_nao_mapeados:
        logger.info(f"   📌 Medium NÃO MAPEADAS → convertidas para 'Outros':")
        # Ordenar por contagem decrescente
        valores_nao_mapeados.sort(key=lambda x: x[1], reverse=True)
        for valor, count in valores_nao_mapeados[:5]:
            logger.info(f"      - '{valor}': {count} leads")
        if len(valores_nao_mapeados) > 5:
            total_resto = sum(v[1] for v in valores_nao_mapeados[5:])
            logger.info(f"      ... e mais {len(valores_nao_mapeados)-5} categorias ({total_resto} leads)")

    return df_unified


def unify_medium_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica colunas Medium aplicando ambas as células da Seção 11.

    Combina:
    1. Extração de públicos (primeira célula)
    2. Unificação baseada em actions (segunda célula)

    Args:
        df: DataFrame com coluna Medium

    Returns:
        DataFrame com Medium completamente unificado
    """
    # Print do cabeçalho para comparação com notebook
    logger.info("UNIFICAÇÃO DE UTM MEDIUM - EXTRAÇÃO DE PÚBLICOS")
    logger.info("=" * 52)

    if 'Medium' not in df.columns:
        logger.info("Coluna 'Medium' não encontrada")
        return df

    logger.info(f"Dataset inicial: {len(df)} registros")
    logger.info(f"Medium - valores únicos antes: {df['Medium'].nunique()}")

    # Mostrar alguns exemplos antes
    logger.info(f"\nExemplos antes da extração:")
    exemplos_antes = df['Medium'].value_counts().head(10)
    for valor, count in exemplos_antes.items():
        if pd.notna(valor):
            logger.info(f"  {str(valor)[:70]:<72} ({count:,})")

    # 1. Extrair públicos (primeira célula)
    logger.info(f"\nExtraindo públicos...")
    df_extracted = extract_medium_audience(df)

    logger.info(f"Medium - valores únicos após extração: {df_extracted['Medium'].nunique()}")

    # Mostrar distribuição após extração inicial
    logger.info(f"\nDistribuição após extração inicial (top 15):")
    medium_apos_extracao = df_extracted['Medium'].value_counts(dropna=False)
    for i, (valor, count) in enumerate(medium_apos_extracao.head(15).items(), 1):
        pct = count / len(df_extracted) * 100
        valor_str = str(valor) if pd.notna(valor) else 'nan'
        logger.info(f"{i:2d}. {valor_str[:60]:<62} {count:>6,} ({pct:>5.1f}%)")

    # 2. Unificar por actions (segunda célula)
    logger.info(f"\nIdentificando públicos similares para unificação...")
    df_unified = unify_medium_by_actions(df_extracted)

    logger.info(f"\nMedium - valores únicos após unificação final: {df_unified['Medium'].nunique()}")

    # Mostrar distribuição final
    logger.info(f"\nDistribuição final (todas as categorias):")
    medium_final = df_unified['Medium'].value_counts(dropna=False)
    for i, (valor, count) in enumerate(medium_final.items(), 1):
        pct = count / len(df_unified) * 100
        valor_str = str(valor) if pd.notna(valor) else 'nan'
        logger.info(f"{i:2d}. {valor_str[:60]:<62} {count:>6,} ({pct:>5.1f}%)")

    return df_unified


def get_medium_summary(df: pd.DataFrame) -> Dict:
    """
    Gera resumo da coluna Medium após unificação.

    Args:
        df: DataFrame com coluna Medium unificada

    Returns:
        Dicionário com estatísticas da coluna Medium
    """
    summary = {}

    if 'Medium' in df.columns:
        summary['medium'] = {
            'unique_count': df['Medium'].nunique(),
            'null_count': df['Medium'].isna().sum(),
            'value_counts': df['Medium'].value_counts(dropna=False).to_dict()
        }

    return summary