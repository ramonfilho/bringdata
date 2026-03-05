"""
Módulo para unificação de Medium para produção - PIPELINE DE TREINO.

Reproduz a célula 11.1 do notebook DevClub.
Unifica categorias Medium baseado em mapeamento de actions + tratamento para produção.

Categorias válidas e descontinuadas são determinadas automaticamente via comparação
entre os dados atuais e as distribuições do modelo ativo (distribuicoes_esperadas.json).
"""

import os
import json
import yaml
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Thresholds de classificação de categorias
THRESHOLD_VALIDA = 0.025    # >= 2.5% nos dados atuais → válida para produção
THRESHOLD_NOVA = 0.05       # >= 5.0% nos dados atuais → nova categoria incluída


def _base_dir() -> str:
    """Retorna o diretório raiz do projeto (V2/)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _carregar_medium_modelo_ativo() -> dict:
    """
    Carrega distribuição de Medium do modelo ativo (distribuicoes_esperadas.json).

    Returns:
        dict {categoria: proporção} do modelo ativo

    Raises:
        FileNotFoundError: se configs/active_model.yaml ou distribuicoes_esperadas.json
                           não existir — falha explicitamente (sem fallback).
    """
    base = _base_dir()
    config_path = os.path.join(base, 'configs', 'active_model.yaml')

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"configs/active_model.yaml não encontrado em {base}. "
            f"Configure o modelo ativo antes de treinar."
        )

    with open(config_path) as f:
        active_cfg = yaml.safe_load(f)

    model_path = active_cfg['active_model']['model_path']
    dist_path = os.path.join(base, model_path, 'distribuicoes_esperadas.json')

    if not os.path.exists(dist_path):
        raise FileNotFoundError(
            f"distribuicoes_esperadas.json não encontrado: {dist_path}. "
            f"O modelo ativo não tem metadados de distribuição. "
            f"Retreine com --save-files para gerar os metadados."
        )

    with open(dist_path) as f:
        distribuicoes = json.load(f)

    return distribuicoes.get('categorical', {}).get('Medium', {})


def unificar_medium_para_producao(
    df_medium_unificado: pd.DataFrame,
    n_bruto: int = None,
    n_apos_extracao: int = None,
    n_apos_norm: int = None,
) -> pd.DataFrame:
    """
    Unifica categorias Medium comparando dados atuais com modelo ativo.

    Categorias são classificadas automaticamente:
    - válida:         freq >= 2.5% nos dados atuais
    - descontinuada:  estava no modelo ativo E freq < 2.5% nos dados atuais → 'Outros'
    - nova >= 5%:     não estava no modelo ativo E freq >= 5% → incluída como válida
    - nova < 5%:      não estava no modelo ativo E freq < 5%  → 'Outros'

    Args:
        df_medium_unificado: DataFrame com Medium já extraído (output da célula 11)
        n_bruto: número de valores únicos brutos (antes do Passo 1), para o funil RESULTADO
        n_apos_extracao: valores únicos após Passo 1, para o funil RESULTADO
        n_apos_norm: valores únicos após Passo 2, para o funil RESULTADO

    Returns:
        DataFrame com Medium unificado para produção
    """
    df = df_medium_unificado.copy()

    if 'Medium' not in df.columns:
        logger.info("Coluna 'Medium' não encontrada")
        return df

    # 1. CARREGAR CATEGORIAS DO MODELO ATIVO
    medium_modelo_ativo = _carregar_medium_modelo_ativo()
    categorias_modelo_ativo = {
        cat for cat in medium_modelo_ativo.keys()
        if cat not in ('nan', 'Outros') and not (isinstance(cat, float))
    }
    # DEBUG: categorias do modelo ativo
    logger.debug(f"  Modelo ativo: {len(categorias_modelo_ativo)} categorias conhecidas")
    for cat, prop in sorted(medium_modelo_ativo.items(), key=lambda x: -x[1]):
        if cat == 'nan':
            continue
        suffix = "  ← agrupamento (não conta)" if cat == 'Outros' else ""
        logger.debug(f"    {cat}: {prop*100:.1f}%{suffix}")

    # 2. MAPEAMENTO DE VARIANTES (normalização de nomes históricos)
    # Mantido para consolidar variações de escrita do mesmo público.
    # Novos valores não presentes aqui são classificados por frequência no passo 3.
    mapping_dict = {
        # Lookalike 2% Cadastrados — variantes
        'Lookalike 2% Cadastrados - DEV 2.0 + Interesses':   'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Lookalike 2% Cadastrados - DEV 2.0   Interesses':   'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Lookalike 2%+Cadastrados - DEV 2.0   Interesses':   'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',
        'Lookalike% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação': 'Outros',
        'ADV+%7C+Lookalike+2%25+Cadastrados+-+DEV+2.0+%2B+Interesses': 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses',

        # Lookalike 2% Alunos — variantes
        'Lookalike 2% Alunos + Interesse Linguagem de Programação': 'Lookalike 2% Alunos + Interesse Linguagem de Programação',
        'Lookalike 2% Alunos   Interesse Linguagem de Programação': 'Lookalike 2% Alunos + Interesse Linguagem de Programação',
        'Lookalike 2% Alunos Interesse Ciência da Computação':       'Outros',
        'Lookalike 2% Alunos + Interesse Ciência da Computação':     'Outros',

        # Lookalike 1% Cadastrados — variantes
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação':    'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'Lookalike 1% Cadastrados - DEV 2.0   Interesse Ciência da Computação':    'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação',
        'Lookalike 1% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação': 'Outros',
        'Lookalike 1% Cadastrados - DEV 2.0   Interesse Linguagem de Programação': 'Outros',
        'Lookalike 1% Cadastrados - DEV 2.0 Interesse Linguagem de Programação':   'Outros',

        # Lookalike 3% — todos para Outros
        'Lookalike 3% Alunos + Interesses':                              'Outros',
        'Lookalike 3% Alunos + Interesse Ciência da Computação':         'Outros',
        'Lookalike 3% Alunos + Interesse Linguagem de Programação':      'Outros',
        'Lookalike 3% Alunos Interesse Ciência da Computação':           'Outros',
        'Lookalike 3% Cadastrados - DEV 2.0 + Interesses':              'Outros',
        'Lookalike 3% Cadastrados - DEV 2.0 + Interesse Ciência da Computação': 'Outros',
        'Lookalike 3% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação': 'Outros',

        # Lookalike Envolvimento — todos para Outros
        'Lookalike Envolvimento 30D Salvou 180D Direct 180D Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 30D   Salvou 180D   Direct 180D   Interesse Linguagem de Programação': 'Outros',
        'Lookalike Envolvimento 30D + Salvou80D + Direct80D + Interesse Linguagem de Programação': 'Outros',
        'Lookalike Envolvimento 30D + Salvou 180D + Direct 180D + Interesse Linguagem de Programação': 'Outros',
        'Lookalike Envolvimento 30D + Salvou 180D + Direct 180D + Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 60D Salvou 365D Direct 365D Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 60D + Salvou 365D + Direct 365D + Interesse Ciência da Computação': 'Outros',
        'Lookalike Envolvimento 60D + Salvou 365D + Direct 365D + Interesse Linguagem de Programação': 'Outros',

        # Interesse — variantes
        'Interesse Linguagem de programação':          'Linguagem de programação',
        'Interesse Programação':                       'Outros',
        'Interesse Python (linguagem de programação)': 'Outros',
        'Interesse Python':                            'Outros',
        'Interesse Ciência da computação':             'Outros',

        # Aberto — variantes
        'Aberto':             'Aberto',
        'Aberto++AD08-1002':  'Outros',

        # Outras canonicas
        'Linguagem de programação': 'Linguagem de programação',
        'dgen':                     'dgen',
        'nan':                      'nan',

        # Lixo / placeholders
        '{{adset.name}}':  'Outros',
        'paid':            'Outros',
        'Interesses':      'Outros',
        'search':          'Outros',
        'pmax':            'Outros',
        'gdn':             'Outros',
        'teste':           'Outros',
        '[field id="utm_medium"]': 'Outros',
        'ADV %7C Linguagem de programação': 'Outros',
        'Desenvolvimento profissional': 'Outros',
        'Funcionários de médias empresas B2B (200 a 500 funcionários)': 'Outros',
        'Funcionários de pequenas empresas B2B (10 a 200 funcionários)': 'Outros',
        'Funcionários de grandes empresas B2B (mais de 500 funcionários) — Cópia': 'Outros',
    }

    # Passo 3 — Classificação para produção
    logger.debug("")
    logger.info(f"  Passo 3 — Classificação para produção")

    # Pass 1 — classificar valores não mapeados por frequência
    freq_atual = df['Medium'].value_counts(normalize=True, dropna=True)
    novos_validos = set()
    novos_para_outros = set()

    for valor, freq in freq_atual.items():
        valor_str = str(valor)
        if valor_str in mapping_dict:
            continue
        if freq >= THRESHOLD_NOVA:
            novos_validos.add(valor_str)
            mapping_dict[valor_str] = valor_str
        else:
            novos_para_outros.add(valor_str)
            mapping_dict[valor_str] = 'Outros'

    if novos_para_outros:
        logger.debug(f"    Novos com freq < {THRESHOLD_NOVA*100:.0f}% → Outros: {sorted(novos_para_outros)}")

    # Aplicar mapping de variantes
    df['Medium'] = df['Medium'].apply(
        lambda v: mapping_dict.get(str(v), 'Outros') if not pd.isna(v) else v
    )

    # Pass 2 — classificar canônicas por frequência vs modelo ativo
    freq_canonical = df['Medium'].value_counts(normalize=True, dropna=True)

    categorias_validas = set()
    categorias_descontinuadas = set()

    for cat, freq in freq_canonical.items():
        if cat in ('Outros', 'nan'):
            continue
        if freq >= THRESHOLD_VALIDA:
            categorias_validas.add(cat)
        elif cat in categorias_modelo_ativo:
            categorias_descontinuadas.add(cat)

    # Mover descontinuadas para Outros
    if categorias_descontinuadas:
        df['Medium'] = df['Medium'].apply(
            lambda v: 'Outros' if v in categorias_descontinuadas else v
        )

    # Recalcular frequências após mover descontinuadas
    freq_canonical = df['Medium'].value_counts(normalize=True, dropna=True)

    # Tabela ATIVO / ATUAL / DELTA
    COL = 48
    SEP = '─' * (COL + 30)
    logger.info(f"")
    logger.info(f"    {'CATEGORIA':<{COL}} {'ATIVO':>6}  {'ATUAL':>6}  {'DELTA':>8}")
    logger.info(f"    {SEP}")

    for cat, prop_ativo in sorted(medium_modelo_ativo.items(), key=lambda x: -x[1]):
        if cat in ('nan', 'Outros'):
            continue
        freq_cat = freq_canonical.get(cat, 0)
        delta = freq_cat - prop_ativo
        delta_str = f"{delta*100:+.1f}pp"
        cat_display = cat if len(cat) <= COL else cat[:COL - 3] + '...'
        logger.info(f"    {cat_display:<{COL}} {prop_ativo*100:>5.1f}%  {freq_cat*100:>5.1f}%  {delta_str:>8}")

    for cat in sorted(novos_validos):
        freq_cat = freq_canonical.get(cat, 0)
        cat_display = cat if len(cat) <= COL else cat[:COL - 3] + '...'
        logger.info(f"    {cat_display:<{COL}} {'—':>6}  {freq_cat*100:>5.1f}%  {'★ nova':>8}")

    logger.info(f"    {SEP}")
    freq_outros = freq_canonical.get('Outros', 0)
    logger.info(f"    {'Outros  (agrupamento de categorias menores)':<{COL}} {'—':>6}  {freq_outros*100:>5.1f}%  {'—':>8}")
    logger.info(f"    {SEP}")
    logger.info(f"")

    # Alertas: descontinuadas e novas
    if categorias_descontinuadas:
        logger.info(f"    Descontinuadas (< {THRESHOLD_VALIDA*100:.0f}%, eram do modelo ativo) → Outros:")
        for cat in sorted(categorias_descontinuadas):
            logger.info(f"      ✗ {cat}")
    else:
        logger.info(f"    Descontinuadas: nenhuma")

    if novos_validos:
        logger.info(f"    Novas incluídas (>= {THRESHOLD_NOVA*100:.0f}%):")
        for cat in sorted(novos_validos):
            logger.info(f"      ★ {cat}")
    else:
        logger.info(f"    Novas incluídas: nenhuma")

    # Distribuição final com contagens absolutas (debug)
    n_final = df['Medium'].nunique()
    logger.debug("")
    logger.debug(f"Distribuição final ({n_final} categorias):")
    logger.debug("-" * 70)
    logger.debug(f"{'#':<3} {'CATEGORIA':<45} {'COUNT':<8} {'%':<6}")
    logger.debug("-" * 70)
    medium_final_vc = df['Medium'].value_counts(dropna=False)
    total_registros = len(df)
    for i, (valor, count) in enumerate(medium_final_vc.items(), 1):
        pct = count / total_registros * 100
        valor_str = str(valor) if pd.notna(valor) else 'nan'
        valor_display = valor_str if len(valor_str) <= 42 else valor_str[:39] + '...'
        logger.debug(f"{i:<3} {valor_display:<45} {count:<8,} {pct:<6.1f}%")

    # Funil RESULTADO
    logger.info(f"")
    partes_funnel = []
    if n_bruto is not None:
        partes_funnel.append(str(n_bruto))
    if n_apos_extracao is not None:
        partes_funnel.append(str(n_apos_extracao))
    if n_apos_norm is not None:
        partes_funnel.append(str(n_apos_norm))
    partes_funnel.append(f"{len(categorias_validas)} categorias + Outros")
    logger.info(f"  RESULTADO: {' → '.join(partes_funnel)}")
    logger.info("")

    return df


def relatorio_unificacao_producao(df_original: pd.DataFrame, df_unificado: pd.DataFrame):
    """
    Gera relatório detalhado da unificação para produção.

    Args:
        df_original: DataFrame antes da unificação
        df_unificado: DataFrame depois da unificação
    """
    # Confirmação detalhada da distribuição final (com counts absolutos)
    antes_count = df_original['Medium'].nunique()
    depois_count = df_unificado['Medium'].nunique()
    reducao = antes_count - depois_count
    reducao_pct = (reducao / antes_count) * 100 if antes_count > 0 else 0

    logger.debug(f"DISTRIBUIÇÃO FINAL — {antes_count} públicos → {depois_count} categorias finais ({reducao_pct:.1f}% de redução)")

    # Distribuição final
    logger.debug(f"\nDistribuição final das categorias:")
    logger.debug("-" * 70)
    logger.debug(f"{'#':<3} {'CATEGORIA':<45} {'COUNT':<8} {'%':<6}")
    logger.debug("-" * 70)

    medium_final = df_unificado['Medium'].value_counts(dropna=False)
    total_registros = len(df_unificado)

    for i, (valor, count) in enumerate(medium_final.items(), 1):
        pct = count / total_registros * 100
        valor_str = str(valor) if pd.notna(valor) else 'nan'

        if len(valor_str) > 42:
            valor_display = valor_str[:39] + '...'
        else:
            valor_display = valor_str

        logger.debug(f"{i:<3} {valor_display:<45} {count:<8,} {pct:<6.1f}%")

    # Verificação final das colunas que serão criadas no encoding
    logger.debug(f"COLUNAS ESPERADAS APÓS ONE-HOT ENCODING")

    categorias_para_encoding = df_unificado['Medium'].dropna().unique()

    logger.debug(f"Serão criadas {len(categorias_para_encoding)} colunas Medium_*:")
    for i, categoria in enumerate(sorted(categorias_para_encoding), 1):
        coluna_nome = (
            f"Medium_{str(categoria)}"
            .replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '')
            .replace('%', 'pct').replace('-', '_').replace('+', 'plus')
        )
        logger.debug(f"  {i:2d}. {coluna_nome}")

    logger.debug(f"\nNenhuma categoria descontinuada será criada no encoding ")
