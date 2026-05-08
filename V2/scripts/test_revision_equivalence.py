#!/usr/bin/env python3
"""
[Gate C v0] Equivalência de score+decil entre revisões Cloud Run.

Compara N leads históricos (Railway) entre uma revisão alvo e uma referência.
Falha se houver qualquer diferença em decil. Score com tolerância numérica.

Uso típico (entre Gate B e promoção 0→10%):
    python3 V2/scripts/test_revision_equivalence.py smart-ads-api-00403-cez

Por default a referência é a revisão com 100% de tráfego em prod no momento.
Para fixar uma referência específica:
    python3 ... smart-ads-api-00403-cez --reference smart-ads-api-00397-hic

Quando o objetivo da revisão alvo é mudar o scoring (novo modelo, encoder, etc):
    python3 ... smart-ads-api-00410-xyz --expect-score-change

Pré-requisitos:
- env vars RAILWAY_DB_* (carregar V2/.env via `set -a; source V2/.env; set +a`)
- gcloud autenticado com acesso ao serviço smart-ads-api
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

import pg8000.native


PESQUISA_KEYS = {
    'O seu gênero:':                          'genero',
    'Qual a sua idade?':                      'idade',
    'O que você faz atualmente?':             'ocupacao',
    'Atualmente, qual a sua faixa salarial?': 'faixaSalarial',
    'Você possui cartão de crédito?':         'cartaoCredito',
    'Já estudou programação?':                'estudouProgramacao',
    'Tem computador/notebook?':               'computador',
}

SCORE_TOL = 1e-6


def get_revision_url(revision: str, region: str, project: str, service: str = 'smart-ads-api') -> str:
    """URL tagged da revisão. Para 100%, retorna a URL principal do serviço."""
    res = subprocess.run(
        ['gcloud', 'run', 'services', 'describe', service,
         '--region', region, '--project', project, '--format=json'],
        capture_output=True, text=True, check=True, timeout=30,
    )
    svc = json.loads(res.stdout)
    traffic = svc.get('status', {}).get('traffic', [])
    for entry in traffic:
        if entry.get('revisionName') == revision and entry.get('url'):
            return entry['url']
    summary = [f"{e.get('revisionName')} (tag={e.get('tag', '-')}, pct={e.get('percent', 0)})" for e in traffic]
    raise RuntimeError(f"Revisão '{revision}' sem URL tagged.\nTráfego atual: {summary}")


def get_prod_revision(region: str, project: str, service: str = 'smart-ads-api') -> str:
    """Retorna a revisão com 100% de tráfego (rolling baseline)."""
    res = subprocess.run(
        ['gcloud', 'run', 'services', 'describe', service,
         '--region', region, '--project', project, '--format=json'],
        capture_output=True, text=True, check=True, timeout=30,
    )
    svc = json.loads(res.stdout)
    traffic = svc.get('status', {}).get('traffic', [])
    candidates = [e for e in traffic if e.get('percent') == 100]
    if len(candidates) == 1:
        return candidates[0]['revisionName']
    raise RuntimeError(f"Não consegui identificar revisão 100%. Candidatos: {candidates}")


def fetch_leads(n: int) -> list[dict[str, Any]]:
    """Pega últimos N leads do Railway com pesquisa preenchida."""
    conn = pg8000.native.Connection(
        host=os.environ['RAILWAY_DB_HOST'],
        port=int(os.environ['RAILWAY_DB_PORT']),
        user=os.environ['RAILWAY_DB_USER'],
        password=os.environ['RAILWAY_DB_PASSWORD'],
        database=os.environ['RAILWAY_DB_NAME'],
        ssl_context=True,
    )
    cols = ', '.join(f'pesquisa->>\'{k}\' AS "{q}"' for q, k in PESQUISA_KEYS.items())
    sql = f"""
        SELECT email, data,
               source AS "Source",
               medium AS "Medium",
               term AS "Term",
               {cols}
        FROM "Lead"
        WHERE pesquisa IS NOT NULL
          AND "leadScore" IS NOT NULL
          AND "createdAt" >= NOW() - INTERVAL '7 days'
        ORDER BY "createdAt" DESC
        LIMIT :n
    """
    rows = conn.run(sql, n=n)
    conn.close()

    keys = ['email', 'Data', 'Source', 'Medium', 'Term'] + list(PESQUISA_KEYS.keys())
    leads = []
    for r in rows:
        d = dict(zip(keys, r))
        email = d.pop('email')
        if d.get('Data') is not None:
            d['Data'] = d['Data'].isoformat() if hasattr(d['Data'], 'isoformat') else str(d['Data'])
        d = {k: v for k, v in d.items() if v is not None}
        leads.append({'email': email, 'data': d, 'row_id': email or f'row_{len(leads)}'})
    return leads


def call_predict_batch(url: str, leads: list[dict[str, Any]], timeout: int = 300) -> dict:
    payload = {
        'leads': [{'data': l['data'], 'email': l['email'], 'row_id': l['row_id']} for l in leads],
        'request_id': f'gate_c_{os.getpid()}',
    }
    req = urllib.request.Request(
        f"{url}/predict/batch",
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode())


def compare(ref: dict, tgt: dict, expect_change: bool) -> int:
    """Imprime diff e retorna exit code."""
    ref_by_id = {p['row_id']: p for p in ref['predictions']}
    tgt_by_id = {p['row_id']: p for p in tgt['predictions']}
    ids = sorted(set(ref_by_id) & set(tgt_by_id))

    decil_diffs = []
    score_diffs = []
    for rid in ids:
        r, t = ref_by_id[rid], tgt_by_id[rid]
        if r['decil'] != t['decil']:
            decil_diffs.append((rid, r['decil'], t['decil'], r['lead_score'], t['lead_score']))
        if abs(r['lead_score'] - t['lead_score']) > SCORE_TOL:
            score_diffs.append((rid, r['lead_score'], t['lead_score']))

    n = len(ids)
    print()
    print(f"  Total comparados:    {n}")
    print(f"  Decis divergentes:   {len(decil_diffs)}")
    print(f"  Scores divergentes:  {len(score_diffs)} (tol={SCORE_TOL})")

    if decil_diffs:
        print()
        print("  Amostras de divergência em decil:")
        for rid, rd, td, rs, ts in decil_diffs[:10]:
            print(f"    {rid[:40]:40s}  ref={rd}({rs:.4f})  tgt={td}({ts:.4f})")

    if expect_change:
        if not decil_diffs and not score_diffs:
            print()
            print("  ⚠️  --expect-score-change foi passado mas score é idêntico.")
            print("      Pode indicar que o modelo NÃO mudou. Confirme antes de promover.")
            return 0
        print()
        print("  ✅ Mudança de scoring detectada (esperada via --expect-score-change).")
        return 0

    if decil_diffs or score_diffs:
        print()
        print("  ❌ FALHOU — divergência inesperada de scoring entre revisões.")
        print("     Se a mudança é intencional, re-rode com --expect-score-change.")
        return 1

    print()
    print("  ✅ PASSOU — score e decil idênticos em todos os leads.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('target', help='Revisão alvo (ex: smart-ads-api-00403-cez)')
    ap.add_argument('--reference', help='Revisão referência. Default: revisão com 100% tráfego.')
    ap.add_argument('--region', default='us-central1')
    ap.add_argument('--project', default='smart-ads-451319')
    ap.add_argument('--n', type=int, default=30, help='Número de leads (default: 30)')
    ap.add_argument('--expect-score-change', action='store_true',
                    help='A revisão alvo MUDA scoring intencionalmente (novo modelo/encoder).')
    args = ap.parse_args()

    print(f"[gate C] Target:    {args.target}")

    if args.reference:
        reference = args.reference
        print(f"[gate C] Reference: {reference} (fixed)")
    else:
        reference = get_prod_revision(args.region, args.project)
        print(f"[gate C] Reference: {reference} (rolling = 100% tráfego)")

    if reference == args.target:
        print("[gate C] ⚠️  target == reference. Nada a comparar.")
        return 0

    print(f"[gate C] Resolvendo URLs...")
    ref_url = get_revision_url(reference, args.region, args.project)
    tgt_url = get_revision_url(args.target, args.region, args.project)

    print(f"[gate C] Buscando {args.n} leads do Railway...")
    leads = fetch_leads(args.n)
    if not leads:
        print("[gate C] ❌ Nenhum lead encontrado no Railway. Não dá pra comparar.")
        return 2
    print(f"[gate C] ✅ {len(leads)} leads carregados")

    print(f"[gate C] POST /predict/batch em {reference} (referência)...")
    ref = call_predict_batch(ref_url, leads)
    print(f"[gate C] POST /predict/batch em {args.target} (alvo)...")
    tgt = call_predict_batch(tgt_url, leads)

    return compare(ref, tgt, args.expect_score_change)


if __name__ == '__main__':
    sys.exit(main())
