"""
core/feature_engineering.py — Criação de features derivadas.

Consolida feature_engineering_training.py e engineering.py.
Canonical: treino (feature_engineering_training.py, dev/retreino).

Divergências resolvidas vs produção (engineering.py):
  - nome_valido, email_valido, telefone_valido: config-driven via
    FeatureConfig.create_valido_features (default False). Champion jan30
    (ativo) depende dessas 3 features — OHE gera 6 colunas binárias
    usadas no scoring. Portado do rollback edf23e9 em 2026-04-23 como
    Porte #2 da Fase 3 de unificação.
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


def _validar_email(email) -> bool:
    """
    [Porte #2] Valida email via regex clássico. Portado do rollback edf23e9.

    Retorna True se o valor tem formato de email (usuário@dominio.tld).
    Usado em create_valido_features para gerar feature binária email_valido.
    """
    if pd.isna(email):
        return False
    email_str = str(email).strip().lower()
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email_str))


def _validar_nome(nome) -> bool:
    """
    [Porte #2] Valida se nome é plausível (tem letras, não é só números, len >= 2).
    Portado do rollback edf23e9.
    """
    if pd.isna(nome):
        return False
    nome_str = str(nome).strip()
    tem_letras = bool(re.search(r'[a-zA-ZÀ-ÿ]', nome_str))
    nao_so_numeros = not nome_str.replace(' ', '').replace('.', '').replace('-', '').isdigit()
    return tem_letras and nao_so_numeros and len(nome_str) >= 2


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
    # 3b. [Porte #2] Features de validação — config-driven
    # -----------------------------------------------------------------------
    # Champion jan30 (ativo) depende de nome_valido_True/False, email_valido_True/False,
    # telefone_valido_True/False após OHE. Mantido atrás de flag para que modelos
    # futuros treinados sem essas features (ex: Challenger mar24) não paguem
    # o custo de features não usadas.
    if config.create_valido_features:
        if name_col in df.columns:
            df['nome_valido'] = df[name_col].apply(_validar_nome)
            logger.debug(f"  FE: nome_valido criado ({df['nome_valido'].mean()*100:.1f}% válidos)")

        email_col = config.pesquisa_email_column
        if email_col and email_col in df.columns:
            df['email_valido'] = df[email_col].apply(_validar_email)
            logger.debug(f"  FE: email_valido criado ({df['email_valido'].mean()*100:.1f}% válidos)")
        elif email_col:
            logger.warning(f"  FE: create_valido_features=true mas coluna {email_col!r} não existe — email_valido não criado")

        if 'telefone_normalizado' in df.columns:
            df['telefone_valido'] = df['telefone_normalizado'].notna()
            logger.debug(f"  FE: telefone_valido criado ({df['telefone_valido'].mean()*100:.1f}% válidos)")

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
