"""
Envio de mensagem ao Slack - miolo ÚNICO do `chat.postMessage`.

Por que este módulo existe: a chamada ao `chat.postMessage` estava copiada em
três lugares (`utm_quality.post_to_slack`, `critical_alerts._post_dm` e
`scripts/slack_digest.py`), cada uma com assinatura e tratamento de erro
próprios. Ao adicionar o alerta de custo do Cloud Run seria a quarta cópia -
então o corpo foi extraído pra cá e o `utm_quality.post_to_slack` virou um
apelido fino que aponta pra função daqui (nenhum consumidor mudou).

Contrato: sempre devolve dicionário, NUNCA levanta exceção. Quem chama decide o
que fazer com `ok=False` - assim um erro de Slack não derruba o relatório ou o
alerta que estava sendo montado.
"""
from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

_SLACK_POST_URL = 'https://slack.com/api/chat.postMessage'


def post_blocks(channel: str, blocks: List[dict], fallback_text: str,
                token: Optional[str] = None) -> dict:
    """
    Posta uma mensagem em blocos num canal (ou DM) do Slack.

    `token`: quando omitido, lê do ambiente (`SLACK_BOT_TOKEN`). O parâmetro
    existe pra quem roda fora do Cloud Run (scripts locais) poder passar o token
    na mão sem exportar variável de ambiente.

    Retorna: {ok: bool, channel: str, ts?: str, error?: str}.
    """
    token = token or os.environ.get('SLACK_BOT_TOKEN')
    if not token:
        return {'ok': False, 'channel': channel, 'error': 'SLACK_BOT_TOKEN missing'}
    import urllib.request
    body = json.dumps({
        'channel': channel,
        'blocks': blocks,
        'text': fallback_text,
    }).encode('utf-8')
    req = urllib.request.Request(
        _SLACK_POST_URL,
        data=body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Authorization': f'Bearer {token}',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.load(r)
        if not resp.get('ok'):
            return {'ok': False, 'channel': channel, 'error': resp.get('error')}
        return {'ok': True, 'channel': channel, 'ts': resp.get('ts')}
    except Exception as e:
        return {'ok': False, 'channel': channel, 'error': str(e)}
