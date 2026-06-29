"""Unificação das fontes de lead → fonte única `train_unified` em analytics.leads.

Colapsa 6 fontes históricas (3 Sheets → train_pesquisa; Railway antigo lead_legado;
Railway novo leads_historico; Cloud SQL registros_ml) numa fonte única, limpa e
canônica para o treino. Construída sob a /data-architect.

Stitch (fonte autoritativa por período, contíguo, sem overlap):
  - dez/24 → out/25 : train_pesquisa (única fonte do começo; survey já canônico)
  - nov/25 → hoje   : UNION(leads_historico, lead_legado, registros_ml) deduplicado
                      por (lower(email), dia), prioridade produção > RW novo > RW antigo

Server-side (INSERT ... SELECT) para mover ~310k linhas sem round-trip. Idempotente
e reversível: tudo rotulado source='train_unified'; rollback = DELETE WHERE source.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

UNIFIED_SOURCE = "train_unified"
BOUNDARY = "2025-11-01"  # train_pesquisa autoritativo antes; Railway/Cloud a partir

# survey canônico = shape do df_pesquisa (chaves texto-pergunta + 2 aliases).
# Mapas reusam o pesquisa_field_map do devclub.yaml (camelCase) e o snake_case espelho.
_CANON = [  # (chave canônica, chave em leads_historico [snake], chave em lead_legado [camel])
    ("O seu gênero:", "genero", "genero"),
    ("Qual a sua idade?", "idade", "idade"),
    ("O que você faz atualmente?", "ocupacao", "ocupacao"),
    ("Atualmente, qual a sua faixa salarial?", "faixa_salarial", "faixaSalarial"),
    ("Você possui cartão de crédito?", "cartao_credito", "cartaoCredito"),
    ("O que mais você quer ver no evento?", "interesse_evento", "interesseEvento"),
    ("Tem computador/notebook?", "tem_computador", "computador"),
    ("Já estudou programação?", "estudou_programacao", "estudouProgramacao"),
    ("Você já fez/faz/pretende fazer faculdade?", "faculdade", "faculdade"),
    ("investiu_curso_online", "investiu_curso", "investiuCurso"),
    ("interesse_programacao", "atracao_profissao", "atracaoProfissao"),
]


def _survey_obj(jcol: str, key_idx: int) -> str:
    """jsonb_build_object canônico lendo a coluna jsonb `jcol`, escolhendo a chave
    nativa do dialeto (key_idx=1 snake/leads_historico, 2 camel/lead_legado)."""
    parts = []
    for canon, snake, camel in _CANON:
        native = snake if key_idx == 1 else camel
        parts.append(f"'{canon}', {jcol}->>'{native}'")
    return "jsonb_build_object(" + ", ".join(parts) + ")"


def _recent_union_cte() -> str:
    """Union das 3 fontes recentes, cada uma já no shape canônico, com prioridade.
    survey_responses canônico inclui Data/E-mail/Telefone/Nome/Source/Medium/Term +
    as 11 perguntas. registros_ml já vem canônico (copia direto)."""
    hist_survey = _survey_obj("survey_responses", 1)
    leg_survey = _survey_obj("pesquisa", 2)
    return f"""
    src AS (
      -- prioridade 1 = produção (registros_ml): survey_responses já é canônico
      SELECT 1 AS prio, lower(email) AS em, (survey_responses->>'Data')::timestamptz AS dt,
             email, phone, utm_source, utm_medium, utm_term, utm_campaign, utm_content,
             user_agent, survey_responses AS canon
      FROM public.registros_ml
      WHERE (survey_responses->>'Data') ~ '^[0-9]{{4}}-'

      UNION ALL
      -- prioridade 2 = Railway novo (leads_historico): snake_case → canônico
      SELECT 2, lower(email), data_captura,
             email, telefone, utm_source, utm_medium, utm_term, utm_campaign, utm_content,
             NULL,
             jsonb_build_object('Data', to_char(data_captura, 'YYYY-MM-DD"T"HH24:MI:SS'),
               'E-mail', email, 'Nome Completo', nome,
               'Telefone', telefone, 'Source', utm_source, 'Medium', utm_medium, 'Term', utm_term)
             || {hist_survey}
      FROM public.leads_historico WHERE data_captura >= '{BOUNDARY}'

      UNION ALL
      -- prioridade 3 = Railway antigo (lead_legado): camelCase → canônico
      SELECT 3, lower(email), data,
             email, telefone, source, medium, term, campaign, content,
             user_agent,
             jsonb_build_object('Data', to_char(data, 'YYYY-MM-DD"T"HH24:MI:SS'),
               'E-mail', email, 'Nome Completo', nome_completo,
               'Telefone', telefone, 'Source', source, 'Medium', medium, 'Term', term)
             || {leg_survey}
      FROM public.lead_legado WHERE data >= '{BOUNDARY}'
    ),
    dedup AS (
      SELECT DISTINCT ON (em, dt::date) *
      FROM src WHERE em IS NOT NULL
      ORDER BY em, dt::date, prio   -- menor prio = mais autoritativo vence
    )
    """


def _insert_recent_sql() -> str:
    return f"""
    INSERT INTO analytics.leads
      (client_id, source, event_id, email, phone, capturado_em,
       utm_source, utm_medium, utm_campaign, utm_content, utm_term,
       user_agent, survey_responses, ingested_at)
    WITH {_recent_union_cte()}
    SELECT 'devclub', '{UNIFIED_SOURCE}',
           md5(em || '|' || (dt::date)::text), email, phone, dt,
           utm_source, utm_medium, utm_campaign, utm_content, utm_term,
           user_agent, canon, now()
    FROM dedup
    """


def _insert_early_sql() -> str:
    """train_pesquisa < BOUNDARY: survey já canônico, só re-rotula pra train_unified."""
    return f"""
    INSERT INTO analytics.leads
      (client_id, source, event_id, email, phone, capturado_em,
       utm_source, utm_medium, utm_campaign, utm_content, utm_term,
       user_agent, survey_responses, ingested_at)
    SELECT client_id, '{UNIFIED_SOURCE}',
           md5(coalesce(lower(email), event_id) || '|' || ((survey_responses->>'Data')::timestamptz::date)::text),
           email, phone, (survey_responses->>'Data')::timestamptz,
           utm_source, utm_medium, utm_campaign, utm_content, utm_term,
           user_agent, survey_responses, now()
    FROM analytics.leads
    WHERE source='train_pesquisa' AND (survey_responses->>'Data') ~ '^[0-9]{{4}}-'
      AND (survey_responses->>'Data')::timestamptz < '{BOUNDARY}'
    """


def build_unified(conn, *, write: bool = False) -> dict:
    """Constrói a fonte única. write=False só conta (dry-run); write=True grava.
    Sempre limpa o source antes (idempotente). Reversível: DELETE source='train_unified'."""
    conn.run("SET search_path TO analytics, public")
    if not write:
        early = conn.run(f"SELECT count(*) FROM analytics.leads WHERE source='train_pesquisa' "
                         f"AND (survey_responses->>'Data') ~ '^[0-9]{{4}}-' "
                         f"AND (survey_responses->>'Data')::timestamptz < '{BOUNDARY}'")[0][0]
        recent = conn.run(f"WITH {_recent_union_cte()} SELECT count(*) FROM dedup")[0][0]
        return {"mode": "dry-run", "early": early, "recent": recent, "total": early + recent}

    deleted = conn.run(f"WITH d AS (DELETE FROM analytics.leads WHERE source='{UNIFIED_SOURCE}' RETURNING 1) "
                       f"SELECT count(*) FROM d")[0][0]
    conn.run(_insert_early_sql())
    conn.run(_insert_recent_sql())
    total = conn.run(f"SELECT count(*) FROM analytics.leads WHERE source='{UNIFIED_SOURCE}'")[0][0]
    logger.info("[leads_unify] source=%s deletados=%d gravados=%d", UNIFIED_SOURCE, deleted, total)
    return {"mode": "write", "deleted_before": deleted, "total": total}
