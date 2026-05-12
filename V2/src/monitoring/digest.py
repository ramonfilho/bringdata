"""
Pipeline de digest do payload de /monitoring/daily-check/railway.

Três funções públicas:

  extract_view(payload) -> dict
      Audita o schema do payload e devolve uma view estruturada pronta pra renderizar.
      Falha alto se o endpoint produzir paths não declarados em payload_schema.py.

  render_text(view) -> str
      Renderer pra terminal — usado pelo `python -m scripts.monitoring_digest`.

  render_slack_blocks(view) -> list[dict]
      Renderer pra Slack Block Kit — usado pelo `python -m scripts.slack_digest`.

O schema explícito em payload_schema.py garante que toda mudança no endpoint
seja decisão consciente (RENDERED / SKIPPED com razão).
"""
from __future__ import annotations

from typing import Any, Iterable

from .payload_schema import PAYLOAD_SCHEMA, FieldDecision


# ──────────────────────────────────────────────────────────────────────────
# Audit
# ──────────────────────────────────────────────────────────────────────────

class PayloadSchemaDriftError(RuntimeError):
    """Endpoint produziu paths não declarados em PAYLOAD_SCHEMA."""


def _walk_paths(d: Any, prefix: str = '') -> Iterable[str]:
    """Yield dotted paths pra todos os campos do payload (lists viram `prefix[]`)."""
    if isinstance(d, dict):
        for k, v in d.items():
            new = f'{prefix}.{k}' if prefix else k
            yield new
            yield from _walk_paths(v, new)
    elif isinstance(d, list):
        for item in d:
            yield from _walk_paths(item, f'{prefix}[]')


def audit_payload_schema(payload: dict) -> None:
    """Falha alto se houver paths novos ou SKIPPED sem razão.

    Chamada por extract_view() antes de qualquer renderização — uma única
    barreira de entrada pros dois renderers.
    """
    actual   = set(_walk_paths(payload))
    declared = set(PAYLOAD_SCHEMA.keys())

    unknown = sorted(actual - declared)
    skipped_no_reason = sorted([
        k for k, (d, r) in PAYLOAD_SCHEMA.items()
        if d == FieldDecision.SKIPPED and not r
    ])

    errs: list[str] = []
    if unknown:
        sample = '\n'.join(f'  + {k}' for k in unknown[:20])
        suffix = f'\n  … +{len(unknown)-20} mais' if len(unknown) > 20 else ''
        errs.append(
            f'⚠️  PAYLOAD SCHEMA DRIFT — endpoint produziu {len(unknown)} '
            f'chave(s) não declaradas em src/monitoring/payload_schema.py:\n\n'
            f'{sample}{suffix}\n\n'
            f'Decida em PAYLOAD_SCHEMA: (R, None) pra renderizar OU (S, \'razão\') pra ignorar.'
        )
    if skipped_no_reason:
        sample = '\n'.join(f'  - {k}' for k in skipped_no_reason[:10])
        errs.append(
            f'❌ {len(skipped_no_reason)} entrada(s) SKIPPED sem razão em '
            f'PAYLOAD_SCHEMA:\n\n{sample}\n\n'
            'Toda entrada SKIPPED precisa carregar razão explícita.'
        )

    if errs:
        raise PayloadSchemaDriftError('\n\n'.join(errs))


def get_skipped_summary(payload: dict) -> list[tuple[str, str]]:
    """Lista (path, razão) dos SKIPPED que de fato aparecem no payload atual."""
    actual = set(_walk_paths(payload))
    return [
        (path, reason or '')
        for path, (decision, reason) in PAYLOAD_SCHEMA.items()
        if decision == FieldDecision.SKIPPED and path in actual
    ]


def _is_rendered(path: str) -> bool:
    """Helper pra renderers: deve mostrar este path?"""
    entry = PAYLOAD_SCHEMA.get(path)
    return entry is not None and entry[0] == FieldDecision.RENDERED


# ──────────────────────────────────────────────────────────────────────────
# Extract view — normaliza o payload em estrutura pronta pra renderizar
# ──────────────────────────────────────────────────────────────────────────

def extract_view(payload: dict, *, audit: bool = True) -> dict:
    """Audita o schema e devolve view estruturada do payload.

    `audit=False` só pra testes com payload mockado parcial.
    """
    if audit:
        audit_payload_schema(payload)

    op = payload.get('operational_routines', {}) or {}

    return {
        'meta': {
            'timestamp':                payload.get('timestamp', '?'),
            'revision':                 op.get('cloud_run_revision', '?'),
            'service':                  op.get('cloud_run_service', '?'),
            'active_model_yaml_path':   op.get('active_model_yaml_path', '?'),
            'minutes_since_last_score': op.get('minutes_since_last_score', '?'),
            'last_scored_at':           op.get('last_scored_at', '?'),
        },
        'severity': {
            'total':       payload.get('total_alerts', 0),
            'by_severity': payload.get('alerts_by_severity', {}) or {},
            'by_category': payload.get('alerts_by_category', {}) or {},
        },
        'alerts':            payload.get('alerts', []) or [],
        'actionable_alerts': payload.get('actionable_alerts', []) or [],
        'funnel':            payload.get('funnel_metrics', {}) or {},
        'lead_quality':      payload.get('lead_quality_metrics', {}) or {},
        'survey_funnel':     payload.get('survey_funnel_metrics', {}) or {},
        'revenue_forecast':  payload.get('revenue_forecast', {}) or {},
        'traffic':           payload.get('traffic_metrics', {}) or {},
        'ab_test':           op,
        'critical_summary':  payload.get('critical_summary', ''),
        'skipped':           get_skipped_summary(payload),
    }


# ──────────────────────────────────────────────────────────────────────────
# Helpers compartilhados pelos renderers
# ──────────────────────────────────────────────────────────────────────────

def _fmt_pp(d: float | None) -> str:
    if d is None: return '   —'
    return f'{d:+.1f}'


def _fmt_pct(p: float | None) -> str:
    if p is None: return '    —'
    return f'{p:>5.1f}%'


def _sev_emoji(sev: str) -> str:
    return {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '⚪'}.get(sev, '·')


def _sev_order(a: dict) -> int:
    return {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}.get(a.get('severity'), 9)


def _short(s: Any, n: int = 50) -> str:
    s = str(s)
    return s if len(s) <= n else s[:n-1] + '…'


def _n(d: dict, key: str, default: float = 0) -> float:
    """Pega valor numérico do dict, com fallback pro default se ausente OU None."""
    v = d.get(key, default)
    return v if v is not None else default


# ──────────────────────────────────────────────────────────────────────────
# render_text — terminal / arquivo
# ──────────────────────────────────────────────────────────────────────────

def render_text(view: dict) -> str:
    lines: list[str] = []
    _render_text_header(view, lines)
    _render_text_ab(view, lines)
    lines.append('─' * 78); lines.append('')
    _render_text_alerts(view, lines)
    lines.append('─' * 78); lines.append('')
    _render_text_funnel(view, lines)
    _render_text_lead_quality(view, lines)
    _render_text_survey(view, lines)
    _render_text_revenue(view, lines)
    _render_text_traffic(view, lines)
    _render_text_skipped_footer(view, lines)
    return '\n'.join(lines)


# Mapa amigável de variant_name → label curto
_VARIANT_LABEL = {
    'champion_jan30':   'Champion',
    'challenger_abr28': 'Challenger',
}


def _variant_label(name: str) -> str:
    return _VARIANT_LABEL.get(name, name)


def _render_text_header(v: dict, L: list):
    # Data curta extraída do timestamp pra dar contexto, sem rev/service/etc.
    ts = (v['meta'].get('timestamp') or '')[:10]   # YYYY-MM-DD
    L.append('═' * 78)
    L.append(f'  DAILY CHECK — DevClub  ·  {ts}')
    L.append('═' * 78); L.append('')


def _render_text_alerts(v: dict, L: list):
    alerts = v['alerts']
    if not alerts:
        L.append('✅  Sem alertas.'); L.append(''); return

    distribution_drifts = [a for a in alerts if a.get('type') == 'distribution_drift']
    category_drifts     = [a for a in alerts if a.get('type') == 'category_drift']
    audience_drifts     = [a for a in alerts if a.get('type') == 'audience_profile_drift']
    other_alerts        = [a for a in alerts if a.get('type') not in (
        'distribution_drift', 'category_drift', 'audience_profile_drift',
        'extra_unexpected_features',
    )]

    sep = lambda: (L.append('· · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · ·'), L.append(''))

    # Header da seção
    L.append('🚨  Mudanças significativas')
    L.append('')

    # 1) Distribution drifts agrupados por coluna
    if distribution_drifts:
        _render_text_distribution_drifts_consolidated(distribution_drifts, L)

    # 2) Category drifts consolidados
    if category_drifts:
        _render_text_category_drifts_consolidated(category_drifts, L)

    # 3) Outros (config_missing etc.)
    for a in other_alerts:
        t = a.get('type', '')
        if t == 'audience_profile_drift_config_missing':
            _render_text_audience_config_missing(a, L)
        else:
            _render_text_other_alert(a, L)

    # 4) Audience drift — seção separada
    if audience_drifts:
        L.append('─' * 78)
        L.append('')
        for a in audience_drifts:
            _render_text_audience_drift(a, L)


def _render_text_audience_drift(a: dict, L: list):
    d = a.get('details', {}) or {}
    L.append('🔵  Características dos leads vs TOP 5 lançamentos com melhores ROAS à vista')
    L.append('')

    top = d.get('top_list', []) or []
    if not top:
        L.append('    (sem dados na top_list)'); L.append(''); return

    has_launch = any(it.get('launch_pct') is not None for it in top)
    has_today  = any(it.get('today_pct') is not None for it in top)

    headers = [f'{"Característica":<36}', f'{"Top5":>6}']
    if has_launch: headers.append(f'{"Lanç. (Δ)":>14}')
    headers.append(f'{"Ontem (Δ)":>14}')
    if has_today:  headers.append(f'{"Hoje (Δ)":>14}')
    L.append('    ' + '  '.join(headers))
    L.append('    ' + '─' * (36 + 6 + 14*(1+int(has_launch)+int(has_today)) + 2*(len(headers)-1)))

    for it in top:
        label = _short(f"{it['feature_label']}: {it['category']}", 36)
        ref = _fmt_pct(it.get('reference_pct'))
        cells = [f'{label:<36}', f'{ref:>6}']
        if has_launch:
            lp, ld = it.get('launch_pct'), it.get('launch_delta_pp')
            cell = f'{_fmt_pct(lp)} ({_fmt_pp(ld):>5})' if lp is not None else '       —'
            cells.append(f'{cell:>14}')
        day_cell = f'{_fmt_pct(it.get("day_pct"))} ({_fmt_pp(it.get("delta_pp")):>5})'
        cells.append(f'{day_cell:>14}')
        if has_today:
            tp, td = it.get('today_pct'), it.get('today_delta_pp')
            cell = f'{_fmt_pct(tp)} ({_fmt_pp(td):>5})' if tp is not None else '       —'
            cells.append(f'{cell:>14}')
        L.append('    ' + '  '.join(cells))
    L.append('')


def _render_text_distribution_drifts_consolidated(alerts: list, L: list):
    # Agrupa por coluna (UTM Medium, Term, etc.)
    by_col: dict[str, list] = {}
    for a in alerts:
        col = (a.get('details') or {}).get('column', '?')
        by_col.setdefault(col, []).append(a)

    for col, group in by_col.items():
        L.append(f'Mudança na UTM {col}:')
        for a in group:
            d = a.get('details', {}) or {}
            variant = _variant_label(d.get('variant_name', '?'))
            changes = d.get('changes', []) or []
            L.append(f'  • {variant} ({len(changes)} mudança{"s" if len(changes) != 1 else ""}):')
            for c in changes:
                treino = (c.get('treino') or 0) * 100
                prod   = (c.get('producao') or 0) * 100
                diff   = prod - treino
                cat    = c.get('categoria', '?')
                L.append(f"      {cat:<53} {treino:>6.1f}% → {prod:>6.1f}%  ({diff:+.1f}pp)")
                bd = c.get('outros_breakdown') or []
                if bd:
                    total = sum(item.get('count', 0) for item in bd)
                    L.append(f"        └ outros breakdown (raw → unify, 24h, n={total}):")
                    for item in bd[:8]:
                        vv = item.get('raw_value', '?') or '(vazio)'
                        n = item.get('count', 0)
                        pct = (n/total*100) if total else 0
                        vv_disp = _short(vv, 50)
                        L.append(f"          {vv_disp:<50} {n:>5}  ({pct:>4.1f}%)")
        L.append('')


def _render_text_category_drifts_consolidated(alerts: list, L: list):
    # Agrupa por variant
    by_variant: dict[str, list] = {}
    for a in alerts:
        d = a.get('details', {}) or {}
        var = _variant_label(d.get('variant_name', '?'))
        by_variant.setdefault(var, []).append(d)

    L.append('Mudanças em categorias:')
    for variant, items in by_variant.items():
        L.append(f'  {variant}:')
        for d in items:
            col = d.get('column', '?')
            new_cats = ', '.join(d.get('new_categories', []) or [])
            n = d.get('affected_count', 0); pct = d.get('percentage', 0)
            L.append(f"    {col}: {new_cats}  ·  {n} leads ({pct:.1f}%)")
    L.append('')


def _render_text_audience_config_missing(a: dict, L: list):
    d = a.get('details', {}) or {}
    L.append(f"🟡  AUDIENCE_PROFILE_DRIFT_CONFIG_MISSING  ({a.get('severity','?')})")
    L.append(f"    client_id: {d.get('client_id','?')}")
    L.append(f"    reason:    {d.get('reason','?')}")
    L.append('')


def _render_text_other_alert(a: dict, L: list):
    sev = a.get('severity', '?')
    emoji = _sev_emoji(sev)
    L.append(f"{emoji}  {a.get('type','?').upper()}  ({sev}) · category={a.get('category','?')}")
    L.append(f"    {a.get('message','?')[:200]}")
    extras = []
    if a.get('metric_value') is not None: extras.append(f"value={a['metric_value']}")
    if a.get('threshold')    is not None: extras.append(f"threshold={a['threshold']}")
    if a.get('timestamp'):                extras.append(f"ts={a['timestamp']}")
    if extras: L.append(f"    [{' · '.join(extras)}]")
    L.append('')


def _render_text_funnel(v: dict, L: list):
    fm = v['funnel']
    cap = fm.get('capture', {}) or {}
    dq  = fm.get('data_quality', {}) or {}
    sc  = fm.get('scoring', {}) or {}
    capi= fm.get('capi_sent', {}) or {}
    meta= fm.get('meta_response', {}) or {}
    win = fm.get('window', {}) or {}

    L.append('📊  FUNIL')
    L.append(f'    Janela: {win.get("start_brt","?")} → {win.get("end_brt","?")} BRT')
    L.append(f'    leads db (pesquisa): {_n(cap,"total_database"):>7,}')
    L.append(f'    Scoreados:           {_n(sc,"total_scored"):>7,}')
    L.append(f'    CAPI enviados:       {_n(capi,"leads_sent"):>7,}  ({_n(capi,"send_rate"):.1f}%)  ·  {_n(capi,"estimated_events"):.0f} eventos')
    L.append(f'    Aceitos Meta:        success={_n(meta,"success_count"):>5,}  partial={_n(meta,"partial_count"):>5,}  error={_n(meta,"error_count"):>5,}  ({_n(meta,"acceptance_rate"):.1f}%)')
    L.append(f'    FBP / FBC / Phone:   {_n(dq,"fbp_percentage"):.1f}% / {_n(dq,"fbc_percentage"):.1f}% / {_n(dq,"phone_percentage"):.1f}%')
    L.append(f'      (FBP/FBC % sobre leads Meta · Phone % sobre leads no banco)')

    decis = sc.get('decil_distribution', {}) or {}
    if decis:
        total = sc.get('total_scored', 0) or 1
        L.append(f'    Decis  ·  {win.get("start_brt","?")} → {win.get("end_brt","?")} BRT  ·  {total:,} scoreados:')
        for d in ['D01','D02','D03','D04','D05','D06','D07','D08','D09','D10']:
            vv = decis.get(d, 0)
            pct = vv/total*100
            L.append(f'      {d}: {vv:>4,}  ({pct:>4.1f}%)')
    L.append('')


def _render_text_lead_quality(v: dict, L: list):
    lq = v['lead_quality']
    lf_label = lq.get('lf_referencia_label')
    has_lf = lf_label is not None and lq.get('lf_referencia')
    L.append('📈  QUALIDADE DOS LEADS (score, D9%, D10%, n leads)')

    if has_lf:
        col_lf = f'{lf_label:>10}'
        L.append(f'    {"":<10}  {"24h":>10}  {col_lf}  {"semana":>10}  {"mês":>10}  {"hist":>10}')
    else:
        L.append(f'    {"":<10}  {"24h":>10}  {"semana":>10}  {"mês":>10}  {"hist":>10}')

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
        if has_lf:
            lf  = lq.get('lf_referencia', {}).get(metric, 0)
            L.append(f'    {label:<10}  {fmt.format(h24)}  {fmt.format(lf)}  {fmt.format(sem)}  {fmt.format(mes)}  {fmt.format(his)}')
        else:
            L.append(f'    {label:<10}  {fmt.format(h24)}  {fmt.format(sem)}  {fmt.format(mes)}  {fmt.format(his)}')
    L.append('')


def _render_text_survey(v: dict, L: list):
    sfm = v['survey_funnel']
    if not sfm: return
    L.append('📋  FUNIL SURVEY')
    L.append('    meta = leads que Meta entregou  ·  db = respondeu pesquisa  ·  capi = enviado a Meta  ·  %resp = db÷meta')
    for k, label in [('periodo_query','lanç. atual'), ('ultimas_24h','24h'),
                     ('ultima_semana','semana'), ('ultimo_mes','mês'), ('historico','hist')]:
        m = sfm.get(k, {}) or {}
        db = m.get('db_leads', 0) or 0
        cs = m.get('capi_sent', 0) or 0
        cr = m.get('capi_rate', 0) or 0
        ml = m.get('meta_leads')
        rr = m.get('response_rate')
        ml_str = f'{ml:>7,}' if ml is not None else '       —'
        rr_str = f'{rr:>6.1f}%' if rr is not None else '      —'
        L.append(f'    {label:<11}  meta={ml_str}  db={db:>7,}  capi={cs:>7,} ({cr:>4.1f}%)  %resp={rr_str}')
    L.append('      (%resp acima de 100% suspeito de inflação — investigar; código pendente)')
    L.append('')


def _render_text_revenue(v: dict, L: list):
    rf = v['revenue_forecast']
    if not rf: return
    inputs = rf.get('inputs', {}) or {}
    L.append('💰  PREVISÃO DE FATURAMENTO')
    L.append(f'    Lançamento atual ({inputs.get("launch_window_start_brt","?")}): {_n(inputs,"total_leads_meta"):,} leads Meta  ·  ticket R$ {_n(inputs,"ticket_contracted"):,.0f}')
    L.append('')

    def _row(label, c):
        return (
            f'    {label:<16} {_n(c,"vendas_total"):>7.1f}  '
            f'R$ {_n(c,"faturamento"):>11,.0f}  '
            f'R$ {_n(c,"faturamento_recebido"):>10,.0f}  '
            f'R$ {_n(c,"cartao_avista_liquido"):>14,.0f}  '
            f'R$ {_n(c,"primeira_parcela_boleto"):>14,.0f}  '
            f'{_n(c,"vendas_guru"):>6.1f}  '
            f'{_n(c,"vendas_tmb"):>6.1f}'
        )

    header = f'    {"Cenário":<16} {"Vendas":>7}  {"Faturamento":>14}  {"Recebido":>13}  {"Cartão à vista":>17}  {"1ª parc boleto":>17}  {"Guru":>6}  {"TMB":>6}'

    def _write_two_methods(forecast: dict):
        L.append('  Método 1: taxa de conversão média LF43-LF53 (recalibrado 08/05)')
        L.append(header)
        for label, key in [('Pessimista','cenario_pessimista'),
                           ('Base',      'cenario_base'),
                           ('Otimista',  'cenario_otimista')]:
            L.append(_row(label, forecast.get(key, {}) or {}))
        L.append('')
        L.append('  Método 2: previsão por ML')
        L.append(header)
        for label, key in [('Pessimista','cenario_ml_aware_pessimista'),
                           ('Base',      'cenario_ml_aware'),
                           ('Otimista',  'cenario_ml_aware_otimista')]:
            L.append(_row(label, forecast.get(key, {}) or {}))
        L.append('')

    # Lançamento atual
    _write_two_methods(rf)

    # Lançamento anterior — mesma metodologia aplicada ao volume Meta do LF anterior
    lf_ant = rf.get('lf_anterior') or {}
    if lf_ant:
        lf_inputs = lf_ant.get('inputs', {}) or {}
        lf_name = lf_inputs.get('lf_name', '?')
        L.append(f'  Lançamento anterior ({lf_name} · {lf_inputs.get("launch_window_start_brt","?")}): {_n(lf_inputs,"total_leads_meta"):,} leads Meta')
        L.append('')
        _write_two_methods(lf_ant)

    L.append('    Mais detalhes sobre a metodologia no payload da API.')
    L.append('')


def _render_text_traffic(v: dict, L: list):
    tm = v['traffic']
    L.append('📺  TRÁFEGO META')
    L.append(f'    {"":<11} {"24h":>14} {"lanç. atual":>14} {"semana":>14} {"mês":>14}')
    for metric, label, fmt in [
        ('spend',      'Spend',       'R$ {:>10,.0f}'),
        ('meta_leads', 'Leads',       '{:>14,}'),
        ('cpl',        'CPL',         'R$ {:>10,.2f}'),
        ('ctr_lead',   'Clique→lead', '{:>13.1f}%'),
        ('clicks',     'Clicks',      '{:>14,}'),
    ]:
        h24 = tm.get('ultimas_24h', {}).get(metric, 0) or 0
        pq  = tm.get('periodo_query', {}).get(metric, 0) or 0
        sem = tm.get('ultima_semana', {}).get(metric, 0) or 0
        mes = tm.get('ultimo_mes', {}).get(metric, 0) or 0
        L.append(f'    {label:<11} {fmt.format(h24):>14} {fmt.format(pq):>14} {fmt.format(sem):>14} {fmt.format(mes):>14}')
    L.append('')


def _render_text_ab(v: dict, L: list):
    op = v['ab_test']
    by_variant = op.get('leads_scored_by_variant_24h') or {}
    total_scored_24h = sum((n or 0) for n in by_variant.values())
    L.append('🤖  A/B TEST LIGADO')
    for vv in op.get('ab_variants', []) or []:
        name = vv.get('name', '?')
        label = _variant_label(name)
        scored = by_variant.get(name) or 0
        pct = (scored / total_scored_24h * 100) if total_scored_24h else 0
        L.append(f"    {label} ({name}) recebeu {scored:,} de {total_scored_24h:,} eventos ({pct:.1f}%) nas últimas 24h")
    L.append('')


def _render_text_actionable(v: dict, L: list):
    aa = v['actionable_alerts']
    if not aa: return
    # Filtra audience_profile_drift (redundante com a tabela detalhada)
    aa = [a for a in aa if a.get('type') != 'audience_profile_drift']
    if not aa: return

    L.append('🎯  Mudanças significativas:')
    for a in aa:
        t = a.get('type')
        msg = (a.get('message') or '').strip()
        if t == 'distribution_drift':
            # Tenta extrair variant + N de "[champion_jan30] Medium: 3 mudança(s) ..."
            import re
            m = re.match(r'\s*\[([^\]]+)\]\s*([^:]+):\s*(\d+)\s*mudan', msg)
            if m:
                variant = _variant_label(m.group(1).strip())
                col = m.group(2).strip()
                n = m.group(3)
                L.append(f"    {n} mudanças nas proporções da UTM {col} para o modelo {variant}")
                continue
        # Fallback genérico
        L.append(f"    [{a.get('type','?')}] {_short(msg.replace(chr(10),' '), 140)}")
    L.append('')


def _render_text_skipped_footer(v: dict, L: list):
    # Footer removido a pedido — paths SKIPPED ainda visíveis via `--show-skipped`.
    return


# ──────────────────────────────────────────────────────────────────────────
# render_slack_blocks — Block Kit
# ──────────────────────────────────────────────────────────────────────────

def render_slack_blocks(view: dict) -> list[dict]:
    blocks: list[dict] = []
    _slack_header(view, blocks)
    _slack_ab(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_alerts(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_funnel(view, blocks)
    _slack_decis(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_lead_quality(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_survey(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_revenue(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_traffic(view, blocks)
    _slack_skipped_footer(view, blocks)
    return blocks


def _slack_header(v: dict, B: list):
    ts = (v['meta'].get('timestamp') or '')[:10]
    B.append({'type': 'header', 'text': {'type': 'plain_text', 'text': f'📊 Daily Check — DevClub · {ts}', 'emoji': True}})


def _slack_alerts(v: dict, B: list):
    alerts = v['alerts']
    if not alerts:
        B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '✅ *Sem alertas.*'}})
        return

    distribution_drifts = [a for a in alerts if a.get('type') == 'distribution_drift']
    category_drifts     = [a for a in alerts if a.get('type') == 'category_drift']
    audience_drifts     = [a for a in alerts if a.get('type') == 'audience_profile_drift']
    others              = [a for a in alerts if a.get('type') not in (
        'distribution_drift', 'category_drift', 'audience_profile_drift',
        'extra_unexpected_features',
    )]

    B.append({'type': 'header', 'text': {'type': 'plain_text', 'text': '🚨 Mudanças significativas', 'emoji': True}})

    if distribution_drifts:
        _slack_distribution_drifts_consolidated(distribution_drifts, B)

    if category_drifts:
        _slack_category_drifts_consolidated(category_drifts, B)

    for a in others:
        t = a.get('type', '')
        if t == 'audience_profile_drift_config_missing':
            _slack_alert_config_missing(a, B)
        else:
            _slack_alert_other(a, B)

    if audience_drifts:
        B.append({'type': 'divider'})
        for a in audience_drifts:
            _slack_alert_audience(a, B)


def _slack_distribution_drifts_consolidated(alerts: list, B: list):
    by_col: dict[str, list] = {}
    for a in alerts:
        col = (a.get('details') or {}).get('column', '?')
        by_col.setdefault(col, []).append(a)

    for col, group in by_col.items():
        lines = [f"*Mudança na UTM {col}:*"]
        for a in group:
            d = a.get('details', {}) or {}
            variant = _variant_label(d.get('variant_name', '?'))
            changes = d.get('changes', []) or []
            n = len(changes)
            lines.append(f"  • *{variant}* ({n} mudança{'s' if n != 1 else ''}):")
            for c in changes:
                cat = _short(c.get('categoria', '?'), 38)
                tp = (c.get('treino') or 0) * 100
                pp = (c.get('producao') or 0) * 100
                diff = pp - tp
                lines.append(f"      `{cat:<38}` {tp:>5.1f}% → {pp:>5.1f}% (`{diff:+.1f}pp`)")
                bd = c.get('outros_breakdown') or []
                if bd:
                    total = sum(it.get('count', 0) for it in bd)
                    lines.append(f"         _└ raw → unify (24h, n={total}):_")
                    for it in bd[:6]:
                        raw = _short(it.get('raw_value', '') or '(vazio)', 32)
                        nn = it.get('count', 0)
                        pct = (nn/total*100) if total else 0
                        lines.append(f"         `{raw:<32}` {nn:>4} ({pct:>4.1f}%)")
        B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(lines)}})


def _slack_alert_audience(a: dict, B: list):
    d = a.get('details', {}) or {}
    rows = [
        '*Características dos leads vs TOP 5 lançamentos com melhores ROAS à vista:*',
        f"`{'Característica':<32} {'Top5':>5}  {'Lanç(Δ)':>11}  {'Ontem(Δ)':>11}  {'Hoje(Δ)':>11}`",
    ]
    def cell(pct, delta):
        if pct is None: return f"{'—':>11}"
        return f"{pct:>5.1f}%({delta:+.1f})"
    for it in d.get('top_list', []) or []:
        label = _short(f"{it['feature_label']}: {it['category']}", 32)
        ref = it.get('reference_pct',0)
        rows.append(f"`{label:<32} {ref:>4.1f}%  "
                    f"{cell(it.get('launch_pct'), it.get('launch_delta_pp')):>11}  "
                    f"{cell(it.get('day_pct'), it.get('delta_pp')):>11}  "
                    f"{cell(it.get('today_pct'), it.get('today_delta_pp')):>11}`")
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(rows)}})


def _slack_category_drifts_consolidated(alerts: list, B: list):
    # Agrupa por variant
    by_variant: dict[str, list] = {}
    for a in alerts:
        d = a.get('details', {}) or {}
        var = _variant_label(d.get('variant_name', '?'))
        by_variant.setdefault(var, []).append(d)

    lines = ['*Mudanças em categorias:*']
    for variant, items in by_variant.items():
        lines.append(f"  *{variant}*:")
        for d in items:
            col = d.get('column', '?')
            new = ', '.join(d.get('new_categories', []) or [])
            n = d.get('affected_count', 0); pct = d.get('percentage', 0)
            lines.append(f"    `{col}`: {new}  ·  {n} leads ({pct:.1f}%)")
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(lines)}})


def _slack_alert_config_missing(a: dict, B: list):
    d = a.get('details', {}) or {}
    sev = a.get('severity','?'); e = _sev_emoji(sev)
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': f"{e} *AUDIENCE_PROFILE_DRIFT_CONFIG_MISSING* `{sev}` · client `{d.get('client_id','?')}` · {d.get('reason','?')}"}})


def _slack_alert_other(a: dict, B: list):
    sev = a.get('severity','?'); e = _sev_emoji(sev)
    extras = []
    if a.get('metric_value') is not None: extras.append(f"value=`{a['metric_value']}`")
    if a.get('threshold')    is not None: extras.append(f"threshold=`{a['threshold']}`")
    if a.get('timestamp'):                extras.append(f"ts=`{a['timestamp']}`")
    extra_tag = ' · ' + ' · '.join(extras) if extras else ''
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': f"{e} *{a.get('type','?').upper()}* `{sev}` · category=`{a.get('category','?')}`{extra_tag}\n   {a.get('message','?')[:300]}"}})


def _slack_funnel(v: dict, B: list):
    fm = v['funnel']
    cap = fm.get('capture', {}) or {}
    sc  = fm.get('scoring', {}) or {}
    capi= fm.get('capi_sent', {}) or {}
    meta= fm.get('meta_response', {}) or {}
    dq  = fm.get('data_quality', {}) or {}
    win = fm.get('window', {}) or {}
    conv= fm.get('conversion', {}) or {}

    rows = [
        f"leads db (pesquisa)    {_n(cap,'total_database'):>7,}",
        f"Scoreados              {_n(sc,'total_scored'):>7,}",
        f"CAPI enviados          {_n(capi,'leads_sent'):>7,}   ({_n(capi,'send_rate'):.1f}%)  ·  {_n(capi,'estimated_events'):.0f} eventos",
        f"Aceitos Meta           {_n(meta,'success_count'):>7,}   (success 100%  ·  partial {_n(meta,'partial_count'):.0f}  ·  error {_n(meta,'error_count'):.0f})",
        f"FBP / FBC / Phone      {_n(dq,'fbp_percentage'):>5.1f}% / {_n(dq,'fbc_percentage'):.1f}% / {_n(dq,'phone_percentage'):.1f}%",
    ]
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': (f"*📊 Funil das últimas 72h*  ·  _{win.get('start_brt','?')} → {win.get('end_brt','?')} BRT_\n"
                 f"```\n" + "\n".join(rows) + "\n```")}})
    B.append({'type': 'context', 'elements': [
        {'type': 'mrkdwn', 'text': '_FBP/FBC % sobre leads Meta · Phone % sobre leads no banco_'}
    ]})


def _slack_decis(v: dict, B: list):
    fm = v['funnel']
    sc = fm.get('scoring', {}) or {}
    win = fm.get('window', {}) or {}
    decis = sc.get('decil_distribution', {}) or {}
    total = sc.get('total_scored', 1) or 1
    rows = []
    for d in ['D01','D02','D03','D04','D05','D06','D07','D08','D09','D10']:
        vv = decis.get(d, 0)
        pct = vv/total*100
        rows.append(f"`{d}`: {vv:>4,}  ({pct:>4.1f}%)")
    left, right = rows[:5], rows[5:]
    two_col = "\n".join(f"{l}     {r}" for l, r in zip(left, right))
    janela = f"_{win.get('start_brt','?')} → {win.get('end_brt','?')} BRT_"
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': f"*Distribuição de decis* · {janela} · {total:,} leads scoreados\n```\n{two_col}\n```"}})


def _slack_lead_quality(v: dict, B: list):
    lq = v['lead_quality']
    lf_label = lq.get('lf_referencia_label')
    has_lf = lf_label is not None and lq.get('lf_referencia')
    def g(period, key): return lq.get(period, {}).get(key, 0)

    if has_lf:
        header = f"               24h        {lf_label:>8}     semana       mês          histórico"
        rows = [
            f"score      {g('ultimas_24h','score'):>8.4f}    {g('lf_referencia','score'):>8.4f}    {g('ultima_semana','score'):>8.4f}    {g('ultimo_mes','score'):>8.4f}    {g('historico','score'):>8.4f}",
            f"D9%        {g('ultimas_24h','d9'):>7.2f}%    {g('lf_referencia','d9'):>7.2f}%    {g('ultima_semana','d9'):>7.2f}%    {g('ultimo_mes','d9'):>7.2f}%    {g('historico','d9'):>7.2f}%",
            f"D10%       {g('ultimas_24h','d10'):>7.2f}%    {g('lf_referencia','d10'):>7.2f}%    {g('ultima_semana','d10'):>7.2f}%    {g('ultimo_mes','d10'):>7.2f}%    {g('historico','d10'):>7.2f}%",
            f"n leads    {g('ultimas_24h','count'):>8,}    {g('lf_referencia','count'):>8,}    {g('ultima_semana','count'):>8,}    {g('ultimo_mes','count'):>8,}    {g('historico','count'):>8,}",
        ]
    else:
        header = "               24h        semana       mês          histórico"
        rows = [
            f"score      {g('ultimas_24h','score'):>8.4f}    {g('ultima_semana','score'):>8.4f}    {g('ultimo_mes','score'):>8.4f}    {g('historico','score'):>8.4f}",
            f"D9%        {g('ultimas_24h','d9'):>7.2f}%    {g('ultima_semana','d9'):>7.2f}%    {g('ultimo_mes','d9'):>7.2f}%    {g('historico','d9'):>7.2f}%",
            f"D10%       {g('ultimas_24h','d10'):>7.2f}%    {g('ultima_semana','d10'):>7.2f}%    {g('ultimo_mes','d10'):>7.2f}%    {g('historico','d10'):>7.2f}%",
            f"n leads    {g('ultimas_24h','count'):>8,}    {g('ultima_semana','count'):>8,}    {g('ultimo_mes','count'):>8,}    {g('historico','count'):>8,}",
        ]
    table = "```\n" + header + "\n" + "\n".join(rows) + "\n```"
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': f"*📈 Qualidade dos Leads (séries temporais)*\n{table}"}})


def _slack_survey(v: dict, B: list):
    sfm = v['survey_funnel']
    if not sfm: return
    rows = []
    for k, label in [('periodo_query','lanç. atual'), ('ultimas_24h','24h'),
                     ('ultima_semana','semana'), ('ultimo_mes','mês'), ('historico','hist')]:
        m = sfm.get(k, {}) or {}
        db = m.get('db_leads', 0) or 0
        cs = m.get('capi_sent', 0) or 0
        cr = m.get('capi_rate', 0) or 0
        ml = m.get('meta_leads'); rr = m.get('response_rate')
        ml_s = f"{ml:>7,}" if ml is not None else f"{'—':>7}"
        rr_s = f"{rr:>6.1f}%" if rr is not None else f"{'—':>7}"
        rows.append(f"{label:<11} meta={ml_s}  db={db:>7,}  capi={cs:>7,} ({cr:>4.1f}%)  %resp={rr_s}")
    header = "_meta = leads que Meta entregou · db = respondeu pesquisa · capi = enviado a Meta · %resp = db÷meta_"
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': f"*📋 Funil Survey*\n{header}\n```\n" + "\n".join(rows) + "\n```"}})
    B.append({'type': 'context', 'elements': [
        {'type': 'mrkdwn', 'text': '_%resp acima de 100% suspeito de inflação — investigar; código pendente._'}
    ]})


def _slack_revenue(v: dict, B: list):
    rf = v['revenue_forecast']
    if not rf: return
    inputs = rf.get('inputs', {}) or {}

    def _row(label, c):
        return (
            f"{label:<14}  {_n(c,'vendas_total'):>5.1f}   "
            f"R$ {_n(c,'faturamento'):>7,.0f}  "
            f"R$ {_n(c,'faturamento_recebido'):>7,.0f}  "
            f"R$ {_n(c,'cartao_avista_liquido'):>11,.0f}  "
            f"R$ {_n(c,'primeira_parcela_boleto'):>9,.0f}  "
            f"{_n(c,'vendas_guru'):>5.1f}  "
            f"{_n(c,'vendas_tmb'):>5.1f}"
        )

    header_table = f"Cenário          Vendas   Faturam.    Recebido    Cartão à vista  1ª parc TMB   Guru   TMB"

    # Método 1 — uma section
    m1_lines = ["```", header_table]
    for label, key in [('Pessim.','cenario_pessimista'),
                       ('Base',   'cenario_base'),
                       ('Otim.',  'cenario_otimista')]:
        m1_lines.append(_row(label, rf.get(key, {}) or {}))
    m1_lines.append("```")

    # Lançamento atual — Método 1
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
        f"*💰 Previsão de Faturamento*\n"
        f"*Lançamento atual*  ·  _{inputs.get('launch_window_start_brt','?')}_  ·  "
        f"{_n(inputs,'total_leads_meta'):,} leads Meta  ·  ticket R$ {_n(inputs,'ticket_contracted'):,.0f}\n"
        f"_*Método 1:* taxa de conversão média LF43-LF53 (recalibrado 08/05)_\n"
        + "\n".join(m1_lines)
    )}})

    # Lançamento atual — Método 2 (cenários ML nativos)
    m2_lines = ["```", header_table,
                _row('Pessim.', rf.get('cenario_ml_aware_pessimista', {}) or {}),
                _row('Base',    rf.get('cenario_ml_aware', {}) or {}),
                _row('Otim.',   rf.get('cenario_ml_aware_otimista', {}) or {}),
                "```"]
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
        f"_*Método 2:* previsão por ML_\n"
        + "\n".join(m2_lines)
    )}})

    # Lançamento anterior — mesma metodologia aplicada ao volume do LF anterior
    lf_ant = rf.get('lf_anterior') or {}
    if lf_ant:
        lf_inputs = lf_ant.get('inputs', {}) or {}
        lf_name = lf_inputs.get('lf_name', '?')

        m1_ant = ["```", header_table]
        for label, key in [('Pessim.','cenario_pessimista'),
                           ('Base',   'cenario_base'),
                           ('Otim.',  'cenario_otimista')]:
            m1_ant.append(_row(label, lf_ant.get(key, {}) or {}))
        m1_ant.append("```")

        m2_ant = ["```", header_table,
                  _row('Pessim.', lf_ant.get('cenario_ml_aware_pessimista', {}) or {}),
                  _row('Base',    lf_ant.get('cenario_ml_aware', {}) or {}),
                  _row('Otim.',   lf_ant.get('cenario_ml_aware_otimista', {}) or {}),
                  "```"]

        B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
            f"*Lançamento anterior — {lf_name}*  ·  _{lf_inputs.get('launch_window_start_brt','?')}_  ·  "
            f"{_n(lf_inputs,'total_leads_meta'):,} leads Meta\n"
            f"_*Método 1:* taxa de conversão média LF43-LF53_\n"
            + "\n".join(m1_ant)
        )}})
        B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': (
            f"_*Método 2:* previsão por ML_\n"
            + "\n".join(m2_ant)
        )}})

    B.append({'type': 'context', 'elements': [
        {'type': 'mrkdwn', 'text': '_Mais detalhes sobre a metodologia no payload da API._'}
    ]})


def _slack_traffic(v: dict, B: list):
    tm = v['traffic']
    def g(p, k): return tm.get(p, {}).get(k, 0) or 0
    table = (
        f"```\n"
        f"              24h            lanç. atual     semana          mês\n"
        f"Spend     R$ {g('ultimas_24h','spend'):>10,.0f}    R$ {g('periodo_query','spend'):>10,.0f}    R$ {g('ultima_semana','spend'):>10,.0f}    R$ {g('ultimo_mes','spend'):>10,.0f}\n"
        f"Leads     {g('ultimas_24h','meta_leads'):>13,}    {g('periodo_query','meta_leads'):>13,}    {g('ultima_semana','meta_leads'):>13,}    {g('ultimo_mes','meta_leads'):>13,}\n"
        f"CPL       R$ {g('ultimas_24h','cpl'):>10,.2f}    R$ {g('periodo_query','cpl'):>10,.2f}    R$ {g('ultima_semana','cpl'):>10,.2f}    R$ {g('ultimo_mes','cpl'):>10,.2f}\n"
        f"Clique→lead {g('ultimas_24h','ctr_lead'):>11.1f}%    {g('periodo_query','ctr_lead'):>11.1f}%    {g('ultima_semana','ctr_lead'):>11.1f}%    {g('ultimo_mes','ctr_lead'):>11.1f}%\n"
        f"Clicks    {g('ultimas_24h','clicks'):>13,}    {g('periodo_query','clicks'):>13,}    {g('ultima_semana','clicks'):>13,}    {g('ultimo_mes','clicks'):>13,}\n"
        f"```"
    )
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': f"*📺 Tráfego Meta*\n{table}"}})


def _slack_ab(v: dict, B: list):
    op = v['ab_test']
    by = op.get('leads_scored_by_variant_24h') or {}
    total_scored_24h = sum((n or 0) for n in by.values())
    lines = ['*🤖 A/B Test* — LIGADO']
    for vv in op.get('ab_variants', []) or []:
        name = vv.get('name','?')
        label = _variant_label(name)
        scored = by.get(name) or 0
        pct = (scored / total_scored_24h * 100) if total_scored_24h else 0
        lines.append(f"• *{label}* (`{name}`) recebeu {scored:,} de {total_scored_24h:,} eventos ({pct:.1f}%) nas últimas 24h")
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': "\n".join(lines)}})


def _slack_actionable(v: dict, B: list):
    aa = v['actionable_alerts']
    if not aa: return
    aa = [a for a in aa if a.get('type') != 'audience_profile_drift']
    if not aa: return

    B.append({'type': 'divider'})
    import re
    lines = ['*🎯 Mudanças significativas:*']
    for a in aa:
        t = a.get('type')
        msg = (a.get('message') or '').strip()
        if t == 'distribution_drift':
            m = re.match(r'\s*\[([^\]]+)\]\s*([^:]+):\s*(\d+)\s*mudan', msg)
            if m:
                variant = _variant_label(m.group(1).strip())
                col = m.group(2).strip()
                n = m.group(3)
                lines.append(f"• {n} mudanças nas proporções da UTM *{col}* para o modelo *{variant}*")
                continue
        lines.append(f"• `{a.get('type','?')}` — {_short(msg.replace(chr(10),' '), 200)}")
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(lines)}})


def _slack_skipped_footer(v: dict, B: list):
    # Footer removido a pedido — paths SKIPPED ainda visíveis via `--show-skipped`.
    return
