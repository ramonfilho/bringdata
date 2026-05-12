"""
CLI thin que fetcha /monitoring/daily-check/railway e posta o digest no Slack.

Toda lógica de audit/extração/renderização vive em src/monitoring/digest.py.
Este script é só fetch + render_slack_blocks + POST.

Requer env var SLACK_BOT_TOKEN (xoxb-...).

Uso:
    SLACK_BOT_TOKEN=xoxb-... python -m scripts.slack_digest --channel '#novo-canal'
    SLACK_BOT_TOKEN=xoxb-... python -m scripts.slack_digest --channel '#team-dados' --hours 24
    SLACK_BOT_TOKEN=xoxb-... python -m scripts.slack_digest --channel '#novo-canal' --cache
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from src.monitoring.digest import (
    extract_view, render_slack_blocks, PayloadSchemaDriftError,
)

PROD_URL = 'https://smart-ads-api-gazrm25mda-uc.a.run.app'
CACHE = Path('/tmp/payload.json')
SLACK_API = 'https://slack.com/api/chat.postMessage'


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--channel', required=True, help='Canal destino (ex: #novo-canal)')
    p.add_argument('--hours', type=int, default=72)
    p.add_argument('--cache', action='store_true', help='Usar /tmp/payload.json se existir')
    p.add_argument('--url', default=PROD_URL)
    p.add_argument('--username', default=None,
                   help='Sobrescreve o nome do bot. Default: usa o display name configurado no Slack App.')
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


def post_to_slack(token: str, channel: str, blocks: list, username: str | None) -> dict:
    body = {
        'channel': channel,
        'blocks': blocks,
        'text': 'Daily Check — DevClub',  # fallback pra notificações
    }
    if username:
        body['username'] = username
    req = urllib.request.Request(
        SLACK_API,
        data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8',
                 'Authorization': f'Bearer {token}'},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    args = parse_args()

    token = os.environ.get('SLACK_BOT_TOKEN')
    if not token:
        print('❌ SLACK_BOT_TOKEN não definido no env.', file=sys.stderr)
        sys.exit(1)

    payload = fetch_payload(args.url, args.hours, args.cache)

    try:
        view = extract_view(payload)
    except PayloadSchemaDriftError as e:
        print(f'\n{e}\n', file=sys.stderr)
        sys.exit(2)

    blocks = render_slack_blocks(view)
    print(f'Total blocks: {len(blocks)}', file=sys.stderr)

    resp = post_to_slack(token, args.channel, blocks, args.username)
    if not resp.get('ok'):
        print(f'❌ Slack rejeitou: {resp}', file=sys.stderr)
        sys.exit(3)
    print(f"✓ posted to {resp.get('channel')} · ts={resp.get('ts')}", file=sys.stderr)


if __name__ == '__main__':
    main()
