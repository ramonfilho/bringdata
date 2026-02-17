"""
Módulo para unificação completa de categorias.

Reproduz a célula 7 do notebook DevClub.
"""

import pandas as pd
import logging
from unidecode import unidecode

logger = logging.getLogger(__name__)


def limpar_texto(texto):
    """
    Normalização canônica de texto para categorias.

    Aplica transformações agressivas para garantir consistência entre treino e produção:
    - Remove caracteres invisíveis
    - Lowercase (maiúsculas  minúsculas)
    - Remove acentos (autônomo  autonomo)
    - Remove pontuação
    - Normaliza espaços múltiplos

    IMPORTANTE: Esta normalização resolve o problema crítico onde 25.9% dos leads
    estavam sendo mal classificados porque "Sou autonomo" (sem acento, vindo do Sheets)
    não dava match com "Sou autônomo" (com acento, usado no treino).

    Args:
        texto: String a ser normalizada

    Returns:
        String normalizada ou valor original se NaN
    """
    if pd.isna(texto):
        return texto

    # Converter para string
    texto_limpo = str(texto)

    # 1. Remover caracteres invisíveis
    texto_limpo = texto_limpo.replace('\u2060', '')  # Word joiner
    texto_limpo = texto_limpo.replace('\xa0', ' ')   # Non-breaking space
    texto_limpo = texto_limpo.replace('\u200b', '')  # Zero width space

    # 2. Strip inicial
    texto_limpo = texto_limpo.strip()

    # 3. Lowercase (NOVO - resolve problema de case)
    texto_limpo = texto_limpo.lower()

    # 4. Remover acentos (NOVO - resolve problema de acentuação)
    # Exemplo: "autônomo"  "autonomo"
    texto_limpo = unidecode(texto_limpo)

    # 5. Remover pontuação (exceto espaços e underscores)
    import re
    texto_limpo = re.sub(r'[^\w\s]', '', texto_limpo)

    # 6. Normalizar múltiplos espaços para um único espaço
    texto_limpo = re.sub(r'\s+', ' ', texto_limpo)

    # 7. Strip final
    texto_limpo = texto_limpo.strip()

    return texto_limpo


def unificar_categorias_completo(df_pesquisa: pd.DataFrame) -> pd.DataFrame:
    """
    Unifica categorias com limpeza e mappings robustos.

    Reproduz a lógica da célula 7 do notebook DevClub.

    Args:
        df_pesquisa: DataFrame de pesquisa

    Returns:
        DataFrame com categorias unificadas
    """
    df = df_pesquisa.copy()

    # NORMALIZAÇÃO INICIAL: aplica limpar_texto em todas as colunas categóricas de uma vez.
    # Colunas excluídas intencionalmente:
    #   - E-mail, Telefone: limpar_texto remove pontuação (@, -, parênteses) — quebra o dado
    #   - Data: não é texto categórico
    #   - Medium: usa separador '|' para parsing posterior (célula 11) — não pode normalizar
    #   - arquivo_origem, aba_origem: metadados internos, não viram features do modelo
    COLUNAS_CATEGORICAS = [
        # Survey — respostas de formulário
        'interesse_programacao',
        'tem_computador',
        'o_que_quer_ver_evento',
        'tem_cartao_credito',
        'faixa_salarial',
        'o_que_faz_atualmente',
        'idade',
        'genero',
        'estudou_programacao',
        'fez_faculdade',
        'investiu_curso_online',
        'nivel_programacao',
        # Identificadores usados para feature engineering (nome_comprimento, nome_valido, etc.)
        'Nome Completo',
        # UTM — processamento próprio na célula 10, mas sem separadores especiais
        'Source',
        'Term',
    ]
    colunas_presentes = [c for c in COLUNAS_CATEGORICAS if c in df.columns]
    for coluna in colunas_presentes:
        df[coluna] = df[coluna].apply(limpar_texto)
    logger.info(f"  Normalização inicial: {len(colunas_presentes)} colunas normalizadas")

    # NORMAL: Apenas cabeçalho
    logger.info("  Aplicando limpeza e unificação completa...")
    logger.info("  1. Unificando interesse_programacao")
    if 'interesse_programacao' in df.columns:

        # Mapeamento semântico pós-normalização: variantes com mesmo significado → categoria canônica
        mapa_interesse = {
            'trabalhar de qualquer lugar':        'poder trabalhar de qualquer lugar do mundo',
            'ganhar mais dinheiro bons salarios': 'a possibilidade de ganhar altos salarios',
            'estabilidade nunca faltar emprego':  'a ideia de nunca faltar emprego na area',
            'trabalhar para fora dolar':          'trabalhar para outros paises e ganhar em outra moeda',
        }
        df['interesse_programacao'] = df['interesse_programacao'].replace(mapa_interesse)

        valores_unicos = df['interesse_programacao'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # DEBUG: Mostrar distribuição final
        total = len(df)
        counts = df['interesse_programacao'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            # Truncar valores longos
            if len(valor_str) > 60:
                valor_str = valor_str[:57] + '...'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 2. TEM COMPUTADOR/NOTEBOOK
    logger.info("  2. Unificando tem_computador")
    if 'tem_computador' in df.columns:
        valores_unicos = df['tem_computador'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['tem_computador'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 3. O QUE MAIS VOCÊ QUER VER NO EVENTO
    logger.info("  3. Unificando o_que_quer_ver_evento")
    if 'o_que_quer_ver_evento' in df.columns:
        # Mapeamento semântico pós-normalização: variantes com mesmo significado → categoria canônica
        mapa_evento = {
            # Erro tipográfico: 'consegui' em vez de 'conseguir'
            'fazer transicao de carreira e consegui meu primeiro emprego na area':
                'fazer transicao de carreira e conseguir meu primeiro emprego na area',
            # Versões curtas/alternativas de categorias existentes
            'projeto na pratica':               'fazer um projeto na pratica',
            'como conseguir emprego':           'fazer transicao de carreira e conseguir meu primeiro emprego na area',
            'como fazer transicao de carreira': 'fazer transicao de carreira e conseguir meu primeiro emprego na area',
            'quero saber se e pra mim':         'quero saber se e para mim',
            'como fazer freelancer':            'fazer freelancer como programador',
        }
        df['o_que_quer_ver_evento'] = df['o_que_quer_ver_evento'].replace(mapa_evento)

        valores_unicos = df['o_que_quer_ver_evento'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['o_que_quer_ver_evento'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            if len(valor_str) > 60:
                valor_str = valor_str[:57] + '...'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 4. VOCÊ POSSUI CARTÃO DE CRÉDITO
    logger.info("  4. Unificando tem_cartao_credito")
    if 'tem_cartao_credito' in df.columns:
        valores_unicos = df['tem_cartao_credito'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['tem_cartao_credito'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 5. ATUALMENTE, QUAL A SUA FAIXA SALARIAL
    logger.info("  5. Unificando faixa_salarial")
    if 'faixa_salarial' in df.columns:
        # Mapeamento pós-normalização: variantes → categorias canônicas (compatível com produção)
        mapa_faixa = {
            'nenhuma renda':   'nao tenho renda',
            'ate r 2000':      'entre r1000 a r2000 reais ao mes',
            'r 2001 a 3000':   'entre r2001 a r3000 reais ao mes',
            'r 3001 a 5000':   'entre r3001 a r5000 reais ao mes',
            'acima de r 5000': 'mais de r5001 reais ao mes',
        }
        df['faixa_salarial'] = df['faixa_salarial'].replace(mapa_faixa)

        valores_unicos = df['faixa_salarial'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['faixa_salarial'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 6. O QUE VOCÊ FAZ ATUALMENTE
    logger.info("  6. Unificando o_que_faz_atualmente")
    if 'o_que_faz_atualmente' in df.columns:
        # Mapeamento semântico pós-normalização: variantes → categorias canônicas (compatível com produção)
        mapa_faz = {
            # Variantes de formulários antigos (formas curtas)
            'clt funcionario publico':              'sou cltfuncionario publico',
            'autonomo empreendedor':                'sou autonomo',
            'desempregado':                         'nao trabalho e nem estudo',
            'estudante':                            'sou apenas estudante',
            'aposentado':                           'sou aposentado',
            'atualmente nao trabalho e nem estudo': 'nao trabalho e nem estudo',
            # Autônomo com descrição → autônomo genérico
            'sou autonomo uber freela vendedor etc': 'sou autonomo',
            # Variantes de faculdade → sou apenas estudante
            'estudo na faculdade':                                     'sou apenas estudante',
            'estudo ti na faculdade mas quero aprender mais por fora': 'sou apenas estudante',
            'faco outro curso na faculdade e quero mudar para ti':     'sou apenas estudante',
        }
        df['o_que_faz_atualmente'] = df['o_que_faz_atualmente'].replace(mapa_faz)

        valores_unicos = df['o_que_faz_atualmente'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['o_que_faz_atualmente'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            if len(valor_str) > 60:
                valor_str = valor_str[:57] + '...'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 7. QUAL A SUA IDADE
    logger.info("  7. Unificando idade")
    if 'idade' in df.columns:
        # Mapeamento pós-normalização: variantes sem "anos" → categorias canônicas (compatível com produção)
        mapa_idade = {
            '18 24':       '18 24 anos',
            '25 34':       '25 34 anos',
            '35 44':       '35 44 anos',
            '45 54':       '45 54 anos',
            'menos de 18': 'menos de 18 anos',
            '55':          'mais de 55 anos',
        }
        df['idade'] = df['idade'].replace(mapa_idade)

        valores_unicos = df['idade'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['idade'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 8. OUTRAS COLUNAS CATEGÓRICAS (normalizadas no batch inicial, sem mapeamento semântico)
    outras_colunas = [
        'genero',
        'estudou_programacao',
        'fez_faculdade',
        'investiu_curso_online',
        'nivel_programacao',
    ]

    total = len(df)
    for coluna in outras_colunas:
        if coluna in df.columns:
            logger.debug(f"")
            logger.debug(f"   {coluna}")
            valores_unicos = df[coluna].nunique()
            logger.debug(f"   Valores únicos: {valores_unicos}")

            counts = df[coluna].value_counts(dropna=False)
            logger.debug(f"    Distribuição:")
            for valor, count in counts.items():
                pct = (count / total) * 100
                valor_str = str(valor) if pd.notna(valor) else 'NaN'
                logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    logger.info("")

    return df
