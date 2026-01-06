"""
Módulo para unificação de UTM Source e Term - PIPELINE DE TREINO.

Reproduz a célula 10 do notebook DevClub.
NÃO confundir com utm_unification.py (pipeline de produção).
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


def unificar_utm_source_term(df_pesquisa: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica categorias das colunas Source e Term.

    Reproduz a lógica da célula 10 do notebook DevClub.

    Args:
        df_pesquisa: DataFrame de pesquisa

    Returns:
        DataFrame com UTMs unificadas
    """
    df = df_pesquisa.copy()

    print(f"Dataset inicial: {len(df)} registros")

    # 1. UNIFICAR COLUNA SOURCE
    print(f"\n1. UNIFICANDO COLUNA SOURCE:")
    print("-" * 35)

    if 'Source' in df.columns:
        # Mostrar distribuição antes
        source_antes = df['Source'].value_counts(dropna=False)
        print(f"Valores únicos antes: {df['Source'].nunique()}")
        print("Distribuição antes:")
        for valor, count in source_antes.head(10).items():
            pct = count / len(df) * 100
            valor_str = str(valor) if pd.notna(valor) else 'nan'
            print(f"  {valor_str:<25} {count:>6,} ({pct:>5.1f}%)")

        # Aplicar unificação
        df['Source'] = df['Source'].astype('object')  # Garantir tipo object

        # Agrupar outras categorias em "outros"
        outras_sources = ['fb', 'teste', '[field id="utm_source"]', 'facebook-ads-SiteLink', 'utm_source']

        for source in outras_sources:
            if source in df['Source'].values:
                df.loc[df['Source'] == source, 'Source'] = 'outros'

        print(f"\nApós unificação:")
        source_depois = df['Source'].value_counts(dropna=False)
        print(f"Valores únicos depois: {df['Source'].nunique()}")
        for valor, count in source_depois.items():
            pct = count / len(df) * 100
            valor_str = str(valor) if pd.notna(valor) else 'nan'
            print(f"  {valor_str:<25} {count:>6,} ({pct:>5.1f}%)")

    # 2. UNIFICAR COLUNA TERM
    print(f"\n2. UNIFICANDO COLUNA TERM:")
    print("-" * 35)

    if 'Term' in df.columns:
        # Mostrar distribuição antes
        term_antes = df['Term'].value_counts(dropna=False)
        print(f"Valores únicos antes: {df['Term'].nunique()}")
        print("Distribuição antes (top 10):")
        for valor, count in term_antes.head(10).items():
            pct = count / len(df) * 100
            valor_str = str(valor) if pd.notna(valor) else 'nan'
            print(f"  {valor_str:<35} {count:>6,} ({pct:>5.1f}%)")

        # Aplicar unificação
        df['Term'] = df['Term'].astype('object')  # Garantir tipo object

        # 1. Instagram: 'ig' -> 'instagram'
        df.loc[df['Term'] == 'ig', 'Term'] = 'instagram'

        # 2. Facebook: 'fb' -> 'facebook'
        df.loc[df['Term'] == 'fb', 'Term'] = 'facebook'

        # 3. IDs numéricos (padrão com --) -> 'outros'
        mask_ids_numericos = df['Term'].str.contains('--', na=False)
        df.loc[mask_ids_numericos, 'Term'] = 'outros'

        # 4. Parâmetros dinâmicos -> 'outros'
        mask_parametros = df['Term'].str.contains('{', na=False)
        df.loc[mask_parametros, 'Term'] = 'outros'

        # 5. Outros valores específicos -> 'outros'
        outros_terms = df['Term'].notna() & (~df['Term'].isin(['instagram', 'facebook']))
        valores_outros = df.loc[outros_terms, 'Term'].unique()

        # Converter valores restantes para 'outros' (exceto os já processados acima)
        for valor in valores_outros:
            if isinstance(valor, str) and valor not in ['instagram', 'facebook']:
                # Verificar se é um valor numérico ou outro tipo que deve virar 'outros'
                if not valor.isdigit() or len(valor) > 10:  # IDs longos ou textos especiais
                    df.loc[df['Term'] == valor, 'Term'] = 'outros'

        print(f"\nApós unificação:")
        term_depois = df['Term'].value_counts(dropna=False)
        print(f"Valores únicos depois: {df['Term'].nunique()}")
        for valor, count in term_depois.items():
            pct = count / len(df) * 100
            valor_str = str(valor) if pd.notna(valor) else 'nan'
            print(f"  {valor_str:<25} {count:>6,} ({pct:>5.1f}%)")

    print(f"\nRESULTADO FINAL:")
    print(f"Dataset: {len(df)} registros, {len(df.columns)} colunas")


    return df


def verificar_consistencia_utm(df: pd.DataFrame):
    """
    Verifica a consistência entre Source e Term após unificação.

    Args:
        df: DataFrame com UTMs unificadas
    """
    print(f"\n3. VERIFICAÇÃO DE CONSISTÊNCIA:")
    print("-" * 40)

    if 'Source' in df.columns and 'Term' in df.columns:
        # Tabela cruzada
        tabela_cruzada = pd.crosstab(df['Source'], df['Term'], margins=True, dropna=False)

        print("Tabela cruzada Source x Term:")
        print(tabela_cruzada)

        # Verificar lógica: Term só deveria ser instagram/facebook quando Source = facebook-ads
        # Term = instagram/facebook mas Source != facebook-ads
        mask_term_fb = df['Term'].isin(['instagram', 'facebook'])
        mask_source_nao_fb = df['Source'] != 'facebook-ads'

        inconsistentes = df[mask_term_fb & mask_source_nao_fb]

        if len(inconsistentes) > 0:
            print(f"\nInconsistências encontradas: {len(inconsistentes)} registros")
            print("Term = instagram/facebook mas Source != facebook-ads")

            for idx, row in inconsistentes.head(5).iterrows():
                print(f"  Source: {row['Source']}, Term: {row['Term']}")
        else:
            print(f"\nNenhuma inconsistência detectada - dados coerentes!")
