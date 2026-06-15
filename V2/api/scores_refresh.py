"""Refresh incremental ONLINE da tabela `scores_historicos` (Cloud SQL ledger).

Roda DENTRO do job que emite o relatório das 06:00 (daily_monitoring_check_railway),
SÓ na run ao vivo (`anchor_date is None`). Re-scoreia pelos DOIS modelos do A/B
apenas os leads NOVOS do lançamento atual (delta vs o que já está na tabela) e
faz upsert idempotente. A tabela é a fonte do "score geral do lançamento".

Por que mora em api/ e não em src/: ORQUESTRA peças do topo — `railway_mapping`
(api/), o `LeadScoringPipeline` já instanciado (src/) e o contrato da tabela
(`src/data/scores_historicos`). Manter aqui preserva a direção de dependência
(api → src; nunca src → api).

Caminho de scoring = o MESMO de produção, in-image: predictors de variante já
carregados no pipeline (`get_variant_predictor`) + `atribuir_decis_batch` sobre os
thresholds do metadata do modelo. NÃO faz self-load por run_id (paridade com o
A/B ao vivo + zero recarga de artefato). Os run_ids vêm do A/B config (não
hardcode) → os mesmos do backfill, então o `score_geral` mistura versões iguais.

Tudo guardado pelo chamador: qualquer falha aqui NÃO pode derrubar o relatório.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Teto de leads re-scoreados por run — protege o job das 06:00 de um caso
# patológico (janela enorme, tabela vazia). Uma semana de captação ~8k; o delta
# diário é ~centenas. Se estourar, processa o teto e o resto entra na próxima
# run (ON CONFLICT garante que nada duplica). NUNCA truncar em silêncio: loga.
MAX_LEADS_POR_RUN = 6000


def _resolve_variantes(pipeline) -> Optional[Dict[str, Dict[str, Any]]]:
    """Mapeia champion/challenger → (variant_name, run_id, encoding_overrides) a
    partir do A/B config do pipeline. Champion = variante cujo run_id == o do
    active_model (pipeline.predictor); challenger = a outra. Retorna None se o
    A/B não está habilitado ou não dá pra identificar os dois papéis."""
    ab = getattr(pipeline, "_ab_test_config", None)
    if not ab or not getattr(ab, "enabled", False):
        return None
    variants = getattr(ab, "variants", None) or {}
    if len(variants) < 2:
        return None
    champ_run = getattr(getattr(pipeline, "predictor", None), "mlflow_run_id", None)
    if not champ_run:
        return None

    champion = challenger = None
    for vname, v in variants.items():
        run_id = getattr(v, "run_id", None)
        info = {
            "variant_name": vname,
            "run_id": run_id,
            "encoding_overrides": getattr(v, "encoding_overrides", None),
        }
        if run_id == champ_run and champion is None:
            champion = info
        else:
            challenger = info
    if not champion or not challenger or not challenger["run_id"]:
        return None
    return {"champion": champion, "challenger": challenger}


def _load_launch_leads(railway_conn, cap_start: str, cap_end: str) -> pd.DataFrame:
    """Leads scoráveis da janela de captação, do `registros_ml` (ledger vivo) →
    formato Sheets. Equivale ao `load_ledger_window` de gerar_scores_2026 (que
    vive em scripts/, fora da imagem): mesma query, mesmo mapeamento, pra que o
    delta online use a MESMA definição de janela do backfill. `has_computer` vem
    do payload ('SIM'/'NAO', 100% fill em quem respondeu pesquisa)."""
    from api.railway_mapping import railway_lead_to_sheets_row

    end_excl = (pd.to_datetime(cap_end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    rows = railway_conn.run(
        """
        SELECT email, phone, first_name, last_name, created_at, survey_responses,
               utm_source, utm_medium, utm_campaign, utm_content, utm_term,
               has_computer
        FROM registros_ml
        WHERE created_at >= :s AND created_at < :e
          AND email IS NOT NULL AND survey_responses IS NOT NULL
        ORDER BY created_at
        """,
        s=cap_start, e=end_excl,
    )

    out_rows = []
    for (email, phone, fn, ln, created, sr, src, med, camp, cont, term, has_comp) in rows:
        pesq = json.loads(sr) if isinstance(sr, str) else dict(sr or {})
        pesq["computador"] = has_comp
        nome = " ".join(p for p in [fn, ln] if p) or None
        row = railway_lead_to_sheets_row({
            "email": email, "nomeCompleto": nome, "telefone": phone,
            "data": created, "source": src, "medium": med, "campaign": camp,
            "content": cont, "term": term, "pesquisa": pesq,
        })
        out_rows.append(row)

    df = pd.DataFrame(out_rows)
    if not len(df):
        return df
    # colunas canônicas p/ merge/re-attach (mesma normalização do loader CLI)
    if "email" not in df.columns:
        for alias in ("E-mail", "e-mail", "Email"):
            if alias in df.columns:
                df["email"] = df[alias]
                break
    df["email"] = df["email"].astype(str).str.lower().str.strip()
    df = df[df["email"].str.contains("@", na=False)]
    if "data_captura" not in df.columns:
        for alias in ("Data", "data", "createdAt"):
            if alias in df.columns:
                df["data_captura"] = df[alias]
                break
    df["data_captura"] = pd.to_datetime(df["data_captura"], errors="coerce")
    df = df.drop_duplicates(subset=["email"], keep="first").reset_index(drop=True)
    return df


def _score_population(leads_df: pd.DataFrame, predictor, encoding_overrides,
                      label: str, pipeline) -> pd.DataFrame:
    """Re-score in-image via pipeline.run com predictor de variante injetado —
    mesmo round-trip CSV e enforce_post_encoding=False do score_with_model do
    backfill (paridade). Decil pelos thresholds do metadata do modelo +
    atribuir_decis_batch (formato D01-D10, idêntico ao backfill nos bins; só
    difere em valor exatamente na borda, caso de medida nula)."""
    from src.model.decil_thresholds import atribuir_decis_batch

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        leads_df.to_csv(tmp_path, index=False)
        scored = pipeline.run(
            filepath=tmp_path,
            with_predictions=True,
            predictor_override=predictor,
            encoding_overrides=encoding_overrides,
            enforce_post_encoding=False,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if "lead_score" not in scored.columns:
        for alt in ("probability", "score", "prediction_proba"):
            if alt in scored.columns:
                scored["lead_score"] = scored[alt]
                break
        else:
            raise RuntimeError(f"score não encontrado. Cols: {list(scored.columns)[:20]}")
    if "email" not in scored.columns:
        n = min(len(scored), len(leads_df))
        scored = scored.iloc[:n].reset_index(drop=True)
        scored["email"] = leads_df["email"].iloc[:n].values

    thresholds = (predictor.metadata or {}).get("decil_thresholds", {}).get("thresholds")
    if not thresholds:
        raise RuntimeError(f"thresholds ausentes no metadata ({label})")
    scored[f"decil_{label}"] = atribuir_decis_batch(scored["lead_score"].values, thresholds)
    scored = scored.rename(columns={"lead_score": f"score_{label}"})
    return scored[["email", f"score_{label}", f"decil_{label}"]].drop_duplicates("email")


def refresh_launch_scores(
    *,
    lf_name: str,
    cap_start: str,
    cap_end: str,
    pipeline,
    railway_conn=None,
    ledger_conn=None,
    max_leads: int = MAX_LEADS_POR_RUN,
    core_commit: Optional[str] = None,
) -> Dict[str, Any]:
    """Refresh incremental do lançamento atual em `scores_historicos`.

    Re-scoreia pelos 2 modelos só os leads NOVOS (não presentes na tabela pro par
    de run_ids) da janela [cap_start, cap_end] e faz upsert idempotente.

    Args:
        lf_name: nome do lançamento (ex.: 'LF59'). Vazio → no-op.
        cap_start, cap_end: datas ISO 'YYYY-MM-DD' (BRT) — mesma janela do backfill.
        pipeline: LeadScoringPipeline já instanciado (com A/B carregado).
        railway_conn, ledger_conn: conexões opcionais (injetadas); se None, abre
            e fecha as próprias.
        max_leads: teto de leads re-scoreados nesta run.
        core_commit: marca de proveniência; default = revisão do Cloud Run.

    Returns:
        dict resumo {status, ...}. status ∈ {ok, noop, skipped}. Nunca levanta por
        conta de "nada a fazer"; exceções reais sobem pro guard do chamador.
    """
    if not lf_name:
        return {"status": "skipped", "reason": "lf_name vazio"}
    if pipeline is None:
        return {"status": "skipped", "reason": "pipeline indisponível"}

    papeis = _resolve_variantes(pipeline)
    if not papeis:
        return {"status": "skipped", "reason": "A/B não habilitado / variantes não identificadas"}
    champ, chall = papeis["champion"], papeis["challenger"]

    own_railway = railway_conn is None
    own_ledger = ledger_conn is None
    if own_railway:
        import pg8000.native
        railway_conn = pg8000.native.Connection(
            host=os.environ["RAILWAY_DB_HOST"],
            port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
            database=os.environ.get("RAILWAY_DB_NAME", "railway"),
            user=os.environ.get("RAILWAY_DB_USER", "postgres"),
            password=os.environ["RAILWAY_DB_PASSWORD"],
            timeout=30,
        )
    try:
        from src.data.scores_historicos import (
            _cloudsql_conn, existing_score_emails, upsert_scores,
        )
        if own_ledger:
            ledger_conn = _cloudsql_conn()
        try:
            existing = existing_score_emails(
                ledger_conn, lf_name, champ["run_id"], chall["run_id"]
            )
            leads = _load_launch_leads(railway_conn, cap_start, cap_end)
            total_janela = len(leads)
            if total_janela:
                leads = leads[~leads["email"].isin(existing)].reset_index(drop=True)
            novos = len(leads)
            if novos == 0:
                return {"status": "noop", "existing": len(existing),
                        "window_total": total_janela, "new": 0}

            truncated = False
            if novos > max_leads:
                truncated = True
                logger.warning(
                    "[scores_refresh] %s: %d novos > teto %d — processando %d, "
                    "resto na próxima run (ON CONFLICT dedup).",
                    lf_name, novos, max_leads, max_leads,
                )
                leads = leads.sort_values("data_captura").head(max_leads).reset_index(drop=True)

            champ_df = _score_population(
                leads, pipeline.get_variant_predictor(champ["variant_name"]),
                champ["encoding_overrides"], "champion", pipeline,
            )
            chall_df = _score_population(
                leads, pipeline.get_variant_predictor(chall["variant_name"]),
                chall["encoding_overrides"], "challenger", pipeline,
            )

            out = leads[["email", "data_captura"]].drop_duplicates("email").copy()
            out = out.merge(champ_df, on="email", how="left")
            out = out.merge(chall_df, on="email", how="left")
            iso = out["data_captura"].dt.isocalendar()
            out["semana_captacao"] = (
                iso["year"].astype("Int64").astype(str) + "-W"
                + iso["week"].astype("Int64").astype(str).str.zfill(2)
            )
            out["lf"] = lf_name
            out["mes_lancamento"] = None      # online: metadata-light (vendas_* é
            out["vendas_inicio"] = None       # do backfill; score_geral só lê decil)
            out["vendas_estimada"] = None
            out["champion_run_id"] = champ["run_id"]
            out["challenger_run_id"] = chall["run_id"]
            out["core_commit"] = core_commit or os.environ.get("K_REVISION", "online_refresh")
            out["generated_at"] = datetime.now(timezone.utc)
            out = out.astype(object).where(pd.notna(out), None)

            sent = upsert_scores(ledger_conn, out.to_dict("records"))
            scored_ch = int(out["decil_challenger"].notna().sum())
            logger.info(
                "[scores_refresh] %s: janela=%d existentes=%d novos=%d enviados=%d "
                "(challenger scoreados=%d)%s",
                lf_name, total_janela, len(existing), novos, sent, scored_ch,
                " [TRUNCADO]" if truncated else "",
            )
            return {
                "status": "ok", "lf": lf_name, "window_total": total_janela,
                "existing": len(existing), "new": novos, "sent": sent,
                "scored_challenger": scored_ch, "truncated": truncated,
            }
        finally:
            if own_ledger:
                try:
                    ledger_conn.close()
                except Exception:
                    pass
    finally:
        if own_railway:
            try:
                railway_conn.close()
            except Exception:
                pass
