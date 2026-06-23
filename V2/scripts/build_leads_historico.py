#!/usr/bin/env python3
"""
build_leads_historico.py — Etapa 2b do PLANO_LEDGER_CLOUDSQL.md.

Consolida TODOS os leads (1 linha por lead × lançamento) numa tabela única no
Cloud SQL `leads_historico`, que vira a **fonte de verdade da validação** (no
lugar dos parquets locais de backtest, que eram só cache regenerável).

Por lead: identidade + pesquisa no FORMATO CANÔNICO (snake_case PT, em JSONB) +
o DECIL REAL DA ÉPOCA (o que foi enviado ao Meta — não o re-score). Cada lead é
atribuído ao lançamento cuja janela de captação contém a data dele.

Fontes (cada era na sua dona), todas já no Cloud SQL ou em cache:
  - planilhas (pré-18/02): caches PROD+BACKUP — survey snake_case + `decile`
  - lead_legado (18/02→mai): cópia da tabela Lead — `pesquisa` jsonb + `decil`
  - registros_ml (LF56+): nosso ledger — `survey_responses` jsonb + `has_computer` + `decil`

Idempotente: ON CONFLICT (email, lf) DO NOTHING. Roda por fonte (--source) ou tudo.

    python scripts/build_leads_historico.py --source all
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Planilha CRUA via export CSV (gid=0, aba "[LF] Pesquisa"). O cache normalizado
# perde as colunas de pesquisa (vêm vazias) — a fonte boa é a crua, com os
# cabeçalhos em português + colunas `decil`/`lead_score`.
SHEET_PROD_URL = "https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo/export?format=csv&gid=0"
SHEET_BACKUP_URL = "https://docs.google.com/spreadsheets/d/1OqNYA5zU9ix1uf52ovRYIdLhcugzwgfKOheKxE_zgvE/export?format=csv&gid=0"

# Cabeçalho em PT da planilha crua → chave canônica.
MAP_SHEET_PT = {
    "O seu gênero:": "genero",
    "Qual a sua idade?": "idade",
    "O que você faz atualmente?": "ocupacao",
    "Atualmente, qual a sua faixa salarial?": "faixa_salarial",
    "Você possui cartão de crédito?": "cartao_credito",
    "Já estudou programação?": "estudou_programacao",
    "Você já fez/faz/pretende fazer faculdade?": "faculdade",
    "Já investiu em algum curso online para aprender uma nova forma de ganhar dinheiro?": "investiu_curso",
    "O que mais te chama atenção na profissão de Programador?": "atracao_profissao",
    "O que mais você quer ver no evento?": "interesse_evento",
    "Tem computador/notebook?": "tem_computador",
}

# Janelas de captação (nome, cap_start, cap_end). Fonte: PC FORMULÁRIOS.
# LF40–44 e LF59 acrescentados às janelas do gerar_scores_2026.LAUNCHES.
LAUNCH_WINDOWS = [
    ("LF40",  "2025-11-25", "2025-12-01"),
    ("LF41",  "2025-12-02", "2025-12-08"),
    ("LF42",  "2025-12-09", "2025-12-15"),
    ("DEV19", "2025-12-16", "2026-01-14"),
    ("LF43",  "2026-01-13", "2026-01-26"),
    ("LF44",  "2026-01-27", "2026-02-03"),
    ("LF45",  "2026-02-03", "2026-02-23"),
    ("LF46",  "2026-02-24", "2026-03-02"),
    ("LF47",  "2026-03-03", "2026-03-09"),
    ("LF48",  "2026-03-10", "2026-03-16"),
    ("LF49",  "2026-03-17", "2026-03-23"),
    ("LF50",  "2026-03-24", "2026-03-29"),
    ("LF51",  "2026-03-30", "2026-04-06"),
    ("LF52",  "2026-04-07", "2026-04-12"),
    ("LF53",  "2026-04-13", "2026-04-20"),
    ("DEV20", "2026-04-21", "2026-05-04"),
    ("LF54",  "2026-05-05", "2026-05-11"),
    ("LF55",  "2026-05-12", "2026-05-18"),
    ("LF56",  "2026-05-25", "2026-05-30"),
    ("LF57",  "2026-06-01", "2026-06-07"),
    ("LF58",  "2026-06-08", "2026-06-14"),
    ("LF59",  "2026-06-15", "2026-06-21"),
]

# Pesquisa canônica (as 11 perguntas que o modelo usa) → chave snake_case PT.
CANONICAL = [
    "genero", "idade", "ocupacao", "faixa_salarial", "cartao_credito",
    "estudou_programacao", "faculdade", "investiu_curso", "interesse_evento",
    "atracao_profissao", "tem_computador",
]
# camelCase do JSON da Lead/ledger → canônico (computador tratado à parte no ledger)
MAP_JSON = {
    "genero": "genero", "idade": "idade", "ocupacao": "ocupacao",
    "faixaSalarial": "faixa_salarial", "cartaoCredito": "cartao_credito",
    "estudouProgramacao": "estudou_programacao", "faculdade": "faculdade",
    "investiuCurso": "investiu_curso", "interesseEvento": "interesse_evento",
    "atracaoProfissao": "atracao_profissao", "computador": "tem_computador",
}
# colunas snake_case do cache da planilha → canônico
MAP_SHEET = {
    "genero": "genero", "idade": "idade", "ocupacao": "ocupacao",
    "faixa_salarial": "faixa_salarial", "cartao_credito": "cartao_credito",
    "estudou_programacao": "estudou_programacao", "pretende_faculdade": "faculdade",
    "investiu_curso_online": "investiu_curso", "interesse_evento": "interesse_evento",
    "interesse_programacao": "atracao_profissao", "tem_computador": "tem_computador",
}

DST_COLS = [
    "email", "lf", "nome", "telefone", "data_captura",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "survey_responses", "tem_computador", "fonte", "score_producao",
    "decil_producao", "generated_at",
]
JSONB_COLS = {"survey_responses"}
BATCH = 500

DDL = """
CREATE TABLE IF NOT EXISTS leads_historico (
    id                BIGSERIAL PRIMARY KEY,
    email             TEXT NOT NULL,
    lf                TEXT NOT NULL,
    nome              TEXT,
    telefone          TEXT,
    data_captura      TIMESTAMP,
    utm_source        TEXT, utm_medium TEXT, utm_campaign TEXT,
    utm_content       TEXT, utm_term TEXT,
    survey_responses  JSONB,
    tem_computador    TEXT,
    fonte             TEXT,
    score_producao    DOUBLE PRECISION,
    decil_producao    TEXT,
    generated_at      TIMESTAMP DEFAULT now(),
    UNIQUE (email, lf)
)
"""
DDL_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_leads_hist_email ON leads_historico (lower(email))",
    "CREATE INDEX IF NOT EXISTS idx_leads_hist_lf ON leads_historico (lf)",
]


def _load_dotenv() -> None:
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def _cloudsql():
    import pg8000.native
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ["LEDGER_DB_HOST"], port=int(os.environ.get("LEDGER_DB_PORT", "5432")),
        database=os.environ.get("LEDGER_DB_NAME", "ledger"),
        user=os.environ.get("LEDGER_DB_USER", "ledger_app"),
        password=os.environ["LEDGER_DB_PASSWORD"], ssl_context=c, timeout=120,
    )


def _lf_for(date, windows) -> str | None:
    if pd.isna(date):
        return None
    d = pd.Timestamp(date).normalize()
    for nome, s, e in windows:
        if pd.Timestamp(s) <= d <= pd.Timestamp(e):
            return nome
    return None


def _decil_str(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip().upper()
    if not s:
        return None
    if s.startswith("D"):
        s = s[1:]
    try:
        return f"D{int(float(s))}"
    except ValueError:
        return None


def _parse_score(v):
    """lead_score da planilha vem com vírgula decimal ('0,4888...')."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def _norm_json_survey(raw, key_map) -> dict:
    d = json.loads(raw) if isinstance(raw, str) else (raw or {})
    return {can: d.get(src) for src, can in key_map.items() if d.get(src) is not None}


def _insert(cs, recs, fonte_label):
    if not recs:
        print(f"  {fonte_label}: 0 linhas")
        return 0
    gen = pd.Timestamp.now().isoformat()
    feitas = 0
    for i in range(0, len(recs), BATCH):
        chunk = recs[i:i + BATCH]
        tuples, params = [], {}
        for j, r in enumerate(chunk):
            vals = []
            for col in DST_COLS:
                v = r.get("generated_at", gen) if col == "generated_at" else r.get(col)
                if col in JSONB_COLS and v is not None and not isinstance(v, str):
                    v = json.dumps(v, ensure_ascii=False)
                elif hasattr(v, "isoformat"):
                    v = v.isoformat()
                params[f"{col}_{j}"] = v
                vals.append(f":{col}_{j}::jsonb" if col in JSONB_COLS else f":{col}_{j}")
            tuples.append("(" + ", ".join(vals) + ")")
        sql = (f"INSERT INTO leads_historico ({', '.join(DST_COLS)}) "
               f"VALUES {', '.join(tuples)} ON CONFLICT (email, lf) DO NOTHING")
        cs.run(sql, **params)
        feitas += len(chunk)
    print(f"  {fonte_label}: {feitas} linhas enviadas")
    return feitas


def from_sheets(cs):
    """Pré-18/02 (+ a parte 03–17/02 do LF45): planilha CRUA (PROD+BACKUP).
    Pesquisa sob cabeçalhos em PT + colunas `decil`/`lead_score`."""
    wins = [w for w in LAUNCH_WINDOWS if w[1] < "2026-02-24"]  # cap_start antes de LF46
    frames = []
    for url in (SHEET_PROD_URL, SHEET_BACKUP_URL):
        try:
            frames.append(pd.read_csv(url, low_memory=False, dtype=str))
        except Exception as e:
            print(f"  aviso: falha lendo planilha ({e})")
    if not frames:
        print("  planilhas: nenhuma lida")
        return 0
    df = pd.concat(frames, ignore_index=True)
    df["email"] = df["E-mail"].astype(str).str.lower().str.strip()
    df["_dt"] = pd.to_datetime(df["Data"], errors="coerce", dayfirst=True)
    # dedup por email: preferir a linha com decil preenchido
    df = (df.assign(_hasdec=df["decil"].notna())
            .sort_values("_hasdec", ascending=False, kind="stable")
            .drop_duplicates("email", keep="first"))
    df["_lf"] = df["_dt"].map(lambda d: _lf_for(d, wins))
    df = df[df["_lf"].notna() & df["email"].str.contains("@", na=False)]
    recs = []
    for _, r in df.iterrows():
        survey = {can: r.get(src) for src, can in MAP_SHEET_PT.items()
                  if pd.notna(r.get(src)) and str(r.get(src)).strip()}
        recs.append({
            "email": r["email"], "lf": r["_lf"], "nome": r.get("Nome Completo"),
            "telefone": r.get("Telefone"), "data_captura": r["_dt"],
            "utm_source": r.get("Source"), "utm_medium": r.get("Medium"),
            "utm_campaign": r.get("Campaign"), "utm_content": r.get("Content"), "utm_term": r.get("Term"),
            "survey_responses": survey, "tem_computador": survey.get("tem_computador"),
            "fonte": "planilha", "score_producao": _parse_score(r.get("lead_score")),
            "decil_producao": _decil_str(r.get("decil")),
        })
    return _insert(cs, recs, "planilhas crua (pré-18/02)")


def from_lead_legado(cs):
    """18/02→mai: cópia da Lead. pesquisa jsonb + decil int. (inclui LF45, que termina 23/02)."""
    wins = [w for w in LAUNCH_WINDOWS if w[2] >= "2026-02-18" and w[1] < "2026-05-25"]
    rows = cs.run(
        '''SELECT lower(email), nome_completo, telefone, created_at, source, medium,
                  campaign, content, term, pesquisa, lead_score, decil
           FROM lead_legado WHERE email IS NOT NULL AND created_at < '2026-05-25' ''')
    recs = []
    for (email, nome, tel, created, src, med, camp, cont, term, pesq, ls, dec) in rows:
        lf = _lf_for(created, wins)
        if not lf:
            continue
        survey = _norm_json_survey(pesq, MAP_JSON)
        recs.append({
            "email": email, "lf": lf, "nome": nome, "telefone": tel, "data_captura": created,
            "utm_source": src, "utm_medium": med, "utm_campaign": camp,
            "utm_content": cont, "utm_term": term,
            "survey_responses": survey, "tem_computador": survey.get("tem_computador"),
            "fonte": "lead_legado", "score_producao": ls, "decil_producao": _decil_str(dec),
        })
    return _insert(cs, recs, "lead_legado (18/02→mai)")


def from_registros_ml(cs):
    """LF56+: ledger. survey_responses jsonb + has_computer + decil."""
    wins = [w for w in LAUNCH_WINDOWS if w[1] >= "2026-05-25"]
    rows = cs.run(
        '''SELECT lower(email), first_name, last_name, phone, created_at,
                  utm_source, utm_medium, utm_campaign, utm_content, utm_term,
                  survey_responses, has_computer, lead_score, decil
           FROM registros_ml WHERE email IS NOT NULL AND created_at >= '2026-05-25' ''')
    recs = []
    for (email, fn, ln, phone, created, src, med, camp, cont, term, sr, hc, ls, dec) in rows:
        lf = _lf_for(created, wins)
        if not lf:
            continue
        survey = _norm_json_survey(sr, MAP_JSON)
        survey["tem_computador"] = hc
        nome = " ".join(p for p in [fn, ln] if p) or None
        recs.append({
            "email": email, "lf": lf, "nome": nome, "telefone": phone, "data_captura": created,
            "utm_source": src, "utm_medium": med, "utm_campaign": camp,
            "utm_content": cont, "utm_term": term,
            "survey_responses": survey, "tem_computador": hc,
            "fonte": "registros_ml", "score_producao": ls, "decil_producao": _decil_str(dec),
        })
    return _insert(cs, recs, "registros_ml (LF56+)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["sheets", "lead_legado", "registros_ml", "all"], default="all")
    args = ap.parse_args()
    _load_dotenv()
    cs = _cloudsql()
    try:
        cs.run(DDL)
        for idx in DDL_IDX:
            cs.run(idx)
        antes = cs.run("SELECT count(*) FROM leads_historico")[0][0]
        if args.source in ("registros_ml", "all"):
            from_registros_ml(cs)
        if args.source in ("lead_legado", "all"):
            from_lead_legado(cs)
        if args.source in ("sheets", "all"):
            from_sheets(cs)
        depois = cs.run("SELECT count(*) FROM leads_historico")[0][0]
        print(f"\n✅ leads_historico: {antes} → {depois} (+{depois - antes})")
        print("  cobertura por LF (linhas · com decil):")
        for r in cs.run("SELECT lf, count(*), count(decil_producao) FROM leads_historico GROUP BY lf "
                        "ORDER BY min(data_captura)"):
            print(f"    {r[0]:<7} {r[1]:>7} · {r[2]:>7} c/decil")
        return 0
    finally:
        cs.close()


if __name__ == "__main__":
    sys.exit(main())
