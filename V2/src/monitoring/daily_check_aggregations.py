"""Agregações puras pro daily-check, em cima de `list[LeadRecord]`.

Substitui as queries SQL inline que antes contavam direto na tabela `Lead`
antiga (morta desde 2026-05-17). Funções aqui são puras: recebem record
list, devolvem dicts no formato esperado pelo digest. Sem efeitos colaterais,
sem acesso a banco.

Quem chama: `daily_monitoring_check_railway` em `api/app.py`. Quem alimenta:
o mesmo `_repo.leads_in_range(start, end)` que já é usado pra `scored_rows`.

Decisões de modelagem:
  - `meta_eligible` (denominador de FBP/FBC) = leads que passaram pelo CAPI
    = `status_envio != 'skipped_allowlist'`. Allowlist marca o lead como
    não-Meta — então não conta como "população Meta".
    NOTA (2026-05-27, desacoplamento scoring × Meta CAPI): após a flag
    SCORE_ALL_LEADS=true, `skipped_allowlist` significa "scoreado mas NÃO
    enviado ao Meta" (utm_source não-Meta, ex.: Google). A semântica do
    filtro continua correta — não-Meta segue sendo não-Meta — mas o lead
    agora tem `score`/`decil` preenchidos.
  - `capi_sent` = `status_envio in {'success', 'error'}`. Tentou enviar
    (sucesso ou erro), espelhando a definição da query antiga
    (`capiSentAt IS NOT NULL AND capiStatus NOT IN ('blocked', 'skipped')`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from ..data.lead_record import LeadRecord


_STATUS_TENTOU_CAPI = ('success', 'error')

_SRC_META = frozenset({'facebook-ads', 'fb', 'ig'})
_SRC_GGL  = frozenset({'google-ads'})


def _classify_source(utm_source: str | None) -> str:
    """Bucket de origem pra split fb/ggl/outr no unified_funnel.

    fb  = facebook-ads / fb / ig
    ggl = google-ads
    outr = qualquer outra coisa (orgânico, tiktok, sem utm, etc.)
    """
    s = (utm_source or '').strip().lower()
    if s in _SRC_META: return 'fb'
    if s in _SRC_GGL:  return 'ggl'
    return 'outr'


def compute_unified_funnel(
    records: List[LeadRecord],
    *,
    date_brt_label: str,
) -> Dict[str, Any]:
    """Funil completo (todas as fontes) com split fb/ggl/outr em cada estágio.

    Substitui o bloco SQL inline de 13+ queries em app.py que lia da Lead
    morta (`createdAt`, `leadScore`, `capiSentAt`, `capiStatus`). Agora opera
    sobre `list[LeadRecord]` vindo do `_repo.leads_in_range(ontem, hoje)`.

    Estágios:
      - capture.leads_capi = leads "Meta-elegíveis" (status_envio != 'skipped_allowlist').
        Equivale ao count antigo `FROM leads_capi WHERE created_at IN [s,e]` —
        a tabela `leads_capi` parou de receber em 17/05, então o ledger novo
        é a fonte. Definição: "passou pelo CAPI" = não foi pulado por allowlist.
      - pipeline.pesquisa     = total de leads no range.
      - pipeline.scoreado     = score IS NOT NULL.
      - pipeline.capi_enviado = status_envio in {'success','error'} (tentou).
      - pipeline.aceito       = status_envio == 'success'.

    phone_pct = % de leads no range que têm phone preenchido (proxy de
    qualidade da captação — mesma definição que existia antes).

    Args:
        records: leads do dia anterior BRT (00:00→23:59).
        date_brt_label: ex '24/05' — vai pro window.date_brt.

    Returns:
        dict no mesmo schema do `unified_funnel` antigo.
    """
    stages = {'pesquisa':     {'total': 0, 'fb': 0, 'ggl': 0, 'outr': 0},
              'scoreado':     {'total': 0, 'fb': 0, 'ggl': 0, 'outr': 0},
              'capi_enviado': {'total': 0, 'fb': 0, 'ggl': 0, 'outr': 0},
              'aceito':       {'total': 0, 'fb': 0, 'ggl': 0, 'outr': 0}}
    leads_capi = 0
    phone_ok = 0
    total = len(records)

    for r in records:
        b = _classify_source(r.utm_source)
        stages['pesquisa']['total'] += 1
        stages['pesquisa'][b] += 1
        if r.score is not None:
            stages['scoreado']['total'] += 1
            stages['scoreado'][b] += 1
        if r.status_envio in _STATUS_TENTOU_CAPI:
            stages['capi_enviado']['total'] += 1
            stages['capi_enviado'][b] += 1
        if r.status_envio == 'success':
            stages['aceito']['total'] += 1
            stages['aceito'][b] += 1
        if r.status_envio != 'skipped_allowlist':
            leads_capi += 1
        if r.phone:
            phone_ok += 1

    phone_pct = round(phone_ok / total * 100, 1) if total else 0.0

    return {
        'window':   {'date_brt': date_brt_label, 'label': 'dia anterior'},
        'capture':  {'leads_capi': leads_capi},
        'pipeline': stages,
        'phone_pct': phone_pct,
    }


_VARIANT_BUCKETS = ('Lead', 'Champion', 'Challenger')


def compute_variant_cpl_conv(
    *,
    meta_rows: List[Dict[str, Any]],
    client_campaigns: List,
    classify_fn,
) -> Dict[str, Dict[str, Any]]:
    """CPL real e conversão de LP por variante (Lead/Champion/Challenger).

    Pura: sem I/O. O caller (`api/app.py`) faz os dois pulls e passa pronto.

    Split por NOME da campanha via `classify_fn` (= `validation.campaign_classifier
    .classify_variant`, o critério do arquivo de validação do LF). `classify_fn`
    devolve 'Lead'|'Champion'|'Challenger'|'EXTERNO'; tudo que não é um dos 3
    buckets (EXTERNO = Google/orgânico/não-captação) fica de fora dos dois lados.

    Denominador de custo / conversão (lado Meta):
      - `meta_rows`: list de dict por campanha Meta CAP — chaves `campaign_name`,
        `spend` (BRL), `lpv` (landing_page_views).

    Numerador de leads (lado Client = TODOS os leads captados, não respostas de
    pesquisa):
      - `client_campaigns`: list de `utm_campaign` (string), 1 por lead já
        deduplicado no caller.

    Returns:
        {bucket: {leads, spend, lpv, cpl, conv_lp}} pros 3 buckets. `cpl` =
        spend/leads (None se leads=0). `conv_lp` = leads/lpv*100 (None se lpv=0).
    """
    agg = {b: {'leads': 0, 'spend': 0.0, 'lpv': 0} for b in _VARIANT_BUCKETS}

    # Lado Meta: spend + landing_page_views por bucket.
    for r in meta_rows:
        bucket = classify_fn(r.get('campaign_name'))
        if bucket in agg:
            agg[bucket]['spend'] += float(r.get('spend') or 0)
            agg[bucket]['lpv'] += int(r.get('lpv') or 0)

    # Lado Client: leads reais por bucket.
    for camp in client_campaigns:
        bucket = classify_fn(camp)
        if bucket in agg:
            agg[bucket]['leads'] += 1

    out: Dict[str, Dict[str, Any]] = {}
    for b in _VARIANT_BUCKETS:
        leads = agg[b]['leads']
        spend = agg[b]['spend']
        lpv = agg[b]['lpv']
        out[b] = {
            'leads': leads,
            'spend': round(spend, 2),
            'lpv': lpv,
            'cpl': round(spend / leads, 2) if leads > 0 else None,
            'conv_lp': round(leads / lpv * 100, 1) if lpv > 0 else None,
        }
    return out


def compute_stats_window(records: List[LeadRecord]) -> Dict[str, int]:
    """Agregação total/scored/capi_sent/success/error/with_phone numa janela.

    Equivalente à query antiga:
        SELECT COUNT(*) FILTER (...) ... FROM "Lead" WHERE createdAt IN [start, end]

    Args:
        records: leads da janela (já filtrados por start/end pelo repo).

    Returns:
        dict com chaves: total, scored, capi_sent, capi_success, capi_error, with_phone.
    """
    total = len(records)
    scored = sum(1 for r in records if r.score is not None)
    capi_sent = sum(1 for r in records if r.status_envio in _STATUS_TENTOU_CAPI)
    capi_success = sum(1 for r in records if r.status_envio == 'success')
    capi_error = sum(1 for r in records if r.status_envio == 'error')
    with_phone = sum(1 for r in records if r.phone)
    return {
        'total':         total,
        'scored':        scored,
        'capi_sent':     capi_sent,
        'capi_success':  capi_success,
        'capi_error':    capi_error,
        'with_phone':    with_phone,
    }


def compute_fbp_fbc_meta_population(records: List[LeadRecord]) -> Dict[str, int]:
    """Contagem de FBP/FBC sobre a população Meta-elegível (denominador justo).

    Equivalente à query antiga que selecionava de `leads_capi`:
        SELECT COUNT(*) FILTER (WHERE fbp IS NOT NULL) AS with_fbp, ... FROM leads_capi

    No ledger novo, "leads_capi" vira "leads que passaram pelo CAPI" =
    `status_envio != 'skipped_allowlist'`.

    Returns:
        dict com chaves: with_fbp, with_fbc, total_meta_leads.
    """
    meta_eligible = [r for r in records if r.status_envio != 'skipped_allowlist']
    with_fbp = sum(1 for r in meta_eligible if r.fbp)
    with_fbc = sum(1 for r in meta_eligible if r.fbc)
    return {
        'with_fbp':         with_fbp,
        'with_fbc':         with_fbc,
        'total_meta_leads': len(meta_eligible),
    }


def _fb_pct(num: int, den: int) -> float:
    return round(num / den * 100, 1) if den else 0.0


def compute_survey_funnel_db(
    records: List[LeadRecord],
    *,
    windows: Dict[str, datetime],
    anchor: datetime,
) -> Dict[str, Dict[str, Any]]:
    """Agregação `_sfm_db` (survey_funnel_metrics DB side) em cima de records.

    Substitui as 4 queries SQL antigas (uma por janela na Lead morta) por
    filtragem in-memory sobre `list[LeadRecord]`. Cada janela tem:
      - `db_leads`: total de leads no intervalo (cut → anchor)
      - `capi_sent`: leads que tentaram CAPI (status_envio in success/error)
      - `capi_rate`: db_leads / capi_sent (em %)

    Args:
        records: leads do range coberto (ex: últimos 90d via repo).
        windows: dict {label: cut_datetime}. Cada label vira chave do retorno.
        anchor: limite superior (= window_end).
    """
    # Normaliza tz pra evitar offset-naive vs offset-aware na comparação.
    anchor_naive = anchor.replace(tzinfo=None) if anchor.tzinfo else anchor
    out: Dict[str, Dict[str, Any]] = {}
    for label, cut in windows.items():
        cut_naive = cut.replace(tzinfo=None) if cut.tzinfo else cut
        bucket = [
            r for r in records
            if r.criado_em
            and cut_naive <= r.criado_em.replace(tzinfo=None) <= anchor_naive
        ]
        db_leads = len(bucket)
        capi_sent = sum(1 for r in bucket if r.status_envio in _STATUS_TENTOU_CAPI)
        out[label] = {
            'db_leads':  db_leads,
            'capi_sent': capi_sent,
            'capi_rate': round(capi_sent / db_leads * 100, 1) if db_leads > 0 else 0,
        }
    return out


def records_to_quality_rows(records: List[LeadRecord]) -> list:
    """Converte `list[LeadRecord]` em `list[tuple]` com mesmo schema da
    antiga query `quality_rows` na Lead morta:
        (leadScore, decil, createdAt, source, medium, campaign, content, term, pageUrl)

    Permite que o código downstream do daily-check (séries temporais, decil
    distribution, expected_conversion) continue funcionando intacto enquanto
    a fonte mudou. Removível em Fatia E quando esses consumidores também
    forem migrados pra operar direto em LeadRecord.
    """
    return [
        (
            float(r.score) if r.score is not None else None,
            r.decil,
            r.criado_em,
            r.utm_source,
            r.utm_medium,
            r.utm_campaign,
            r.utm_content,
            r.utm_term,
            r.utm_url,
        )
        for r in records
    ]


def compute_fbp_fbc_rolling(
    records_7d: List[LeadRecord],
    *,
    anchor: datetime,
) -> Dict[str, Dict[str, float]]:
    """FBP/FBC % em janelas rolling 1d/3d/7d, ancoradas em `anchor`.

    Equivalente à query antiga que filtrava `leads_capi` por created_at >=
    anchor - Nd. Cada janela tem `n` (total Meta-elegível), `fbp_pct` e
    `fbc_pct`.

    Args:
        records_7d: leads dos últimos 7d ancorados em `anchor` (já filtrados
                    por start/end pelo repo).
        anchor: timestamp final da janela (geralmente `window_end` do report).

    Returns:
        dict com chaves '1d', '3d', '7d', cada uma com sub-dict
        {n, fbp_pct, fbc_pct}.
    """
    from datetime import timedelta
    # `r.criado_em` vem do pg8000 como datetime offset-naive (UTC implícito);
    # `anchor` pode ser aware. Normaliza removendo tz da anchor pra que a
    # comparação `>=` funcione sem `offset-naive vs offset-aware`.
    anchor_naive = anchor.replace(tzinfo=None) if anchor.tzinfo else anchor
    d1 = anchor_naive - timedelta(days=1)
    d3 = anchor_naive - timedelta(days=3)
    d7 = anchor_naive - timedelta(days=7)
    # Considera "Meta-eligible" = passou pelo CAPI (não skipped_allowlist).
    meta_7d = [r for r in records_7d if r.status_envio != 'skipped_allowlist']

    def _bucket(lim: datetime) -> Dict[str, float]:
        bucket = [
            r for r in meta_7d
            if r.criado_em and r.criado_em.replace(tzinfo=None) >= lim
        ]
        n = len(bucket)
        return {
            'n':       n,
            'fbp_pct': _fb_pct(sum(1 for r in bucket if r.fbp), n),
            'fbc_pct': _fb_pct(sum(1 for r in bucket if r.fbc), n),
        }

    return {'1d': _bucket(d1), '3d': _bucket(d3), '7d': _bucket(d7)}
