"""
Trava de tráfego: relatório diário só sai se houve veiculação paga na janela.

Motivo: entre lançamentos a captação fica pausada. Sem esta trava, os 4 crons
da manhã seguem postando tabelas de zeros no Slack todo dia, o que treina o
time a ignorar o relatório. Com ela, o silêncio passa a significar "não houve
tráfego" em vez de "ninguém olhou".

Regra em uma linha: **tráfego medido e abaixo do piso → não posta. Qualquer
outra coisa → posta.**

O "qualquer outra coisa" é deliberado. A trava é fail-safe por design: se a
medição falhar (API da Meta fora, bloco ausente no payload, exceção), o
veredito é `medido=False` e o relatório VAI. O modo de falha barato é receber
um relatório de zeros; o caro é o relatório desaparecer no dia em que o
tráfego voltou e ninguém notar por uma semana.

Cada relatório mede o que ele mesmo mostra, na janela que ele mesmo usa:

- Digest (daily-check): gasto e leads da Meta (`traffic_metrics.dia_anterior`)
  somados aos do Google (`google_funnel`). São as mesmas duas chamadas de API
  que alimentam o bloco de funil, então gate e relatório nunca discordam.
- Relatório de criativo (utm-quality): leads de origem PAGA na janela, contados
  nos registros que o próprio endpoint já carregou. Sem chamada extra. Orgânico
  não conta como tráfego: não tem custo, não tem criativo, não orienta gestor.
- Relatório semanal de performance de modelo: gasto em `analytics.ad_spend` na
  semana. Janela longa não precisa de API viva — a tabela já é o materializado
  daquelas mesmas APIs e, com uma semana de folga, está completa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional

# Piso de gasto (R$) na janela. Acima disto = houve veiculação. Não é zero puro
# porque conta de anúncio devolve centavo residual de campanha encerrando.
MIN_SPEND_BRL = 1.0

# Piso de leads pagos na janela. Zero = qualquer lead pago já conta como tráfego.
MIN_LEADS = 0

# Quantos dias olhar ATRÁS da janela para saber se `analytics.ad_spend` está viva.
# Serve só para separar "não houve veiculação" de "a ingestão quebrou".
LOOKBACK_SANITY_DAYS = 60

# Origens pagas. Mesmo conjunto usado no split de canal do digest
# (`daily_check_aggregations._SRC_META` + allowlist do Google), replicado aqui
# pra este módulo não puxar o mundo pra decidir "isto é pago?".
PAID_SOURCES = frozenset({
    'facebook-ads', 'facebook-ads-sitelink', 'facebook', 'fb', 'ig', 'instagram', 'meta',
    'google-ads', 'google', 'googleads', 'gclid',
})


@dataclass(frozen=True)
class TrafficCheck:
    """Veredito da trava.

    ativo:  True = posta o relatório. É o único campo que o caller precisa ler.
    medido: False = não foi possível medir, então `ativo` veio True por
            segurança, não por evidência de tráfego.
    motivo: frase pronta pro log e pra resposta HTTP do endpoint.
    """
    ativo: bool
    medido: bool
    motivo: str
    spend: Optional[float] = None
    leads: Optional[int] = None
    fontes: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            'trafego_ativo': self.ativo,
            'medido': self.medido,
            'motivo': self.motivo,
            'spend': self.spend,
            'leads': self.leads,
            'fontes': self.fontes,
        }


def _num(x) -> Optional[float]:
    """Converte pra float ou devolve None. None aqui quer dizer "não medido",
    e é diferente de 0.0, que quer dizer "medido e não houve"."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def _soma_medida(valores: Iterable[Optional[float]]) -> Optional[float]:
    """Soma ignorando None. Devolve None só se NADA foi medido — assim uma
    plataforma fora do ar não zera a outra nem finge que o total é zero."""
    vistos = [v for v in valores if v is not None]
    return sum(vistos) if vistos else None


def avaliar_trafego(
    *,
    spend: Optional[float],
    leads: Optional[float],
    min_spend: float = MIN_SPEND_BRL,
    min_leads: int = MIN_LEADS,
    fontes: Optional[Dict[str, Any]] = None,
) -> TrafficCheck:
    """Regra CANÔNICA da trava: fonte única do projeto.

    Pura de propósito — sem I/O, sem env, sem payload. Os extratores abaixo
    convertem cada relatório nestes dois números e chamam aqui.
    """
    fontes = fontes or {}
    if spend is None and leads is None:
        return TrafficCheck(
            ativo=True, medido=False,
            motivo='tráfego não medido (sem dado de gasto nem de leads) — posta por segurança',
            fontes=fontes,
        )
    n_leads = int(leads) if leads is not None else None
    if (spend is not None and spend > min_spend) or (n_leads is not None and n_leads > min_leads):
        return TrafficCheck(
            ativo=True, medido=True,
            motivo=f'tráfego ativo: gasto R$ {spend or 0:,.2f} · {n_leads or 0} leads pagos',
            spend=spend, leads=n_leads, fontes=fontes,
        )
    return TrafficCheck(
        ativo=False, medido=True,
        motivo=f'sem tráfego na janela: gasto R$ {spend or 0:,.2f} · {n_leads or 0} leads pagos',
        spend=spend, leads=n_leads, fontes=fontes,
    )


def check_from_daily_check(payload: Dict[str, Any], **kwargs) -> TrafficCheck:
    """Trava do digest, lida do payload já computado.

    Usa `dia_anterior` da Meta (não `ultimas_24h`) porque é a janela que o bloco
    de funil renderiza. Google vem de `google_funnel`, que já é "ontem".
    """
    tr = payload.get('traffic_metrics') or {}
    meta = tr.get('dia_anterior') or {}
    ggl = ((payload.get('operational_routines') or {}).get('google_funnel')) or {}

    meta_spend, meta_leads = _num(meta.get('spend')), _num(meta.get('meta_leads'))
    ggl_spend, ggl_leads = _num(ggl.get('total_spend')), _num(ggl.get('n_leads'))

    return avaliar_trafego(
        spend=_soma_medida([meta_spend, ggl_spend]),
        leads=_soma_medida([meta_leads, ggl_leads]),
        fontes={
            'meta': {'spend': meta_spend, 'leads': meta_leads},
            'google': {'spend': ggl_spend, 'leads': ggl_leads},
        },
        **kwargs,
    )


def contar_leads_pagos(records: Iterable[Any]) -> int:
    """Leads de origem paga numa lista de `LeadRecord`. Orgânico e sem source
    ficam fora: relatório de criativo é sobre anúncio."""
    n = 0
    for r in records or []:
        src = (getattr(r, 'utm_source', None) or '').strip().lower()
        if src in PAID_SOURCES:
            n += 1
    return n


def check_from_utm_result(result: Any, **kwargs) -> TrafficCheck:
    """Trava do relatório de criativo.

    Só leads: gasto por campanha vive em `analytics.ad_spend`, que é ingerido
    depois do horário do cron da manhã, então no momento do disparo a tabela
    ainda não tem a janela. Contar lead pago não depende de ingestão nenhuma.
    """
    win = getattr(result, 'window', None) or {}
    pagos = win.get('n_pago')
    return avaliar_trafego(
        spend=None,
        leads=_num(pagos),
        fontes={'ledger': {'leads_pagos': pagos, 'leads_total': win.get('n_total')}},
        **kwargs,
    )


def check_from_ad_spend(start, end, *, conn=None, client_id: str = 'devclub',
                        lookback_days: int = LOOKBACK_SANITY_DAYS, **kwargs) -> TrafficCheck:
    """Trava de janela longa (relatório semanal), lida de `analytics.ad_spend`.

    Janela `[start, end)`, fim exclusivo, igual ao reader. Aqui não vale chamar a
    API viva: a tabela já é o materializado das mesmas APIs e, com uma semana de
    folga, está completa.

    O detalhe que importa é a **desambiguação da tabela vazia**. Zero linha na
    semana pode ser "não houve veiculação" ou "a ingestão quebrou", e os dois
    pedem decisões opostas. Desempata olhando `lookback_days` para trás: se a
    tabela tem linha recente, a ingestão está viva e a semana vazia é fato
    (bloqueia); se não tem nada nem no lookback, a tabela é que é suspeita
    (posta, fail-safe).
    """
    from datetime import timedelta

    fontes: Dict[str, Any] = {'ad_spend': {'start': str(start), 'end': str(end)}}
    try:
        import pandas as pd
        from src.data.ad_spend_reader import read_ad_spend
        df = read_ad_spend(start - timedelta(days=lookback_days), end,
                           conn=conn, client_id=client_id)
    except Exception as exc:  # noqa: BLE001 — tabela ilegível não pode calar o relatório
        fontes['ad_spend']['erro'] = f'{type(exc).__name__}: {exc}'
        return TrafficCheck(
            ativo=True, medido=False,
            motivo='ad_spend ilegível — posta por segurança',
            fontes=fontes,
        )

    if df.empty:
        fontes['ad_spend']['linhas_no_lookback'] = 0
        return TrafficCheck(
            ativo=True, medido=False,
            motivo=f'ad_spend sem nenhuma linha nos {lookback_days}d anteriores '
                   '(ingestão suspeita) — posta por segurança',
            fontes=fontes,
        )

    dias = pd.to_datetime(df['spend_date']).dt.date
    na_janela = df[(dias >= start) & (dias < end)]
    fontes['ad_spend'].update({
        'linhas_na_janela': int(len(na_janela)),
        'linhas_no_lookback': int(len(df)),
        'ultimo_dia_com_gasto': str(max(dias)),
    })
    return avaliar_trafego(
        spend=float(na_janela['spend'].sum()),
        leads=float(pd.to_numeric(na_janela['leads'], errors='coerce').fillna(0).sum()),
        fontes=fontes,
        **kwargs,
    )


def trava_habilitada(env: Optional[Dict[str, str]] = None) -> bool:
    """Kill-switch por ambiente. `REPORTS_REQUIRE_TRAFFIC=0` volta o
    comportamento antigo (posta sempre) sem precisar de deploy de código."""
    import os
    src = env if env is not None else os.environ
    return str(src.get('REPORTS_REQUIRE_TRAFFIC', '1')).strip().lower() not in (
        '0', 'false', 'no', 'off',
    )
