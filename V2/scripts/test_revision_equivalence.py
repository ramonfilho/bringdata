#!/usr/bin/env python3
"""
[Gate C] Equivalência de score+decil+valor entre revisões Cloud Run.

Compara N leads históricos (Railway) entre uma revisão alvo e uma referência.
Falha se houver diferença em decil OU em valor_projetado. Score com tolerância.

Modo default `capi-dry-run`: usa /capi/process_daily_batch?dry_run=true que
exercita o caminho A/B completo (utm routing → variant matching → conversion_rates
override) e retorna o `valor_projetado` calculado SEM chamar Meta. Cobre o bug
do champion_jan30/challenger_abr28 com conversion_rates zerado (08/05/2026).

Modo `predict`: usa /predict/batch (NÃO toca path A/B) — só compara score+decil.
Útil quando você quer validar o pipeline de scoring isoladamente.

Uso típico (entre Gate B e promoção 0→10%):
    python3 V2/scripts/test_revision_equivalence.py smart-ads-api-00404-xxx

Forçar referência específica:
    python3 ... smart-ads-api-00404-xxx --reference smart-ads-api-00397-hic

Quando o objetivo da revisão alvo é mudar o scoring (novo modelo):
    python3 ... smart-ads-api-00410-xyz --expect-score-change

Pré-requisitos:
- env vars RAILWAY_DB_* (carregar V2/.env via `eval "$(grep -E '^RAILWAY_DB_' V2/.env | sed 's/^/export /')"`)
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
VALUE_TOL = 0.01  # R$ 0.01 — round() na expressão value=value, evita flutuação numérica


# ============================================================================
# gcloud helpers
# ============================================================================

def get_revision_url(revision: str, region: str, project: str, service: str = 'smart-ads-api') -> str:
    """URL tagged da revisão. Para 100%, retorna URL principal do serviço."""
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


# ============================================================================
# Railway data fetching
# ============================================================================

def _connect_railway() -> pg8000.native.Connection:
    return pg8000.native.Connection(
        host=os.environ['RAILWAY_DB_HOST'],
        port=int(os.environ['RAILWAY_DB_PORT']),
        user=os.environ['RAILWAY_DB_USER'],
        password=os.environ['RAILWAY_DB_PASSWORD'],
        database=os.environ['RAILWAY_DB_NAME'],
        ssl_context=True,
    )


def fetch_leads_predict_mode(n: int) -> list[dict[str, Any]]:
    """Pega N leads para o endpoint /predict/batch (sem score)."""
    conn = _connect_railway()
    cols = ', '.join(f'pesquisa->>\'{k}\' AS "{q}"' for q, k in PESQUISA_KEYS.items())
    sql = f"""
        SELECT email, data,
               source AS "Source", medium AS "Medium", term AS "Term",
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


def fetch_leads_capi_mode(n: int) -> list[dict[str, Any]]:
    """
    Pega N leads para /capi/process_daily_batch?dry_run=true.

    Faz JOIN Lead × leads_capi pra montar payload com utm_*, FBP/FBC, lead_score
    já populado. Esses campos são o que o A/B router lê pra decidir variant.
    """
    conn = _connect_railway()
    sql = """
        SELECT
            l.email,
            l."leadScore" AS lead_score,
            l.data,
            l.source AS "Source",
            l.medium AS "Medium",
            l.term   AS "Term",
            COALESCE(lc.utm_source,   l.source) AS utm_source,
            COALESCE(lc.utm_medium,   l.medium) AS utm_medium,
            COALESCE(lc.utm_term,     l.term)   AS utm_term,
            lc.utm_campaign,
            lc.utm_content,
            lc.event_source_url
        FROM "Lead" l
        LEFT JOIN leads_capi lc ON LOWER(lc.email) = LOWER(l.email)
        WHERE l.pesquisa IS NOT NULL
          AND l."leadScore" IS NOT NULL
          AND l."createdAt" >= NOW() - INTERVAL '7 days'
        ORDER BY l."createdAt" DESC
        LIMIT :n
    """
    rows = conn.run(sql, n=n)
    conn.close()
    keys = ['email', 'lead_score', 'data', 'Source', 'Medium', 'Term',
            'utm_source', 'utm_medium', 'utm_term', 'utm_campaign', 'utm_content',
            'event_source_url']
    leads = []
    for r in rows:
        d = dict(zip(keys, r))
        email = d.pop('email')
        if d.get('data') is not None:
            d['data'] = d['data'].isoformat() if hasattr(d['data'], 'isoformat') else str(d['data'])
        d['lead_score'] = float(d['lead_score'])
        d['email'] = email
        d = {k: v for k, v in d.items() if v is not None}
        leads.append(d)
    return leads


# ============================================================================
# HTTP calls
# ============================================================================

def _post_json(url: str, body: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode())


def call_predict_batch(url: str, leads: list[dict[str, Any]]) -> dict:
    payload = {
        'leads': [{'data': l['data'], 'email': l['email'], 'row_id': l['row_id']} for l in leads],
        'request_id': f'gate_c_predict_{os.getpid()}',
    }
    return _post_json(f"{url}/predict/batch", payload)


def call_capi_dry_run(url: str, leads: list[dict[str, Any]]) -> dict:
    payload = {
        'leads': leads,
        'dry_run': True,
    }
    return _post_json(f"{url}/capi/process_daily_batch", payload)


# ============================================================================
# Comparison
# ============================================================================

def _index_predict(resp: dict) -> dict[str, dict]:
    """{row_id: {decil, lead_score}}"""
    return {p['row_id']: {'decil': p['decil'], 'lead_score': p['lead_score']}
            for p in resp.get('predictions', [])}


def _index_capi_dry_run(resp: dict) -> dict[str, dict]:
    """{email: {decil, valor_projetado, event_name}}"""
    out = {}
    for d in resp.get('details', []):
        if d.get('status') != 'success':
            continue
        ev = d.get('evento_com_valor', {})
        out[d['email']] = {
            'decil': ev.get('decil'),
            'valor_projetado': ev.get('valor_projetado'),
            'event_name': ev.get('event_name'),
            'pixel_id': ev.get('pixel_id'),
        }
    return out


def compare_predict(ref: dict, tgt: dict, expect_change: bool) -> int:
    ref_idx = _index_predict(ref)
    tgt_idx = _index_predict(tgt)
    ids = sorted(set(ref_idx) & set(tgt_idx))
    decil_diffs = [(rid, ref_idx[rid]['decil'], tgt_idx[rid]['decil'])
                   for rid in ids if ref_idx[rid]['decil'] != tgt_idx[rid]['decil']]
    score_diffs = [(rid, ref_idx[rid]['lead_score'], tgt_idx[rid]['lead_score'])
                   for rid in ids if abs(ref_idx[rid]['lead_score'] - tgt_idx[rid]['lead_score']) > SCORE_TOL]
    print()
    print(f"  Modo: predict (sem path A/B)")
    print(f"  Total comparados:    {len(ids)}")
    print(f"  Decis divergentes:   {len(decil_diffs)}")
    print(f"  Scores divergentes:  {len(score_diffs)} (tol={SCORE_TOL})")
    return _verdict(bool(decil_diffs or score_diffs), expect_change, decil_diffs[:5])


def compare_capi_dry_run(ref: dict, tgt: dict, expect_change: bool) -> int:
    ref_idx = _index_capi_dry_run(ref)
    tgt_idx = _index_capi_dry_run(tgt)
    ids = sorted(set(ref_idx) & set(tgt_idx))
    decil_diffs = [(rid, ref_idx[rid]['decil'], tgt_idx[rid]['decil'])
                   for rid in ids if ref_idx[rid]['decil'] != tgt_idx[rid]['decil']]
    value_diffs = []
    for rid in ids:
        rv = ref_idx[rid]['valor_projetado']
        tv = tgt_idx[rid]['valor_projetado']
        if rv is None or tv is None or abs(float(rv) - float(tv)) > VALUE_TOL:
            value_diffs.append((rid, rv, tv))
    name_diffs = [(rid, ref_idx[rid]['event_name'], tgt_idx[rid]['event_name'])
                  for rid in ids if ref_idx[rid]['event_name'] != tgt_idx[rid]['event_name']]
    print()
    print(f"  Modo: capi-dry-run (path A/B coberto)")
    print(f"  Total comparados:    {len(ids)}")
    print(f"  Decis divergentes:   {len(decil_diffs)}")
    print(f"  Values divergentes:  {len(value_diffs)} (tol={VALUE_TOL})")
    print(f"  Event names divergentes: {len(name_diffs)}")
    if value_diffs:
        print()
        print("  Amostras de divergência em value:")
        for rid, rv, tv in value_diffs[:10]:
            print(f"    {rid[:40]:40s}  ref={rv}  tgt={tv}")
    return _verdict(bool(decil_diffs or value_diffs or name_diffs), expect_change, decil_diffs[:5])


def _verdict(any_diff: bool, expect_change: bool, sample_decil_diffs: list) -> int:
    if expect_change:
        if not any_diff:
            print()
            print("  ⚠️  --expect-score-change foi passado mas tudo idêntico. Confirme antes de promover.")
            return 0
        print()
        print("  ✅ Mudança de scoring/value detectada (esperada via --expect-score-change).")
        return 0
    if any_diff:
        if sample_decil_diffs:
            print()
            print("  Amostras de divergência em decil:")
            for rid, rd, td in sample_decil_diffs:
                print(f"    {rid[:40]:40s}  ref={rd}  tgt={td}")
        print()
        print("  ❌ FALHOU — divergência inesperada entre revisões.")
        print("     Se a mudança é intencional, re-rode com --expect-score-change.")
        return 1
    print()
    print("  ✅ PASSOU — sem divergência entre revisões.")
    return 0


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('target', help='Revisão alvo (ex: smart-ads-api-00404-xxx)')
    ap.add_argument('--reference', help='Revisão referência. Default: revisão com 100% tráfego.')
    ap.add_argument('--region', default='us-central1')
    ap.add_argument('--project', default='smart-ads-451319')
    ap.add_argument('--n', type=int, default=30, help='Número de leads (default: 30)')
    ap.add_argument('--mode', choices=['capi-dry-run', 'predict'], default='capi-dry-run',
                    help='capi-dry-run (default): cobre path A/B + value. predict: só score+decil.')
    ap.add_argument('--expect-score-change', action='store_true',
                    help='A revisão alvo MUDA scoring intencionalmente.')
    args = ap.parse_args()

    print(f"[gate C] Target:    {args.target}")
    print(f"[gate C] Modo:      {args.mode}")

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
    fetch_fn = fetch_leads_capi_mode if args.mode == 'capi-dry-run' else fetch_leads_predict_mode
    leads = fetch_fn(args.n)
    if not leads:
        print("[gate C] ❌ Nenhum lead encontrado no Railway.")
        return 2
    print(f"[gate C] ✅ {len(leads)} leads carregados")

    if args.mode == 'capi-dry-run':
        print(f"[gate C] POST /capi/process_daily_batch?dry_run=true em {reference} (referência)...")
        ref = call_capi_dry_run(ref_url, leads)
        print(f"[gate C] POST /capi/process_daily_batch?dry_run=true em {args.target} (alvo)...")
        tgt = call_capi_dry_run(tgt_url, leads)
        return compare_capi_dry_run(ref, tgt, args.expect_score_change)
    else:
        print(f"[gate C] POST /predict/batch em {reference} (referência)...")
        ref = call_predict_batch(ref_url, leads)
        print(f"[gate C] POST /predict/batch em {args.target} (alvo)...")
        tgt = call_predict_batch(tgt_url, leads)
        return compare_predict(ref, tgt, args.expect_score_change)


if __name__ == '__main__':
    sys.exit(main())
