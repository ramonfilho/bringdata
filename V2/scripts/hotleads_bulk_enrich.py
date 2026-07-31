#!/usr/bin/env python3
"""Enriquece a base HISTÓRICA de leads com o selo do HotLeads (compra na Hotmart).

Percorre `analytics.leads` em lotes de até 1.000 e submete ao `batch_enrich`. O
selo volta pelo webhook de produção, que reconhece o rótulo `bulk` e grava em
`analytics.hotleads_seal` — SEM disparar evento no pixel (são leads antigos,
fora da janela de 7 dias do Meta; o objetivo é medir e segmentar, não anunciar).

Retomável: pula quem já tem selo, então pode rodar de novo depois de uma queda
sem re-perguntar o que já foi respondido.

⚠️ O selo é um retrato de HOJE ("já comprou na Hotmart até agora"), não do
estado na captura do lead. Serve para medir valor e montar público; para virar
feature de treino exige o diagnóstico de lift por idade de coorte.

Uso:
    python3 scripts/hotleads_bulk_enrich.py --dry-run
    python3 scripts/hotleads_bulk_enrich.py --limit 5000 --execute
    python3 scripts/hotleads_bulk_enrich.py --execute            # base toda
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from src.core.client_config import ClientConfig  # noqa: E402
from src.core.hotmart_auth import get_hotmart_access_token  # noqa: E402
from src.data.analytics_connection import open_analytics_connection  # noqa: E402

API = "https://developers.hotmart.com/send/api/v1/leadscoring/batch_enrich"
BATCH = 1000
MAX_TENTATIVAS = 5      # a API da Hotmart oscila: timeout e 500 sob volume
ESPERA_BASE = 10        # segundos; dobra a cada tentativa (10, 20, 40, 80)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="sem isso, só conta quantos seriam enviados")
    ap.add_argument("--limit", type=int, default=None,
                    help="teto de leads nesta execução (default: todos)")
    ap.add_argument("--sleep", type=float, default=3.0,
                    help="pausa entre lotes, em segundos (respeita a API)")
    ap.add_argument("--webhook", default=None,
                    help="URL de retorno; default = serviço de produção + token")
    args = ap.parse_args()

    cfg = ClientConfig.from_yaml("configs/clients/devclub.yaml")
    if not cfg.hotleads.enabled:
        print("hotleads.enabled=false no YAML — nada a fazer")
        return 1

    webhook = args.webhook
    if not webhook:
        base = os.environ.get("HOTLEADS_PUBLIC_URL",
                              "https://smart-ads-api-gazrm25mda-uc.a.run.app")
        token = os.environ.get("HOTLEADS_WEBHOOK_TOKEN", "")
        if not token:
            print("ERRO: HOTLEADS_WEBHOOK_TOKEN ausente — o selo não teria como voltar.")
            return 1
        webhook = f"{base.rstrip('/')}/hotleads/webhook?token={token}"

    conn = open_analytics_connection()

    pendentes = conn.run(
        """
        SELECT COUNT(DISTINCT lower(l.email))
        FROM analytics.leads l
        LEFT JOIN analytics.hotleads_seal s ON s.email = lower(l.email)
        WHERE l.email IS NOT NULL AND l.email <> '' AND s.email IS NULL
        """
    )[0][0]
    ja = conn.run("SELECT COUNT(*) FROM analytics.hotleads_seal")[0][0]
    print(f"já com selo : {ja:,}")
    print(f"pendentes   : {pendentes:,}")
    alvo = min(pendentes, args.limit) if args.limit else pendentes
    print(f"a enviar    : {alvo:,}  (~{-(-alvo // BATCH)} lotes de {BATCH})")

    if not args.execute:
        print("\n[dry-run] nada enviado. Use --execute para valer.")
        return 0

    token = get_hotmart_access_token(cfg.hotleads.basic_auth_env_var)
    if not token:
        print("ERRO: sem token da Hotmart")
        return 1
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Carrega a lista de pendentes UMA VEZ e itera sobre ela.
    #
    # ⚠️ Não dá pra reconsultar "quem ainda não tem selo" a cada lote: o selo só
    # volta pelo webhook ~2 min depois, e o laço avança em segundos. Reconsultar
    # devolveria os MESMOS emails e o script remoeria o primeiro bloco pra
    # sempre — foi exatamente o que aconteceu no teste de 2.000 (os 2 lotes
    # voltaram idênticos, 986 selos e 92 quentes nos dois). A consulta inicial
    # já exclui quem tem selo, então a retomada entre execuções segue valendo.
    todos = conn.run(
        """
        SELECT lower(l.email), MAX(l.phone)
        FROM analytics.leads l
        LEFT JOIN analytics.hotleads_seal s ON s.email = lower(l.email)
        WHERE l.email IS NOT NULL AND l.email <> '' AND s.email IS NULL
        GROUP BY lower(l.email)
        LIMIT :n
        """,
        n=alvo,
    )
    print(f"carregados  : {len(todos):,} emails distintos\n")

    enviados = 0
    lote_n = 0
    for i in range(0, len(todos), BATCH):
        pedaco = todos[i:i + BATCH]
        leads = [{
            "custom_label": "bulk",
            "email": r[0],
            "phone": str(r[1] or ""),
            "utm": {"source": "", "campaign": "", "medium": "", "term": "", "content": ""},
        } for r in pedaco]

        # A API da Hotmart oscila sob volume: numa passada deu read timeout,
        # noutra HTTP 500 (internal_server_error). Tratar isso como fatal fazia
        # o script morrer no lote 23 de 338 e exigir religar na mão. Agora
        # reenvia o MESMO lote com espera progressiva; só desiste após
        # MAX_TENTATIVAS seguidas, aí sim para pra não martelar.
        resp = None
        for tentativa in range(1, MAX_TENTATIVAS + 1):
            try:
                resp = requests.post(
                    API, headers=headers,
                    json={"webhook": webhook, "leads": leads,
                          "campaign": {"launch_date": "2026-08-04",
                                       "expected_ticket": cfg.hotleads.expected_ticket,
                                       "currency_code_type": cfg.hotleads.currency}},
                    timeout=120,
                )
                if resp.status_code in (200, 201):
                    break
                motivo = f"HTTP {resp.status_code}"
            except Exception as e:
                resp = None
                motivo = f"{type(e).__name__}"
            espera = ESPERA_BASE * (2 ** (tentativa - 1))
            if tentativa < MAX_TENTATIVAS:
                print(f"      {motivo} no lote {lote_n + 1} — tentativa "
                      f"{tentativa}/{MAX_TENTATIVAS}, aguardando {espera}s")
                time.sleep(espera)

        lote_n += 1
        if resp is None or resp.status_code not in (200, 201):
            print(f"  lote {lote_n}: falhou {MAX_TENTATIVAS}x seguidas — parando. "
                  f"Rode de novo depois; o script retoma de onde parou.")
            break

        enviados += len(leads)
        print(f"  lote {lote_n:3d}/{-(-len(todos)//BATCH)}: {len(leads):4d} enviados "
              f"({enviados:,}/{len(todos):,}) exec={resp.json().get('executionId','?')[:8]}")
        time.sleep(args.sleep)

    print(f"\nsubmetidos nesta execução: {enviados:,}")
    print("os selos chegam pelo webhook em ~2 min por lote; "
          "confira com: SELECT COUNT(*) FROM analytics.hotleads_seal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
