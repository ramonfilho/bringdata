"""Decis por canal na régua ÚNICA do Challenger (abr_28) — miolo reusável.

Extraído do handler `daily-check/railway` (api/app.py) para virar fonte única
de cálculo: o relatório das 06:00 E o endpoint de dashboard do cliente
(`/monitoring/audience-quality`) consomem exatamente as MESMAS funções, sobre
os MESMOS readers (`challenger_decils_in_window`, ledger via
`LEDGER_READ_SOURCE`). Assim os números do dashboard batem com os do Slack por
construção — não por coincidência.

Contrato de saída (payload por janela) idêntico ao que o daily-check já
produzia antes da extração:

    {
      'distribution':        {D01..D10: int},      # Total (todas as fontes)
      'total':               int,
      'window_label':        str,
      'baseline_challenger': {pct, n_leads, label} | None,   # ref Top ROAS única
      'by_source':  {'meta': {distribution,total}, 'google': {distribution,total}},
      'by_optgoal': {'lead'|'champion'|'challenger': {distribution,total}},
    }

`score_geral` é anexado pelo caller (leitura separada de `launch_score_geral`).

Todos os buckets saem de UMA população numa régua só (o `decil_challenger` da
`scores_historicos`); a comparação é sempre contra a ref única do Challenger.
Fail-soft: se a régua não veio, cai na régua de PRODUÇÃO só pra mostrar as
barras, SEM referência (⚪) — NUNCA o modelo antigo jan_30.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Split por fonte (Meta vs Google) — mesmo bucketing do unified_funnel em
# src/monitoring/daily_check_aggregations._classify_source. Outras fontes
# (orgânico, tiktok, sem_utm) ficam implícitas na barra Total.
META_SOURCES_DECIL = frozenset({'facebook-ads', 'fb', 'ig'})
GGL_SOURCES_DECIL = frozenset({'google-ads'})


@dataclass
class DecisContext:
    """Contexto de cálculo dos decis por canal, resolvido uma vez por request
    a partir do pipeline (A/B config + ClientConfig) e do snapshot de baseline.
    Injetado em `build_decis_window_payload` — o miolo não conhece o pipeline."""
    challenger_run_id: Optional[str] = None
    baseline_payload: Optional[Dict[str, Any]] = None   # pct por decil na régua Challenger, ou None
    meta_sources_og: set = field(default_factory=set)   # allowlist CAPI (filtro do by_optgoal)
    ab_bucket_map: Optional[dict] = None                 # tag→balde do YAML; None → classificador usa legado


def resolve_decis_context(pipeline, *, client_id: str = 'devclub',
                          config_root: Optional[Path] = None) -> DecisContext:
    """Resolve o `DecisContext` do request. Reúne o que antes eram locais soltos
    do handler: run_id do Challenger (régua), baseline puro do snapshot, allowlist
    de fontes Meta (filtro do split por optimization_goal) e o mapa tag→balde do
    YAML. Fail-soft campo a campo — nenhum pedaço faltando derruba o resto."""
    # 1. run_id do Challenger (abr_28) — casa os leads na régua única scores_historicos.
    challenger_run_id = None
    try:
        _abc = getattr(pipeline, '_ab_test_config', None) if pipeline else None
        if _abc and getattr(_abc, 'enabled', False):
            _vn = list(_abc.variants.keys())
            _chn = next((n for n in _vn if 'challenger' in n.lower()),
                        _vn[1] if len(_vn) > 1 else None)
            _cv = _abc.variants.get(_chn) if _chn else None
            challenger_run_id = getattr(_cv, 'run_id', None)
    except Exception as e:
        logger.warning(f"⚠️ challenger run_id p/ régua de decis falhou: {e}")

    # 2. Mapa tag→balde (fonte única YAML) + allowlist de fontes Meta.
    ab_bucket_map = None
    try:
        _abc_og = getattr(pipeline, '_ab_test_config', None) if pipeline else None
        ab_bucket_map = _abc_og.campaign_bucket_map() if (_abc_og and _abc_og.enabled) else None
    except Exception as e:
        logger.warning(f"⚠️ ab_bucket_map p/ decis by_optgoal falhou: {e}")
    _allow_capi = []
    try:
        if pipeline and pipeline._client_config and pipeline._client_config.capi:
            _allow_capi = pipeline._client_config.capi.utm_source_allowlist or []
    except Exception as e:
        logger.warning(f"⚠️ allowlist CAPI p/ decis by_optgoal falhou: {e}")
    meta_sources_og = {str(x).lower().strip() for x in _allow_capi}

    # 3. Baseline de decis Top ROAS na régua ÚNICA do Challenger (abr_28). É a
    #    referência de TODOS os buckets. O modelo jan_30 foi REMOVIDO do relatório.
    baseline_payload = None
    _base_label = 'Top 6 ROAS atribuível 60d'
    try:
        root = config_root or Path(__file__).resolve().parents[2]
        _baseline_path = root / 'configs' / 'reference_audience_profiles' / f'{client_id}.json'
        if _baseline_path.exists():
            _bjson = json.loads(_baseline_path.read_text())
            _rp = (_bjson.get('reference_pool') or {})
            _bcl = _rp.get('decil_distribution_challenger') or {}
            _base_label = _rp.get('label', _base_label)
            if _bcl:
                baseline_payload = pure_baseline(
                    {'distribution': _bcl.get('distribution', {}), 'total': _bcl.get('n_leads', 0)},
                    _base_label,
                )
    except Exception as e:
        logger.warning(f"⚠️ baseline decis indisponível: {e}")

    return DecisContext(
        challenger_run_id=challenger_run_id,
        baseline_payload=baseline_payload,
        meta_sources_og=meta_sources_og,
        ab_bucket_map=ab_bucket_map,
    )


def pure_baseline(b: Optional[Dict[str, Any]], label: str) -> Optional[Dict[str, Any]]:
    """Baseline puro (pct por decil) na régua do Challenger — a ÚNICA referência
    do relatório. Deriva pct a partir de distribution/total."""
    if not b:
        return None
    d = b.get('distribution') or {}
    t = b.get('total') or 1
    pct = {f'D{i:02d}': round((d.get(f'D{i:02d}', 0) / t) * 100, 2) for i in range(1, 11)}
    return {'pct': pct, 'n_leads': int(b.get('total') or 0), 'label': label}


def _empty_decil() -> Dict[str, int]:
    return {f'D{i:02d}': 0 for i in range(1, 11)}


def decil_dist(rows) -> Dict[str, int]:
    """Distribuição Total (D01..D10) a partir das quality_rows
    (r[1] = decil). Path de fallback (régua de produção)."""
    dist = _empty_decil()
    for r in rows:
        d = r[1]
        if d is None:
            continue
        key = f'D{int(d):02d}'
        if key in dist:
            dist[key] += 1
    return dist


def decil_dist_by_source(rows) -> Dict[str, Dict]:
    """Split Meta/Google a partir das quality_rows (r[1]=decil, r[3]=source).
    Path de fallback (régua de produção)."""
    dist_meta = _empty_decil()
    dist_ggl = _empty_decil()
    n_meta = n_ggl = 0
    for r in rows:
        d = r[1]
        src = (r[3] or '').strip().lower() if len(r) > 3 else ''
        if d is None:
            continue
        key = f'D{int(d):02d}'
        if src in META_SOURCES_DECIL:
            if key in dist_meta:
                dist_meta[key] += 1
                n_meta += 1
        elif src in GGL_SOURCES_DECIL:
            if key in dist_ggl:
                dist_ggl[key] += 1
                n_ggl += 1
    return {
        'meta': {'distribution': dist_meta, 'total': n_meta},
        'google': {'distribution': dist_ggl, 'total': n_ggl},
    }


def decil_dist_by_variant(records, *, meta_sources_og: set,
                          ab_bucket_map: Optional[dict]) -> Dict[str, Dict]:
    """Split Lead/Champion/Challenger pela TAG de optimization_goal no NOME da
    campanha (utm_campaign), via campaign_classifier.bucket_from_utm — SEM Meta
    API. Só fontes Meta (allowlist CAPI). Path de fallback (régua de produção)."""
    from src.monitoring.campaign_classifier import bucket_from_utm
    buckets = ('Lead', 'Champion', 'Challenger')
    dists = {b: _empty_decil() for b in buckets}
    totals = {b: 0 for b in buckets}
    for rec in records:
        if rec.decil is None:
            continue
        src = (rec.utm_source or '').strip().lower()
        if src not in meta_sources_og:
            continue
        bucket = bucket_from_utm(rec.utm_campaign, ab_bucket_map)
        key = f'D{int(rec.decil):02d}'
        if key in dists[bucket]:
            dists[bucket][key] += 1
            totals[bucket] += 1
    if totals['Lead'] > 0 and (totals['Champion'] + totals['Challenger']) == 0:
        logger.warning(
            "[decis by_variant] %d leads Meta mas 0 com tag LEADQUALIFIED/LEADHQLB "
            "— convenção de nome de campanha mudou? Tudo caiu em Lead.",
            totals['Lead'],
        )
    return {
        'lead': {'distribution': dists['Lead'], 'total': totals['Lead']},
        'champion': {'distribution': dists['Champion'], 'total': totals['Champion']},
        'challenger': {'distribution': dists['Challenger'], 'total': totals['Challenger']},
    }


def challenger_decis_buckets(recs, *, meta_sources_og: set,
                             ab_bucket_map: Optional[dict]) -> Dict[str, Any]:
    """recs: List[ChallengerDecilRec] (régua abr_28) → distribution (Total),
    by_source (meta/google) e by_optgoal (lead/champion/challenger), TODOS na
    MESMA régua e MESMA população. Reusa os MESMOS classificadores das versões
    de produção (META/GGL_SOURCES_DECIL por fonte; bucket_from_utm por optgoal,
    só em fontes Meta) — só a régua (decil_challenger) muda."""
    from src.monitoring.campaign_classifier import bucket_from_utm
    d_tot = _empty_decil(); n_tot = 0
    d_meta = _empty_decil(); n_meta = 0
    d_ggl = _empty_decil(); n_ggl = 0
    og = {b: _empty_decil() for b in ('Lead', 'Champion', 'Challenger')}
    og_n = {b: 0 for b in ('Lead', 'Champion', 'Challenger')}
    for rec in recs:
        dk = rec.decil
        if dk not in d_tot:
            continue
        d_tot[dk] += 1; n_tot += 1
        src = (rec.utm_source or '').strip().lower()
        if src in META_SOURCES_DECIL:
            d_meta[dk] += 1; n_meta += 1
        elif src in GGL_SOURCES_DECIL:
            d_ggl[dk] += 1; n_ggl += 1
        if src in meta_sources_og:
            _b = bucket_from_utm(rec.utm_campaign, ab_bucket_map)
            og[_b][dk] += 1; og_n[_b] += 1
    if og_n['Lead'] > 0 and (og_n['Champion'] + og_n['Challenger']) == 0:
        logger.warning(
            "[decis by_optgoal chal] %d leads Meta mas 0 com tag ML — "
            "convenção de nome de campanha mudou?", og_n['Lead'])
    return {
        'distribution': d_tot, 'total': n_tot,
        'by_source': {
            'meta': {'distribution': d_meta, 'total': n_meta},
            'google': {'distribution': d_ggl, 'total': n_ggl},
        },
        'by_optgoal': {
            'lead': {'distribution': og['Lead'], 'total': og_n['Lead']},
            'champion': {'distribution': og['Champion'], 'total': og_n['Champion']},
            'challenger': {'distribution': og['Challenger'], 'total': og_n['Challenger']},
        },
    }


def records_between(recs, a_utc, b_utc, incl_b: bool) -> List:
    """Fatia records de ledger pela janela [a_utc, b_utc] (por rec.criado_em, UTC).
    `incl_b` inclui/exclui o limite superior. Usado pra montar os fallback_records
    por janela a partir do bloco de 90d já lido pelo repo."""
    out = []
    for rec in recs:
        c = rec.criado_em
        if c is None:
            continue
        if c.tzinfo is None:
            c = c.replace(tzinfo=timezone.utc)
        if c >= a_utc and (c <= b_utc if incl_b else c < b_utc):
            out.append(rec)
    return out


def build_decis_window_payload(*, window_label: str, start_utc, end_utc,
                               pin_lf: bool, lf_name: Optional[str],
                               ctx: DecisContext,
                               fallback_rows, fallback_records) -> Dict[str, Any]:
    """Payload de decis de UMA janela na régua ÚNICA do Challenger (abr_28):
    todos os buckets saem de `challenger_decils_in_window` (uma população, uma
    régua) e comparam contra a ref única (`ctx.baseline_payload`). Fail-soft: se a
    régua não veio (sem run_id / falha dura), cai na régua de PRODUÇÃO só pra
    mostrar as barras, SEM ref (⚪) — NUNCA jan_30.

    `fallback_rows` / `fallback_records` são só pro caminho degradado (quality_rows
    e records de ledger da janela). No caminho normal (régua Challenger) não são
    usados."""
    recs = None
    if ctx.challenger_run_id:
        try:
            from src.data.scores_historicos import challenger_decils_in_window
            recs = challenger_decils_in_window(
                challenger_run_id=ctx.challenger_run_id, win_start=start_utc,
                win_end=end_utc, lf_name=lf_name, pin_lf=pin_lf)
        except Exception as e:
            logger.warning(f"⚠️ régua Challenger p/ decis ({window_label}) falhou: {e}")
            recs = None
    if recs is not None:
        b = challenger_decis_buckets(
            recs, meta_sources_og=ctx.meta_sources_og, ab_bucket_map=ctx.ab_bucket_map)
        _prod = len(fallback_rows)
        if _prod > 0 and b['total'] < _prod * 0.9:
            logger.warning(
                "[decis %s] cobertura Challenger %d/%d (<90%%) — refresh da "
                "scores_historicos incompleto?", window_label, b['total'], _prod)
        return {
            'distribution': b['distribution'],
            'total': b['total'],
            'window_label': window_label,
            'baseline_challenger': ctx.baseline_payload,
            'by_source': b['by_source'],
            'by_optgoal': b['by_optgoal'],
        }
    # Degradado: régua Challenger indisponível → produção SEM ref (nunca jan_30).
    logger.warning(
        "[decis %s] régua Challenger indisponível — barras na régua de produção "
        "SEM referência (jan_30 nunca é usado).", window_label)
    return {
        'distribution': decil_dist(fallback_rows),
        'total': len(fallback_rows),
        'window_label': window_label,
        'baseline_challenger': None,
        'by_source': decil_dist_by_source(fallback_rows),
        'by_optgoal': decil_dist_by_variant(
            fallback_records, meta_sources_og=ctx.meta_sources_og,
            ab_bucket_map=ctx.ab_bucket_map),
    }
