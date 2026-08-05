"""Nota do criativo como feature numérica, calculada ponto a ponto no tempo.

O pipeline remove `Content` (o nome do anúncio) de propósito, em
`feature_removal.remover_features_desnecessarias`, com o motivo certo: identidade de
anúncio como categoria faz o modelo decorar lançamento em vez de aprender sobre a pessoa.

Esta é a versão segura daquilo. Em vez da identidade, entra UM NÚMERO: quanto aquele
criativo convertia **antes da semana em que o lead entrou**. Não é categoria, não guarda
qual anúncio era, e não pode conter o futuro.

    lift  = conversão do criativo ÷ conversão do período
    peso  = n ÷ (n + K)                    <- encolhimento empírico de Bayes
    NOTA  = peso × lift + (1 − peso) × 1,0

O encolhimento é o que faz funcionar: sem ele (K=0) a nota fica PIOR que chutar a média,
porque criativo com 300 leads e 9 compradores receberia nota 3,0 e sequestraria o ranking.

Validação offline que motivou esta feature (sessão 083c887b, 03-05/08/2026):
  · leave-one-launch-out, 224 pares criativo×lançamento: erro −28%, separação 1,83x
  · composto com o modelo: lift do D10 de 1,69x para 2,93x, top 10% de 65 para 88
    compradores, positivo em 100% de 400 reamostras de criativos inteiros
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

K_ENCOLHIMENTO = 4000     # varrido em [0, 250, ..., 16000]; 4000 foi o melhor, 2000 empata
MIN_HIST = 50             # histórico mínimo do criativo para ele ganhar nota própria
MIN_HIST_PERIODO = 20_000  # leads mínimos no passado para a semana ser calculável
NOTA_NEUTRA = 1.0         # criativo sem histórico não é bom nem ruim


def _carrega_historico() -> pd.DataFrame:
    """Histórico de captação com desfecho, de `analytics.captacoes`."""
    from src.data.analytics_connection import open_analytics_connection

    conn = open_analytics_connection(timeout=900)
    try:
        # utm_content, não ad_name: a coluna do treino também é utm_content, e casar por
        # ela cobre 61% dos leads contra 54% do ad_name (que é uma versão normalizada,
        # com 1.287 nomes distintos contra 1.969). A união não acrescenta nada.
        linhas = conn.run("""
            SELECT utm_content, captured_at::date, bought_45d
            FROM captacoes
            WHERE utm_content IS NOT NULL AND captured_at IS NOT NULL
        """)
    finally:
        conn.close()
    hist = pd.DataFrame(linhas, columns=["criativo", "dia", "buy"])
    hist["dia"] = pd.to_datetime(hist["dia"])
    hist["buy"] = pd.to_numeric(hist["buy"], errors="coerce").fillna(0).astype(int)
    hist["criativo"] = hist["criativo"].astype(str).str.strip()
    return hist


def _notas_da_semana(hist_ate_aqui: pd.DataFrame) -> dict:
    """NOTA por criativo, usando SÓ o histórico passado como argumento."""
    if len(hist_ate_aqui) < MIN_HIST_PERIODO:
        return {}
    nivel = hist_ate_aqui["buy"].mean()
    if nivel <= 0:
        return {}
    g = hist_ate_aqui.groupby("criativo").agg(n=("buy", "size"), k=("buy", "sum"))
    g = g[g["n"] >= MIN_HIST]
    if g.empty:
        return {}
    lift = (g["k"] / g["n"]) / nivel
    peso = g["n"] / (g["n"] + K_ENCOLHIMENTO)
    return (peso * lift + (1 - peso) * NOTA_NEUTRA).to_dict()


def adicionar_nota_criativo(df: pd.DataFrame, *, col_criativo: str = "Content",
                            col_data: str = "Data", nome_saida: str = "nota_criativo",
                            historico: pd.DataFrame | None = None,
                            cobertura_minima: float = 0.30) -> pd.DataFrame:
    """Devolve o df com a coluna `nota_criativo`, calculada ponto a ponto no tempo.

    Para cada SEMANA presente no df, a nota sai só das captações anteriores àquela semana.
    Um lead de junho recebe a nota que o criativo dele tinha em junho, nunca a de hoje.

    Falha alto se as colunas de origem sumirem ou se a cobertura vier abaixo do piso: nota
    neutra em quase todo mundo significa feature inerte, e isso tem que aparecer no log em
    vez de virar uma coluna de 1,0 que ninguém percebe.
    """
    faltando = [c for c in (col_criativo, col_data) if c not in df.columns]
    if faltando:
        raise KeyError(
            f"[nota_criativo] coluna(s) ausente(s): {faltando}. A nota precisa do nome do "
            f"anúncio e da data do lead, e ambas somem na Célula 8 — chame esta função ANTES "
            f"de remover_features_desnecessarias()."
        )

    hist = _carrega_historico() if historico is None else historico.copy()
    logger.info(f"  [nota_criativo] histórico: {len(hist):,} captações · "
                f"{hist['criativo'].nunique():,} criativos · "
                f"{int(hist['buy'].sum()):,} compradores")

    data = pd.to_datetime(df[col_data], errors="coerce")
    criativo = df[col_criativo].astype(str).str.strip()
    semana = data.dt.to_period("W")

    notas_por_semana: dict = {}
    for sem in sorted(s for s in semana.dropna().unique()):
        notas_por_semana[sem] = _notas_da_semana(hist[hist["dia"] < sem.start_time])

    nota = np.array([
        notas_por_semana.get(s, {}).get(c, NOTA_NEUTRA) if pd.notna(s) else NOTA_NEUTRA
        for s, c in zip(semana, criativo)
    ], dtype=float)

    out = df.copy()
    out[nome_saida] = nota
    cobertura = float((nota != NOTA_NEUTRA).mean())
    logger.info(f"  [nota_criativo] {len(out):,} leads · cobertura {cobertura*100:.1f}% "
                f"(o resto fica em {NOTA_NEUTRA:.1f}, que é neutro)")
    logger.info(f"  [nota_criativo] nota: mediana {np.median(nota):.2f} · "
                f"p5 {np.percentile(nota, 5):.2f} · p95 {np.percentile(nota, 95):.2f}")
    if cobertura < cobertura_minima:
        raise ValueError(
            f"[nota_criativo] cobertura {cobertura*100:.1f}% abaixo do piso de "
            f"{cobertura_minima*100:.0f}%. Com quase todo mundo em nota neutra a feature é "
            f"inerte e o treino sairia igual ao sem ela. Verifique se `{col_criativo}` "
            f"casa com `captacoes.utm_content` (mesma nomenclatura de anúncio)."
        )
    return out
