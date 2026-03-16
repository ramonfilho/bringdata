"""
core/medium.py — Unificação de Medium (consolida 3 arquivos atuais).

Substitui:
  - medium_training.py          (extração ADV + normalização de variantes)
  - medium_production_training.py (mapeamento + classificação por distribuição)
  - medium_unification.py       (versão produção — static mapping + whitelist)

Dois modos de operação, selecionados automaticamente por config.valid_categories:

  Modo treino  (config.valid_categories = None):
    Categorias com freq >= config.frequency_threshold → válidas
    Resto → 'Outros'
    Resultado: quais categorias existem é derivado dos dados do treinamento atual.

  Modo produção (config.valid_categories preenchido a partir do feature registry):
    Whitelist das categorias conhecidas pelo modelo
    Qualquer categoria fora da whitelist → 'Outros'
    Resultado: estrutura de colunas idêntica à do treino que gerou o modelo.

Componente 4 da Fase 2.
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from .client_config import MediumConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Funções auxiliares (privadas)
# ---------------------------------------------------------------------------

def _extrair_publico(v, adv_upper: str) -> object:
    """Remove prefixo 'ADV |' e retorna o nome do público."""
    if pd.isna(v):
        return v
    s = str(v).strip()
    if '|' in s:
        partes = s.split('|')
        if partes[0].strip().upper() in (adv_upper, adv_upper + ' '):
            return partes[1].strip()
        return partes[0].strip()
    return s


def _normalizar_para_comparacao(s: str) -> str:
    """Normaliza texto para comparação de variantes (case-insensitive, whitespace, trailing dot)."""
    return re.sub(r'\s+', ' ', s.lower().strip()).rstrip('.')


def _construir_mapa_normalizacao(df: pd.DataFrame) -> dict:
    """
    Detecta grupos de variantes de escrita (ex: 'Aberto' e 'ABERTO' são o mesmo público)
    e retorna um mapa {variante → representante canônico}.

    Regra de representante: preferir a versão não-all-caps mais frequente;
    fallback para a mais frequente independente de capitalização.
    """
    valores = df['Medium'].dropna().unique()
    mapa = {}
    processados: set = set()

    for v in valores:
        if v in processados:
            continue
        v_norm = _normalizar_para_comparacao(str(v))
        grupo = [v]
        for outro in valores:
            if outro != v and outro not in processados:
                if _normalizar_para_comparacao(str(outro)) == v_norm:
                    grupo.append(outro)
                    processados.add(outro)
        if len(grupo) > 1:
            contagens = [(x, int((df['Medium'] == x).sum())) for x in grupo]
            nao_allcaps = [(x, c) for x, c in contagens if str(x) != str(x).upper()]
            representante = max(nao_allcaps if nao_allcaps else contagens, key=lambda t: t[1])[0]
            for x in grupo:
                if x != representante:
                    mapa[x] = representante
        processados.add(v)

    return mapa


# ---------------------------------------------------------------------------
# Função pública
# ---------------------------------------------------------------------------

def unify_medium(df: pd.DataFrame, config: MediumConfig) -> pd.DataFrame:
    """
    Unifica coluna Medium em categorias canônicas.

    Passos:
      1. Extrai nome do público — remove prefixo ADV (config.adv_prefix)
      2. Normaliza variantes de escrita (case-insensitive dedup puro nos dados)
      3. Aplica mapeamento de variantes históricas (config.category_mappings)
      4. Aplica unificações adicionais opcionais (config.manual_unifications)
      5a. Modo treino  (config.valid_categories=None):
              freq >= config.frequency_threshold → mantém; resto → 'Outros'
      5b. Modo produção (config.valid_categories preenchido):
              whitelist; não-listadas → 'Outros'

    Args:
        df:     DataFrame com coluna 'Medium'
        config: MediumConfig carregado de configs/clients/{client}.yaml

    Returns:
        Novo DataFrame com Medium unificado.
    """
    if 'Medium' not in df.columns:
        logger.info("  Medium: coluna 'Medium' não encontrada — sem efeito")
        return df

    df = df.copy()
    n_bruto = df['Medium'].nunique()

    # ------------------------------------------------------------------
    # Passo 1 — Extração do nome do público (remove prefixo ADV)
    # ------------------------------------------------------------------
    adv_upper = (config.adv_prefix or 'ADV').upper()
    df['Medium'] = df['Medium'].apply(lambda v: _extrair_publico(v, adv_upper))
    n_apos_extracao = df['Medium'].nunique()
    logger.info(f"  Medium passo 1 (extração '{config.adv_prefix or 'ADV'} |'): "
                f"{n_bruto} → {n_apos_extracao} valores únicos")

    # ------------------------------------------------------------------
    # Passo 2 — Normalização de variantes de escrita (puro dos dados)
    # ------------------------------------------------------------------
    mapa_norm = _construir_mapa_normalizacao(df)
    if mapa_norm:
        df['Medium'] = df['Medium'].apply(
            lambda v: mapa_norm.get(v, v) if not pd.isna(v) else v
        )
        logger.debug(f"  Medium passo 2: {len(mapa_norm)} variantes normalizadas")
    n_apos_norm = df['Medium'].nunique()
    logger.info(f"  Medium passo 2 (normalização de variantes): "
                f"{n_apos_extracao} → {n_apos_norm} valores únicos")

    # ------------------------------------------------------------------
    # Passo 3 — Mapeamento de variantes históricas (config.category_mappings)
    # ------------------------------------------------------------------
    if config.category_mappings:
        mapping = config.category_mappings
        df['Medium'] = df['Medium'].apply(
            lambda v: mapping.get(str(v), str(v)) if not pd.isna(v) else v
        )
        logger.debug(f"  Medium passo 3: category_mappings aplicado "
                     f"({len(mapping)} entradas)")

    # ------------------------------------------------------------------
    # Passo 4 — Unificações adicionais opcionais (config.manual_unifications)
    # ------------------------------------------------------------------
    if config.manual_unifications:
        extra = config.manual_unifications
        df['Medium'] = df['Medium'].apply(
            lambda v: extra.get(str(v), str(v)) if not pd.isna(v) else v
        )
        logger.debug(f"  Medium passo 4: manual_unifications aplicado "
                     f"({len(extra)} entradas)")

    # ------------------------------------------------------------------
    # Passo 5 — Classificação de categorias válidas
    # ------------------------------------------------------------------
    SKIP = {'Outros', 'nan'}

    if config.valid_categories is not None:
        # ---- Modo produção: whitelist do feature registry ----
        valid_set = set(config.valid_categories)
        df['Medium'] = df['Medium'].apply(
            lambda v: v if (pd.isna(v) or str(v) in valid_set or str(v) in SKIP)
                      else 'Outros'
        )
        n_final = df['Medium'].nunique()
        logger.info(f"  Medium passo 5 (produção — whitelist {len(valid_set)} categorias): "
                    f"{n_final} valores únicos")

    else:
        # ---- Modo treino: frequência nos dados atuais ----
        threshold = config.frequency_threshold
        freq = df['Medium'].value_counts(normalize=True, dropna=True)
        categorias_validas = {
            cat for cat, f in freq.items()
            if f >= threshold and cat not in SKIP
        }
        df['Medium'] = df['Medium'].apply(
            lambda v: v if (pd.isna(v) or str(v) in categorias_validas or str(v) in SKIP)
                      else 'Outros'
        )
        n_final = df['Medium'].nunique()

        # Log detalhado das categorias válidas encontradas
        logger.info(f"  Medium passo 5 (treino — threshold {threshold * 100:.1f}%): "
                    f"{len(categorias_validas)} categorias válidas + Outros")
        for cat in sorted(categorias_validas):
            f = freq.get(cat, 0)
            logger.debug(f"    ✓ {cat}: {f * 100:.1f}%")

        # Categorias abaixo do threshold (colocadas em Outros)
        abaixo = {
            cat: f for cat, f in freq.items()
            if cat not in SKIP and cat not in categorias_validas
        }
        if abaixo:
            logger.debug(f"  → Outros ({len(abaixo)} categorias abaixo de {threshold * 100:.1f}%):")
            for cat, f in sorted(abaixo.items(), key=lambda t: -t[1]):
                logger.debug(f"    ✗ {cat}: {f * 100:.1f}%")

        logger.info(f"  Medium resultado: {n_bruto} → {n_apos_extracao} → "
                    f"{n_apos_norm} → {n_final} valores únicos")

    return df
