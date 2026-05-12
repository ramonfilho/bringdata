"""
CLI thin que fetcha /monitoring/daily-check/railway e imprime o digest no terminal.

Toda lógica de audit/extração/renderização vive em src/monitoring/digest.py.
Este script é só fetch + render_text + print.

Uso:
    python -m scripts.monitoring_digest
    python -m scripts.monitoring_digest --hours 24
    python -m scripts.monitoring_digest --save
    python -m scripts.monitoring_digest --cache         # usa /tmp/payload.json se existir
    python -m scripts.monitoring_digest --show-skipped  # lista paths SKIPPED + razões
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from src.monitoring.digest import (
    extract_view, render_text, PayloadSchemaDriftError,
)
from src.monitoring.payload_schema import PAYLOAD_SCHEMA, FieldDecision

REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_URL = 'https://smart-ads-api-gazrm25mda-uc.a.run.app'
CACHE = Path('/tmp/payload.json')


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--hours', type=int, default=72)
    p.add_argument('--save', action='store_true')
    p.add_argument('--cache', action='store_true', help='Usar /tmp/payload.json se existir')
    p.add_argument('--url', default=PROD_URL)
    p.add_argument('--show-skipped', action='store_true', help='Lista paths SKIPPED com razões e sai')
    return p.parse_args()


def fetch_payload(base_url: str, hours: int, use_cache: bool) -> dict:
    if use_cache and CACHE.exists():
        return json.loads(CACHE.read_text())
    url = f'{base_url}/monitoring/daily-check/railway?hours={hours}'
    print(f'⏳ GET {url} (~30s)…', file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as r:
        raw = r.read().decode('utf-8')
    CACHE.write_text(raw)
    return json.loads(raw)


def print_skipped():
    skipped = [(p, r) for p, (d, r) in PAYLOAD_SCHEMA.items() if d == FieldDecision.SKIPPED]
    if not skipped:
        print('Nenhum path declarado como SKIPPED ainda.')
        return
    print(f'─── PAYLOAD_SCHEMA · {len(skipped)} paths SKIPPED ───\n')
    width = max(len(p) for p, _ in skipped)
    for p, r in sorted(skipped):
        print(f'  {p:<{width}}  →  {r}')


def main():
    args = parse_args()

    if args.show_skipped:
        print_skipped()
        return

    payload = fetch_payload(args.url, args.hours, args.cache)

    try:
        view = extract_view(payload)
    except PayloadSchemaDriftError as e:
        print(f'\n{e}\n', file=sys.stderr)
        sys.exit(2)

    out = render_text(view)
    print(out)

    if args.save:
        out_dir = REPO_ROOT / 'files' / 'monitoring'
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y-%m-%d_%H%M')
        out_path = out_dir / f'digest_{ts}.txt'
        out_path.write_text(out, encoding='utf-8')
        print(f'\n→ Salvo em {out_path.relative_to(REPO_ROOT)}', file=sys.stderr)


if __name__ == '__main__':
    main()
