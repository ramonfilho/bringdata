"""src/data/audience_reader.py — monta os DOIS conjuntos de membros dos públicos
da Meta (Custom Audiences), no shape mínimo `{email, phone}`, deduplicado por email.

Papel na arquitetura (padrão Repositório/Adaptador): isola "de onde vêm os membros"
do cliente da Graph API (`api/meta_audiences.py`). Ele pede "os leads" ou "os
alunos" e recebe uma lista de pessoas, sem saber que leads = união de duas bases
(Cloud SQL + Railway) nem que alunos = a tabela de vendas.

Fontes (decididas com o operador, 20/07/2026):
  LEADS  = TODOS os leads (respondentes da pesquisa OU não). União de:
             (a) `analytics.leads` source=`respondents_source` (Cloud SQL, fresco;
                 nome CONFIGURÁVEL — hoje `leads_treino_prod`, era `train_unified`) —
                 só respondentes, mas histórico completo (~325k, email+telefone);
             (b) `Client` (Railway, base do front) — todos os cadastros, inclusive
                 quem não respondeu, desde ~mar/2026 (~109k, email+telefone).
           Deduplicado por email (mantém o telefone quando qualquer fonte tiver).
  ALUNOS = compradores. `analytics.sales`, todos os gateways, dedup por email.
           (Email em ~100%; telefone só ~58% — a TMB, 64% das vendas, não traz
           telefone. Não é problema: a Meta casa por email OU telefone.)

Reusa as conexões que já existem (não reinventa driver): `open_analytics_connection`
(Cloud SQL) e `cadastro_records.open_railway_connection` (Railway), e o
`sales_reader.read_sales` pro público de alunos.

SEGURANÇA (fail-loud): estes conjuntos alimentam um REPLACE de membros na conta do
cliente — se o reader devolvesse vazio por um soluço de banco, o público seria
ZERADO. Por isso `min_size` levanta erro em vez de devolver lista curta silenciosa.
Quem escreve (meta_audiences) NUNCA deve substituir por um conjunto suspeito.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from src.data.analytics_connection import open_analytics_connection
from src.data.cadastro_records import open_railway_connection
from src.data.sales_reader import read_sales

# Import do normalizador canônico de email (mesma regra que o hasher usa depois).
# api/ está no sys.path em runtime (o CLI insere o V2 root, igual etl_sales).
from api.pii_hashing import normalize_email

logger = logging.getLogger(__name__)

# Pisos de sanidade: abaixo disso, algo quebrou (não é um público real). São
# ordens de grandeza abaixo dos valores observados (leads ~325k, alunos ~10k) —
# não é um alvo, é um alarme de "isso não pode estar certo".
_MIN_LEADS = 50_000
_MIN_BUYERS = 3_000
_MIN_CARDONLY = 2_000   # público SÓ CARTÃO é subconjunto dos alunos (~2,8k hoje); piso = alarme, não alvo

# Nome da source unificada de respondentes no `analytics.leads`. Default = o nome
# ATUAL (a fonte foi renomeada `train_unified` → `leads_treino_prod` em 21/07 por
# um deploy de ingestão fora da main). É só o default; o valor de produção vem de
# `meta_audiences.leads_source` no yaml do cliente e é passado pelo CLI.
def _default_respondents_source() -> str:
    """Default = o dono único do nome (`ingestion.leads_unified_source` no config).

    Era uma terceira cópia literal do nome. Em produção o valor chega injetado pelo CLI
    (`meta_audiences.leads_source`, que por sua vez herda do dono), então este default só
    vale pra chamada direta — mas manter uma cópia literal aqui era exatamente o padrão
    que deixou escritor e leitor divergirem por 9 dias.
    """
    from src.data.leads_unify import unified_source

    return unified_source()


_DEFAULT_RESPONDENTS_SOURCE = _default_respondents_source()


def _dedup_by_email(df: pd.DataFrame) -> pd.DataFrame:
    """Recebe DataFrame com colunas email/phone (nomes já normalizados p/ 'email',
    'phone'); devolve 1 linha por email normalizado, preferindo a linha que TEM
    telefone. Descarta linhas sem email (email é a chave; são raras, <0.1%)."""
    out = df.copy()
    out["email"] = out["email"].map(normalize_email)
    out = out[out["email"].notna()]
    # 1 = tem telefone (não vazio), 0 = não. Ordena telefone-primeiro e mantém o 1º.
    out["_has_phone"] = out["phone"].map(
        lambda p: 0 if (p is None or str(p).strip() == "" or str(p).strip().lower() == "none") else 1
    )
    out = out.sort_values("_has_phone", ascending=False).drop_duplicates("email", keep="first")
    return out[["email", "phone"]].reset_index(drop=True)


def read_buyers_audience(
    client_id: str = "devclub",
    *,
    conn=None,
    min_size: int = _MIN_BUYERS,
) -> pd.DataFrame:
    """Público de ALUNOS: compradores distintos (todos os gateways) → {email, phone}.

    Reusa `sales_reader.read_sales` (mesma fonte/shape do pipeline) e só reduz a
    email+telefone distinto. Levanta ValueError se vier abaixo de `min_size`.
    """
    sales = read_sales(client_id=client_id, gateways=None, conn=conn)  # todos os gateways
    if sales.empty:
        raise ValueError("[audience_reader] analytics.sales vazio — não substituo público de alunos.")
    df = sales.rename(columns={"telefone": "phone"})[["email", "phone"]]
    result = _dedup_by_email(df)
    n = len(result)
    logger.info("[audience_reader] alunos: %d compradores únicos (%d com telefone)",
                n, int((result["phone"].map(lambda p: bool(p) and str(p).strip() not in ('', 'None'))).sum()))
    if n < min_size:
        raise ValueError(f"[audience_reader] só {n} alunos (< {min_size}) — suspeito, abortando.")
    return result


def read_cardonly_audience(
    client_id: str = "devclub",
    *,
    conn=None,
    card_gateways=None,
    boleto_gateways=None,
    min_size: int = _MIN_CARDONLY,
) -> pd.DataFrame:
    """Público de ALUNOS SÓ CARTÃO: compradores cujas compras são TODAS em gateways
    de cartão (`card_gateways`) e NENHUMA em gateway de boleto (`boleto_gateways`).

    A régua gateway→forma-de-pagamento é do cliente (no DevClub: Guru/Hotmart =
    cartão; TMB/boletex/Asaas = boleto) e vem do YAML — nunca cravada aqui. Reusa
    `read_sales` (mesma fonte/shape do público de alunos) e `_dedup_by_email`; só
    acrescenta a partição por gateway NO NÍVEL DO EMAIL (não do pedido: quem comprou
    1x no cartão e 1x no boleto NÃO entra — é 'apenas cartão')."""
    card = {g for g in (card_gateways or [])}
    boleto = {g for g in (boleto_gateways or [])}
    if not card:
        raise ValueError("[audience_reader] card_gateways vazio — não monto o público de cartão "
                         "(configure meta_audiences.card_gateways no yaml).")
    sales = read_sales(client_id=client_id, gateways=None, conn=conn)  # todos os gateways
    if sales.empty:
        raise ValueError("[audience_reader] analytics.sales vazio — não substituo público de cartão.")
    df = sales.rename(columns={"telefone": "phone"}).copy()
    df["_em"] = df["email"].map(normalize_email)
    df = df[df["_em"].notna()]
    # Por email: comprou em cartão? comprou em boleto? ('origem' = gateway, do read_sales)
    gws_por_email = df.groupby("_em")["origem"].agg(lambda s: set(s))
    so_cartao = gws_por_email[
        gws_por_email.map(lambda gws: bool(gws & card) and not (gws & boleto))
    ].index
    only = df[df["_em"].isin(so_cartao)]
    result = _dedup_by_email(only[["email", "phone"]])
    n = len(result)
    com_tel = int(result["phone"].map(
        lambda p: 0 if (p is None or str(p).strip() == "" or str(p).strip().lower() == "none") else 1
    ).sum())
    logger.info("[audience_reader] só-cartão: %d compradores (%d com telefone) | cartão=%s boleto=%s",
                n, com_tel, sorted(card), sorted(boleto))
    if n < min_size:
        raise ValueError(f"[audience_reader] só {n} alunos de cartão (< {min_size}) — suspeito, abortando.")
    return result


def read_leads_audience(
    client_id: str = "devclub",
    *,
    conn_analytics=None,
    conn_railway=None,
    respondents_source: str = _DEFAULT_RESPONDENTS_SOURCE,
    min_size: int = _MIN_LEADS,
) -> pd.DataFrame:
    """Público de LEADS: união de respondentes (Cloud SQL, source=`respondents_source`)
    + todos os cadastros (Railway, Client) → {email, phone} deduplicado por email.

    `respondents_source` é CONFIGURÁVEL (não cravado) porque o nome da fonte
    unificada já mudou uma vez sem aviso (era `train_unified`, virou
    `leads_treino_prod` em 21/07 num deploy de ingestão que não foi pra main) e
    deixou o job lendo 0 → público degradado. Vem de `meta_audiences.leads_source`
    no yaml, então re-apontar é 1 linha, sem deploy de código.

    FAIL-LOUD: se a fonte de respondentes vier VAZIA, levanta erro ANTES de qualquer
    escrita (nome de source stale não pode virar replace silencioso pela metade — foi
    o que aconteceu em 21/07). Também levanta se a união ficar abaixo de `min_size`.
    """
    # (a) Respondentes — Cloud SQL analytics.leads, fonte unificada e fresca.
    own_a = conn_analytics is None
    conn_a = conn_analytics or open_analytics_connection()
    try:
        rows_resp = conn_a.run(
            "SELECT email, phone FROM analytics.leads "
            "WHERE client_id = :c AND source = :src "
            "AND email IS NOT NULL AND email <> ''",
            c=client_id, src=respondents_source,
        )
    finally:
        if own_a:
            conn_a.close()
    df_resp = pd.DataFrame(rows_resp, columns=["email", "phone"])
    logger.info("[audience_reader] leads/respondentes (Cloud SQL source=%s): %d", respondents_source, len(df_resp))
    if df_resp.empty:
        raise ValueError(
            f"[audience_reader] fonte de respondentes '{respondents_source}' VAZIA — "
            "provável rename da source no pipeline (ver meta_audiences.leads_source no yaml). "
            "Abortando ANTES de escrever pra não degradar o público."
        )

    # (b) Todos os cadastros — Railway Client (base do front). Client é mono-cliente
    # (devclub) no Railway, então não há filtro de client_id lá.
    own_r = conn_railway is None
    conn_r = conn_railway or open_railway_connection()
    try:
        rows_cad = conn_r.run(
            'SELECT LOWER(TRIM(email)) AS email, phone FROM "Client" '
            "WHERE email IS NOT NULL AND email <> ''"
        )
    finally:
        if own_r:
            conn_r.close()
    df_cad = pd.DataFrame(rows_cad, columns=["email", "phone"])
    logger.info("[audience_reader] leads/cadastros (Railway Client): %d", len(df_cad))

    if df_resp.empty and df_cad.empty:
        raise ValueError("[audience_reader] ambas as fontes de leads vazias — não substituo o público.")

    combined = pd.concat([df_resp, df_cad], ignore_index=True)
    result = _dedup_by_email(combined)
    n = len(result)
    n_phone = int((result["phone"].map(lambda p: bool(p) and str(p).strip() not in ('', 'None'))).sum())
    logger.info("[audience_reader] leads (união dedup por email): %d pessoas (%d com telefone)", n, n_phone)
    if n < min_size:
        raise ValueError(f"[audience_reader] só {n} leads (< {min_size}) — suspeito, abortando.")
    return result
