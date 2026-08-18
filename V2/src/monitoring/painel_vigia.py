"""
Vigia do painel da agência - DM no Slack quando o painel trava ou fica cego.

Por que existe: em 18/08/2026 o robô de publicação morreu na virada do dia
(estreia do LF65) e o painel exibiu por 11 horas o "hoje" de ONTEM (373 leads
do LF64 posando de dado do dia). Quem descobriu foi o gestor de tráfego, não
nós. Este vigia inverte isso: o silêncio do painel vira mensagem no DM antes
de virar constrangimento no cliente.

O que ele vigia (nesta ordem):
  1. CORAÇÃO do robô - `analytics.job_heartbeats`, batido ao fim de CADA rodada
     bem-sucedida do push, mesmo quando não há linha a publicar (estreia de
     lançamento fica horas legitimamente quieta). Coração parado >N horas =
     robô morto. Vigiar o conteúdo confundiria silêncio legítimo com travada.
  2. HOMÔNIMOS - dois conjuntos de anúncios com o MESMO nome na MESMA campanha
     (janela de 3 dias do gerenciador). O split por público separa pelo NOME do
     conjunto (é o que a UTM do lead carrega); homônimos deixam o split cego, e
     o aviso pede nome distinto ao tráfego ANTES de virar número fundido.

Quando manda mensagem:
  - painel sem escrita há mais de N horas → 🔴 travado (com o que fazer)
  - painel vazio → 🔴 (nunca deveria acontecer; o acumulado sempre fica)
  - conjuntos homônimos na janela viva → ⚠️ aviso, uma vez por rodada
  - tudo certo → não manda nada (só com `force`, pra validar a formatação)

Rodado de hora em hora pelo Cloud Scheduler, depois da rodada do robô.
O destino é SEMPRE o DM do operador (`SLACK_USER_DM`): é vigia de
infraestrutura nossa, não relatório de cliente.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Horas sem escrita no painel até gritar. O robô roda de hora em hora (cron
# :22), então 2h = duas rodadas perdidas - uma falha isolada de rede não
# acorda ninguém, duas seguidas sim. Trocar não exige deploy (env).
LIMITE_HORAS_DEFAULT = float(os.getenv('PAINEL_VIGIA_HORAS', '2'))

BRT = timezone(timedelta(hours=-3))


@dataclass
class EstadoPainel:
    """Fotografia do painel + achados, sem juízo de Slack."""
    linhas: int
    ultima_atualizacao: Optional[datetime]
    horas_paradas: Optional[float]
    limite_horas: float
    homonimos: List[tuple] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.linhas == 0:
            return 'vazio'
        if self.horas_paradas is not None and self.horas_paradas > self.limite_horas:
            return 'travado'
        return 'fresco'

    @property
    def deve_avisar(self) -> bool:
        return self.status != 'fresco' or bool(self.homonimos)

    def as_dict(self) -> dict:
        return {'status': self.status, 'linhas': self.linhas,
                'ultima_atualizacao': (self.ultima_atualizacao.isoformat()
                                       if self.ultima_atualizacao else None),
                'horas_paradas': (round(self.horas_paradas, 2)
                                  if self.horas_paradas is not None else None),
                'limite_horas': self.limite_horas,
                'homonimos': [list(h) for h in self.homonimos],
                'deve_avisar': self.deve_avisar}


def medir(destino_conn, analytics_conn,
          limite_horas: float = LIMITE_HORAS_DEFAULT,
          agora: Optional[datetime] = None) -> EstadoPainel:
    """Lê o estado do painel e da janela viva. Sem efeito colateral."""
    agora = agora or datetime.now(timezone.utc)
    linhas, _conteudo = destino_conn.run(
        "SELECT count(*), max(atualizado_em) FROM public.scores_inbound")[0]
    # A idade que importa é a do CORAÇÃO do robô (batido a cada rodada ok,
    # mesmo sem linhas), não a do conteúdo: em estreia de lançamento o painel
    # fica horas legitimamente quieto. Antes do primeiro deploy do coração,
    # cai no carimbo do conteúdo (transição, documentada).
    try:
        hb = analytics_conn.run(
            "SELECT ultima_ok FROM job_heartbeats "
            "WHERE job = 'push-scores-zanelato'")
    except Exception:
        hb = None   # tabela ainda não criada (nasce na 1ª rodada pós-deploy)
    ultima = hb[0][0] if hb else _conteudo
    horas = None
    if ultima is not None:
        if ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        horas = (agora - ultima).total_seconds() / 3600.0

    homonimos = [tuple(r) for r in analytics_conn.run(
        "SELECT campaign_id, adset_name, count(DISTINCT adset_id) "
        "FROM ad_insights "
        "WHERE insight_date >= CURRENT_DATE - 3 AND adset_name IS NOT NULL "
        "GROUP BY 1, 2 HAVING count(DISTINCT adset_id) >= 2")]
    return EstadoPainel(int(linhas or 0), ultima, horas, limite_horas, homonimos)


def render_blocks(e: EstadoPainel) -> List[dict]:
    """Mensagem do Slack em português de gente, com o que FAZER."""
    blocks: List[dict] = []
    if e.status == 'vazio':
        blocks += [
            {'type': 'header', 'text': {'type': 'plain_text',
                                        'text': '🔴 Painel da agência VAZIO'}},
            {'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
                'A tabela de tetos que a agência lê está sem NENHUMA linha. '
                'Isso não acontece em operação normal (o acumulado do '
                'lançamento sempre fica). Onde olhar: execuções do job '
                '`push-scores-zanelato` no Cloud Run.'
            )}},
        ]
    elif e.status == 'travado':
        ultima_brt = e.ultima_atualizacao.astimezone(BRT)
        blocks += [
            {'type': 'header', 'text': {'type': 'plain_text',
                                        'text': '🔴 Painel da agência TRAVADO'}},
            {'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
                f"O robô de publicação não completa uma rodada desde "
                f"*{ultima_brt:%d/%m %H:%M}* ({e.horas_paradas:.1f}h atrás; "
                f"o normal é de hora em hora). "
                f"Enquanto isso, o gestor pode estar lendo número velho como "
                f"se fosse de agora - foi exatamente o caso dos 373 leads "
                f"fantasmas de 18/08.\n*Onde olhar:* execuções do job "
                f"`push-scores-zanelato` (Cloud Run) - o erro da última "
                f"execução diz o motivo."
            )}},
        ]
    if e.homonimos:
        linhas = '\n'.join(
            f"• `{str(nome)[:60]}` - {n} conjuntos na campanha `...{str(cid)[-6:]}`"
            for cid, nome, n in e.homonimos[:5])
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
            f"⚠️ *Conjuntos de anúncios com o MESMO nome na MESMA campanha* "
            f"(janela de 3 dias):\n{linhas}\n"
            f"O split por público separa pelo nome do conjunto - homônimos "
            f"deixam o número fundido sem aviso. Pedir ao tráfego nomes "
            f"distintos dentro da mesma campanha."
        )}})
    if not blocks:
        blocks = [
            {'type': 'header', 'text': {'type': 'plain_text',
                                        'text': '🟢 Painel da agência em dia'}},
            {'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
                f"Última escrita "
                f"{e.ultima_atualizacao.astimezone(BRT):%d/%m %H:%M} · "
                f"{e.linhas} linhas · nenhum conjunto homônimo na janela."
            )}},
        ]
    return blocks


def executar(abre_destino: Callable, abre_analytics: Callable,
             limite_horas: float = LIMITE_HORAS_DEFAULT,
             canal: Optional[str] = None,
             force: bool = False,
             poster: Optional[Callable[..., dict]] = None) -> dict:
    """Mede, decide e posta. Conexões e poster INJETADOS (teste roda sem nada).

    `abre_destino`/`abre_analytics` são fábricas de conexão com `.run()` e
    `.close()` - o endpoint compõe com o banco da agência e o analytics reais.
    """
    if poster is None:
        from src.monitoring.slack_client import post_blocks
        poster = post_blocks

    d, a = abre_destino(), abre_analytics()
    try:
        estado = medir(d, a, limite_horas=limite_horas)
    finally:
        for c in (d, a):
            try:
                c.close()
            except Exception:
                pass

    canal = canal or os.getenv('SLACK_USER_DM') or ''
    resultado = {'ok': True, 'canal': canal, 'forcado': bool(force),
                 **estado.as_dict()}

    if not estado.deve_avisar and not force:
        logger.info('[painel_vigia] fresco - nada a avisar')
        resultado['postado'] = False
        return resultado
    if not canal:
        logger.error('[painel_vigia] SLACK_USER_DM ausente - não enviei')
        resultado.update({'ok': False, 'postado': False,
                          'erro': 'SLACK_USER_DM ausente'})
        return resultado

    envio = poster(canal, render_blocks(estado),
                   f"Painel da agência: {estado.status}")
    resultado['postado'] = bool(envio.get('ok'))
    if not envio.get('ok'):
        resultado.update({'ok': False, 'erro': envio.get('error')})
        logger.error(f"[painel_vigia] Slack recusou: {envio.get('error')}")
    return resultado
