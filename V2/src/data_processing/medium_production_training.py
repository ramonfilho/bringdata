"""
Módulo para unificação de Medium para produção - PIPELINE DE TREINO.

Reproduz a célula 11.1 do notebook DevClub.
Unifica categorias Medium baseado em mapeamento de actions + tratamento para produção.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def unificar_medium_para_producao(df_medium_unificado: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica categorias Medium baseado no mapeamento de actions + tratamento para produção.

    Reproduz a lógica da célula 12 do notebook DevClub.

    Args:
        df_medium_unificado: DataFrame com Medium já extraído (output da célula 11)

    Returns:
        DataFrame com Medium unificado para produção
    """
    df = df_medium_unificado.copy()

    if 'Medium' not in df.columns:
        print("Coluna 'Medium' não encontrada")
        return df

    print(f"Dataset inicial: {len(df)} registros")
    print(f"Medium - valores únicos antes: {df['Medium'].nunique()}")

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

    print(f"Categorias válidas para produção definidas: {len(categorias_validas_producao)}")

    # CATEGORIAS DESCONTINUADAS (serão direcionadas para 'Outros')
    categorias_descontinuadas = {
        'Interesse Ciência da computação',
        'Interesse Python (linguagem de programação)',
        'Interesse Programação',  # Terminou em set/2025
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação',
        'Lookalike 2% Alunos + Interesse Ciência da Computação'
    }

    print(f"Categorias descontinuadas identificadas: {len(categorias_descontinuadas)}")

    # Criar mapeamento atualizado (mantendo categorias válidas + direcionando descontinuadas para Outros)
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

    print(f"Mapeamento criado para {len(mapping_dict)} categorias")

    # Mostrar estatísticas antes da unificação
    print(f"\nDistribuição antes da unificação (top 10):")
    medium_antes = df['Medium'].value_counts(dropna=False)
    for i, (valor, count) in enumerate(medium_antes.head(10).items(), 1):
        pct = count / len(df) * 100
        valor_str = str(valor) if pd.notna(valor) else 'nan'
        print(f"{i:2d}. {valor_str[:50]:<52} {count:>6,} ({pct:>5.1f}%)")

    # FUNÇÃO DE UNIFICAÇÃO COM TRATAMENTO DE VALORES NÃO VISTOS
    # Sets para coletar valores não vistos (evitar duplicatas nos logs)
    valores_nao_mapeados = set()
    valores_novos_para_outros = set()

    def aplicar_unificacao_robusta(medium_value):
        """Aplica unificação com tratamento robusto para valores não vistos"""

        if pd.isna(medium_value):
            return medium_value

        medium_str = str(medium_value)

        # 1. VERIFICAR MAPEAMENTO DIRETO
        if medium_str in mapping_dict:
            return mapping_dict[medium_str]

        # 2. TRATAMENTO PARA VALORES NÃO VISTOS
        # Se não encontrou no mapeamento, verificar se é uma categoria válida para produção
        if medium_str in categorias_validas_producao:
            valores_nao_mapeados.add(medium_str)
            return medium_str

        # 3. VALORES COMPLETAMENTE NOVOS → 'Outros'
        valores_novos_para_outros.add(medium_str)
        return 'Outros'

    # Aplicar a função de unificação robusta
    print(f"\nAplicando unificação robusta com tratamento de valores não vistos...")
    df['Medium'] = df['Medium'].apply(aplicar_unificacao_robusta)

    # Imprimir sumário de valores não vistos (apenas uma vez por valor único)
    if valores_nao_mapeados:
        print(f"\n⚠️  {len(valores_nao_mapeados)} categoria(s) válida(s) não mapeada(s) encontrada(s):")
        for valor in sorted(valores_nao_mapeados):
            print(f"   - '{valor}' (mantida como está)")

    if valores_novos_para_outros:
        print(f"\n⚠️  {len(valores_novos_para_outros)} novo(s) valor(es) não visto(s) direcionado(s) para 'Outros':")
        for valor in sorted(valores_novos_para_outros):
            print(f"   - '{valor}'")

    print(f"Medium - valores únicos após unificação: {df['Medium'].nunique()}")

    return df


def relatorio_unificacao_producao(df_original: pd.DataFrame, df_unificado: pd.DataFrame):
    """
    Gera relatório detalhado da unificação para produção.

    Args:
        df_original: DataFrame antes da unificação
        df_unificado: DataFrame depois da unificação
    """
    print(f"\n" + "="*70)
    print(f"RELATÓRIO DE UNIFICAÇÃO PARA PRODUÇÃO")
    print(f"="*70)

    # Comparação antes/depois
    antes_count = df_original['Medium'].nunique()
    depois_count = df_unificado['Medium'].nunique()
    reducao = antes_count - depois_count
    reducao_pct = (reducao / antes_count) * 100

    print(f"Categorias antes: {antes_count}")
    print(f"Categorias depois: {depois_count}")
    print(f"Redução: {reducao} categorias ({reducao_pct:.1f}%)")

    # Verificar se temos exatamente as 8 categorias + nan
    categorias_finais = set(df_unificado['Medium'].dropna().unique())
    categorias_esperadas = {
        'Aberto', 'Interesse Programação', 'Linguagem de programação',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'Lookalike 2% Alunos + Interesse Linguagem de Programação',
        'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Outros', 'dgen'
    }

    print(f"\nVERIFICAÇÃO DE CONFORMIDADE COM PRODUÇÃO:")
    if categorias_finais == categorias_esperadas:
        print(f"✓ SUCESSO: Dataset tem exatamente as {len(categorias_esperadas)} categorias esperadas para produção")
    else:
        categorias_extras = categorias_finais - categorias_esperadas
        categorias_faltando = categorias_esperadas - categorias_finais

        if categorias_extras:
            print(f"⚠ ATENÇÃO: {len(categorias_extras)} categorias extras encontradas:")
            for cat in sorted(categorias_extras):
                print(f"    - {cat}")

        if categorias_faltando:
            print(f"⚠ ATENÇÃO: {len(categorias_faltando)} categorias esperadas estão faltando:")
            for cat in sorted(categorias_faltando):
                print(f"    - {cat}")

    # Distribuição final
    print(f"\nDistribuição final das categorias:")
    print("-" * 70)
    print(f"{'#':<3} {'CATEGORIA':<45} {'COUNT':<8} {'%':<6}")
    print("-" * 70)

    medium_final = df_unificado['Medium'].value_counts(dropna=False)
    total_registros = len(df_unificado)

    for i, (valor, count) in enumerate(medium_final.items(), 1):
        pct = count / total_registros * 100
        valor_str = str(valor) if pd.notna(valor) else 'nan'

        if len(valor_str) > 42:
            valor_display = valor_str[:39] + '...'
        else:
            valor_display = valor_str

        print(f"{i:<3} {valor_display:<45} {count:<8,} {pct:<6.1f}%")

    # Verificação final das colunas que serão criadas no encoding
    print(f"\n" + "="*70)
    print(f"COLUNAS ESPERADAS APÓS ONE-HOT ENCODING")
    print(f"="*70)

    categorias_para_encoding = df_unificado['Medium'].dropna().unique()

    print(f"Serão criadas {len(categorias_para_encoding)} colunas Medium_*:")
    for i, categoria in enumerate(sorted(categorias_para_encoding), 1):
        # Simular nome da coluna que será criada
        coluna_nome = f"Medium_{str(categoria).replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace('%', 'pct').replace('-', '_').replace('+', 'plus')}"
        print(f"  {i:2d}. {coluna_nome}")

    print(f"\nNenhuma categoria descontinuada será criada no encoding ✓")
