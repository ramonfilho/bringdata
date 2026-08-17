"""Fecha os leads que ficaram esperando resposta da Hotmart para sempre.

CONTEXTO (incidente de 06 a 14/08/2026). O fluxo HotLeads é ida e volta: a
gente manda um lote de emails para a Hotmart perguntando "esse já comprou algo
com vocês?" e ela responde ~17s depois batendo num endereço nosso. Entre 06 e
14/08 esse endereço passou a exigir credencial do Google, a Hotmart levou porta
na cara e NÃO tenta entregar de novo. A ida funcionou; a resposta se perdeu.

O re-envio automático (a cada 6h) só pega lead com até 7 dias de vida. Quando o
endereço foi consertado, 4 leads de 06-07/08 já tinham envelhecido além disso:
ficaram "esperando resposta" sem ninguém para responder. Em 16/08 eles foram
re-submetidos NA MÃO (execução ad362391) e, 24h depois, a Hotmart seguia sem
devolver o selo desses 4 — no mesmo período 1.525 selos voltaram normalmente,
ou seja, o fluxo está saudável e o problema é específico desses emails.

O QUE ESTE SCRIPT FAZ (roda uma vez e nunca mais):

1. Lead cujo email JÁ tem resposta guardada na tabela de selos (de uma captação
   anterior): copia a resposta para o ledger — é exatamente o que a volta da
   Hotmart teria escrito. Fica 'scored' com o valor real do selo.
2. Lead sem resposta em lugar nenhum: recebe o estado final 'sem_retorno' com o
   motivo escrito no campo de erro. Esse valor é INERTE no código: a seleção de
   elegíveis só pega status NULL ou 'submitted', e o relatório das 06:00 só
   conta 'error'/'submitted' — ou seja, o lead sai da linha de pendência sem
   virar alarme e sem sumir do histórico.

Se a Hotmart um dia responder, o webhook sobrescreve normalmente: `store_seal`
só protege quem já está em 'sent'.

Uso:
    python -m scripts.fechar_hotleads_presos_pane_agosto            # só mostra
    python -m scripts.fechar_hotleads_presos_pane_agosto --aplicar  # escreve
"""
from __future__ import annotations

import argparse
import sys

MOTIVO = (
    "sem_retorno: submetido durante a pane do callback (06-14/08/2026, endereco "
    "de volta exigindo credencial Google); a Hotmart nao reentrega. Envelheceu "
    "para fora da janela de 7d do re-envio automatico. Re-submetido na mao em "
    "16/08/2026 (exec ad362391) e sem selo depois de 24h com o fluxo saudavel "
    "(1.525 selos no mesmo periodo). Fechado em 17/08/2026 por decisao manual."
)

JANELA_DIAS = 7  # a MESMA do re-envio automático (hotleads.submit_window_days)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true",
                    help="escreve no banco (sem isso, só mostra o que faria)")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    from src.data.ledger_connection import open_cloudsql_ledger_connection

    conn = open_cloudsql_ledger_connection()
    try:
        presos = conn.run(
            """
            SELECT r.event_id, r.email, r.created_at, r.hotleads_submitted_at,
                   s.hot, s.sealed_at, s.execution_id
            FROM registros_ml r
            LEFT JOIN analytics.hotleads_seal s ON lower(s.email) = lower(r.email)
            WHERE r.hotleads_status = 'submitted'
              AND r.created_at < NOW() - (:wd * INTERVAL '1 day')
            ORDER BY r.created_at
            """,
            wd=JANELA_DIAS,
        )
        if not presos:
            print("nada preso fora da janela — nada a fazer.")
            return 0

        com_selo = [p for p in presos if p[4] is not None]
        sem_selo = [p for p in presos if p[4] is None]

        print(f"presos fora da janela de {JANELA_DIAS}d: {len(presos)}")
        for ev, em, criado, submetido, hot, selado, exec_id in presos:
            marca = f"selo hot={hot} de {selado:%d/%m}" if hot is not None else "SEM resposta"
            print(f"  {em[:6]}*** criado {criado:%d/%m} submetido {submetido:%d/%m %H:%M} -> {marca}")

        if not args.aplicar:
            print(f"\nDRY-RUN. Aplicaria: {len(com_selo)} com selo copiado, "
                  f"{len(sem_selo)} fechados como 'sem_retorno'. Rode com --aplicar.")
            return 0

        # 1) quem já tem resposta guardada: copia para o ledger (o que o webhook faria)
        for ev, em, _c, _s, hot, selado, exec_id in com_selo:
            conn.run(
                """
                UPDATE registros_ml
                SET hotleads_hot = :hot,
                    hotleads_scored_at = :selado,
                    hotleads_status = 'scored',
                    hotleads_execution_id = COALESCE(:exec_id, hotleads_execution_id)
                WHERE event_id = :ev AND hotleads_status = 'submitted'
                """,
                hot=hot, selado=selado, exec_id=exec_id, ev=ev,
            )
            print(f"  copiado selo (hot={hot}) -> {em[:6]}***")

        # 2) quem não tem resposta em lugar nenhum: estado final + motivo
        for ev, em, *_ in sem_selo:
            conn.run(
                """
                UPDATE registros_ml
                SET hotleads_status = 'sem_retorno',
                    hotleads_error = :motivo
                WHERE event_id = :ev AND hotleads_status = 'submitted'
                """,
                motivo=MOTIVO, ev=ev,
            )
            print(f"  fechado sem_retorno -> {em[:6]}***")

        restante = conn.run(
            """
            SELECT COUNT(*) FROM registros_ml
            WHERE hotleads_status = 'submitted'
              AND created_at < NOW() - (:wd * INTERVAL '1 day')
            """,
            wd=JANELA_DIAS,
        )[0][0]
        print(f"\nOK. presos fora da janela agora: {restante} (esperado 0)")
        return 0 if restante == 0 else 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
