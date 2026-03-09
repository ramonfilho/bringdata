"""
core/feature_engineering.py — Criação de features derivadas.

Consolida feature_engineering_training.py e engineering.py.
Canonical: treino (feature_engineering_training.py, dev/retreino).

Divergências resolvidas vs produção (engineering.py):
  - nome_valido, email_valido, telefone_valido: NÃO criados (noisy, removidos em dev/retreino)
  - telefone_comprimento grouping: mantido (treino canonical) — config.telefone_comprimento_keep_values
  - arquivo_origem guard: removido — core/ não depende de contexto de execução

Componente 2 da Fase 2.
Hardcodes migrados: #47 (pesquisa_name_column), #48 (columns_to_drop_after_fe), #157 (telefone grouping).
"""

from __future__ import annotations

import re
import logging
from typing import Optional

import pandas as pd

from .client_config import FeatureConfig

logger = logging.getLogger(__name__)


def _normalizar_telefone(telefone) -> Optional[str]:
    """Normaliza telefone para dígitos, removendo código de país 55 se presente."""
    if pd.isna(telefone):
        return None

    if isinstance(telefone, float):
        tel_str = str(int(telefone))
    else:
        tel_str = str(telefone)

    if 'e+' in tel_str.lower():
        try:
            tel_str = str(int(float(tel_str)))
        except Exception:
            pass

    if '.0' in tel_str:
        tel_str = tel_str.replace('.0', '')

    digitos = re.sub(r'\D', '', tel_str)

    if len(digitos) < 8:
        return None

    if digitos.startswith('55') and len(digitos) > 10:
        digitos = digitos[2:]

    if len(digitos) in [10, 11, 8, 9]:
        return digitos

    return None


def create_features(df: pd.DataFrame, config: FeatureConfig) -> pd.DataFrame:
    """
    Cria features derivadas e remove colunas desnecessárias.

    Features criadas:
        dia_semana          — dia da semana (0=segunda … 6=domingo)
        nome_comprimento    — len(config.pesquisa_name_column)
        nome_tem_sobrenome  — bool, >= 2 palavras no nome
        telefone_comprimento — len(telefone_normalizado); valores fora de
                               config.telefone_comprimento_keep_values → 'outros'

    Args:
        df:     DataFrame com colunas de pesquisa (Nome Completo, E-mail, Telefone, Data…)
        config: FeatureConfig carregada do YAML do cliente

    Returns:
        DataFrame com features derivadas e colunas brutas removidas.
    """
    df = df.copy()

    name_col  = config.pesquisa_name_column or 'Nome Completo'
    phone_col = config.pesquisa_phone_column or 'Telefone'

    # -----------------------------------------------------------------------
    # 1. Feature temporal — dia_semana
    # -----------------------------------------------------------------------
    if 'Data' in df.columns:
        if len(df) > 0:
            sample_date = df['Data'].iloc[0]
            if sample_date and isinstance(sample_date, str):
                if sample_date.strip()[:4].isdigit():
                    df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
                else:
                    df['Data'] = pd.to_datetime(df['Data'], format='%d/%m/%Y', errors='coerce')
            else:
                df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
        else:
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce')

        df['dia_semana'] = df['Data'].dt.dayofweek
        logger.debug(f"  FE: dia_semana criado ({df['Data'].isna().sum()} datas inválidas)")

    # -----------------------------------------------------------------------
    # 2. Features de nome
    # -----------------------------------------------------------------------
    if name_col in df.columns:
        df['nome_comprimento'] = df[name_col].astype(str).str.len()
        df['nome_tem_sobrenome'] = df[name_col].astype(str).str.split().str.len() >= 2
        logger.debug(f"  FE: nome_comprimento, nome_tem_sobrenome criados (col={name_col!r})")

    # -----------------------------------------------------------------------
    # 3. Features de telefone
    # -----------------------------------------------------------------------
    if phone_col in df.columns:
        df['telefone_normalizado'] = df[phone_col].apply(_normalizar_telefone)
        df['telefone_comprimento'] = df['telefone_normalizado'].astype(str).str.len()

        keep_values = config.telefone_comprimento_keep_values
        if keep_values:
            df['telefone_comprimento'] = df['telefone_comprimento'].apply(
                lambda x: x if x in keep_values else 'outros'
            )
            logger.debug(f"  FE: telefone_comprimento agrupado (keep={keep_values})")
        else:
            logger.warning("  FE: telefone_comprimento_keep_values não configurado — sem agrupamento")

    # -----------------------------------------------------------------------
    # 4. Remover colunas brutas
    # -----------------------------------------------------------------------
    colunas_remover = config.columns_to_drop_after_fe or []
    if not colunas_remover:
        logger.warning("  FE: columns_to_drop_after_fe não configurado — nenhuma coluna removida")
    else:
        colunas_existentes = [col for col in colunas_remover if col in df.columns]
        if colunas_existentes:
            df = df.drop(columns=colunas_existentes)
            logger.debug(f"  FE: {len(colunas_existentes)} colunas removidas")

    return df
