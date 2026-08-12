"""
Quantas mensagens estão paradas numa assinatura do Pub/Sub, agora.

Para que serve: o consumidor de leads drena a fila puxando mensagens até ela
responder vazio. O problema é que puxada vazia NÃO prova fila vazia (em
31/07/2026 o dreno se declarou vazio com 253 leads parados), então o código
compensava puxando três vezes seguidas pra ter certeza. Cada puxada vazia
custa 10 segundos de máquina ligada. Aqui a gente pergunta pra própria fila,
em vez de deduzir de puxada.

De onde vem o número: a métrica `num_undelivered_messages` do Cloud Monitoring,
amostrada de minuto em minuto. Medido em 11/08/2026, o ponto mais recente fica
disponível uns 26 segundos depois do minuto fechar.

O ATRASO É A RAZÃO DE ESTE MÓDULO SÓ SABER DIZER "VAZIA" COM SEGURANÇA:
uma leitura zero pode estar 26 segundos desatualizada e não enxergar um lead
que acabou de entrar. Já uma leitura maior que zero pode ser eco de um backlog
que a gente acabou de drenar. Por isso quem consome deve usar o "vazia" só pra
PARAR mais cedo, nunca usar o "tem backlog" pra continuar puxando: no primeiro
caso o pior cenário é um lead esperar o próximo ciclo; no segundo seria ficar
puxando o vazio contra um número velho, que é justamente a conta que a gente
está tentando cortar.

Sem dependência nova: usa o `google-auth` que já está na imagem pra pegar o
token e fala com a API por HTTP puro.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_MONITORING_URL = 'https://monitoring.googleapis.com/v3/projects/{projeto}/timeSeries'
_METRICA = 'pubsub.googleapis.com/subscription/num_undelivered_messages'

# Janela de busca. Precisa cobrir mais de um ponto pra tolerar a amostra do
# minuto corrente ainda não ter fechado.
_JANELA_MINUTOS = 5

# Teto de tempo da consulta. Ela roda no caminho quente do consumidor de leads,
# então é melhor desistir rápido e cair no comportamento antigo do que segurar
# a drenagem esperando resposta do Monitoring.
_TIMEOUT_S = 3.0

_credenciais = None


def _token() -> Optional[str]:
    """Token de acesso da própria conta de serviço do Cloud Run. None se falhar."""
    global _credenciais
    try:
        import google.auth
        from google.auth.transport.requests import Request
        if _credenciais is None:
            _credenciais, _ = google.auth.default(
                scopes=['https://www.googleapis.com/auth/monitoring.read'])
        if not _credenciais.valid:
            _credenciais.refresh(Request())
        return _credenciais.token
    except Exception as e:
        logger.warning(f"[pubsub_backlog] não consegui autenticar: {e}")
        return None


def mensagens_paradas(projeto: str, assinatura: str) -> Optional[int]:
    """
    Quantas mensagens estão sem entregar na assinatura, na amostra mais recente.

    Devolve None quando NÃO foi possível saber (erro de rede, permissão negada,
    métrica sem pontos). None é diferente de zero de propósito: quem consome
    precisa distinguir "a fila está vazia" de "não consegui perguntar".
    """
    token = _token()
    if not token:
        return None

    agora = datetime.now(timezone.utc)
    filtro = (f'metric.type="{_METRICA}" AND '
              f'resource.labels.subscription_id="{assinatura}"')
    query = urllib.parse.urlencode({
        'filter': filtro,
        'interval.startTime': (agora - timedelta(minutes=_JANELA_MINUTOS)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'interval.endTime': agora.strftime('%Y-%m-%dT%H:%M:%SZ'),
    })
    url = f"{_MONITORING_URL.format(projeto=projeto)}?{query}"

    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
            corpo = json.load(r)
    except Exception as e:
        logger.warning(f"[pubsub_backlog] consulta falhou: {e}")
        return None

    series = corpo.get('timeSeries') or []
    if not series:
        logger.warning(f"[pubsub_backlog] métrica sem série para {assinatura}")
        return None
    pontos = series[0].get('points') or []
    if not pontos:
        return None
    try:
        # A API devolve do mais recente pro mais antigo.
        return int(pontos[0]['value']['int64Value'])
    except (KeyError, TypeError, ValueError):
        return None


def fila_comprovadamente_vazia(projeto: str, assinatura: str) -> bool:
    """
    True SÓ quando a fila respondeu e respondeu zero.

    Qualquer outra situação (tem mensagem, erro, permissão, métrica muda) devolve
    False, que para quem consome significa "siga com o comportamento de antes".
    É a forma de garantir que este módulo nunca torne a drenagem mais curta por
    engano nem mais longa por indisponibilidade.
    """
    n = mensagens_paradas(projeto, assinatura)
    return n == 0
