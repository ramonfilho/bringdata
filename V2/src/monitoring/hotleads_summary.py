"""Saúde do pipeline HotLeads nas últimas 24h — insumo do bloco do DM.

O fluxo HotLeads (submit → webhook → evento CAPI) roda sozinho num cron de 15
min e, sem esta leitura, uma parada seria INVISÍVEL: o scheduler não alerta em
401/500, a Hotmart não reentrega webhook perdido, e o sintoma final ("o evento
parou de popular") só apareceria no Events Manager dias depois.

Lê o ledger direto (agregação simples, sem passar pelo `LeadRepository`) pelo
mesmo motivo do `decis_by_channel`: é contagem agregada de colunas
`hotleads_*` que o modelo de domínio do repositório não carrega, e ampliar o
modelo por causa de um COUNT espalharia mudança numa camada que muitos
monitores consomem.

Fail-soft por contrato: qualquer erro devolve o esqueleto zerado em vez de
levantar — este bloco NUNCA pode derrubar o relatório das 06:00.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

WINDOW_HOURS = 24


def _empty_summary() -> Dict[str, Any]:
    return {
        'window_hours': WINDOW_HOURS,
        'selados': 0,          # leads que receberam selo na janela
        'quentes': 0,          # selados com hot=1
        'pct_quentes': 0.0,
        'eventos_enviados': 0, # quentes cujo evento CAPI saiu
        'erros': 0,            # falhas de envio ainda não resolvidas
        'aguardando_selo': 0,  # submetidos e sem retorno da Hotmart
        'idade_max_aguardando_h': 0.0,  # há quanto tempo o mais antigo espera
        'sem_selo_na_janela': 0,  # elegíveis que o cron ainda não pegou
        'disponivel': False,   # False = não conseguiu ler (não confundir com "zero")
    }


def compute_hotleads_summary(conn=None, source_allowlist=None) -> Dict[str, Any]:
    """Resumo 24h do pipeline HotLeads.

    Args:
        conn: conexão do ledger já aberta (injetada). None = abre e fecha a sua.
        source_allowlist: as MESMAS fontes que o submit envia (`capi.utm_source_allowlist`).
            Obrigatório na prática para a fila fazer sentido: sem esse filtro, a
            contagem inclui lead de google-ads/manychat/orgânico, que o submit
            NUNCA pega (o evento é do pixel do Meta) — na base do DevClub isso é
            a esmagadora maioria (2.757 de 2.767 numa medição de 30/07), e o
            bloco gritaria "fila alta" todo dia sem nada estar errado.

    Returns:
        Dict com o esqueleto acima. `disponivel=False` distingue "não li" de
        "li e deu zero" — a diferença importa, porque zero selado com o cron
        vivo é alarme, e falha de leitura não é.
    """
    out = _empty_summary()
    own = conn is None
    try:
        if conn is None:
            from src.data.ledger_connection import open_cloudsql_ledger_connection
            conn = open_cloudsql_ledger_connection()

        row = conn.run(
            """
            SELECT
              COUNT(*) FILTER (WHERE hotleads_scored_at >= NOW() - (:h * INTERVAL '1 hour')),
              COUNT(*) FILTER (WHERE hotleads_scored_at >= NOW() - (:h * INTERVAL '1 hour')
                                 AND hotleads_hot IS TRUE),
              COUNT(*) FILTER (WHERE hotleads_capi_sent_at >= NOW() - (:h * INTERVAL '1 hour')),
              COUNT(*) FILTER (WHERE hotleads_status = 'error'),
              COUNT(*) FILTER (WHERE hotleads_status = 'submitted'),
              -- SINAL PRINCIPAL de retorno quebrado. A volta normal leva ~17s;
              -- qualquer coisa acima de uma hora é anomalia inequívoca, e este
              -- número CRESCE sozinho enquanto o problema durar. A fila não
              -- serve para isso: o cron a drena, e foi por isso que o alarme
              -- ficou mudo os 8 dias de 06 a 14/08/2026.
              COALESCE(EXTRACT(EPOCH FROM (
                  NOW() - MIN(hotleads_submitted_at)
                    FILTER (WHERE hotleads_status = 'submitted')
              )) / 3600.0, 0)
            FROM registros_ml
            """,
            h=WINDOW_HOURS,
        )[0]
        out['selados'] = int(row[0] or 0)
        out['quentes'] = int(row[1] or 0)
        out['eventos_enviados'] = int(row[2] or 0)
        out['erros'] = int(row[3] or 0)
        out['aguardando_selo'] = int(row[4] or 0)
        out['idade_max_aguardando_h'] = round(float(row[5] or 0), 1)
        if out['selados']:
            out['pct_quentes'] = round(100.0 * out['quentes'] / out['selados'], 1)

        # Fila: elegíveis da janela de submissão que ainda não têm selo. Fila
        # alta e estável = cron parado ou submissão falhando. O filtro de fonte
        # espelha o do submit — sem ele a conta viraria alarme falso permanente.
        params = {}
        filtro_fonte = ""
        if source_allowlist:
            chaves = []
            for i, src in enumerate(source_allowlist):
                k = f"s{i}"
                params[k] = src
                chaves.append(f":{k}")
            filtro_fonte = f"AND utm_source IN ({', '.join(chaves)})"
        out['sem_selo_na_janela'] = int(conn.run(
            f"""
            SELECT COUNT(*) FROM registros_ml
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND email IS NOT NULL AND email <> ''
              {filtro_fonte}
              AND hotleads_status IS NULL
            """,
            **params
        )[0][0] or 0)
        out['disponivel'] = True
    except Exception as e:
        logger.warning(f"[hotleads_summary] leitura falhou, devolvendo esqueleto: {e}")
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return out
