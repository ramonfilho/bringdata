#!/usr/bin/env python3
"""
gerar_scores_2026.py — Re-score de TODOS os lançamentos de 2026 com os dois
modelos ativos (Champion jan30 e Challenger abr28), mês a mês, LF por LF.

Por que regenerar: os scores gravados no Railway sofreram bugs ao longo do
caminho (versões de código diferentes — ver PLANO_REMEDIACAO_LEAD_SCORE.md).
O Champion só é confiável desde 05/05 (LF54+); o Challenger só existe em
produção desde o A/B (LF56+). Re-score local com o código atual dá uma base
única e comparável para o ano inteiro.

Classificação de "lançamento de 2026": data de VENDAS (coluna N da planilha
PC FORMULÁRIOS). Os leads scorados são os da janela de CAPTAÇÃO (coluna L).

Fontes de leads por LF (decididas por disponibilidade, sem refetch desnecessário):
  - base parquet      → backtests existentes em files/validation/ (Railway/Sheets da época)
  - sheets            → planilha central "[LF] Pesquisa" (morreu ~17/05/2026)
  - railway_cache     → cache local da tabela Lead (morreu ~13-17/05/2026)
  - ledger            → registros_ml + Client.hasComputer (vivo desde 23/05, survey desde 25/05)
  - lf55_hybrid       → Lead (cache) ∪ lead_surveys×Client×UTMTracking (janela da migração de schema)

Saída (CSV em outputs/validation/scores_2026/):
  - scores_2026_por_lead.csv       (1 linha por lead, scores+decis dos 2 modelos)
  - scores_2026_resumo_mensal.csv  (mês de lançamento × LF)
  - scores_2026_resumo_semanal.csv (semana ISO de captação)
"""

from __future__ import annotations

import json
import os
import ssl
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # V2/
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# _load_dotenv roda no import do backtest_compare_models
from backtest_compare_models import (  # noqa: E402
    _load_decil_thresholds,
    _load_encoding_overrides_for_run,
    _score_to_decil,
)

CHAMPION_RUN = "d51757f5041c44b7ab1a056fce8c3c35"   # jan30
CHALLENGER_RUN = "5d158f0aa6e54b489498470446194a6c"  # abr28
MLRUNS_ROOT = PROJECT_ROOT / "mlruns"
VAL_DIR = PROJECT_ROOT / "files" / "validation"
RAILWAY_CACHE = VAL_DIR / "cache" / "railway_leads_2025-02-01_2026-06-10.parquet"
OUT_DIR = PROJECT_ROOT / "outputs" / "validation" / "scores_2026"

# ---------------------------------------------------------------------------
# Janelas — fonte: PC FORMULÁRIOS (lida 12/06/2026), col A (nome), L (captação),
# N (vendas). LF57/LF58 ainda sem data de vendas na planilha → estimada pelo
# padrão captação+14d (flag vendas_estimada).
# ---------------------------------------------------------------------------
LAUNCHES = [
    # (nome, cap_start, cap_end, vendas_start, vendas_end, vendas_estimada, fonte)
    ("DEV19", "2025-12-16", "2026-01-14", "2026-01-19", "2026-01-25", False, "sheets"),
    ("LF43",  "2026-01-13", "2026-01-26", "2026-02-02", "2026-02-08", False, "base:backtest_lf43/base_dataset.parquet"),
    ("LF44",  "2026-01-27", "2026-02-03", "2026-02-09", "2026-02-15", False, "base:backtest_lf44/base_dataset.parquet"),
    # base existente do LF45 cobre só 18-23/02 (Railway começou 18/02) → Sheets cobre a janela inteira
    ("LF45",  "2026-02-03", "2026-02-23", "2026-03-02", "2026-03-08", False, "sheets"),
    ("LF46",  "2026-02-24", "2026-03-02", "2026-03-09", "2026-03-15", False, "base:backtest_lf46/base_dataset.parquet"),
    ("LF47",  "2026-03-03", "2026-03-09", "2026-03-16", "2026-03-22", False, "base:backtest_lf47/base_dataset.parquet"),
    ("LF48",  "2026-03-10", "2026-03-16", "2026-03-23", "2026-03-29", False, "base:backtest_lf48/base_dataset.parquet"),
    ("LF49",  "2026-03-17", "2026-03-23", "2026-03-30", "2026-04-05", False, "base:backtest_lf49/base_dataset.parquet"),
    ("LF50",  "2026-03-24", "2026-03-29", "2026-04-01", "2026-04-06", False, "base:backtest_lf50/base_dataset.parquet"),
    ("LF51",  "2026-03-30", "2026-04-06", "2026-04-13", "2026-04-19", False, "base:backtest_historico/LF51/base.parquet"),
    ("LF52",  "2026-04-07", "2026-04-12", "2026-04-17", "2026-04-24", False, "base:backtest_lf52/base_dataset.parquet"),
    ("LF53",  "2026-04-13", "2026-04-20", "2026-04-27", "2026-05-03", False, "base:backtest_lf53fp/base_dataset.parquet"),
    ("DEV20", "2026-04-21", "2026-05-04", "2026-05-11", "2026-05-17", False, "base:backtest_dev20/base_dataset.parquet"),
    # base existente do LF54 cobre só 05-10/05 → cache Railway tem a janela cheia
    ("LF54",  "2026-05-05", "2026-05-11", "2026-05-18", "2026-05-24", False, "railway_cache"),
    ("LF55",  "2026-05-12", "2026-05-18", "2026-05-25", "2026-05-31", False, "lf55_hybrid"),
    ("LF56",  "2026-05-25", "2026-05-30", "2026-06-08", "2026-06-14", False, "ledger"),
    ("LF57",  "2026-06-01", "2026-06-07", "2026-06-15", "2026-06-21", True,  "ledger"),
    ("LF58",  "2026-06-08", "2026-06-14", "2026-06-22", "2026-06-28", True,  "ledger"),
]

# Scorados mas fora do relatório (decisão 12/06: vendas ainda não definidas na
# PC FORMULÁRIOS; LF58 com captação em aberto). Remover daqui quando fecharem.
FORA_DO_RELATORIO = {"LF57", "LF58"}

SURVEY_PT_COLS = [
    "O seu gênero:", "Qual a sua idade?", "O que você faz atualmente?",
    "Atualmente, qual a sua faixa salarial?", "Você possui cartão de crédito?",
    "O que mais você quer ver no evento?", "Tem computador/notebook?",
    "Já estudou programação?", "Você já fez/faz/pretende fazer faculdade?",
    "investiu_curso_online", "interesse_programacao",
]

# "Tem computador/notebook?" pós-migração: NÃO está no survey_responses (o form
# novo pergunta na captura, não na pesquisa). A fonte é o próprio Railway:
#   - registros_ml.has_computer ('SIM'/'NAO', 100% fill em leads com pesquisa) — LF56+
#   - Client.hasComputer (text 'SIM'/'NAO', 99,9% fill na era lead_surveys) — LF55
# Sem isso, feature top-5 do Champion (5,6% de importância) fica zerada e o
# guard DT-19 do encoding acusa o batch (corretamente).


def _railway_conn():
    import pg8000.native
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ.get("RAILWAY_DB_HOST", "shortline.proxy.rlwy.net"),
        port=int(os.environ.get("RAILWAY_DB_PORT", "11594")),
        database=os.environ.get("RAILWAY_DB_NAME", "railway"),
        user=os.environ.get("RAILWAY_DB_USER", "postgres"),
        password=os.environ["RAILWAY_DB_PASSWORD"],
        ssl_context=ctx,
    )


def _survey_para_row(base: dict, pesquisa: dict) -> dict:
    """Monta a linha formato-Sheets a partir de campos diretos + pesquisa PT."""
    from api.railway_mapping import railway_lead_to_sheets_row
    lead_row = dict(base)
    lead_row["pesquisa"] = pesquisa
    return railway_lead_to_sheets_row(lead_row)


def load_ledger_window(cap_start: str, cap_end: str) -> pd.DataFrame:
    """registros_ml (todas as variantes) → formato Sheets. has_computer vem
    direto do payload Pub/Sub gravado no ledger ('SIM'/'NAO', 100% fill)."""
    conn = _railway_conn()
    end_excl = (pd.to_datetime(cap_end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    rows = conn.run(
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
    conn.close()

    out_rows = []
    for (email, phone, fn, ln, created, sr, src, med, camp, cont, term, has_comp) in rows:
        pesq = json.loads(sr) if isinstance(sr, str) else dict(sr or {})
        pesq["computador"] = has_comp
        nome = " ".join(p for p in [fn, ln] if p) or None
        out_rows.append(_survey_para_row(
            {"email": email, "nomeCompleto": nome, "telefone": phone,
             "data": created, "source": src, "medium": med,
             "campaign": camp, "content": cont, "term": term},
            pesq,
        ))
    df = pd.DataFrame(out_rows)
    if len(df):
        df = df.drop_duplicates(subset=["E-mail"], keep="first")
    return df


def load_lf55_hybrid(cap_start: str, cap_end: str) -> pd.DataFrame:
    """União: tabela Lead (cache local, degrada após 13/05) ∪ lead_surveys
    (transitória da migração) enriquecida com Client + UTMTracking.
    Computador: coluna Lead já traz (parte A); Client.hasComputer text
    'SIM'/'NAO' cobre 99,9% da parte B."""
    # Parte A — cache da tabela Lead
    cache = pd.read_parquet(RAILWAY_CACHE)
    d = pd.to_datetime(cache["Data"], errors="coerce")
    end_excl = pd.to_datetime(cap_end) + pd.Timedelta(days=1)
    parte_a = cache[(d >= cap_start) & (d < end_excl)].copy()

    # Parte B — lead_surveys × Client × UTMTracking
    conn = _railway_conn()
    rows = conn.run(
        """
        SELECT ls."clientEmail", ls."submittedAt", ls.genero, ls.idade, ls.ocupacao,
               ls."faixaSalarial", ls."cartaoCredito", ls."estudouProgramacao",
               ls.faculdade, ls."investiuCurso", ls."atracaoProfissao", ls."interesseEvento",
               c."firstName", c."lastName", c.phone, c."hasComputer",
               u.source, u.medium, u.campaign, u.content, u.term
        FROM lead_surveys ls
        LEFT JOIN "Client" c ON lower(c.email) = lower(ls."clientEmail")
        LEFT JOIN LATERAL (
            SELECT source, medium, campaign, content, term
            FROM "UTMTracking" u2
            WHERE lower(u2."clientEmail") = lower(ls."clientEmail")
            ORDER BY u2."trackedAt" DESC LIMIT 1
        ) u ON TRUE
        WHERE ls."submittedAt" >= :s AND ls."submittedAt" < :e
          AND ls."clientEmail" IS NOT NULL
        """,
        s=cap_start, e=end_excl.strftime("%Y-%m-%d"),
    )
    conn.close()

    out_rows = []
    for (email, submitted, genero, idade, ocup, faixa, cartao, estudou,
         facul, investiu, atracao, interesse, fn, ln, phone, has_comp,
         src, med, camp, cont, term) in rows:
        pesq = {
            "genero": genero, "idade": idade, "ocupacao": ocup,
            "faixaSalarial": faixa, "cartaoCredito": cartao,
            "estudouProgramacao": estudou, "faculdade": facul,
            "investiuCurso": investiu, "atracaoProfissao": atracao,
            "interesseEvento": interesse,
            "computador": has_comp,
        }
        nome = " ".join(p for p in [fn, ln] if p) or None
        out_rows.append(_survey_para_row(
            {"email": email, "nomeCompleto": nome, "telefone": phone,
             "data": submitted, "source": src, "medium": med,
             "campaign": camp, "content": cont, "term": term},
            pesq,
        ))
    parte_b = pd.DataFrame(out_rows)

    if len(parte_a) and len(parte_b):
        emails_a = set(parte_a["E-mail"].astype(str).str.lower().str.strip())
        mask_novo = ~parte_b["E-mail"].astype(str).str.lower().str.strip().isin(emails_a)
        parte_b = parte_b[mask_novo]
        print(f"  [LF55] Lead cache: {len(parte_a)} | lead_surveys novos: {len(parte_b)}")
        return pd.concat([parte_a, parte_b], ignore_index=True, sort=False)
    return parte_a if len(parte_a) else parte_b


def load_leads_for_launch(nome, cap_start, cap_end, fonte) -> pd.DataFrame:
    if fonte.startswith("base:"):
        df = pd.read_parquet(VAL_DIR / fonte.split(":", 1)[1])
    elif fonte == "sheets":
        from src.validation.data_loader import LeadDataLoader
        df = LeadDataLoader().load_leads_from_sheets(
            start_date=cap_start, end_date=cap_end, training_mode=True
        )
        # training_mode entrega schema lowercase (email/data_captura/...), mas o
        # pipeline de scoring espera as canônicas do form ('Data', 'E-mail', ...)
        # — sem 'Data' a feature dia_semana não nasce e o encoding aborta (T1-1).
        aliases = {"data_captura": "Data", "email": "E-mail", "nome": "Nome Completo",
                   "telefone": "Telefone", "campaign": "Campaign", "source": "Source",
                   "medium": "Medium", "term": "Term", "content": "Content"}
        for lo, up in aliases.items():
            if up not in df.columns and lo in df.columns:
                df[up] = df[lo]
        # colunas de um segundo formulário (Idade, Gênero, ...) colidem com a
        # unificação de categorias — fora do schema que o backtest LF40 provou
        junk = ["Gênero", "Idade", "Ocupação Atual", "Faixa Salarial",
                "Possui Cartão de Crédito?", "Já comprou curso online?", "Urgência",
                "Maior Motivo", "Interesse no Evento", "Maior Barreira",
                "Intenção de Investimento", "IP"]
        df = df.drop(columns=[c for c in junk if c in df.columns])
    elif fonte == "railway_cache":
        cache = pd.read_parquet(RAILWAY_CACHE)
        d = pd.to_datetime(cache["Data"], errors="coerce")
        end_excl = pd.to_datetime(cap_end) + pd.Timedelta(days=1)
        df = cache[(d >= cap_start) & (d < end_excl)].copy()
    elif fonte == "ledger":
        df = load_ledger_window(cap_start, cap_end)
    elif fonte == "lf55_hybrid":
        df = load_lf55_hybrid(cap_start, cap_end)
    else:
        raise ValueError(f"fonte desconhecida: {fonte}")

    if df is None or len(df) == 0:
        return pd.DataFrame()

    # colunas canônicas p/ merge e agregação
    if "email" not in df.columns:
        for alias in ("E-mail", "e-mail", "Email"):
            if alias in df.columns:
                df["email"] = df[alias]
                break
    df["email"] = df["email"].astype(str).str.lower().str.strip()
    if "data_captura" not in df.columns:
        for alias in ("Data", "data", "createdAt"):
            if alias in df.columns:
                df["data_captura"] = df[alias]
                break
    df["data_captura"] = pd.to_datetime(df["data_captura"], errors="coerce")
    df = df[df["email"].str.contains("@", na=False)]

    # População canônica = leads que responderam a pesquisa (produção só scoreia
    # esses; fontes Railway/ledger já vêm assim). Nas planilhas o mesmo lead
    # aparece 2x (linha de captura vazia + linha com pesquisa) — dedup precisa
    # preferir a linha preenchida, senão o score sai cego (DT-19 pegou isso).
    survey_chave = [c for c in ("O seu gênero:", "Qual a sua idade?",
                                "O que você faz atualmente?") if c in df.columns]
    if survey_chave:
        fill = df[survey_chave].notna().sum(axis=1)
        df = (df.assign(_fill=fill)
                .sort_values("_fill", ascending=False, kind="stable"))
        df = df.drop_duplicates(subset=["email"], keep="first")
        n_sem = int((df["_fill"] == 0).sum())
        if n_sem:
            print(f"  descartados {n_sem} leads sem pesquisa (não-scoráveis)")
        df = df[df["_fill"] > 0].drop(columns=["_fill"])
        df = df.sort_values("data_captura").reset_index(drop=True)
    else:
        df = df.drop_duplicates(subset=["email"], keep="first").reset_index(drop=True)
    return df


def score_with_model(leads: pd.DataFrame, run_id: str, label: str) -> pd.DataFrame:
    """Re-score via LeadScoringPipeline — mesmo round-trip CSV do backtest, mas
    com enforce_post_encoding=False (paridade com produção, app.py:419): leads
    pós-migração têm fração pequena sem 'Tem computador/notebook?' e o guard
    DT-19 bloquearia o batch inteiro por causa deles."""
    import tempfile

    from src.model.prediction import LeadScoringPredictor
    from src.production_pipeline import LeadScoringPipeline

    predictor = LeadScoringPredictor(mlflow_run_id=run_id, use_active_model=False)
    predictor.load_model()
    encoding_overrides = _load_encoding_overrides_for_run(run_id)
    pipeline = LeadScoringPipeline(model_name=None, model_path=None, client_id="devclub")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        leads.to_csv(tmp_path, index=False)
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
            raise RuntimeError(f"Score não encontrado. Cols: {list(scored.columns)[:20]}")

    if "email" not in scored.columns:
        n = min(len(scored), len(leads))
        scored = scored.iloc[:n].reset_index(drop=True)
        scored["email"] = leads["email"].iloc[:n].values

    thresholds = _load_decil_thresholds(run_id, MLRUNS_ROOT)
    scored[f"decil_{label}"] = scored["lead_score"].apply(
        lambda s: _score_to_decil(s, thresholds) if pd.notna(s) else None
    )
    scored = scored.rename(columns={"lead_score": f"score_{label}"})
    return scored[["email", f"score_{label}", f"decil_{label}"]].drop_duplicates("email")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_leads = []

    falhas = []
    for nome, cap_s, cap_e, ven_s, ven_e, ven_est, fonte in LAUNCHES:
        print(f"\n=== {nome} (captação {cap_s} a {cap_e} | fonte {fonte}) ===", flush=True)
        try:
            leads = load_leads_for_launch(nome, cap_s, cap_e, fonte)
            if len(leads) == 0:
                print(f"  ⚠️ {nome}: NENHUM lead carregado — pulando")
                falhas.append((nome, "0 leads"))
                continue
            print(f"  {len(leads)} leads únicos", flush=True)

            champion = score_with_model(leads, CHAMPION_RUN, "champion")
            print(f"  champion scorado: {champion['score_champion'].notna().sum()}", flush=True)
            challenger = score_with_model(leads, CHALLENGER_RUN, "challenger")
            print(f"  challenger scorado: {challenger['score_challenger'].notna().sum()}", flush=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ⚠️ {nome}: FALHOU ({type(e).__name__}: {e}) — seguindo pro próximo", flush=True)
            falhas.append((nome, f"{type(e).__name__}: {e}"))
            continue

        out = leads[["email", "data_captura"]].copy()
        out["lf"] = nome
        out["mes_lancamento"] = ven_s[:7]
        out["vendas_inicio"] = ven_s
        out["vendas_estimada"] = ven_est
        iso = out["data_captura"].dt.isocalendar()
        out["semana_captacao"] = (
            iso["year"].astype("Int64").astype(str) + "-W"
            + iso["week"].astype("Int64").astype(str).str.zfill(2)
        )
        out = out.merge(champion, on="email", how="left")
        out = out.merge(challenger, on="email", how="left")
        all_leads.append(out)

    if falhas:
        print(f"\n⚠️ LFs com falha: {falhas}")
    if not all_leads:
        raise RuntimeError("Nenhum LF processado com sucesso")
    final = pd.concat(all_leads, ignore_index=True)
    gerar_relatorios(final)


def gerar_relatorios(final: pd.DataFrame) -> None:
    """CSV por lead + xlsx de resumos (mensal e semanal) no padrão Excel do
    projeto (mesmos formatos do report_generator._create_formats)."""
    col_order = ["lf", "mes_lancamento", "vendas_inicio", "vendas_estimada",
                 "data_captura", "semana_captacao", "email",
                 "score_champion", "decil_champion",
                 "score_challenger", "decil_challenger"]
    final = final[col_order].sort_values(["vendas_inicio", "lf", "data_captura"])
    final = final[~final["lf"].isin(FORA_DO_RELATORIO)]

    f1 = OUT_DIR / "scores_2026_por_lead.csv"
    final.to_csv(f1, index=False)
    print(f"\n✅ {len(final)} leads → {f1}")

    def _resumo(g):
        d9_10 = {"D09", "D10"}
        return pd.Series({
            "Leads": len(g),
            "Score Champion Médio": g["score_champion"].mean(),
            "Score Challenger Médio": g["score_challenger"].mean(),
            "%D9+D10 Champion": g["decil_champion"].isin(d9_10).mean(),
            "%D9+D10 Challenger": g["decil_challenger"].isin(d9_10).mean(),
        })

    ordem_lf = (final[["lf", "vendas_inicio"]].drop_duplicates()
                .sort_values("vendas_inicio")["lf"].tolist())
    mensal = final.groupby("lf", sort=False).apply(_resumo).reindex(ordem_lf).reset_index()
    mensal = mensal.rename(columns={"lf": "LF"})

    semanal = final.groupby("semana_captacao", sort=True).apply(_resumo).reset_index()
    semanal = semanal.rename(columns={"semana_captacao": "Semana"})

    fx = OUT_DIR / "scores_2026_resumos.xlsx"
    writer = pd.ExcelWriter(fx, engine="xlsxwriter")
    wb = writer.book
    fmt_header = wb.add_format({
        "bold": True, "bg_color": "#4472C4", "font_color": "white", "border": 1,
        "align": "center", "valign": "vcenter", "text_wrap": True,
    })
    fmt_text = wb.add_format({"border": 1, "align": "left", "valign": "vcenter"})
    fmt_number = wb.add_format({"num_format": "#,##0", "border": 1})
    fmt_decimal = wb.add_format({"num_format": "0.000", "border": 1})
    fmt_percent = wb.add_format({"num_format": "0.00%", "border": 1})

    def _write_tab(df, aba):
        df.to_excel(writer, sheet_name=aba, index=False, startrow=0)
        ws = writer.sheets[aba]
        for j, col in enumerate(df.columns):
            ws.write(0, j, col, fmt_header)
        col_fmt = {"Leads": fmt_number}
        for c in df.columns:
            if c.startswith("Score"):
                col_fmt[c] = fmt_decimal
            elif c.startswith("%"):
                col_fmt[c] = fmt_percent
        for i in range(len(df)):
            for j, col in enumerate(df.columns):
                ws.write(i + 1, j, df.iloc[i, j], col_fmt.get(col, fmt_text))
        ws.set_column(0, 0, 14)
        ws.set_column(1, len(df.columns) - 1, 20)
        ws.freeze_panes(1, 0)

    _write_tab(mensal, "Resumo Mensal")
    _write_tab(semanal, "Resumo Semanal")
    writer.close()
    print(f"✅ resumos (mensal {len(mensal)} linhas, semanal {len(semanal)}) → {fx}")


if __name__ == "__main__":
    main()
