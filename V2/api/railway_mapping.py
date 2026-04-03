"""
Mapeamento de leads do Railway PostgreSQL para o formato de entrada do pipeline ML.

O pipeline ML espera um DataFrame com colunas no formato Google Sheets
(ex.: 'O seu gênero:', 'Qual a sua idade?').  Este módulo converte os campos
do Railway — que usa camelCase no JSONB `pesquisa` e na tabela `Lead` —
para esse formato, aplicando a mesma normalização de texto que o pipeline
de treinamento aplicou.

Fluxo:
    Railway Lead (dict) → railway_lead_to_sheets_row() → dict no formato Sheets
                        → pd.DataFrame([...]) → pipeline.run() → lead_score + decil
"""

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalização de texto (idêntica a category_unification.limpar_texto)
# ---------------------------------------------------------------------------

def _limpar_texto(texto: Any) -> Optional[str]:
    """
    Normalização canônica de texto para categorias.

    Aplica as mesmas transformações de category_unification.limpar_texto:
    lowercase → remove acentos (unidecode) → remove pontuação → normaliza espaços.

    Returns None para NaN/None/vazio.
    """
    if texto is None:
        return None

    texto_limpo = str(texto).strip()
    if not texto_limpo:
        return None

    # Remover caracteres invisíveis
    texto_limpo = texto_limpo.replace('\u2060', '').replace('\xa0', ' ').replace('\u200b', '')
    texto_limpo = texto_limpo.strip()
    texto_limpo = texto_limpo.lower()

    # Remover acentos via unidecode
    try:
        from unidecode import unidecode
        texto_limpo = unidecode(texto_limpo)
    except ImportError:
        # fallback manual para os casos mais comuns
        subs = {'ã': 'a', 'â': 'a', 'á': 'a', 'à': 'a', 'ê': 'e', 'é': 'e',
                'í': 'i', 'õ': 'o', 'ô': 'o', 'ó': 'o', 'ú': 'u', 'ç': 'c',
                'ñ': 'n'}
        for k, v in subs.items():
            texto_limpo = texto_limpo.replace(k, v)

    # Remover pontuação (exceto espaços e underscores)
    texto_limpo = re.sub(r'[^\w\s]', '', texto_limpo)
    # Normalizar espaços múltiplos
    texto_limpo = re.sub(r'\s+', ' ', texto_limpo).strip()

    return texto_limpo if texto_limpo else None


def _normalizar(valor: Any, mapa: Optional[Dict[str, str]] = None) -> Optional[str]:
    """
    Aplica _limpar_texto e depois o mapa semântico (se fornecido).

    Returns None se o valor for nulo ou vazio.
    """
    limpo = _limpar_texto(valor)
    if limpo is None:
        return None
    if mapa:
        limpo = mapa.get(limpo, limpo)
    return limpo


# ---------------------------------------------------------------------------
# Mapas semânticos (mesmos de category_unification.py, estendidos com
# variantes encontradas no formulário Railway)
# ---------------------------------------------------------------------------

# Faixa salarial: Railway usa formato 'R$ 3.001 a 5.000'
# Após limpar_texto: 'r 3001 a 5000' → mapa → valor esperado pelo modelo
MAPA_FAIXA_SALARIAL: Dict[str, str] = {
    # Variantes Railway (após limpar_texto)
    'r 1000 a 2000':          'entre r1000 a r2000 reais ao mes',
    'r 2001 a 3000':          'entre r2001 a r3000 reais ao mes',
    'r 3001 a 5000':          'entre r3001 a r5000 reais ao mes',
    'acima de r 5000':        'mais de r5001 reais ao mes',
    'mais de r 5000':         'mais de r5001 reais ao mes',
    'mais de r 5001':         'mais de r5001 reais ao mes',
    'sem renda':              'nao tenho renda',
    'nao tenho renda':        'nao tenho renda',
    'nenhuma renda':          'nao tenho renda',
    # Variantes Sheets antigas (já usadas no category_unification)
    'ate r 2000':             'entre r1000 a r2000 reais ao mes',
    'acima de r 5001':        'mais de r5001 reais ao mes',
    # Valores já normalizados (passam direto)
    'entre r1000 a r2000 reais ao mes':  'entre r1000 a r2000 reais ao mes',
    'entre r2001 a r3000 reais ao mes':  'entre r2001 a r3000 reais ao mes',
    'entre r3001 a r5000 reais ao mes':  'entre r3001 a r5000 reais ao mes',
    'mais de r5001 reais ao mes':        'mais de r5001 reais ao mes',
}

# Ocupação: Railway usa 'CLT / Funcionário Público'
# Após limpar_texto: 'clt funcionario publico' → mapa
MAPA_OCUPACAO: Dict[str, str] = {
    # Variantes Railway (após limpar_texto)
    'clt funcionario publico':              'sou cltfuncionario publico',
    'autonomo':                             'sou autonomo',
    'autonomo empreendedor':                'sou autonomo',
    'desempregado':                         'nao trabalho e nem estudo',
    'estudante':                            'sou apenas estudante',
    'aposentado':                           'sou aposentado',
    # Variantes Sheets antigas
    'atualmente nao trabalho e nem estudo': 'nao trabalho e nem estudo',
    'sou autonomo uber freela vendedor etc':'sou autonomo',
    'estudo na faculdade':                  'sou apenas estudante',
    # Valores já normalizados
    'nao trabalho e nem estudo':  'nao trabalho e nem estudo',
    'sou apenas estudante':       'sou apenas estudante',
    'sou aposentado':             'sou aposentado',
    'sou autonomo':               'sou autonomo',
    'sou cltfuncionario publico': 'sou cltfuncionario publico',
}

# Idade: Railway usa '25 – 34' (com en/em dash)
# Após limpar_texto: '25 34' → mapa → '25 34 anos'
MAPA_IDADE: Dict[str, str] = {
    # Após limpar_texto (dash e espaços normalizados)
    '18 24':       '18 24 anos',
    '25 34':       '25 34 anos',
    '35 44':       '35 44 anos',
    '45 54':       '45 54 anos',
    'menos de 18': 'menos de 18 anos',
    'mais de 55':  'mais de 55 anos',
    'acima de 55': 'mais de 55 anos',
    '55':          'mais de 55 anos',
    # Valores já normalizados
    '18 24 anos':       '18 24 anos',
    '25 34 anos':       '25 34 anos',
    '35 44 anos':       '35 44 anos',
    '45 54 anos':       '45 54 anos',
    'menos de 18 anos': 'menos de 18 anos',
    'mais de 55 anos':  'mais de 55 anos',
}

# Interesse no evento: Railway usa 'Projeto na prática'
# Após limpar_texto: 'projeto na pratica' → mapa
MAPA_INTERESSE_EVENTO: Dict[str, str] = {
    # Variantes Railway (após limpar_texto)
    'projeto na pratica':               'fazer um projeto na pratica',
    'como conseguir emprego':           'fazer transicao de carreira e conseguir meu primeiro emprego na area',
    'como fazer transicao de carreira': 'fazer transicao de carreira e conseguir meu primeiro emprego na area',
    'como fazer freelancer':            'fazer freelancer como programador',
    'quero saber se e pra mim':         'quero saber se e para mim',
    'quero saber se e para mim':        'quero saber se e para mim',
    'a aula com a recrutadora':         'a aula com a recrutadora',
    # Valores já normalizados
    'fazer um projeto na pratica':      'fazer um projeto na pratica',
    'fazer freelancer como programador':'fazer freelancer como programador',
    'fazer transicao de carreira e conseguir meu primeiro emprego na area':
        'fazer transicao de carreira e conseguir meu primeiro emprego na area',
}

# Atração pela profissão: Railway usa 'Trabalhar de qualquer lugar'
# Após limpar_texto → mapa
MAPA_ATRACAO_PROFISSAO: Dict[str, str] = {
    # Variantes Railway (após limpar_texto)
    'trabalhar de qualquer lugar':        'poder trabalhar de qualquer lugar do mundo',
    'ganhar mais dinheiro bons salarios': 'a possibilidade de ganhar altos salarios',
    'estabilidade nunca faltar emprego':  'a ideia de nunca faltar emprego na area',
    'trabalhar para fora dolar':          'trabalhar para outros paises e ganhar em outra moeda',
    'todas as alternativas':              'todas as alternativas',
    # Valores já normalizados
    'poder trabalhar de qualquer lugar do mundo':          'poder trabalhar de qualquer lugar do mundo',
    'a possibilidade de ganhar altos salarios':             'a possibilidade de ganhar altos salarios',
    'a ideia de nunca faltar emprego na area':              'a ideia de nunca faltar emprego na area',
    'trabalhar para outros paises e ganhar em outra moeda':'trabalhar para outros paises e ganhar em outra moeda',
}


# ---------------------------------------------------------------------------
# Função principal de conversão
# ---------------------------------------------------------------------------

def railway_lead_to_sheets_row(lead_row: Dict, client_config=None) -> Dict:
    """
    Converte um lead do Railway PostgreSQL para o formato de entrada do pipeline ML.

    O pipeline ML espera um dict (row) com as mesmas colunas que o Google Sheets envia.
    Esta função:
      1. Extrai campos diretos da tabela Lead (email, nome, telefone, data, UTMs)
      2. Extrai e normaliza campos do JSONB `pesquisa`
      3. Retorna dict pronto para pd.DataFrame([row])

    Args:
        lead_row: Dict com todos os campos do Railway Lead (retornado pela query SQL).
                  Campos esperados: id, data, nomeCompleto, email, telefone,
                  pesquisa (dict/JSONB), source, medium, campaign, content, term.
        client_config: ClientConfig do cliente — se fornecido, usa os mapas e nomes de colunas
                       definidos em api.railway_field_mappings (fallback para defaults DevClub).

    Returns:
        Dict com chaves no formato Google Sheets, pronto para o pipeline ML.

    Campos não mapeados (Railway-only):
        barreira, urgencia, investimento → ignorados (não são features do modelo)

    Campos ausentes no Railway:
        'Você já fez/faz/pretende fazer faculdade?' → None (feature não coletada)
    """
    pesquisa: Dict = lead_row.get('pesquisa') or {}

    # Carregar mapas: preferir ClientConfig, fallback para módulo-level defaults
    _mappings: Dict = {}
    if client_config and hasattr(client_config, 'api') and client_config.api and client_config.api.railway_field_mappings:
        _mappings = client_config.api.railway_field_mappings

    _mapa_faixa_salarial = _mappings.get('mapa_faixa_salarial', MAPA_FAIXA_SALARIAL)
    _mapa_ocupacao       = _mappings.get('mapa_ocupacao', MAPA_OCUPACAO)
    _mapa_idade          = _mappings.get('mapa_idade', MAPA_IDADE)
    _mapa_interesse      = _mappings.get('mapa_interesse_evento', MAPA_INTERESSE_EVENTO)
    _mapa_atracao        = _mappings.get('mapa_atracao_profissao', MAPA_ATRACAO_PROFISSAO)

    _direct = _mappings.get('direct_field_map', {
        'email': 'E-mail', 'nomeCompleto': 'Nome Completo', 'telefone': 'Telefone',
        'data': 'Data', 'source': 'Source', 'medium': 'Medium',
        'campaign': 'Campaign', 'term': 'Term', 'content': 'Content',
    })
    _pesquisa_map = _mappings.get('pesquisa_field_map', {
        'genero': 'O seu gênero:',
        'idade': 'Qual a sua idade?',
        'ocupacao': 'O que você faz atualmente?',
        'faixaSalarial': 'Atualmente, qual a sua faixa salarial?',
        'cartaoCredito': 'Você possui cartão de crédito?',
        'interesseEvento': 'O que mais você quer ver no evento?',
        'computador': 'Tem computador/notebook?',
        'estudouProgramacao': 'Já estudou programação?',
        'faculdade': 'Você já fez/faz/pretende fazer faculdade?',
        'investiuCurso': 'investiu_curso_online',
        'atracaoProfissao': 'interesse_programacao',
    })

    # ------------------------------------------------------------------
    # 1. Campos diretos da tabela Lead
    # Construir row a partir do direct_field_map (Railway key → Sheets col)
    # ------------------------------------------------------------------
    row: Dict = {}
    for railway_key, sheets_col in _direct.items():
        row[sheets_col] = lead_row.get(railway_key)

    # ------------------------------------------------------------------
    # 2. Campos do JSONB pesquisa → Sheets column names + normalização
    # ------------------------------------------------------------------
    # Campos com mapa semântico específico
    _col_idade     = _pesquisa_map.get('idade', 'Qual a sua idade?')
    _col_ocupacao  = _pesquisa_map.get('ocupacao', 'O que você faz atualmente?')
    _col_salarial  = _pesquisa_map.get('faixaSalarial', 'Atualmente, qual a sua faixa salarial?')
    _col_interesse = _pesquisa_map.get('interesseEvento', 'O que mais você quer ver no evento?')
    _col_atracao   = _pesquisa_map.get('atracaoProfissao', 'interesse_programacao')

    # Gênero: passar sem normalização semântica; string vazia → None (evita OHE de categoria vazia)
    _col_genero = _pesquisa_map.get('genero', 'O seu gênero:')
    row[_col_genero] = pesquisa.get('genero') or None

    row[_col_idade]     = _normalizar(pesquisa.get('idade'), _mapa_idade)
    row[_col_ocupacao]  = _normalizar(pesquisa.get('ocupacao'), _mapa_ocupacao)
    row[_col_salarial]  = _normalizar(pesquisa.get('faixaSalarial'), _mapa_faixa_salarial)
    row[_pesquisa_map.get('cartaoCredito', 'Você possui cartão de crédito?')] = _normalizar(pesquisa.get('cartaoCredito'))
    row[_col_interesse] = _normalizar(pesquisa.get('interesseEvento'), _mapa_interesse)
    row[_pesquisa_map.get('computador', 'Tem computador/notebook?')] = _normalizar(pesquisa.get('computador'))

    # Campos sem mapa semântico; string vazia → None (evita OHE de categoria vazia)
    row[_pesquisa_map.get('estudouProgramacao', 'Já estudou programação?')] = pesquisa.get('estudouProgramacao') or None
    row[_pesquisa_map.get('faculdade', 'Você já fez/faz/pretende fazer faculdade?')] = pesquisa.get('faculdade') or None
    row[_pesquisa_map.get('investiuCurso', 'investiu_curso_online')] = pesquisa.get('investiuCurso') or None
    row[_col_atracao] = _normalizar(pesquisa.get('atracaoProfissao'), _mapa_atracao)

    # ------------------------------------------------------------------
    # 3. Campos Railway ignorados (não são features do modelo)
    # barreira, urgencia, investimento, estudouIA, porqueGestor → não incluídos no row
    # ------------------------------------------------------------------

    # Log para debug
    logger.debug(
        f"[railway_mapping] Lead {lead_row.get('email', '?')} → "
        f"idade={row.get(_col_idade)}, "
        f"ocupacao={row.get(_col_ocupacao)}, "
        f"faixaSalarial={row.get(_col_salarial)}"
    )

    return row
