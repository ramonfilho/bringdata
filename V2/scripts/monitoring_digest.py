"""
Renderer puro do payload /monitoring/daily-check/railway. NÃO interpreta,
não consulta Railway, não simula pipeline. Só formata o JSON do endpoint
em tabelas legíveis no terminal.

Toda lógica de drift, breakdown, hoje parcial etc. vive no endpoint.
Se um campo não está no payload, não aparece aqui.

Uso:
    python -m scripts.monitoring_digest
    python -m scripts.monitoring_digest --hours 24
    python -m scripts.monitoring_digest --save
    python -m scripts.monitoring_digest --cache  # usa /tmp/payload.json se existir
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PROD_URL = 'https://smart-ads-api-gazrm25mda-uc.a.run.app'


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--hours', type=int, default=72)
    p.add_argument('--save', action='store_true')
    p.add_argument('--cache', action='store_true', help='Usar /tmp/payload.json se existir')
    p.add_argument('--url', default=PROD_URL)
    p.add_argument('--full', action='store_true', help='Inclui critical_summary (texto cru, redundante com tabelas)')
    return p.parse_args()


def fetch_payload(base_url: str, hours: int, use_cache: bool) -> dict:
    cache_path = Path('/tmp/payload.json')
    if use_cache and cache_path.exists():
        return json.loads(cache_path.read_text())
    url = f'{base_url}/monitoring/daily-check/railway?hours={hours}'
    print(f'⏳ GET {url} (~30s)…', file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as r:
        raw = r.read().decode('utf-8')
    cache_path.write_text(raw)
    return json.loads(raw)


# ──────────────────────────────────────────────────────────────────────────
# Helpers de formatação
# ──────────────────────────────────────────────────────────────────────────

def fmt_pp(d: float | None) -> str:
    if d is None:
        return '   —'
    return f'{d:+.1f}'


def fmt_pct(p: float | None) -> str:
    if p is None:
        return '    —'
    return f'{p:>5.1f}%'


# ──────────────────────────────────────────────────────────────────────────
# Renderers — cada bloco lê só o payload, sem interpretar
# ──────────────────────────────────────────────────────────────────────────

def render_header(p: dict, lines: list):
    op = p.get('operational_routines', {}) or {}
    sev = p.get('alerts_by_severity', {}) or {}
    ts = p.get('timestamp', '?')
    rev = op.get('cloud_run_revision', '?')
    last_score = op.get('minutes_since_last_score', '?')
    lines.append('═' * 78)
    lines.append(f'  DAILY CHECK — DevClub')
    lines.append(f'  timestamp: {ts}')
    lines.append(f'  rev: {rev} · scoring há {last_score} min')
    lines.append(f'  STATUS: {sev.get("HIGH",0)} HIGH · {sev.get("MEDIUM",0)} MEDIUM · {sev.get("LOW",0)} LOW · total {p.get("total_alerts",0)}')
    lines.append('═' * 78)
    lines.append('')


def render_audience_profile_drift(a: dict, lines: list):
    d = a.get('details', {}) or {}
    lines.append(f'🔴  AUDIENCE_PROFILE_DRIFT  ({a["severity"]})')

    launch_n = d.get('launch_n_responses', 0)
    launch_w = d.get('launch_window')
    if launch_w:
        if launch_n > 0:
            lines.append(f'    Janela lanç.: {launch_w} (n={launch_n})')
        else:
            lines.append(f'    Janela lanç.: {launch_w} (sem dados)')

    lines.append(f'    Janela ontem: {d.get("compared_window","?")} (n={d.get("day_n_responses",0)})')
    today_n = d.get('today_n_responses', 0)
    today_w = d.get('today_window', '?')
    if today_n > 0:
        lines.append(f'    Janela hoje:  {today_w} (n={today_n})')
    else:
        lines.append(f'    Janela hoje:  {today_w} (sem dados ainda)')
    lines.append(f'    Referência:   {d.get("reference_pool_label","?")} (n={d.get("reference_pool_n",0):,})')
    lines.append(f'    Threshold:    ≥{d.get("top_threshold_pp","?")}pp')
    lines.append('')

    top = d.get('top_list', []) or []
    if not top:
        lines.append('    (top_list vazia)')
        lines.append('')
        return

    has_launch = any(it.get('launch_pct') is not None for it in top)
    has_today = any(it.get('today_pct') is not None for it in top)

    label_w = 36
    ref_w = 6
    cell_w = 14

    headers = [f'{"Característica":<{label_w}}', f'{"Top5":>{ref_w}}']
    if has_launch:
        headers.append(f'{"Lanç. (Δ)":>{cell_w}}')
    headers.append(f'{"Ontem (Δ)":>{cell_w}}')
    if has_today:
        headers.append(f'{"Hoje (Δ)":>{cell_w}}')

    sep_width = label_w + ref_w + cell_w * (1 + int(has_launch) + int(has_today)) + 2 * (len(headers) - 1)
    lines.append('    ' + '  '.join(headers))
    lines.append('    ' + '─' * sep_width)

    for it in top:
        label = f"{it['feature_label']}: {it['category']}"[:label_w]
        ref = fmt_pct(it.get('reference_pct'))
        cells = [f'{label:<{label_w}}', f'{ref:>{ref_w}}']
        if has_launch:
            lp = it.get('launch_pct')
            ld = it.get('launch_delta_pp')
            cell = f'{fmt_pct(lp)} ({fmt_pp(ld):>5})' if lp is not None else '       —'
            cells.append(f'{cell:>{cell_w}}')
        day_cell = f'{fmt_pct(it.get("day_pct"))} ({fmt_pp(it.get("delta_pp")):>5})'
        cells.append(f'{day_cell:>{cell_w}}')
        if has_today:
            tp = it.get('today_pct')
            td = it.get('today_delta_pp')
            cell = f'{fmt_pct(tp)} ({fmt_pp(td):>5})' if tp is not None else '       —'
            cells.append(f'{cell:>{cell_w}}')
        lines.append('    ' + '  '.join(cells))
    lines.append('')


def render_audience_quality_signal(a: dict, lines: list):
    """Renderiza o alerta `audience_quality_signal` — re-score do LF atual
    com Challenger vs baseline Top5 ROAS realized."""
    d = a.get('details', {}) or {}
    sev = a.get('severity', '?')
    # LOW é o severity "informativo" (DENTRO/ACIMA do padrão). Emoji muda
    # para 🔵 (DENTRO) ou 🟢 (ACIMA) baseado no campo `sinal` quando severity=LOW.
    if sev == 'HIGH':
        emoji = '🔴'
    elif sev == 'MEDIUM':
        emoji = '🟡'
    else:
        sinal_str = (a.get('details', {}) or {}).get('sinal', '')
        emoji = '🟢' if 'ACIMA' in sinal_str else '🔵'
    lf = d.get('lf_name', '?')
    sinal = d.get('sinal', '?')
    n_launch = d.get('n_leads_launch', 0)
    baseline_label = d.get('baseline_pool_label', '?')
    baseline_n = d.get('baseline_n_leads', 0)
    model = d.get('model', {})
    cur = d.get('current', {}) or {}
    bl  = d.get('baseline', {}) or {}
    dlt = d.get('delta', {}) or {}

    lines.append(f'{emoji}  AUDIENCE_QUALITY_SIGNAL  ({sev}) · {lf} — {sinal}')
    lines.append(f'    Modelo:       {model.get("label", "?")} (run_id={model.get("run_id","?")[:8]}…)')
    lines.append(f'    Lançamento:   {lf} cap {d.get("cap_start","?")}→{d.get("cap_end","?")} '
                 f'(n={n_launch:,})')
    lines.append(f'    Baseline:     {baseline_label} (n={baseline_n:,})')
    lines.append('')

    # Tabela de comparação
    rows = [
        ('score médio', cur.get('score_mean'), bl.get('score_mean'),
         dlt.get('score_pct'), 'pct'),
        ('%D10',        cur.get('pct_d10'),    bl.get('pct_d10'),
         dlt.get('pct_d10_pp'), 'pp'),
        ('%D9-D10',     cur.get('pct_d9_d10'), bl.get('pct_d9_d10'),
         dlt.get('pct_d9_d10_pp'), 'pp'),
        ('%D8-D10',     cur.get('pct_d8_d10'), bl.get('pct_d8_d10'),
         dlt.get('pct_d8_d10_pp'), 'pp'),
    ]
    label_w = 14
    col_w = 10
    lines.append('    ' + f'{"Métrica":<{label_w}}' + f'{"Atual":>{col_w}}'
                 + f'{"Baseline":>{col_w}}' + f'{"Δ":>{col_w}}')
    lines.append('    ' + '─' * (label_w + col_w * 3))
    for label, cur_v, bl_v, dlt_v, dlt_kind in rows:
        if cur_v is None or bl_v is None:
            continue
        if label == 'score médio':
            cur_s = f'{cur_v:.4f}'
            bl_s  = f'{bl_v:.4f}'
            dlt_s = f'{dlt_v*100:+.1f}%' if dlt_v is not None else ''
        else:
            cur_s = f'{cur_v*100:.1f}%'
            bl_s  = f'{bl_v*100:.1f}%'
            dlt_s = f'{dlt_v*100:+.1f}pp' if dlt_v is not None else ''
        lines.append('    ' + f'{label:<{label_w}}' + f'{cur_s:>{col_w}}'
                     + f'{bl_s:>{col_w}}' + f'{dlt_s:>{col_w}}')
    lines.append('')


def render_distribution_drift(a: dict, lines: list):
    d = a.get('details', {}) or {}
    sev = a.get('severity', '?')
    emoji = '🔴' if sev == 'HIGH' else '🟡' if sev == 'MEDIUM' else '⚪'
    variant = d.get('variant_name')
    variant_tag = f' · {variant}' if variant else ''
    lines.append(f'{emoji}  DISTRIBUTION_DRIFT  ({sev}) · {d.get("column","?")}{variant_tag}')

    changes = d.get('changes', []) or []
    for c in changes:
        treino = c.get('treino', 0) * 100
        prod = c.get('producao', 0) * 100
        diff_pp = (prod - treino)
        cat = c.get('categoria', '?')
        lines.append(f"    {cat:<55} {treino:>6.1f}% → {prod:>6.1f}%  ({diff_pp:+.1f}pp)")
        bd = c.get('outros_breakdown') or []
        if bd:
            total = sum(item.get('count', 0) for item in bd)
            lines.append(f"      └ outros breakdown (raw → unify, últimas 24h, n={total}):")
            for item in bd[:8]:
                v = item.get('raw_value', '?')
                n = item.get('count', 0)
                pct = (n / total * 100) if total else 0
                v_disp = v if len(v) <= 50 else v[:47] + '...'
                lines.append(f"        {v_disp:<52} {n:>5}  ({pct:>4.1f}%)")
    lines.append('')


def render_category_drift(a: dict, lines: list):
    d = a.get('details', {}) or {}
    variant = d.get('variant_name')
    variant_tag = f' · {variant}' if variant else ''
    new_cats = ', '.join(d.get('new_categories', []) or [])
    lines.append(
        f"⚪  CATEGORY_DRIFT  ({a.get('severity','?')}) · {d.get('column','?')}{variant_tag}"
    )
    lines.append(
        f"    novas: {new_cats}  ·  "
        f"{d.get('affected_count',0)} leads  ({d.get('percentage',0):.1f}%)"
    )
    lines.append('')


def render_extra_features(a: dict, lines: list):
    d = a.get('details', {}) or {}
    feats = ', '.join(d.get('extra_features', []) or [])
    variants = ', '.join(d.get('variants_checked', []) or [])
    lines.append(f"⚪  EXTRA_UNEXPECTED_FEATURES  ({a.get('severity','?')})")
    lines.append(f"    {feats}  (ignoradas pelas variants: {variants})")
    lines.append('')


def render_audience_config_missing(a: dict, lines: list):
    d = a.get('details', {}) or {}
    lines.append(f"🟡  AUDIENCE_PROFILE_DRIFT_CONFIG_MISSING  ({a.get('severity','?')})")
    lines.append(f"    client_id: {d.get('client_id','?')}")
    lines.append(f"    reason:    {d.get('reason','?')}")
    lines.append('')


def render_other_alert(a: dict, lines: list):
    sev = a.get('severity', '?')
    emoji = '🔴' if sev == 'HIGH' else '🟡' if sev == 'MEDIUM' else '⚪'
    lines.append(f"{emoji}  {a.get('type','?').upper()}  ({sev})")
    lines.append(f"    {a.get('message','?')[:200]}")
    lines.append('')


def render_alerts(p: dict, lines: list):
    alerts = p.get('alerts', []) or []
    if not alerts:
        lines.append('✅  Sem alertas.')
        lines.append('')
        return

    # Ordenar por severity HIGH → MEDIUM → LOW
    sev_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    alerts_sorted = sorted(alerts, key=lambda a: sev_order.get(a.get('severity', 'LOW'), 9))

    for i, a in enumerate(alerts_sorted):
        if i > 0:
            lines.append('· · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · ·')
            lines.append('')
        t = a.get('type', '')
        if t == 'audience_profile_drift':
            render_audience_profile_drift(a, lines)
        elif t == 'audience_profile_drift_config_missing':
            render_audience_config_missing(a, lines)
        elif t == 'audience_quality_signal':
            render_audience_quality_signal(a, lines)
        elif t == 'distribution_drift':
            render_distribution_drift(a, lines)
        elif t == 'category_drift':
            render_category_drift(a, lines)
        elif t == 'extra_unexpected_features':
            render_extra_features(a, lines)
        else:
            render_other_alert(a, lines)


def render_funnel(p: dict, lines: list):
    fm = p.get('funnel_metrics', {}) or {}
    cap = fm.get('capture', {}) or {}
    dq = fm.get('data_quality', {}) or {}
    sc = fm.get('scoring', {}) or {}
    capi = fm.get('capi_sent', {}) or {}
    meta = fm.get('meta_response', {}) or {}
    win = fm.get('window', {}) or {}

    lines.append('📊  FUNIL')
    lines.append(f'    Janela: {win.get("start_brt","?")} → {win.get("end_brt","?")} BRT')
    lines.append(f'    Capturados:    {cap.get("total_database",0):>7,}')
    lines.append(f'    Scoreados:     {sc.get("total_scored",0):>7,}')
    lines.append(f'    CAPI enviados: {capi.get("leads_sent",0):>7,}  ({capi.get("send_rate",0):.1f}%)  · {capi.get("estimated_events",0)} eventos')
    lines.append(f'    Aceitos Meta:  {meta.get("success_count",0):>7,}  ({meta.get("acceptance_rate",0):.1f}%)')
    lines.append(f'    FBP / FBC:     {dq.get("fbp_percentage",0):.1f}% / {dq.get("fbc_percentage",0):.1f}%')
    lines.append(f'    Phone:         {dq.get("phone_percentage",0):.1f}%')
    lines.append(f'    Score médio:   {sc.get("avg_score",0):.4f}')

    decis = sc.get('decil_distribution', {}) or {}
    if decis:
        total = sc.get('total_scored', 0) or 1
        lines.append('    Decis:')
        for d in ['D01', 'D02', 'D03', 'D04', 'D05', 'D06', 'D07', 'D08', 'D09', 'D10']:
            v = decis.get(d, 0)
            pct = v / total * 100
            lines.append(f'      {d}: {v:>4,}  ({pct:>4.1f}%)')
    lines.append('')


def render_lead_quality(p: dict, lines: list):
    lq = p.get('lead_quality_metrics', {}) or {}
    lines.append('📈  QUALIDADE DOS LEADS (score, D9%, D10%, n leads)')
    lines.append(f'    {"":<10}  {"24h":>10}  {"semana":>10}  {"mês":>10}  {"hist":>10}')
    for metric, label, fmt in [
        ('score', 'score',   '{:>9.4f} '),
        ('d9',    'D9%',     '{:>9.2f}%'),
        ('d10',   'D10%',    '{:>9.2f}%'),
        ('count', 'n leads', '{:>10,}'),
    ]:
        h24 = lq.get('ultimas_24h', {}).get(metric, 0)
        sem = lq.get('ultima_semana', {}).get(metric, 0)
        mes = lq.get('ultimo_mes', {}).get(metric, 0)
        his = lq.get('historico', {}).get(metric, 0)
        lines.append(f'    {label:<10}  {fmt.format(h24)}  {fmt.format(sem)}  {fmt.format(mes)}  {fmt.format(his)}')
    lines.append('')


def render_revenue_forecast(p: dict, lines: list):
    rf = p.get('revenue_forecast', {}) or {}
    if not rf:
        return
    lines.append('💰  REVENUE FORECAST')
    inputs = rf.get('inputs', {}) or {}
    lines.append(f'    Janela:    {inputs.get("launch_window_start_brt","?")}  ·  {inputs.get("total_leads_meta",0):,} leads Meta')
    lines.append(f'    Ticket:    R$ {inputs.get("ticket_contracted",0):,.0f}  ·  método {inputs.get("metodologia","?")}')
    lines.append(f'    {"Cenário":<14} {"Vendas":>8} {"Faturamento":>14} {"Recebido":>14}')
    for label, key in [('Pessimista', 'cenario_pessimista'),
                        ('Base',       'cenario_base'),
                        ('Otimista',   'cenario_otimista')]:
        c = rf.get(key, {}) or {}
        lines.append(
            f'    {label:<14} {c.get("vendas_total",0):>8.1f}  R$ {c.get("faturamento",0):>10,}  R$ {c.get("faturamento_recebido",0):>10,}'
        )

    ec = rf.get('expected_conversion', {}) or {}
    dl = ec.get('distribuicao_leads', {}) or {}
    if dl:
        lines.append('    Distribuição leads (banco):')
        for tier in ['D1_D5', 'D6_D9', 'D10']:
            t = dl.get(tier, {}) or {}
            lines.append(f'      {tier:<6} {t.get("leads",0):>5,} leads ({t.get("pct",0):.1f}%)')
        lines.append(f'      total_db: {dl.get("total_db",0):,} · response_rate: {dl.get("response_rate_pct",0):.1f}%')

    ce = ec.get('compradores_esperados', {}) or {}
    if ce:
        lines.append(f'    Compradores esperados: D1-5={ce.get("D1_D5",0):.1f}, '
                     f'D6-9={ce.get("D6_D9",0):.1f}, D10={ce.get("D10",0):.1f}, '
                     f'total={ce.get("total",0):.1f}')
    lines.append('')


def render_traffic(p: dict, lines: list):
    tm = p.get('traffic_metrics', {}) or {}
    lines.append('📺  TRÁFEGO META')
    lines.append(f'    {"":<10} {"período":>14} {"semana":>14} {"24h":>14} {"mês":>14}')
    for metric, label, fmt in [
        ('spend',     'Spend',    'R$ {:>10,.0f}'),
        ('meta_leads','Leads',    '{:>14,}'),
        ('cpl',       'CPL',      'R$ {:>10,.2f}'),
        ('ctr_lead',  'CTR→lead', '{:>13.1f}%'),
    ]:
        pq = tm.get('periodo_query', {}).get(metric, 0)
        sem = tm.get('ultima_semana', {}).get(metric, 0)
        h24 = tm.get('ultimas_24h', {}).get(metric, 0)
        mes = tm.get('ultimo_mes', {}).get(metric, 0)
        lines.append(f'    {label:<10} {fmt.format(pq):>14} {fmt.format(sem):>14} {fmt.format(h24):>14} {fmt.format(mes):>14}')
    lines.append('')


def render_survey_funnel(p: dict, lines: list):
    sfm = p.get('survey_funnel_metrics', {}) or {}
    if not sfm:
        return
    lines.append('📋  FUNIL SURVEY (db_leads, capi_sent, capi_rate, meta_leads, response_rate)')
    for period_key, period_label in [
        ('periodo_query', 'período'),
        ('ultimas_24h',   '24h'),
        ('ultima_semana', 'semana'),
        ('ultimo_mes',    'mês'),
        ('historico',     'hist'),
    ]:
        m = sfm.get(period_key, {}) or {}
        db = m.get('db_leads', 0) or 0
        cs = m.get('capi_sent', 0) or 0
        cr = m.get('capi_rate', 0) or 0
        ml = m.get('meta_leads')
        rr = m.get('response_rate')
        ml_str = f'{ml:>7,}' if ml is not None else '       —'
        rr_str = f'{rr:>5.1f}%' if rr is not None else '     —'
        lines.append(f'    {period_label:<8}  db={db:>7,}  capi={cs:>7,} ({cr:>4.1f}%)  meta={ml_str}  resp={rr_str}')
    lines.append('')


def render_ab_test(p: dict, lines: list):
    op = p.get('operational_routines', {}) or {}
    by_variant = op.get('leads_scored_by_variant_24h') or {}
    lines.append('🤖  A/B TEST')
    lines.append(f'    Active model run_id: {op.get("active_run_id","?")[:16]}…')
    lines.append(f'    AB enabled: {op.get("ab_test_enabled", False)}')
    for v in op.get('ab_variants', []) or []:
        ativo = '✓ ATIVO' if v.get('routing_active') else 'standby'
        scored = by_variant.get(v.get('name'))
        scored_tag = f'  scored {scored:>4,}/24h' if scored is not None else ''
        lines.append(f"    {v.get('name','?'):<22}  {ativo:<10}{scored_tag}  {v.get('routing_desc','?')}")
        lines.append(f"      run_id: {v.get('run_id','?')[:16]}…")
    lines.append(f'    Leads (24h): recebidos {op.get("leads_received_24h",0)}, '
                 f'scoreados {op.get("leads_scored_24h",0)}, '
                 f'capi_sent {op.get("capi_sent_24h",0)}')
    lines.append(f'    Último scoring: {op.get("last_scored_at","?")} · há {op.get("minutes_since_last_score","?")} min')
    lines.append('')


def render_critical_summary(p: dict, lines: list):
    cs = p.get('critical_summary', '') or ''
    if cs:
        lines.append('📋  CRITICAL_SUMMARY (texto cru do payload)')
        for ln in cs.strip().split('\n'):
            lines.append(f'    {ln}')
        lines.append('')


def main():
    args = parse_args()
    payload = fetch_payload(args.url, args.hours, args.cache)

    lines: list[str] = []
    render_header(payload, lines)
    render_alerts(payload, lines)
    lines.append('─' * 78)
    lines.append('')
    render_funnel(payload, lines)
    render_lead_quality(payload, lines)
    render_survey_funnel(payload, lines)
    render_revenue_forecast(payload, lines)
    render_traffic(payload, lines)
    render_ab_test(payload, lines)
    if args.full:
        render_critical_summary(payload, lines)

    out = '\n'.join(lines)
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
