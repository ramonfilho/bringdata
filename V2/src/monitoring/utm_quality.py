"""
Qualidade de UTM (source, medium, content) por modelo Champion vs Challenger.

Para cada UTM em cada nível, agrega leads scoreados em duas janelas:
- Últimas N horas (default 24h)
- LF ativo (cap_start → hoje BRT); fallback no LF mais recente encerrado.

Métricas por (UTM × modelo × janela):
- n  (volume)
- avg_decil
- pct_d8_d10

Ranking unificado por avg_decil combinado (ponderado por n) na janela 24h;
filtragem por `min_volume` na janela 24h. Split por modelo visível em cada
linha (mesma fonte de verdade da atribuição em produção — reusa
`ABTestConfig.match_variant`).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))


# ──────────────────────────────────────────────────────────────────────────
# Connection + query
# ──────────────────────────────────────────────────────────────────────────

def _railway_conn():
    import pg8000.native
    return pg8000.native.Connection(
        host=os.environ['RAILWAY_DB_HOST'],
        port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
        user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
        password=os.environ['RAILWAY_DB_PASSWORD'],
        database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
        timeout=30,
    )


_SCORED_WITH_UTMS_SQL = '''
SELECT
  l."leadScore"::float                                            AS score,
  l.decil::int                                                    AS decil,
  LOWER(COALESCE(NULLIF(TRIM(lc.utm_source),  ''), 'sem_utm'))    AS source,
  LOWER(COALESCE(NULLIF(TRIM(lc.utm_medium),  ''), 'sem_utm'))    AS medium,
  LOWER(COALESCE(NULLIF(TRIM(lc.utm_content), ''), 'sem_utm'))    AS content,
  COALESCE(lc.utm_campaign, '')                                   AS campaign,
  COALESCE(l."pageUrl", '')                                       AS page_url
FROM "Lead" l
LEFT JOIN leads_capi lc ON LOWER(l.email) = LOWER(lc.email)
WHERE l."createdAt" >= :start_utc AND l."createdAt" < :end_utc
  AND l."leadScore" IS NOT NULL
  AND l.decil IS NOT NULL
'''


def _fetch_scored(start_utc: datetime, end_utc: datetime, conn) -> list:
    return conn.run(_SCORED_WITH_UTMS_SQL, start_utc=start_utc, end_utc=end_utc)


# ──────────────────────────────────────────────────────────────────────────
# Variant attribution (reusa ABTestConfig.match_variant)
# ──────────────────────────────────────────────────────────────────────────

def _classify_variant(ab_cfg, source, medium, content, campaign, page_url,
                      champion_name, challenger_name) -> str:
    """Sem match → champion (default fallback, mesmo critério de produção)."""
    utms = {
        'utm_source':   source if source != 'sem_utm' else '',
        'utm_medium':   medium if medium != 'sem_utm' else '',
        'utm_campaign': campaign,
        'utm_content':  content if content != 'sem_utm' else '',
        'utm_term':     '',
    }
    matched = ab_cfg.match_variant(utms, event_source_url=page_url)
    if matched is None:
        return champion_name
    name = next((n for n, v in ab_cfg.variants.items() if v is matched), None)
    return name or champion_name


# ──────────────────────────────────────────────────────────────────────────
# Aggregation
# ──────────────────────────────────────────────────────────────────────────

_LEVEL_IDX = {'source': 2, 'medium': 3, 'content': 4}  # índice na row


def _aggregate(rows, level_col: str, ab_cfg,
               champion_name: str, challenger_name: str) -> Dict[str, Dict[str, dict]]:
    idx = _LEVEL_IDX[level_col]
    buckets: Dict[str, Dict[str, dict]] = {}
    for row in rows:
        score, decil, source, medium, content, campaign, page_url = row
        key = row[idx]
        variant = _classify_variant(
            ab_cfg, source, medium, content, campaign, page_url,
            champion_name, challenger_name,
        )
        b = buckets.setdefault(key, {})
        v = b.setdefault(variant, {'n': 0, 'sum_decil': 0, 'n_d8d10': 0})
        v['n'] += 1
        v['sum_decil'] += decil
        if decil >= 8:
            v['n_d8d10'] += 1

    out: Dict[str, Dict[str, dict]] = {}
    for utm_val, variants in buckets.items():
        out[utm_val] = {}
        for var_name, v in variants.items():
            out[utm_val][var_name] = {
                'n': v['n'],
                'avg_decil':  v['sum_decil'] / v['n'] if v['n'] else None,
                'pct_d8_d10': (v['n_d8d10'] / v['n'] * 100) if v['n'] else None,
            }
    return out


def _combined_avg_decil(ch: dict, cl: dict) -> Optional[float]:
    n_ch = (ch or {}).get('n', 0) or 0
    n_cl = (cl or {}).get('n', 0) or 0
    n_total = n_ch + n_cl
    if n_total == 0:
        return None
    sum_ch = ((ch or {}).get('avg_decil') or 0) * n_ch
    sum_cl = ((cl or {}).get('avg_decil') or 0) * n_cl
    return (sum_ch + sum_cl) / n_total


# ──────────────────────────────────────────────────────────────────────────
# LF window resolution
# ──────────────────────────────────────────────────────────────────────────

def _resolve_lf_window() -> Tuple[Optional[str], Optional[datetime], Optional[datetime], bool]:
    """
    Retorna (lf_label, start_utc, end_utc, is_active).

    - LF ativo (cap_start ≤ hoje ≤ cap_end): janela = [cap_start 00:00 BRT, min(cap_end 23:59 BRT, now)].
    - Senão: fallback no LF mais recente encerrado (ce < hoje BRT).
    - Sem nenhum: (None, None, None, False).
    """
    from src.core.launches import resolve_active_launch_brt, load_launches

    now_utc = datetime.now(timezone.utc)
    active = resolve_active_launch_brt()
    if active is not None:
        start = datetime(active.cap_start.year, active.cap_start.month, active.cap_start.day,
                         0, 0, 0, tzinfo=BRT).astimezone(timezone.utc)
        end_brt = datetime(active.cap_end.year, active.cap_end.month, active.cap_end.day,
                           23, 59, 59, tzinfo=BRT)
        end = min(end_brt.astimezone(timezone.utc), now_utc)
        return (active.name, start, end, True)

    launches = load_launches()
    today_brt = datetime.now(BRT).date()
    candidates = []
    for name, cfg in launches.items():
        try:
            cs = datetime.strptime(cfg.get('cap_start', ''), '%Y-%m-%d').date()
            ce = datetime.strptime(cfg.get('cap_end', ''), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        if ce < today_brt:
            candidates.append((ce, name, cs, ce))
    if not candidates:
        return (None, None, None, False)
    candidates.sort(reverse=True)
    _, name, cs, ce = candidates[0]
    start = datetime(cs.year, cs.month, cs.day, 0, 0, 0,
                     tzinfo=BRT).astimezone(timezone.utc)
    end = datetime(ce.year, ce.month, ce.day, 23, 59, 59,
                   tzinfo=BRT).astimezone(timezone.utc)
    return (name, start, end, False)


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class UtmQualityResult:
    window_24h: dict
    window_lf: dict
    champion_name: str
    challenger_name: str
    by_level: dict   # {'source'|'medium'|'content': {worst, best, totals}}
    min_volume: int = 20  # N mínimo de leads em 24h pra um UTM aparecer


def compute_utm_quality(
    client_id: str = 'devclub',
    hours: int = 24,
    top_n: int = 5,
    min_volume: int = 20,
) -> UtmQualityResult:
    """
    Args:
        client_id: id do cliente (carrega `configs/active_models/{id}.yaml`).
        hours: janela em horas para a coluna "agora" (default 24).
        top_n: tamanho do Top piores e Top melhores por nível.
        min_volume: N mínimo de leads (24h) para entrar no ranking.
    """
    from src.core.client_config import ABTestConfig

    yaml_path = f'configs/active_models/{client_id}.yaml'
    ab_cfg = ABTestConfig.from_active_model_yaml(yaml_path)
    if not ab_cfg.enabled:
        raise RuntimeError(f'A/B test not enabled in {yaml_path}')

    variant_names = list(ab_cfg.variants.keys())
    champion_name = next(
        (n for n in variant_names if 'champion' in n.lower()),
        variant_names[0] if variant_names else 'champion',
    )
    challenger_name = next(
        (n for n in variant_names if 'challenger' in n.lower()),
        variant_names[1] if len(variant_names) > 1 else 'challenger',
    )

    now_utc = datetime.now(timezone.utc)
    start_24h = now_utc - timedelta(hours=hours)
    lf_label, lf_start, lf_end, lf_is_active = _resolve_lf_window()

    conn = _railway_conn()
    try:
        rows_24h = _fetch_scored(start_24h, now_utc, conn)
        rows_lf = _fetch_scored(lf_start, lf_end, conn) if lf_start else []
    finally:
        conn.close()

    by_level: Dict[str, dict] = {}
    for level in ('source', 'medium', 'content'):
        agg_24h = _aggregate(rows_24h, level, ab_cfg, champion_name, challenger_name)
        agg_lf  = _aggregate(rows_lf,  level, ab_cfg, champion_name, challenger_name)

        all_utms = set(agg_24h.keys()) | set(agg_lf.keys())
        entries: List[dict] = []
        for utm in all_utms:
            ch_24h = agg_24h.get(utm, {}).get(champion_name)
            cl_24h = agg_24h.get(utm, {}).get(challenger_name)
            ch_lf  = agg_lf.get(utm, {}).get(champion_name)
            cl_lf  = agg_lf.get(utm, {}).get(challenger_name)

            n_24h = ((ch_24h or {}).get('n') or 0) + ((cl_24h or {}).get('n') or 0)
            n_lf  = ((ch_lf  or {}).get('n') or 0) + ((cl_lf  or {}).get('n') or 0)
            avg_24h_combined = _combined_avg_decil(ch_24h or {}, cl_24h or {})

            entries.append({
                'utm': utm,
                'n_24h': n_24h,
                'n_lf': n_lf,
                'avg_decil_24h_combined': avg_24h_combined,
                'champion_24h': ch_24h,
                'challenger_24h': cl_24h,
                'champion_lf': ch_lf,
                'challenger_lf': cl_lf,
            })

        qualifying = [e for e in entries
                      if e['n_24h'] >= min_volume
                      and e['avg_decil_24h_combined'] is not None]
        qualifying.sort(key=lambda e: e['avg_decil_24h_combined'])  # pior → melhor

        # Split só faz sentido quando há UTMs suficientes pra "piores" e
        # "melhores" serem conjuntos disjuntos. Com poucas (≤ 2×top_n) o
        # split sobrepõe — então expõe uma lista única ranqueada.
        n_qual = len(qualifying)
        if n_qual <= 2 * top_n:
            split_mode = 'single'
            ranked = qualifying            # pior → melhor, sem corte
            worst, best = [], []
        else:
            split_mode = 'extremes'
            ranked = qualifying
            worst = qualifying[:top_n]
            best = list(reversed(qualifying[-top_n:]))

        by_level[level] = {
            'split_mode': split_mode,
            'ranked': ranked,
            'worst': worst,
            'best':  best,
            'total_distinct_utms': len(entries),
            'qualifying_min_volume': n_qual,
        }

    return UtmQualityResult(
        window_24h={
            'start': start_24h.isoformat(),
            'end': now_utc.isoformat(),
            'hours': hours,
            'n_total': len(rows_24h),
        },
        window_lf={
            'label': lf_label,
            'start': lf_start.isoformat() if lf_start else None,
            'end':   lf_end.isoformat()   if lf_end   else None,
            'is_active': lf_is_active,
            'n_total': len(rows_lf),
        },
        champion_name=champion_name,
        challenger_name=challenger_name,
        by_level=by_level,
        min_volume=min_volume,
    )


# ──────────────────────────────────────────────────────────────────────────
# Slack renderer — só Content, mini-tabela alinhada
# ──────────────────────────────────────────────────────────────────────────

def _combine(ch: Optional[dict], cl: Optional[dict], key: str) -> Optional[float]:
    """Média ponderada por n de `key` entre Champion e Challenger."""
    ch = ch or {}
    cl = cl or {}
    n_ch = ch.get('n', 0) or 0
    n_cl = cl.get('n', 0) or 0
    n = n_ch + n_cl
    if n == 0:
        return None
    return ((ch.get(key) or 0) * n_ch + (cl.get(key) or 0) * n_cl) / n


def _challenger_note(entry: dict) -> Optional[str]:
    """Linha de Challenger só quando tem ≥10 leads em 24h (em Content ~nunca)."""
    cl = entry.get('challenger_24h') or {}
    if (cl.get('n') or 0) < 10:
        return None
    d = cl.get('avg_decil')
    p = cl.get('pct_d8_d10')
    d_s = f"{d:.1f}" if d is not None else "–"
    p_s = f"{p:.0f}%" if p is not None else "–"
    return f"_Challenger: decil {d_s} · {p_s} no topo · {cl.get('n')} leads_"


def _mini_table_block(entry: dict, lf_label: str, marker: str) -> dict:
    """Section mrkdwn: nome + mini-tabela monoespaçada (24h vs LF)."""
    d24 = _combine(entry.get('champion_24h'), entry.get('challenger_24h'), 'avg_decil')
    p24 = _combine(entry.get('champion_24h'), entry.get('challenger_24h'), 'pct_d8_d10')
    dlf = _combine(entry.get('champion_lf'), entry.get('challenger_lf'), 'avg_decil')
    plf = _combine(entry.get('champion_lf'), entry.get('challenger_lf'), 'pct_d8_d10')

    def fd(v): return f"{v:.1f}" if v is not None else "–"
    def fp(v): return f"{v:.0f}%" if v is not None else "–"

    table = (
        "```\n"
        "         decil   topo    leads\n"
        f"24h      {fd(d24):<7} {fp(p24):<7} {entry['n_24h']}\n"
        f"{lf_label:<8} {fd(dlf):<7} {fp(plf):<7} {entry['n_lf']}\n"
        "```"
    )
    text = f"{marker} *{entry['utm']}*\n{table}"
    note = _challenger_note(entry)
    if note:
        text += f"\n{note}"
    return {'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}


def render_slack_blocks(r: UtmQualityResult) -> List[dict]:
    """
    Só Content. Mini-tabela alinhada (24h vs LF) por creative.

    - split_mode='single': lista única ranqueada pior → melhor (poucas UTMs)
    - split_mode='extremes': 🔴 Piores + 🟢 Melhores (muitas UTMs, disjuntas)
    """
    blocks: List[dict] = []

    lf_label = r.window_lf.get('label') or 'LF'
    lf_state = 'em captação' if r.window_lf.get('is_active') else 'encerrado'
    hours = r.window_24h.get('hours', 24)
    n24 = r.window_24h.get('n_total', 0)
    nlf = r.window_lf.get('n_total', 0)

    data = r.by_level.get('content', {})
    qual = data.get('qualifying_min_volume', 0)
    total = data.get('total_distinct_utms', 0)
    split_mode = data.get('split_mode', 'single')
    min_vol = r.min_volume

    blocks.append({
        'type': 'header',
        'text': {'type': 'plain_text',
                 'text': f'Qualidade de Content — últimas {hours}h × {lf_label}'},
    })
    blocks.append({
        'type': 'context',
        'elements': [{
            'type': 'mrkdwn',
            'text': (
                f"*{n24}* leads scoreados nas {hours}h · "
                f"*{nlf}* no {lf_label} ({lf_state}) · "
                f"*{qual}* de {total} creatives com *N ≥ {min_vol}* leads nas {hours}h"
            ),
        }],
    })
    blocks.append({
        'type': 'context',
        'elements': [{
            'type': 'mrkdwn',
            'text': (
                f"Classificação pelo *decil médio das últimas {hours}h*. "
                f"{lf_label} é só referência (tendência) — não entra no ranking. "
                f"_decil = média 1–10 · topo = % em D8–D10 · N mín = {min_vol} leads/{hours}h_"
            ),
        }],
    })
    blocks.append({'type': 'divider'})

    if qual == 0:
        blocks.append({
            'type': 'context',
            'elements': [{'type': 'mrkdwn',
                          'text': '_nenhum creative com volume mínimo na janela 24h._'}],
        })
        return blocks

    if split_mode == 'single':
        ranked = data.get('ranked') or []
        blocks.append({
            'type': 'section',
            'text': {'type': 'mrkdwn', 'text': '*Ranking — pior → melhor*'},
        })
        for i, e in enumerate(ranked):
            marker = '🔴' if i == 0 else ('🟢' if i == len(ranked) - 1 else '⚪')
            blocks.append(_mini_table_block(e, lf_label, marker))
    else:
        worst = data.get('worst') or []
        best = data.get('best') or []
        blocks.append({
            'type': 'section',
            'text': {'type': 'mrkdwn', 'text': '🔴 *Piores*'},
        })
        for e in worst:
            blocks.append(_mini_table_block(e, lf_label, '🔴'))
        blocks.append({'type': 'divider'})
        blocks.append({
            'type': 'section',
            'text': {'type': 'mrkdwn', 'text': '🟢 *Melhores*'},
        })
        for e in best:
            blocks.append(_mini_table_block(e, lf_label, '🟢'))

    return blocks


# ──────────────────────────────────────────────────────────────────────────
# Slack dispatch
# ──────────────────────────────────────────────────────────────────────────

def post_to_slack(channel: str, blocks: List[dict], fallback_text: str) -> dict:
    """Posta via chat.postMessage. Retorna {ok, channel, ts?, error?}."""
    token = os.environ.get('SLACK_BOT_TOKEN')
    if not token:
        return {'ok': False, 'channel': channel, 'error': 'SLACK_BOT_TOKEN missing'}
    import urllib.request
    body = json.dumps({
        'channel': channel,
        'blocks': blocks,
        'text': fallback_text,
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://slack.com/api/chat.postMessage',
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
