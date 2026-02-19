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
        'Tem computador/notebook?',
        'O que mais você quer ver no evento?',
        'Você possui cartão de crédito?',
        'Atualmente, qual a sua faixa salarial?',
        'O que você faz atualmente?',
        'Qual a sua idade?',
        'O seu gênero:',
        'Já estudou programação?',
        'Você já fez/faz/pretende fazer faculdade?',
        'investiu_curso_online',
        'Qual o seu nível em programação?',
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
    logger.info("  2. Unificando Tem computador/notebook?")
    if 'Tem computador/notebook?' in df.columns:
        valores_unicos = df['Tem computador/notebook?'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['Tem computador/notebook?'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 3. O QUE MAIS VOCÊ QUER VER NO EVENTO
    logger.info("  3. Unificando O que mais você quer ver no evento?")
    if 'O que mais você quer ver no evento?' in df.columns:
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
        df['O que mais você quer ver no evento?'] = df['O que mais você quer ver no evento?'].replace(mapa_evento)

        valores_unicos = df['O que mais você quer ver no evento?'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['O que mais você quer ver no evento?'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            if len(valor_str) > 60:
                valor_str = valor_str[:57] + '...'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 4. VOCÊ POSSUI CARTÃO DE CRÉDITO
    logger.info("  4. Unificando Você possui cartão de crédito?")
    if 'Você possui cartão de crédito?' in df.columns:
        valores_unicos = df['Você possui cartão de crédito?'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['Você possui cartão de crédito?'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 5. ATUALMENTE, QUAL A SUA FAIXA SALARIAL
    logger.info("  5. Unificando Atualmente, qual a sua faixa salarial?")
    if 'Atualmente, qual a sua faixa salarial?' in df.columns:
        # Mapeamento pós-normalização: variantes → categorias canônicas (compatível com produção)
        mapa_faixa = {
            'nenhuma renda':   'nao tenho renda',
            'ate r 2000':      'entre r1000 a r2000 reais ao mes',
            'r 2001 a 3000':   'entre r2001 a r3000 reais ao mes',
            'r 3001 a 5000':   'entre r3001 a r5000 reais ao mes',
            'acima de r 5000': 'mais de r5001 reais ao mes',
        }
        df['Atualmente, qual a sua faixa salarial?'] = df['Atualmente, qual a sua faixa salarial?'].replace(mapa_faixa)

        valores_unicos = df['Atualmente, qual a sua faixa salarial?'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['Atualmente, qual a sua faixa salarial?'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 6. O QUE VOCÊ FAZ ATUALMENTE
    logger.info("  6. Unificando O que você faz atualmente?")
    if 'O que você faz atualmente?' in df.columns:
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
        df['O que você faz atualmente?'] = df['O que você faz atualmente?'].replace(mapa_faz)

        valores_unicos = df['O que você faz atualmente?'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['O que você faz atualmente?'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            if len(valor_str) > 60:
                valor_str = valor_str[:57] + '...'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 7. QUAL A SUA IDADE
    logger.info("  7. Unificando Qual a sua idade?")
    if 'Qual a sua idade?' in df.columns:
        # Mapeamento pós-normalização: variantes sem "anos" → categorias canônicas (compatível com produção)
        mapa_idade = {
            '18 24':       '18 24 anos',
            '25 34':       '25 34 anos',
            '35 44':       '35 44 anos',
            '45 54':       '45 54 anos',
            'menos de 18': 'menos de 18 anos',
            '55':          'mais de 55 anos',
        }
        df['Qual a sua idade?'] = df['Qual a sua idade?'].replace(mapa_idade)

        valores_unicos = df['Qual a sua idade?'].nunique()
        logger.debug(f"   Resultado: {valores_unicos} valores únicos")

        # Mostrar distribuição final
        total = len(df)
        counts = df['Qual a sua idade?'].value_counts(dropna=False)
        logger.debug(f"    Distribuição final:")
        for valor, count in counts.items():
            pct = (count / total) * 100
            valor_str = str(valor) if pd.notna(valor) else 'NaN'
            logger.debug(f"      - '{valor_str}': {count} leads ({pct:.1f}%)")

    # 8. OUTRAS COLUNAS CATEGÓRICAS (normalizadas no batch inicial, sem mapeamento semântico)
    outras_colunas = [
        'O seu gênero:',
        'Já estudou programação?',
        'Você já fez/faz/pretende fazer faculdade?',
        'investiu_curso_online',
        'Qual o seu nível em programação?',
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
