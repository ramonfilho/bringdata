"""Reconstrução da fonte única de leads (`train_unified`) a partir das fontes ATÔMICAS.

Metodologia e legenda: V2/docs/RECONSTRUCAO_LEADS_UNIFICADA.md (skill /data-architect).

Regra de governança: TODA modificação de dado roda por este script (CLI), nunca inline.
  python -m src.data.leads_unify --dry-run   # conta por fonte, não grava
  python -m src.data.leads_unify --write      # grava (idempotente, reversível)

Fontes atômicas (proveniência por linha gravada na coluna analytics.leads.provenance):
  registros_ml  (Cloud SQL public)         prio 1  produção, camelCase, data=created_at
  Lead          (= lead_legado, Cloud SQL) prio 2  pesquisa jsonb camelCase, data=data
  lead_surveys  (Railway → espelhado)      prio 3  survey em colunas camelCase, submittedAt
  sheet:*       (de train_pesquisa)        prio 4  survey já canônico, arquivo_origem Google Sheets
  xlsx:*        (de train_pesquisa)        prio 5  survey já canônico, arquivo_origem *.xlsx

Lei de conservação (por fonte): linhas_na_fonte = incluídas + deduplicadas + excluídas.
Dedup determinístico por (lower(email), dia), menor prio vence. Rollback = DELETE source.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

UNIFIED_SOURCE = "train_unified"
STG_LEAD_SURVEYS = "lead_surveys_stg"  # espelho do lead_surveys do Railway no Cloud SQL

# (chave canônica texto-pergunta, chave camelCase nativa)
_CANON = [
    ("O seu gênero:", "genero"),
    ("Qual a sua idade?", "idade"),
    ("O que você faz atualmente?", "ocupacao"),
    ("Atualmente, qual a sua faixa salarial?", "faixaSalarial"),
    ("Você possui cartão de crédito?", "cartaoCredito"),
    ("O que mais você quer ver no evento?", "interesseEvento"),
    ("Tem computador/notebook?", "computador"),
    ("Já estudou programação?", "estudouProgramacao"),
    ("Você já fez/faz/pretende fazer faculdade?", "faculdade"),
    ("investiu_curso_online", "investiuCurso"),
    ("interesse_programacao", "atracaoProfissao"),
]


def _survey_from_jsonb(jcol: str) -> str:
    """survey canônico lendo a coluna jsonb camelCase `jcol`."""
    parts = [f"'{canon}', {jcol}->>'{camel}'" for canon, camel in _CANON]
    return "jsonb_build_object(" + ", ".join(parts) + ")"


def _survey_from_cols() -> str:
    """survey canônico lendo COLUNAS camelCase (lead_surveys_stg). 'computador' não existe
    no lead_surveys (sem coluna) → NULL nessa pergunta."""
    parts = []
    for canon, camel in _CANON:
        col = "NULL" if camel == "computador" else f'"{camel}"'
        parts.append(f"'{canon}', {col}")
    return "jsonb_build_object(" + ", ".join(parts) + ")"


def _dt(c: str) -> str:
    return f"to_char({c}, 'YYYY-MM-DD\"T\"HH24:MI:SS')"  # ISO tz-naive uniforme


# dedup determinístico: por (lower(email), dia), menor prio vence. Reutilizado em dry-run e write.
_DEDUP = ("SELECT DISTINCT ON (em, (dt::date)) * FROM {rel} "
          "WHERE em IS NOT NULL AND em <> '' ORDER BY em, (dt::date), prio")


def _src_cte() -> str:
    """CTE `src`: union das 5 fontes ATÔMICAS, cada uma já canônica + provenance + prioridade.
    Pré-dedup (inclui linhas sem email — contadas como excluídas na auditoria)."""
    ml = _survey_from_jsonb("survey_responses")
    leg = _survey_from_jsonb("pesquisa")
    surv = _survey_from_cols()
    return f"""
    src AS (
      -- 1) registros_ml (ledger cru, camelCase, data=created_at)
      SELECT 1 AS prio, 'registros_ml'::text AS prov, lower(email) AS em, created_at AS dt,
             email, phone, utm_source, utm_medium, utm_term, utm_campaign, utm_content, user_agent,
             jsonb_build_object('Data', {_dt('created_at')}, 'E-mail', email,
               'Nome Completo', concat_ws(' ', first_name, last_name), 'Telefone', phone,
               'Source', utm_source, 'Medium', utm_medium, 'Term', utm_term) || {ml} AS canon
      FROM public.registros_ml WHERE created_at IS NOT NULL

      UNION ALL
      -- 2) Lead (= lead_legado): pesquisa jsonb camelCase, data=data
      SELECT 2, 'Lead', lower(email), data,
             email, telefone, source, medium, term, campaign, content, user_agent,
             jsonb_build_object('Data', {_dt('data')}, 'E-mail', email,
               'Nome Completo', nome_completo, 'Telefone', telefone,
               'Source', source, 'Medium', medium, 'Term', term) || {leg} AS canon
      FROM public.lead_legado WHERE data IS NOT NULL

      UNION ALL
      -- 3) lead_surveys (espelhado): survey em colunas camelCase, data=submittedAt
      SELECT 3, 'lead_surveys', lower("clientEmail"), "submittedAt",
             "clientEmail", NULL, NULL, NULL, NULL, NULL, NULL, NULL,
             jsonb_build_object('Data', {_dt('"submittedAt"')}, 'E-mail', "clientEmail",
               'Nome Completo', NULL, 'Telefone', NULL,
               'Source', NULL, 'Medium', NULL, 'Term', NULL) || {surv} AS canon
      FROM public.{STG_LEAD_SURVEYS} WHERE "submittedAt" IS NOT NULL

      UNION ALL
      -- 4) Sheets (de train_pesquisa): survey JÁ canônico
      SELECT 4, 'sheet:'||coalesce(survey_responses->>'arquivo_origem','?'),
             lower(email), (survey_responses->>'Data')::timestamptz,
             email, phone, utm_source, utm_medium, utm_term, utm_campaign, utm_content, user_agent,
             survey_responses
      FROM analytics.leads
      WHERE source='train_pesquisa' AND survey_responses->>'arquivo_origem' LIKE '%Google Sheets%'
        AND (survey_responses->>'Data') ~ '^[0-9]{{4}}-'

      UNION ALL
      -- 5) xlsx locais (de train_pesquisa): survey JÁ canônico
      SELECT 5, 'xlsx:'||coalesce(survey_responses->>'arquivo_origem','?'),
             lower(email), (survey_responses->>'Data')::timestamptz,
             email, phone, utm_source, utm_medium, utm_term, utm_campaign, utm_content, user_agent,
             survey_responses
      FROM analytics.leads
      WHERE source='train_pesquisa' AND survey_responses->>'arquivo_origem' LIKE '%.xlsx%'
        AND (survey_responses->>'Data') ~ '^[0-9]{{4}}-'
    )
    """


PROVENANCE_TBL = "analytics.leads_provenance"  # sidecar de linhagem (não cabe ALTER em leads: dono=postgres)


def mirror_lead_surveys(railway_conn, cloud_conn) -> int:
    """Espelha Railway.lead_surveys → Cloud SQL public.lead_surveys_stg (transform registrado).
    ATÔMICO (DDL transacional: kill no meio faz rollback, nunca deixa tabela parcial) e
    LOSSLESS (assert staging == origem; aborta se perder linha)."""
    rows = railway_conn.run(
        'SELECT "clientEmail", "submittedAt", genero, idade, ocupacao, "faixaSalarial", '
        '"cartaoCredito", "estudouProgramacao", faculdade, "investiuCurso", "atracaoProfissao", '
        '"interesseEvento" FROM public.lead_surveys')
    cloud_conn.run("BEGIN")
    try:
        cloud_conn.run(f"DROP TABLE IF EXISTS public.{STG_LEAD_SURVEYS}")
        cloud_conn.run(f'''CREATE TABLE public.{STG_LEAD_SURVEYS} (
            "clientEmail" varchar, "submittedAt" timestamptz, genero varchar, idade varchar,
            ocupacao varchar, "faixaSalarial" varchar, "cartaoCredito" varchar,
            "estudouProgramacao" varchar, faculdade varchar, "investiuCurso" varchar,
            "atracaoProfissao" varchar, "interesseEvento" varchar)''')
        # batch insert (1 round-trip por lote, não por linha): row-by-row sobre a conexão
        # cloud estourava o timeout de socket em ~1.6k INSERTs.
        ncols, chunk = 12, 400
        for start in range(0, len(rows), chunk):
            batch = rows[start:start + chunk]
            vals, params = [], {}
            for j, r in enumerate(batch):
                keys = [f"p{j}_{k}" for k in range(ncols)]
                vals.append("(" + ",".join(":" + k for k in keys) + ")")
                for k in range(ncols):
                    params[f"p{j}_{k}"] = r[k]
            cloud_conn.run(f"INSERT INTO public.{STG_LEAD_SURVEYS} VALUES " + ",".join(vals), **params)
        staged = cloud_conn.run(f"SELECT count(*) FROM public.{STG_LEAD_SURVEYS}")[0][0]
        if staged != len(rows):
            raise RuntimeError(f"mirror lossy: origem={len(rows)} staging={staged}")
        cloud_conn.run("COMMIT")
    except Exception:
        try:
            cloud_conn.run("ROLLBACK")  # se a conexão morreu, o PG já fez rollback do lado dele
        except Exception:
            pass
        raise
    logger.info("[leads_unify] espelhado lead_surveys → %s: %d linhas (lossless)", STG_LEAD_SURVEYS, len(rows))
    return len(rows)


# Lei de conservação: na_fonte (linhas físicas da fonte) = excl_data + excl_email + dedup + incluídas.
# `na_fonte` = contagem física da tabela/subconjunto de origem; `in_branch` = o que entra no UNION
# (já filtra data nula / regex de data) → a diferença é `excl_data`. Tudo medido no MESMO snapshot
# REPEATABLE READ da transação de write (senão fonte viva como registros_ml dá dedup negativo).
_PRIO = {
    1: ("registros_ml", "SELECT count(*) FROM public.registros_ml"),
    2: ("Lead",         "SELECT count(*) FROM public.lead_legado"),
    3: ("lead_surveys", f"SELECT count(*) FROM public.{STG_LEAD_SURVEYS}"),
    4: ("sheet",        "SELECT count(*) FROM analytics.leads WHERE source='train_pesquisa' "
                        "AND survey_responses->>'arquivo_origem' LIKE '%Google Sheets%'"),
    5: ("xlsx",         "SELECT count(*) FROM analytics.leads WHERE source='train_pesquisa' "
                        "AND survey_responses->>'arquivo_origem' LIKE '%.xlsx%'"),
}

AUDIT_TBL = "analytics.leads_unified_audit"


def _ensure_provenance_table(conn) -> None:
    """Tabela-sidecar de linhagem 1:1 com leads (join por event_id). Existe porque o usuário
    ledger_app não é dono de analytics.leads (não pode ALTER), e mexer no survey_responses jsonb
    arriscaria poluir features de treino. Linhagem fica separada do dado."""
    conn.run(f"""CREATE TABLE IF NOT EXISTS {PROVENANCE_TBL} (
        source varchar, event_id varchar, provenance varchar, prio smallint, ingested_at timestamptz,
        PRIMARY KEY (source, event_id))""")


def _ensure_audit_table(conn) -> None:
    conn.run(f"""CREATE TABLE IF NOT EXISTS {AUDIT_TBL} (
        run_at timestamptz, source varchar, prio int, fonte varchar, na_fonte int, excl_data int,
        excl_email int, deduplicadas int, incluidas int, conserva boolean)""")
    # migra tabela pré-existente (criada nesta sessão sem a coluna source); nós somos donos, ALTER ok
    conn.run(f"ALTER TABLE {AUDIT_TBL} ADD COLUMN IF NOT EXISTS source varchar")


def _conservation_rows(conn) -> list:
    """Conservação por fonte, lendo as temps _src/_u + contagens físicas — TUDO no snapshot aberto.
    excl_data/deduplicadas nunca podem ser negativos (seriam sinal de leitura fora de snapshot)."""
    branch = {p: (0, 0) for p in _PRIO}
    for prio, inb, exe in conn.run(
            "SELECT prio, count(*), count(*) FILTER (WHERE em IS NULL OR em='') FROM _src GROUP BY prio"):
        branch[prio] = (inb, exe)
    incl = {p: 0 for p in _PRIO}
    for prio, n in conn.run("SELECT prio, count(*) FROM _u GROUP BY prio"):
        incl[prio] = n
    rows = []
    for prio, (fonte, raw_sql) in _PRIO.items():
        na_fonte = conn.run(raw_sql)[0][0]
        in_branch, excl_email = branch[prio]
        excl_data = na_fonte - in_branch
        incluidas = incl[prio]
        deduplicadas = in_branch - excl_email - incluidas
        conserva = (na_fonte == excl_data + excl_email + deduplicadas + incluidas
                    and excl_data >= 0 and deduplicadas >= 0)
        rows.append({"prio": prio, "fonte": fonte, "na_fonte": na_fonte, "excl_data": excl_data,
                     "excl_email": excl_email, "deduplicadas": deduplicadas,
                     "incluidas": incluidas, "conserva": conserva})
    return rows


def build_unified(cloud_conn, *, write: bool = False) -> dict:
    """Reconstrói o train_unified das fontes atômicas. Pressupõe lead_surveys_stg já espelhado.
    write=False = dry-run (conta por proveniência). write=True grava + audita atomicamente."""
    cloud_conn.run("SET search_path TO analytics, public")
    src = _src_cte()
    if not write:
        by_prov = cloud_conn.run(
            f"WITH {src}, dedup AS ({_DEDUP.format(rel='src')}) "
            "SELECT split_part(prov,':',1), count(*) FROM dedup GROUP BY 1 ORDER BY 2 DESC")
        total = sum(n for _, n in by_prov)
        return {"mode": "dry-run", "por_proveniencia": {p: n for p, n in by_prov}, "total": total}

    _ensure_provenance_table(cloud_conn)
    _ensure_audit_table(cloud_conn)
    # REPEATABLE READ: leads, linhagem e auditoria saem todos do MESMO snapshot congelado.
    cloud_conn.run("BEGIN ISOLATION LEVEL REPEATABLE READ")
    try:
        cloud_conn.run("DROP TABLE IF EXISTS _src")
        cloud_conn.run("DROP TABLE IF EXISTS _u")
        # 1) materializa pré-dedup (_src) e dedup (_u) — congela o snapshot das 5 fontes
        cloud_conn.run(f"CREATE TEMP TABLE _src AS WITH {src} SELECT * FROM src")
        cloud_conn.run(
            f"CREATE TEMP TABLE _u AS SELECT *, md5(em || '|' || (dt::date)::text) AS event_id "
            f"FROM ({_DEDUP.format(rel='_src')}) q")
        # 2) conservação por fonte no MESMO snapshot; aborta se alguma fonte não fechar
        rows = _conservation_rows(cloud_conn)
        if not all(r["conserva"] for r in rows):
            raise RuntimeError(f"conservação falhou: {[r for r in rows if not r['conserva']]}")
        # 3) substitui train_unified + linhagem (idempotente; rollback = transação)
        deleted = cloud_conn.run(f"WITH d AS (DELETE FROM analytics.leads WHERE source='{UNIFIED_SOURCE}' RETURNING 1) SELECT count(*) FROM d")[0][0]
        cloud_conn.run(f"""
            INSERT INTO analytics.leads
              (client_id, source, event_id, email, phone, capturado_em,
               utm_source, utm_medium, utm_campaign, utm_content, utm_term, user_agent,
               survey_responses, ingested_at)
            SELECT 'devclub', '{UNIFIED_SOURCE}', event_id, email, phone, dt,
                   utm_source, utm_medium, utm_campaign, utm_content, utm_term, user_agent,
                   canon, now()
            FROM _u""")
        cloud_conn.run(f"DELETE FROM {PROVENANCE_TBL} WHERE source='{UNIFIED_SOURCE}'")
        cloud_conn.run(f"""
            INSERT INTO {PROVENANCE_TBL} (source, event_id, provenance, prio, ingested_at)
            SELECT '{UNIFIED_SOURCE}', event_id, prov, prio, now() FROM _u""")
        # 4) persiste a reconciliação desta execução (mesmo snapshot); limpa runs impossíveis
        cloud_conn.run(f"DELETE FROM {AUDIT_TBL} WHERE deduplicadas < 0 OR excl_data < 0 OR conserva = false")
        for r in rows:
            cloud_conn.run(
                f"INSERT INTO {AUDIT_TBL} (run_at, source, prio, fonte, na_fonte, excl_data, "
                f"excl_email, deduplicadas, incluidas, conserva) "
                f"VALUES (now(),:s,:p,:f,:nf,:ed,:ee,:dd,:inc,:cv)",
                s=UNIFIED_SOURCE, p=r["prio"], f=r["fonte"], nf=r["na_fonte"], ed=r["excl_data"],
                ee=r["excl_email"], dd=r["deduplicadas"], inc=r["incluidas"], cv=r["conserva"])
        cloud_conn.run("COMMIT")
    except Exception:
        try:
            cloud_conn.run("ROLLBACK")  # conexão morta = PG já reverteu
        except Exception:
            pass
        raise
    total = cloud_conn.run(f"SELECT count(*) FROM analytics.leads WHERE source='{UNIFIED_SOURCE}'")[0][0]
    prov_n = cloud_conn.run(f"SELECT count(*) FROM {PROVENANCE_TBL} WHERE source='{UNIFIED_SOURCE}'")[0][0]
    incl_total = sum(r["incluidas"] for r in rows)
    logger.info("[leads_unify] source=%s deletados=%d gravados=%d linhagem=%d", UNIFIED_SOURCE, deleted, total, prov_n)
    return {"mode": "write", "deleted_before": deleted, "total": total, "linhagem": prov_n,
            "conserva_tudo": all(r["conserva"] for r in rows),
            "tudo_bate": total == prov_n == incl_total, "por_fonte": rows}


def audit_unified(cloud_conn) -> dict:
    """Verificador READ-ONLY: lê a última reconciliação persistida (gerada pelo write, em snapshot
    congelado) e confere que leads == linhagem == soma(incluídas). Não recomputa sobre fonte viva."""
    cloud_conn.run("SET search_path TO analytics, public")
    last = cloud_conn.run(
        f"SELECT prio, fonte, na_fonte, excl_data, excl_email, deduplicadas, incluidas, conserva "
        f"FROM {AUDIT_TBL} WHERE run_at=(SELECT max(run_at) FROM {AUDIT_TBL}) ORDER BY prio")
    por_fonte = [{"prio": p, "fonte": f, "na_fonte": nf, "excl_data": ed, "excl_email": ee,
                  "deduplicadas": dd, "incluidas": inc, "conserva": cv}
                 for p, f, nf, ed, ee, dd, inc, cv in last]
    leads_n = cloud_conn.run(f"SELECT count(*) FROM analytics.leads WHERE source='{UNIFIED_SOURCE}'")[0][0]
    prov_n = cloud_conn.run(f"SELECT count(*) FROM {PROVENANCE_TBL} WHERE source='{UNIFIED_SOURCE}'")[0][0]
    incl_total = sum(r["incluidas"] for r in por_fonte)
    return {"mode": "audit-verify", "conserva_tudo": all(r["conserva"] for r in por_fonte),
            "leads": leads_n, "linhagem": prov_n, "audit_incluidas_total": incl_total,
            "tudo_bate": leads_n == prov_n == incl_total, "por_fonte": por_fonte}


def _open(prefix, timeout=600):
    import os, ssl, pg8000.native
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    return pg8000.native.Connection(
        host=os.environ[f"{prefix}_HOST"], port=int(os.environ.get(f"{prefix}_PORT", "5432")),
        database=os.environ[f"{prefix}_NAME"], user=os.environ[f"{prefix}_USER"],
        password=os.environ[f"{prefix}_PASSWORD"], ssl_context=ctx, timeout=timeout)


def main():
    import argparse, json
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Reconstrução da fonte única de leads (train_unified)")
    ap.add_argument("--write", action="store_true", help="grava + audita atomicamente (default: dry-run)")
    ap.add_argument("--audit", action="store_true", help="verifica a última reconciliação gravada (read-only)")
    ap.add_argument("--skip-mirror", action="store_true", help="não re-espelhar lead_surveys")
    args = ap.parse_args()

    cloud = _open("LEDGER_DB", timeout=1800)  # write materializa ~316k linhas com jsonb: socket folgado
    cloud.run("SET search_path TO analytics, public")
    if not args.skip_mirror and not args.audit:
        rail = _open("RAILWAY_DB", timeout=120)
        mirror_lead_surveys(rail, cloud); rail.close()

    def _run():
        if args.audit:
            return audit_unified(cloud)
        return build_unified(cloud, write=args.write)

    # operação transacional + idempotente → retry seguro reconectando em blip de rede.
    res = None
    for attempt in range(1, 4):
        try:
            res = _run(); break
        except Exception as e:
            if attempt == 3:
                raise
            logger.warning("[leads_unify] tentativa %d falhou (%s); reconectando", attempt, e)
            try:
                cloud.close()
            except Exception:
                pass
            cloud = _open("LEDGER_DB", timeout=1800)
            cloud.run("SET search_path TO analytics, public")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    cloud.close()


if __name__ == "__main__":
    main()
