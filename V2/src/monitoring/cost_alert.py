"""
Alerta de custo do Cloud Run - DM no Slack quando o uso de um dia estoura o teto.

O que ele vigia: o custo BRUTO (uso, antes da camada gratuita) de UM dia de
calendário BRT. Foi a escolha do operador em 09/08/2026, e a razão é que a
camada gratuita zera a cobrança do Cloud Run quase todo dia - vigiar só o valor
cobrado deixaria uma disparada passar em silêncio por dias, até a cota acabar e
a conta aparecer inteira de uma vez. O bruto acende a luz no primeiro dia.

O que ele NÃO é: um substituto do orçamento da conta de faturamento (hoje R$ 150
por mês, com avisos por e-mail em 50%, 90%, 100% e 150%). Aquele cobre a conta
toda e chega por e-mail; este cobre o Cloud Run isolado e chega no DM.

Quando manda mensagem:
  - uso do dia acima do teto  → 🔴 alerta, com o ranking de quem gastou
  - export de faturamento sem nenhuma linha do dia → ⚠️ aviso de "não consegui
    medir" (um export quebrado devolveria zero, e zero passaria por dia calmo)
  - uso dentro do teto → não manda nada (só com `force`, pra validar formatação)

Rodado 1x/dia pelo Cloud Scheduler, logo depois do relatório da manhã.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, List, Optional

from src.monitoring.gcp_cost import BRT, CustoDiario, SERVICO_DEFAULT, ler_custo_diario

logger = logging.getLogger(__name__)

# Teto do uso diário, em reais. Trocar não exige deploy - é variável de ambiente
# no serviço. R$ 10 foi calibrado sobre o histórico: dia típico do Cloud Run fica
# entre R$ 3 e R$ 5 de uso bruto, e o pico da virada de julho/2026 (retreino +
# carga do dash) bateu R$ 12,21.
LIMITE_DEFAULT = float(os.getenv('CLOUD_RUN_COST_ALERT_BRL', '10'))

# Quantos recursos listar no ranking de quem gastou.
TOP_RECURSOS = 5


@dataclass
class AvaliacaoCusto:
    """Veredito da regra sobre um dia de custo."""
    status: str                 # 'acima_do_limite' | 'dentro_do_limite' | 'sem_dados'
    limite: float
    custo: CustoDiario

    @property
    def deve_avisar(self) -> bool:
        return self.status in ('acima_do_limite', 'sem_dados')

    def as_dict(self) -> dict:
        return {'status': self.status, 'limite': round(self.limite, 2),
                'deve_avisar': self.deve_avisar, 'custo': self.custo.as_dict()}


def avaliar(custo: CustoDiario, limite: float = LIMITE_DEFAULT) -> AvaliacaoCusto:
    """Compara o uso bruto do dia com o teto. Sem efeito colateral, sem Slack."""
    if not custo.tem_dados:
        return AvaliacaoCusto('sem_dados', limite, custo)
    status = 'acima_do_limite' if custo.bruto > limite else 'dentro_do_limite'
    return AvaliacaoCusto(status, limite, custo)


# ──────────────────────────────────────────────────────────────────────────
# Mensagem
# ──────────────────────────────────────────────────────────────────────────

def _brl(valor: float) -> str:
    """12.5 → 'R$ 12,50'."""
    return f"R$ {valor:,.2f}".replace(',', '·').replace('.', ',').replace('·', '.')


def _dia_por_extenso(dia: date) -> str:
    return dia.strftime('%d/%m')


def render_blocks(av: AvaliacaoCusto) -> List[dict]:
    """Monta a mensagem do Slack. Fala em português, não em nome de coluna."""
    c = av.custo

    if av.status == 'sem_dados':
        return [
            {'type': 'header', 'text': {'type': 'plain_text',
                                        'text': '⚠️ Não consegui medir o custo do Cloud Run'}},
            {'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
                f"O relatório de faturamento do Google não trouxe *nenhuma linha* do dia "
                f"*{_dia_por_extenso(c.dia)}*.\n"
                f"Isso não quer dizer que o custo foi zero - quer dizer que a exportação "
                f"que alimenta este alerta parou de chegar. Enquanto ela não voltar, "
                f"um estouro de custo passaria despercebido."
            )}},
            {'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': (
                'Onde olhar: faturamento → exportação para BigQuery '
                '(`billing_export`), no projeto `smart-ads-451319`.'
            )}]},
        ]

    estourou = av.status == 'acima_do_limite'
    titulo = ('🔴 Custo do Cloud Run acima do limite' if estourou
              else '🟢 Custo do Cloud Run dentro do limite')
    veredito = (f"passou do teto de {_brl(av.limite)}" if estourou
                else f"abaixo do teto de {_brl(av.limite)}")

    blocks: List[dict] = [
        {'type': 'header', 'text': {'type': 'plain_text', 'text': titulo}},
        {'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
            f"*{_dia_por_extenso(c.dia)}* - o Cloud Run consumiu *{_brl(c.bruto)}* "
            f"em uso, {veredito}.\n"
            f"Do bolso mesmo saiu *{_brl(c.liquido)}*: o resto foi absorvido pela "
            f"camada gratuita, que zera todo mês. É por isso que o alerta vigia o "
            f"uso e não a cobrança - quando a cobrança aparece, já é tarde."
        )}},
    ]

    if c.por_recurso:
        linhas = '\n'.join(
            f"• `{recurso}` - {_brl(valor)}"
            for recurso, valor in c.por_recurso[:TOP_RECURSOS]
        )
        restantes = len(c.por_recurso) - TOP_RECURSOS
        if restantes > 0:
            sobra = sum(v for _, v in c.por_recurso[TOP_RECURSOS:])
            linhas += f"\n• _outros {restantes} - {_brl(sobra)}_"
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn',
                       'text': f"*Quem gastou* (uso do dia)\n{linhas}"}})

    rodape = f"Fonte: faturamento do Google, dia fechado no horário de Brasília."
    if c.export_time:
        rodape += f" Dados atualizados até {c.export_time.astimezone(BRT):%d/%m %H:%M} BRT."
    blocks.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': rodape}]})
    return blocks


# ──────────────────────────────────────────────────────────────────────────
# Execução (usada pelo endpoint)
# ──────────────────────────────────────────────────────────────────────────

def dia_anterior_brt() -> date:
    """Ontem no calendário de Brasília - o último dia completo quando o alerta
    roda de manhã."""
    return (datetime.now(BRT) - timedelta(days=1)).date()


def executar(dia: Optional[date] = None,
             limite: float = LIMITE_DEFAULT,
             servico: str = SERVICO_DEFAULT,
             canal: Optional[str] = None,
             force: bool = False,
             leitor: Callable[..., CustoDiario] = ler_custo_diario,
             poster: Optional[Callable[..., dict]] = None) -> dict:
    """
    Lê o custo, aplica a regra e manda o DM se for o caso.

    `leitor` e `poster` são injetados pra que o teste rode sem BigQuery e sem
    Slack. Em produção ficam nos defaults.

    Devolve um resumo do que aconteceu - é o corpo da resposta do endpoint, e é
    o que aparece no log do Cloud Scheduler.
    """
    if poster is None:
        from src.monitoring.slack_client import post_blocks
        poster = post_blocks

    dia = dia or dia_anterior_brt()
    canal = canal or os.getenv('SLACK_USER_DM') or os.getenv('SLACK_VALIDATION_DM_CHANNEL', '')

    custo = leitor(dia, servico=servico)
    av = avaliar(custo, limite)
    resultado = {'ok': True, 'servico': servico, 'canal': canal,
                 'forcado': bool(force), **av.as_dict()}

    if not av.deve_avisar and not force:
        logger.info(f"[cost_alert] {servico} {dia}: {av.status} - nada a avisar")
        resultado['postado'] = False
        return resultado

    if not canal:
        logger.error('[cost_alert] SLACK_USER_DM não configurado - não enviei')
        resultado.update({'ok': False, 'postado': False, 'erro': 'SLACK_USER_DM ausente'})
        return resultado

    envio = poster(canal, render_blocks(av),
                   f"Custo do Cloud Run em {_dia_por_extenso(dia)}: {_brl(custo.bruto)}")
    resultado['postado'] = bool(envio.get('ok'))
    if not envio.get('ok'):
        resultado.update({'ok': False, 'erro': envio.get('error')})
        logger.error(f"[cost_alert] Slack recusou: {envio.get('error')}")
    else:
        logger.info(f"[cost_alert] DM enviado ({av.status}, {_brl(custo.bruto)})")
    return resultado
