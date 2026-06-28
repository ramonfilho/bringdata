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
        'google_funnel':     op.get('google_funnel') or {},
        'critical_summary':  payload.get('critical_summary', ''),
        'skipped':           get_skipped_summary(payload),
        # Resolução da janela do LF atual; consumido só pelo aviso de fallback no DM.
        'launch_resolution': payload.get('launch_resolution') or {},
        # Sumário do consumer Pub/Sub (24h) — Etapa 7 do refator do monitoramento.
        'pubsub_24h':        payload.get('pubsub_24h_summary', {}) or {},
        'training_drift_24h': payload.get('training_drift_24h_summary', {}) or {},
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


def _fmt_brl(x: float | None) -> str:
    if x is None: return '—'
    s = f'{x:,.2f}'
    return s.replace(',', '\x00').replace('.', ',').replace('\x00', '.')


def _color_emoji(delta_pp: float | None) -> str:
    """Bola colorida pelo |Δpp|: <2 verde, 2-4 amarelo, ≥4 vermelho.

    None vira '·' (sem comparação possível).

    Usado em contextos onde NÃO temos direction_map (e.g., decil distribution).
    Pra drift de público, use _quality_emoji que considera bom/ruim por categoria.
    """
    if delta_pp is None: return '·'
    a = abs(delta_pp)
    if a < 2.0:  return '🟢'
    if a < 4.0:  return '🟡'
    return '🔴'


def _quality_emoji(quality: str | None) -> str:
    """Emoji pelo campo `quality` ∈ {'bom', 'ruim', 'neutro', None}.

    Vem de _classify_drift_quality em data_quality.py — combina direction
    (positive/negative do audience_direction_map) com sign(Δpp).

    Fallback: se quality é None ou 'neutro', retorna '⚪'.
    """
    if quality == 'bom':  return '🟢'
    if quality == 'ruim': return '🔴'
    return '⚪'


def _load_direction_map_for_renderer() -> dict:
    """Lê configs/audience_direction_map.json pra usar no renderer
    (categorias + decil_direction). Sem cache; só carrega 1x por render.
    Retorna {} se ausente — degradação graceful."""
    import os
    import json as _stdjson
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     'configs', 'audience_direction_map.json'),
        'configs/audience_direction_map.json',
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p) as f:
                    return _stdjson.load(f)
            except Exception:
                pass
    return {}


def _classify_quality_inline(direction: str | None, delta_pp: float | None) -> str:
    """Espelha src.monitoring.data_quality._classify_drift_quality.
    Vive aqui pro renderer aplicar em campos não-pré-computados (ex: decis)."""
    if delta_pp is None or direction in (None, 'neutral', 'uncertain', 'insufficient_data'):
        return 'neutro'
    positive = direction in ('positive', 'very_positive')
    negative = direction in ('negative', 'very_negative')
    if delta_pp > 0 and positive: return 'bom'
    if delta_pp > 0 and negative: return 'ruim'
    if delta_pp < 0 and negative: return 'bom'
    if delta_pp < 0 and positive: return 'ruim'
    return 'neutro'


def _slack_drift_legend_header(B: list):
    """Header único da seção de drift (Fix 1): legenda 🟢/🔴/⚪ + ✅."""
    B.append({
        'type': 'section',
        'text': {
            'type': 'mrkdwn',
            'text': (
                '*Drift de público — leitura das tabelas*\n'
                '🟢 bom · 🔴 ruim · ⚪ neutro/incerto · ✅ modelo de melhor performance'
            ),
        },
    })


def _render_decil_bar(decil_dist: dict, width: int = 20) -> list[str]:
    """Renderiza distribuição de decis como barra horizontal ASCII.

    decil_dist: dict no formato {'D01': {'count': int, 'pct': float}, ...}
    ou {'D01': float_pct, ...}. Pcts em [0, 100].
    """
    lines: list[str] = []
    # Ordem fixa D01-D10
    keys = [f'D{i:02d}' for i in range(1, 11)]
    # Maior pct define escala
    raw_pcts = {}
    raw_counts = {}
    for k in keys:
        v = decil_dist.get(k)
        if isinstance(v, dict):
            raw_pcts[k] = float(v.get('pct') or 0)
            raw_counts[k] = int(v.get('count') or 0)
        elif v is None:
            raw_pcts[k] = 0.0
            raw_counts[k] = 0
        else:
            raw_pcts[k] = float(v)
            raw_counts[k] = 0
    max_pct = max(raw_pcts.values()) if raw_pcts else 0
    for k in keys:
        pct = raw_pcts[k]
        n = raw_counts[k]
        bar_len = int(round((pct / max_pct) * width)) if max_pct > 0 else 0
        bar = '▇' * bar_len + ' ' * (width - bar_len)
        count_suffix = f"  ({n:,})" if n > 0 else ''
        lines.append(f"{k} {bar} {pct:>4.1f}%{count_suffix}")
    return lines


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


def _scored_n(rf: dict):
    """Nº de respostas scoreadas (base do Método 2/ML) — total_db do expected_conversion.
    O flat-rate usa leads Meta; o ML usa respostas de pesquisa (todas as fontes)."""
    return ((rf.get('expected_conversion') or {}).get('distribuicao_leads') or {}).get('total_db')


def _bases_md(leads_total: float, scored) -> str:
    """Rótulo das duas bases do forecast: leads totais all-source (flat-rate) + respostas scoreadas (ML)."""
    s = f'  ·  {scored:,} respostas scoreadas (ML)' if scored else ''
    return f'{leads_total:,.0f} leads — todas as fontes (flat-rate){s}'


# ──────────────────────────────────────────────────────────────────────────
# render_text — terminal / arquivo
# ──────────────────────────────────────────────────────────────────────────

def render_text(view: dict) -> str:
    _set_render_labels(view)   # Frente 2: rótulos do YAML (fallback legado)
    lines: list[str] = []
    _render_text_header(view, lines)
    _render_text_ab(view, lines)
    lines.append('─' * 78); lines.append('')
    _render_text_alerts(view, lines)
    lines.append('─' * 78); lines.append('')
    _render_text_funnel(view, lines)
    _render_text_lead_quality(view, lines)
    _render_text_revenue(view, lines)
    _render_text_traffic(view, lines)
    _render_text_skipped_footer(view, lines)
    return '\n'.join(lines)


# Frente 2 (DT-19): os rótulos do relatório vêm do YAML — cada variante declara
# display_name (e role), o orchestrator injeta em ab_test.ab_variants no payload, e
# _set_render_labels() monta os mapas (por MODELO e por BALDE) no início de cada
# render. FONTE ÚNICA — os mapas chumbados antigos (_VARIANT_LABEL/_AB_BUCKET_LABEL)
# foram removidos. Render é sequencial, então o estado de módulo é seguro.
_RENDER_LABELS: dict = {'variant': {}, 'bucket': {}}


def _set_render_labels(v: dict) -> None:
    """Monta os mapas de rótulo (por MODELO e por BALDE) a partir das variantes do
    payload (ab_test.ab_variants, cada uma com role/display_name vindos do YAML).
    Fonte única; variante sem display_name cai no nome cru no lookup."""
    variant_map: dict = {}
    bucket_map: dict = {'Lead': 'Lead'}
    _bucket_of = {'champion': 'Champion', 'challenger': 'Challenger'}
    for vv in ((v.get('ab_test') or {}).get('ab_variants') or []):
        name, dn, role = vv.get('name'), vv.get('display_name'), (vv.get('role') or '').lower()
        if name and dn:
            variant_map[name] = dn
        if role in _bucket_of and dn:
            bucket_map[_bucket_of[role]] = dn
    _RENDER_LABELS['variant'] = variant_map
    _RENDER_LABELS['bucket'] = bucket_map


def _variant_label(name: str) -> str:
    return _RENDER_LABELS['variant'].get(name, name)


def _ab_bucket_label(bucket: str) -> str:
    return _RENDER_LABELS['bucket'].get(bucket, bucket)


# ──────────────────────────────────────────────────────────────────────────
# Humanização SÓ-DISPLAY de nome de feature/coluna e valor de categoria.
#
# CONTRATO DE CONFIABILIDADE:
#   - Funções puras, idempotentes, aplicadas APENAS dentro de f-string de
#     render. NUNCA usar como chave de lookup/agrupamento/comparação/dedup.
#   - Caso conhecido → reverte com certeza (mapa curado).
#   - Caso desconhecido → volta EXATAMENTE como veio (não chuta), pra não
#     mascarar um valor que pode ser um bug real de normalização.
# ──────────────────────────────────────────────────────────────────────────

_FEATURE_DISPLAY = {
    'Source':               'UTM Source',
    'Medium':               'UTM Medium',
    'Term':                 'UTM Term',
    'Campaign':             'UTM Campaign',
    'Content':              'UTM Content',
    'telefone_comprimento': 'Comprimento do telefone',
    'nome_comprimento':     'Comprimento do nome',
    'email_comprimento':    'Comprimento do e-mail',
}


def _humanize_feature(name: Any) -> str:
    """Display-only. Mapa curado; fallback = underscore→espaço só se houver
    '_'. Sem '_' e fora do mapa → volta cru (não chuta)."""
    s = str(name)
    if s in _FEATURE_DISPLAY:
        return _FEATURE_DISPLAY[s]
    if '_' in s:
        t = s.replace('_', ' ').strip()
        return (t[:1].upper() + t[1:]) if t else s
    return s


_CATEGORY_DISPLAY = {
    'facebookads': 'Facebook Ads',
    'googleads':   'Google Ads',
    'instagram':   'Instagram',
    'tiktok':      'TikTok',
    'youtube':     'YouTube',
    'organico':    'Orgânico',
    'outros':      'Outros',
    'mixquente':   'Mix Quente',
    'aberto':      'Aberto',
}


def _humanize_category(value: Any) -> str:
    """Display-only. Mapa curado de formas canônicas conhecidas. Fora do
    mapa → volta exatamente como veio (não chuta)."""
    return _CATEGORY_DISPLAY.get(str(value), str(value))


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
    outros_inflated     = [a for a in alerts if a.get('type') == 'outros_bucket_inflated']
    other_alerts        = [a for a in alerts if a.get('type') not in (
        'distribution_drift', 'category_drift', 'audience_profile_drift',
        'outros_bucket_inflated', 'extra_unexpected_features',
        # audience_quality_signal não pertence a "Mudanças significativas" — tem
        # seção própria (lead_quality / audience). LOW + dentro do padrão não
        # deve poluir o topo.
        'audience_quality_signal', 'audience_profile_drift_by_variant',
        'audience_profile_drift_by_source',
    )]

    sep = lambda: (L.append('· · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · ·'), L.append(''))

    # Header da seção
    L.append('🚨  Mudanças significativas')
    L.append('')

    # 0) Outros bucket inflado — categorias raw caindo em 'outros' acima do threshold
    if outros_inflated:
        _render_text_outros_inflated_consolidated(outros_inflated, L)

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
    ref_label = d.get('reference_pool_label') or 'lançamentos referência'
    L.append(f'🔵  Características dos leads vs {ref_label}')
    L.append('')

    top = d.get('top_list', []) or []
    if not top:
        L.append('    (sem dados na top_list)'); L.append(''); return

    has_launch = any(it.get('launch_pct') is not None for it in top)
    has_prev   = any(it.get('prev_day_pct') is not None for it in top)
    has_today  = any(it.get('today_pct') is not None for it in top)

    headers = [f'{"Característica":<36}', f'{"Ref%":>6}']
    if has_launch: headers.append(f'{"Lanç. (Δ)":>14}')
    if has_prev:   headers.append(f'{"Anteontem (Δ)":>14}')
    headers.append(f'{"Ontem (Δ)":>14}')
    if has_today:  headers.append(f'{"Hoje (Δ)":>14}')
    L.append('    ' + '  '.join(headers))
    n_delta_cols = 1 + int(has_launch) + int(has_prev) + int(has_today)
    L.append('    ' + '─' * (36 + 6 + 14*n_delta_cols + 2*(len(headers)-1)))

    for it in top:
        label = _short(f"{it['feature_label']}: {_humanize_category(it['category'])}", 36)
        ref = _fmt_pct(it.get('reference_pct'))
        cells = [f'{label:<36}', f'{ref:>6}']
        if has_launch:
            lp, ld = it.get('launch_pct'), it.get('launch_delta_pp')
            cell = f'{_fmt_pct(lp)} ({_fmt_pp(ld):>5})' if lp is not None else '       —'
            cells.append(f'{cell:>14}')
        if has_prev:
            pp, pd_ = it.get('prev_day_pct'), it.get('prev_day_delta_pp')
            cell = f'{_fmt_pct(pp)} ({_fmt_pp(pd_):>5})' if pp is not None else '       —'
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
        L.append(f'Drift de proporções — {_humanize_feature(col)}:')
        for a in group:
            d = a.get('details', {}) or {}
            variant = _variant_label(d.get('variant_name', '?'))
            changes = d.get('changes', []) or []
            n = len(changes)
            n_sil = int(d.get('n_silenced') or 0)
            sil_suffix = f', +{n_sil} silenciada{"s" if n_sil != 1 else ""}' if n_sil > 0 else ''
            L.append(f'  • {variant} ({n} mudança{"s" if n != 1 else ""}{sil_suffix}):')
            for c in changes:
                treino = (c.get('treino') or 0) * 100
                prod   = (c.get('producao') or 0) * 100
                diff   = prod - treino
                cat    = _humanize_category(c.get('categoria', '?'))
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


def _render_text_outros_inflated_consolidated(alerts: list, L: list):
    """Renderiza alertas `outros_bucket_inflated` com breakdown raw → % do volume da coluna.

    Cada alerta tem (em `details`): column, outros_pct_of_total, outros_count,
    total_count, breakdown=[{raw_value, count, pct_total}], restrict_to_sources.
    pct_total já vem como fração do total da coluna (pós-restrição se aplicável).
    """
    for a in alerts:
        d     = a.get('details', {}) or {}
        col   = d.get('column', '?')
        tot   = d.get('total_count', 0)
        outn  = d.get('outros_count', 0)
        pct   = (d.get('outros_pct_of_total') or 0) * 100
        hours = d.get('window_hours', 24)
        bd    = d.get('breakdown') or []
        rs    = d.get('restrict_to_sources') or []
        scope = f' (entre Source ∈ {{{", ".join(rs)}}})' if rs else ''
        L.append(f'Bucket "outros" inflado na UTM {col}{scope}: {outn}/{tot} leads ({pct:.1f}% do volume, janela {hours}h)')
        if bd:
            for it in bd[:8]:
                raw = _short(it.get('raw_value', '') or '(vazio)', 50)
                n = it.get('count', 0)
                p = (it.get('pct_total') or 0) * 100
                L.append(f"    {raw:<50} {n:>5}  ({p:>4.1f}% do total)")
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
            new_cats = ', '.join(_humanize_category(c) for c in (d.get('new_categories', []) or []))
            n = d.get('affected_count', 0); pct = d.get('percentage', 0)
            L.append(f"    {_humanize_feature(col)}: {new_cats}  ·  {n} leads ({pct:.1f}%)")
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
        L.append(f'    {"":<10}  {"Ontem":>10}  {col_lf}  {"semana":>10}  {"mês":>10}  {"hist":>10}')
    else:
        L.append(f'    {"":<10}  {"Ontem":>10}  {"semana":>10}  {"mês":>10}  {"hist":>10}')

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
    L.append(f'    Lançamento atual ({inputs.get("launch_window_start_brt","?")}): {_bases_md(_n(inputs,"total_leads_meta"), _scored_n(rf))}  ·  ticket R$ {_n(inputs,"ticket_contracted"):,.0f}')
    L.append('')

    def _row(label, c):
        return (
            f'    {label:<16} {_n(c,"vendas_total"):>7.1f}  '
            f'R$ {_n(c,"faturamento"):>14,.0f}  '
            f'R$ {_n(c,"faturamento_recebido"):>16,.0f}'
        )

    header = f'    {"Cenário":<16} {"Vendas":>7}  {"Fat. contratado":>17}  {"Recebido 1ª janela":>19}'

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
        L.append(f'  Lançamento anterior ({lf_name} · {lf_inputs.get("launch_window_start_brt","?")}): {_bases_md(_n(lf_inputs,"total_leads_meta"), _scored_n(lf_ant))}')
        L.append('')
        _write_two_methods(lf_ant)

    L.append('    Mais detalhes sobre a metodologia no payload da API.')
    L.append('')


def _render_text_traffic(v: dict, L: list):
    tm = v['traffic']
    L.append('📺  TRÁFEGO META')
    L.append(f'    {"":<11} {"24h":>14} {"lanç. atual":>14} {"semana":>14}')
    # CPL lead: meta_leads vem do evento 'offsite_conversion.fb_pixel_lead' da
    # Meta Insights API — corresponde ao lead capture (tabela `leads_capi`),
    # NÃO à pesquisa preenchida (tabela `Lead`). Por isso "CPL lead".
    for metric, label, fmt in [
        ('spend',      'Spend',       'R$ {:>10,.0f}'),
        ('meta_leads', 'Leads',       '{:>14,}'),
        ('cpl',        'CPL lead',    'R$ {:>10,.2f}'),
        ('ctr_lead',   'Clique→lead', '{:>13.1f}%'),
    ]:
        h24 = tm.get('ultimas_24h', {}).get(metric, 0) or 0
        pq  = tm.get('periodo_query', {}).get(metric, 0) or 0
        sem = tm.get('ultima_semana', {}).get(metric, 0) or 0
        L.append(f'    {label:<11} {fmt.format(h24):>14} {fmt.format(pq):>14} {fmt.format(sem):>14}')
    L.append('')


def _render_text_ab(v: dict, L: list):
    op = v['ab_test']
    by_variant = op.get('leads_scored_by_variant_24h') or {}
    by_spend = op.get('spend_by_variant_24h_brl') or {}
    by_cpl = op.get('cpl_by_variant_24h_brl') or {}
    total_scored_24h = sum((n or 0) for n in by_variant.values())
    L.append('🤖  A/B TEST LIGADO')
    for vv in op.get('ab_variants', []) or []:
        name = vv.get('name', '?')
        label = _variant_label(name)
        scored = by_variant.get(name) or 0
        pct = (scored / total_scored_24h * 100) if total_scored_24h else 0
        suffix = f" · R$ {_fmt_brl(by_spend[name])} investidos" if name in by_spend else ''
        L.append(f"    {label} ({name}) recebeu {scored:,} de {total_scored_24h:,} eventos ({pct:.1f}%) nas últimas 24h{suffix}")
    L.append('')


def _render_text_actionable(v: dict, L: list):
    aa = v['actionable_alerts']
    if not aa: return
    # Filtra audience_profile_drift (redundante com a tabela detalhada)
    aa = [a for a in aa if a.get('type') != 'audience_profile_drift']
    if not aa: return

    L.append('🎯  Mudanças significativas:')
    # Outros buckets primeiro — chama o mesmo renderer detalhado do bloco principal.
    outros_inflated = [a for a in aa if a.get('type') == 'outros_bucket_inflated']
    if outros_inflated:
        _render_text_outros_inflated_consolidated(outros_inflated, L)
    for a in aa:
        t = a.get('type')
        if t == 'outros_bucket_inflated':
            continue  # já rendido acima
        msg = (a.get('message') or '').strip()
        if t == 'distribution_drift':
            # Tenta extrair variant + N de "[champion_jan30] Medium: 3 mudança(s) ..."
            import re
            m = re.match(r'\s*\[([^\]]+)\]\s*([^:]+):\s*(\d+)\s*mudan', msg)
            if m:
                variant = _variant_label(m.group(1).strip())
                col = m.group(2).strip()
                n = m.group(3)
                L.append(f"    {n} mudanças nas proporções de {col} para o modelo {variant}")
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
    """View 'DM' — só conteúdo exclusivo do operador.

    Não duplica nada do que já vai pro canal do cliente (A/B, drift por A/B,
    drift por fonte, drift geral, decis ontem/lançamento). Mantém apenas o
    header (âncora de data) e os blocos só-DM: aviso de fallback de
    lançamento, drift de score (decis vs baseline), alertas detalhados,
    funil completo, qualidade dos leads, Pub/Sub 24h, features OHE zeradas
    em batch, previsão de faturamento.
    """
    blocks: list[dict] = []
    _set_render_labels(view)   # Frente 2: rótulos do YAML (fallback legado)
    _slack_header(view, blocks)
    _slack_launch_fallback_notice_dm(view, blocks)  # DM-only — no-op se YAML em dia
    _slack_score_distribution_change_dm(view, blocks)  # Drift de Score (decis)
    blocks.append({'type': 'divider'})
    _slack_alerts(view, blocks, include_audience_drift=False)
    blocks.append({'type': 'divider'})
    _slack_unified_funnel(view, blocks)
    _slack_survey_response_rate(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_lead_quality(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_pubsub_24h(view, blocks)
    blocks.append({'type': 'divider'})
    _slack_training_drift_24h(view, blocks)  # Features OHE zeradas em batch (T1-16)
    blocks.append({'type': 'divider'})
    _slack_revenue(view, blocks)
    _slack_skipped_footer(view, blocks)
    return blocks


def _slack_audience_drift_by_variant_dm(v: dict, B: list):
    """Tabelas de drift de público por A/B (Lead × Champion × Challenger) no DM.

    Renderiza o mesmo conteúdo que `render_slack_blocks_client` mostra
    (`audience_profile_drift_by_variant`), com ordenação previous_day antes
    de current_launch. Skipa silenciosamente se não houver alertas.

    Desde 2026-06-15 o split lê a *tag de optimization_goal no nome da campanha*
    (utm_campaign: LEADQUALIFIED=Champion, LEADHQLB=Challenger, sem tag=Lead),
    localmente via campaign_classifier.bucket_from_utm — NÃO mais via Meta API
    (que rate-limitava e zerava o split). Mesma semântica 3-way, fonte confiável.
    """
    alerts = v.get('alerts') or []
    by_variant = [a for a in alerts if a.get('type') == 'audience_profile_drift_by_variant']
    if not by_variant:
        return

    _slack_drift_legend_header(B)
    by_variant.sort(
        key=lambda a: 0 if (a.get('details', {}) or {}).get('window') == 'previous_day' else 1
    )
    for a in by_variant:
        _slack_alert_audience_by_variant(a, B)
        B.append({'type': 'divider'})


def _slack_score_distribution_change_dm(v: dict, B: list):
    """Bloco "📊 Drift de Score — distribuição de decis" no DM.

    Renderiza alertas `score_distribution_change` emitidos por
    `_check_score_distribution` (data_quality.py). Mostra os decis que
    desviaram da baseline (rolling 30d em produção ou metadata do treino)
    e a fonte da baseline.

    Antes desse renderer dedicado, o alerta caía em `_slack_alert_other`
    e saía como linha solta sem contexto.
    """
    alerts = v.get('alerts') or []
    drift_alerts = [a for a in alerts if a.get('type') == 'score_distribution_change']
    if not drift_alerts:
        return

    B.append({'type': 'header',
              'text': {'type': 'plain_text',
                       'text': '📊 Drift de Score — distribuição de decis',
                       'emoji': True}})

    for a in drift_alerts:
        d = a.get('details', {}) or {}
        sev = a.get('severity', '?')
        e = _sev_emoji(sev)
        total = d.get('total_leads', 0)
        baseline = d.get('baseline_source', '?')
        changes = d.get('changes') or []
        header_line = (
            f"{e} *{sev}* · `{total}` leads na janela · baseline `{baseline}`"
        )
        B.append({'type': 'section',
                  'text': {'type': 'mrkdwn', 'text': header_line}})

        if changes:
            lines = ['*Decis que mudaram (top 5 por |Δ|):*']
            for c in changes[:5]:
                decil = c.get('decil', '?')
                esp = (c.get('esperado') or 0) * 100
                atu = (c.get('atual') or 0) * 100
                diff = atu - esp
                arrow = '🔺' if diff > 0 else '🔻'
                lines.append(
                    f"• `{decil}` — esperado *{esp:.1f}%* → atual *{atu:.1f}%* "
                    f"{arrow} `{diff:+.1f}pp`"
                )
            B.append({'type': 'section',
                      'text': {'type': 'mrkdwn', 'text': '\n'.join(lines)}})

    B.append({'type': 'divider'})


def _slack_pubsub_24h(v: dict, B: list):
    """Bloco "📨 Pub/Sub 24h" — saúde do consumer do ledger novo.

    Mostra:
      - Total + quebra por status (sucesso/erro/pulados).
      - Distribuição por decil dos sucessos (compacto, só decis com volume).
      - Top mensagens de erro.

    Skipado silenciosamente se a fonte não trouxe dados (total=0 e sem erros).
    """
    ps = v.get('pubsub_24h') or {}
    total = ps.get('total', 0) or 0
    by_status = ps.get('by_status') or {}
    decis = ps.get('decil_distribution') or {}
    top_errs = ps.get('top_errors') or []

    if total == 0 and not top_errs:
        return  # nada útil pra mostrar

    B.append({'type': 'header',
              'text': {'type': 'plain_text', 'text': '📨 Pub/Sub 24h', 'emoji': True}})

    ok   = by_status.get('success', 0) or 0
    err  = by_status.get('error', 0) or 0
    sall = by_status.get('skipped_allowlist', 0) or 0
    smd  = by_status.get('skipped_missing_data', 0) or 0
    status_line = (
        f"*{total}* leads · ✅ {ok} sucesso · ❌ {err} erro · "
        f"⏭️ {sall} fora da allowlist · 🚫 {smd} faltou fbp/fbc/computador"
    )
    B.append({'type': 'section',
              'text': {'type': 'mrkdwn', 'text': status_line}})

    # Distribuição por decil dos sucessos — só decis com volume, em ordem D10→D01
    com_volume = [(d, decis.get(d, 0)) for d in
                  ('D10','D09','D08','D07','D06','D05','D04','D03','D02','D01')
                  if (decis.get(d, 0) or 0) > 0]
    if com_volume:
        decil_line = '*Decis dos sucessos:* ' + ' · '.join(
            f'{d}: {n}' for d, n in com_volume
        )
        B.append({'type': 'section',
                  'text': {'type': 'mrkdwn', 'text': decil_line}})

    # Top erros — limita a mensagem em 200 chars pra não estourar bloco Slack
    if top_errs:
        lines = ['*Top erros:*']
        for e in top_errs:
            msg = (e.get('message') or '').strip()
            if len(msg) > 200:
                msg = msg[:197] + '...'
            lines.append(f"• `{e.get('count', 0)}×` {msg}")
        B.append({'type': 'section',
                  'text': {'type': 'mrkdwn', 'text': '\n'.join(lines)}})


def _slack_training_drift_24h(v: dict, B: list):
    """Bloco "🎯 Features zeradas em batch" — colunas OHE pós-encoding que
    foram zeradas em massa em algum batch de scoring nas últimas 24h
    (`validate_post_encoding_zero_rates` / T1-16 do feature_validator).

    Sinaliza problema de encoding silencioso (categoria sumiu, parsing JSONB
    falhou, casing mudou no front). Complementa o "Drift de proporções 24h":
    aquele é categoria-level agregado do dia; este é OHE-level por batch.

    Mostra:
      - Quantos batches dispararam (= quantos lotes do Pub/Sub vieram com
        coluna OHE caída pra <30% do esperado de treino).
      - Top 5 colunas OHE mais afetadas (obs vs treino, delta pp, em quantos
        batches apareceram).

    Skipado se não há warnings na janela (estado limpo).
    """
    td = v.get('training_drift_24h') or {}
    batches = td.get('batches_com_drift', 0) or 0
    top = td.get('top_features') or []

    if batches == 0 and not td.get('erro'):
        return  # estado limpo — encoding consistente com treino

    B.append({'type': 'header',
              'text': {'type': 'plain_text',
                       'text': '🎯 Features zeradas em batch (24h)',
                       'emoji': True}})

    if td.get('erro'):
        B.append({'type': 'section',
                  'text': {'type': 'mrkdwn',
                           'text': f"⚠️ erro ao consultar logs: `{td['erro']}`"}})
        return

    hours = td.get('window_hours', 24)
    header_line = (
        f"*{batches}* batches do Pub/Sub vieram com alguma coluna OHE zerada "
        f"em massa nas últimas {hours}h "
        f"({td.get('total_observacoes', 0)} ocorrências no total). "
        f"_Diferente do drift de proporções (agregado do dia): aqui é por batch "
        f"individual, no nível da coluna OHE pós-encoding._"
    )
    B.append({'type': 'section',
              'text': {'type': 'mrkdwn', 'text': header_line}})

    if top:
        lines = ['*Top colunas OHE zeradas (obs vs treino):*']
        for f in top:
            delta = f.get('delta_pp', 0)
            arrow = '🔻' if delta < 0 else '🔺'
            lines.append(
                f"• `{f.get('feature','?')}` — obs *{100*f.get('obs_media',0):.1f}%* "
                f"vs treino *{100*f.get('exp',0):.1f}%* {arrow} {abs(delta):.1f}pp  "
                f"(em {f.get('count', 0)} batches)"
            )
        B.append({'type': 'section',
                  'text': {'type': 'mrkdwn', 'text': '\n'.join(lines)}})

    obs = td.get('observacao')
    if obs:
        B.append({'type': 'context',
                  'elements': [{'type': 'mrkdwn', 'text': f"_{obs}_"}]})


def render_slack_blocks_client(view: dict) -> list[dict]:
    """View 'cliente' — A/B test + 2 tabelas de drift por variante + drift geral
    com cores 🟢🟡🔴 + 2 distribuições de decis (ontem + lançamento atual)."""
    blocks: list[dict] = []
    _set_render_labels(view)   # Frente 2: rótulos do YAML (fallback legado)
    _slack_header(view, blocks)
    _slack_ab(view, blocks)
    blocks.append({'type': 'divider'})

    # Per-variant drift tables (uma por janela). Desde 2026-05-28 split é por
    # optimization_goal da campanha (3 buckets Lead/Champion/Challenger), não
    # por A/B model routing — sempre faz sentido renderizar.
    audience_by_variant = [a for a in view.get('alerts', [])
                           if a.get('type') == 'audience_profile_drift_by_variant']
    audience_by_source = [a for a in view.get('alerts', [])
                          if a.get('type') == 'audience_profile_drift_by_source']
    audience_general = [a for a in view.get('alerts', [])
                        if a.get('type') == 'audience_profile_drift']
    # Header único da seção de drift (Fix 1)
    if audience_by_variant or audience_by_source or audience_general:
        _slack_drift_legend_header(blocks)

    # Ordena: previous_day primeiro, depois current_launch
    audience_by_variant.sort(
        key=lambda a: 0 if (a.get('details', {}) or {}).get('window') == 'previous_day' else 1
    )
    audience_by_source.sort(
        key=lambda a: 0 if (a.get('details', {}) or {}).get('window') == 'previous_day' else 1
    )
    for a in audience_by_variant:
        _slack_alert_audience_by_variant(a, blocks)
        blocks.append({'type': 'divider'})

    for a in audience_by_source:
        _slack_alert_audience_by_source(a, blocks)
        blocks.append({'type': 'divider'})

    # Drift geral com cores
    for a in audience_general:
        _slack_alert_audience(a, blocks)
        blocks.append({'type': 'divider'})

    # Decis ontem + lançamento atual
    _slack_decis_window(view, blocks, 'previous_day')
    _slack_decis_window(view, blocks, 'current_launch')
    # Taxa de resposta da pesquisa (cadastro→pesquisa) — esta view vai pro grupo
    # de dados do cliente (#team-dados). Mesmo bloco da view completa; omite-se
    # sozinho se a métrica veio ausente.
    _slack_survey_response_rate(view, blocks)
    return blocks


def _slack_header(v: dict, B: list):
    ts = (v['meta'].get('timestamp') or '')[:10]
    B.append({'type': 'header', 'text': {'type': 'plain_text', 'text': f'📊 Daily Check — DevClub · {ts}', 'emoji': True}})


def _slack_alerts(v: dict, B: list, include_audience_drift: bool = True):
    """Renderer principal de alertas. `include_audience_drift=False` esconde
    audience_profile_drift{,_by_variant} pra DM (cliente recebe tabelas
    dedicadas com cores/✅)."""
    alerts = v['alerts']
    if not alerts:
        B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '✅ *Sem alertas.*'}})
        return

    distribution_drifts = [a for a in alerts if a.get('type') == 'distribution_drift']
    category_drifts     = [a for a in alerts if a.get('type') == 'category_drift']
    audience_drifts     = [a for a in alerts if a.get('type') == 'audience_profile_drift']
    outros_inflated     = [a for a in alerts if a.get('type') == 'outros_bucket_inflated']
    others              = [a for a in alerts if a.get('type') not in (
        'distribution_drift', 'category_drift', 'audience_profile_drift',
        'audience_profile_drift_by_variant',
        'audience_profile_drift_by_source',
        'outros_bucket_inflated', 'extra_unexpected_features',
        # audience_quality_signal tem seção própria (lead_quality / audience);
        # LOW dentro do padrão não vai pra Mudanças significativas.
        'audience_quality_signal',
        # score_distribution_change tem renderer dedicado
        # `_slack_score_distribution_change_dm` na render_slack_blocks (DM).
        'score_distribution_change',
    )]

    B.append({'type': 'header', 'text': {'type': 'plain_text', 'text': '🚨 Mudanças significativas', 'emoji': True}})

    if outros_inflated:
        _slack_outros_inflated_consolidated(outros_inflated, B)

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

    if include_audience_drift and audience_drifts:
        B.append({'type': 'divider'})
        for a in audience_drifts:
            _slack_alert_audience(a, B)


def _slack_outros_inflated_consolidated(alerts: list, B: list):
    """Slack block para alertas `outros_bucket_inflated`. % do volume da coluna
    (não do bucket Outros). Lê campos de `details`."""
    for a in alerts:
        d     = a.get('details', {}) or {}
        col   = d.get('column', '?')
        tot   = d.get('total_count', 0)
        outn  = d.get('outros_count', 0)
        pct   = (d.get('outros_pct_of_total') or 0) * 100
        hours = d.get('window_hours', 24)
        bd    = d.get('breakdown') or []
        rs    = d.get('restrict_to_sources') or []
        scope = f' _(Source ∈ {{{", ".join(rs)}}})_' if rs else ''
        lines = [f'*Bucket "outros" inflado na UTM {col}{scope}:* `{outn}/{tot}` leads '
                 f'(`{pct:.1f}%` do volume, janela `{hours}h`)']
        if bd:
            for it in bd[:6]:
                raw = _short(it.get('raw_value', '') or '(vazio)', 32)
                n   = it.get('count', 0)
                p   = (it.get('pct_total') or 0) * 100
                lines.append(f"     `{raw:<32}` {n:>4} (`{p:>4.1f}%` do total)")
        B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(lines)}})


def _slack_distribution_drifts_consolidated(alerts: list, B: list):
    by_col: dict[str, list] = {}
    for a in alerts:
        col = (a.get('details') or {}).get('column', '?')
        by_col.setdefault(col, []).append(a)

    for col, group in by_col.items():
        lines = [f"*Drift de proporções — {_humanize_feature(col)}:*"]
        for a in group:
            d = a.get('details', {}) or {}
            variant = _variant_label(d.get('variant_name', '?'))
            changes = d.get('changes', []) or []
            n = len(changes)
            n_sil = int(d.get('n_silenced') or 0)
            sil_suffix = f', +{n_sil} silenciada{"s" if n_sil != 1 else ""}' if n_sil > 0 else ''
            lines.append(f"  • *{variant}* ({n} mudança{'s' if n != 1 else ''}{sil_suffix}):")
            for c in changes:
                cat = _short(_humanize_category(c.get('categoria', '?')), 38)
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
    """Drift geral com 🟢 bom · 🔴 ruim · ⚪ neutro/uncertain.

    Quality = direction (audience_direction_map) × sign(Δpp).
    Ver docs/METODOLOGIA_TOP5_ROAS.md.
    """
    d = a.get('details', {}) or {}
    ref_label = d.get('reference_pool_label') or 'lançamentos referência'
    top = d.get('top_list', []) or []
    has_launch = any(it.get('launch_pct') is not None for it in top)
    has_prev   = any(it.get('prev_day_pct') is not None for it in top)
    has_today  = any(it.get('today_pct') is not None for it in top)

    # Legenda movida pra _slack_drift_legend_header (uma vez por seção).
    rows = [f"*Drift de público geral vs {ref_label}*"]
    col_header = [f"{'Característica':<32} {'Ref%':>5}"]
    if has_launch: col_header.append(f"{'Lanç(Δ)':>15}")
    if has_prev:   col_header.append(f"{'Anteontem(Δ)':>15}")
    col_header.append(f"{'Ontem(Δ)':>15}")
    if has_today:  col_header.append(f"{'Hoje(Δ)':>15}")
    rows.append(f"`{'  '.join(col_header)}`")

    def cell_qual(pct, delta, quality):
        if pct is None: return f"{'—':>15}"
        return f"{_quality_emoji(quality)} {pct:>5.1f}%({delta:+.1f})"

    for it in top:
        label = _short(f"{it['feature_label']}: {_humanize_category(it['category'])}", 32)
        ref = it.get('reference_pct', 0)
        parts = [f"{label:<32} {ref:>4.1f}%"]
        if has_launch:
            parts.append(f"{cell_qual(it.get('launch_pct'), it.get('launch_delta_pp'), it.get('launch_quality')):>15}")
        if has_prev:
            # Cor do Anteontem vem da quality própria dele (direction × sign(prev_day_delta_pp)),
            # calculada no data_quality.py. Fallback inline cobre payload antigo sem o campo.
            prev_q = it.get('prev_day_quality') or _classify_quality_inline(it.get('direction'), it.get('prev_day_delta_pp'))
            parts.append(f"{cell_qual(it.get('prev_day_pct'), it.get('prev_day_delta_pp'), prev_q):>15}")
        parts.append(f"{cell_qual(it.get('day_pct'), it.get('delta_pp'), it.get('day_quality')):>15}")
        if has_today:
            today_q = it.get('today_quality') or _classify_quality_inline(it.get('direction'), it.get('today_delta_pp'))
            parts.append(f"{cell_qual(it.get('today_pct'), it.get('today_delta_pp'), today_q):>15}")
        rows.append(f"`{'  '.join(parts)}`")
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(rows)}})


def _slack_alert_audience_by_variant(a: dict, B: list):
    """Drift por A/B (Champion vs Challenger) com 🟢 bom · 🔴 ruim · ⚪ neutro por variante.

    Quality = direction da categoria × sign(Δpp) (ver _classify_drift_quality
    em data_quality.py). Ver docs/METODOLOGIA_TOP5_ROAS.md.
    """
    d = a.get('details', {}) or {}
    window = d.get('window') or ''
    top = d.get('top_list', []) or []

    n_lead = d.get('lead_n', 0) or 0
    n_champion = d.get('champion_n', 0) or 0
    n_challenger = d.get('challenger_n', 0) or 0
    n_google = d.get('google_n', 0) or 0
    n_outros = d.get('outros_n', 0) or 0
    window_title = 'Ontem' if window == 'previous_day' else (
        'Lançamento Atual' if window == 'current_launch' else (d.get('window_label') or 'janela')
    )
    # Legenda movida pra _slack_drift_legend_header (uma vez por seção).
    header = f"*📉 Drift por A/B - {window_title}*"
    # Header: 3 contadores que entram nas colunas Δ (Lead/Champion/Challenger,
    # leads Meta separados pela tag de optimization_goal no nome da campanha,
    # lida localmente sem Meta API) + 2 que ficam fora da tabela mas aparecem pra
    # deixar claro o universo total (Google e Outros).
    # Colunas dinâmicas: só os baldes com leads > 0 entram ("o que não está
    # scoreando some"). Rótulo via _ab_bucket_label (fonte única) — a campanha
    # LEADHQLB/abr_28 vira "Champion (abr_28)"; a LEADQUALIFIED antiga (jan_30),
    # quando não está no ar, nem aparece. Lead não compete (não ganha ✅).
    _arms = [
        ('Lead',       n_lead,       False, 'lead_pct',       'lead_delta_pp',       'lead_quality'),
        ('Champion',   n_champion,   True,  'champion_pct',   'champion_delta_pp',   'champion_quality'),
        ('Challenger', n_challenger, True,  'challenger_pct', 'challenger_delta_pp', 'challenger_quality'),
    ]
    _arms = [a for a in _arms if a[1] > 0]
    _n_compete = sum(1 for a in _arms if a[2])  # ✅ de vencedor só faz sentido com 2 braços comparáveis
    _AW = 22  # largura da coluna de cada braço (cabe "Champion (abr_28)(Δ)")

    if (n_lead + n_champion + n_challenger + n_google + n_outros) > 0:
        in_table = ' · '.join(f"{_ab_bucket_label(b)}={n:,}" for b, n, *_ in _arms)
        out_table = f"Google={n_google:,} · Outros={n_outros:,}"
        header += f"\n_n Meta na tabela: {in_table}  ·  fora da tabela: {out_table}_"
    rows = [header]
    col_header = f"{'Característica':<32} {'Top%':>5}  " + '  '.join(
        f"{_ab_bucket_label(b) + '(Δ)':>{_AW}}" for b, *_ in _arms
    )
    rows.append(f"`{col_header}`")

    def cell(pct, delta, quality, is_winner):
        if pct is None or delta is None:
            return f"{'—':>{_AW}}"
        mark = ' ✅' if is_winner else ''
        return f"{_quality_emoji(quality)} {pct:>5.1f}%({delta:+.1f}){mark}"

    def _pick_winner_direction(direction, ch_delta, cl_delta):
        """Braço mais alinhado à direção da categoria (só vale com 2 comparáveis).
        positive: maior Δpp vence; negative: Δpp mais negativo vence; neutro: sem winner.
        """
        if direction not in ('positive', 'very_positive', 'negative', 'very_negative'):
            return None
        if ch_delta is None or cl_delta is None:
            return None
        sign = 1 if direction in ('positive', 'very_positive') else -1
        if ch_delta * sign == cl_delta * sign:
            return None
        return 'champion' if ch_delta * sign > cl_delta * sign else 'challenger'

    for it in top:
        label = _short(f"{it['feature_label']}: {_humanize_category(it['category'])}", 32)
        ref = it.get('reference_pct', 0)
        winner = (_pick_winner_direction(it.get('direction'),
                                         it.get('champion_delta_pp'),
                                         it.get('challenger_delta_pp'))
                  if _n_compete >= 2 else None)
        parts = [f"{label:<32} {ref:>4.1f}%"]
        for b, _n, compete, pk, dk, qk in _arms:
            is_winner = compete and winner == b.lower()
            parts.append(f"{cell(it.get(pk), it.get(dk), it.get(qk), is_winner):>{_AW}}")
        rows.append('`' + '  '.join(parts) + '`')
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(rows)}})


def _slack_alert_audience_by_source(a: dict, B: list):
    """Drift por fonte de tráfego (Meta vs Google) com 🟢 bom · 🔴 ruim · ⚪ neutro.

    Mesmo display do `_slack_alert_audience_by_variant`, trocando Champion/
    Challenger por Meta/Google. Não depende de ABTestConfig (split é pelo
    `utm_source` direto). Renderiza header com n_meta/n_google e tabela com
    Top% (referência) + Meta(Δ) + Google(Δ).
    """
    d = a.get('details', {}) or {}
    window = d.get('window') or ''
    top = d.get('top_list', []) or []
    n_meta = d.get('meta_n', 0) or 0
    n_ggl  = d.get('google_n', 0) or 0

    window_title = 'Ontem' if window == 'previous_day' else (
        'Lançamento Atual' if window == 'current_launch' else (d.get('window_label') or 'janela')
    )
    header = (f"*📉 Drift por Fonte - {window_title}*  "
              f"·  Meta `n={n_meta:,}`  ·  Google `n={n_ggl:,}`")
    rows = [header]
    col_header = f"{'Característica':<32} {'Top%':>5}  {'Meta(Δ)':>20}  {'Google(Δ)':>20}"
    rows.append(f"`{col_header}`")

    def cell_qual(pct, delta, quality):
        if pct is None or delta is None: return f"{'—':>20}"
        return f"{_quality_emoji(quality)} {pct:>5.1f}%({delta:+.1f})    "

    for it in top:
        label = _short(f"{it['feature_label']}: {_humanize_category(it['category'])}", 32)
        ref = it.get('reference_pct', 0)
        meta_cell = cell_qual(it.get('meta_pct'), it.get('meta_delta_pp'),
                              it.get('meta_quality'))
        ggl_cell  = cell_qual(it.get('google_pct'), it.get('google_delta_pp'),
                              it.get('google_quality'))
        rows.append(f"`{label:<32} {ref:>4.1f}%  {meta_cell:>20}  {ggl_cell:>20}`")
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(rows)}})


def _slack_audience_drift_by_source_dm(v: dict, B: list):
    """Tabelas de drift de público por fonte (Meta × Google) no DM.

    Mesmo conteúdo que `render_slack_blocks_client` mostra
    (`audience_profile_drift_by_source`). Skipa silenciosamente se não houver
    alertas (ex.: top_list vazio ou snapshot ausente).

    Diferente de `_slack_audience_drift_by_variant_dm`, NÃO gate em
    `_ab_test_active` — drift por fonte é independente do A/B.
    """
    alerts = v.get('alerts') or []
    by_source = [a for a in alerts if a.get('type') == 'audience_profile_drift_by_source']
    if not by_source:
        return

    _slack_drift_legend_header(B)
    by_source.sort(
        key=lambda a: 0 if (a.get('details', {}) or {}).get('window') == 'previous_day' else 1
    )
    for a in by_source:
        _slack_alert_audience_by_source(a, B)
        B.append({'type': 'divider'})


def _slack_decis_window(v: dict, B: list, window_key: str):
    """KPI panel da distribuição de decis por janela.

    Substitui a tabela tradicional de 10 linhas × N colunas por um sumário
    compacto: 1 linha por bucket com `n`, `%D9-D10`, `Δpp vs Ref` (com emoji)
    e `avg decil`. Decisão de design (2026-05-28) baseada em data-viz
    research: 80+ células de detalhe diluíam o sinal; %D9-D10 é a métrica
    que move decisão de tráfego.

    Dois grupos no painel:
      - Por fonte: Total, Meta, Google
      - Por optimization_goal Meta: Lead, Champion, Challenger
        (excludentes — soma ≈ Total)

    Quem precisa da forma da curva por decil acessa via endpoint daily-check
    direto. Aqui o canal de cliente recebe só o sinal que dispara ação.

    Direction-aware: %D9-D10 alto = bom (D10 direction=positive). Δpp > +2 =
    🟢, Δpp < -2 = 🔴, |Δpp| ≤ 2 = ⚪. Mesma escala pro avg decil em torno do
    ref calculado a partir da baseline ponderada.
    """
    lq = v.get('lead_quality') or {}
    key = f'decil_distribution_{window_key}'
    info = lq.get(key) or {}
    if not info:
        return
    dist = info.get('distribution') or {}
    total = info.get('total', 0) or 0
    win_label = info.get('window_label', '?')
    if total == 0:
        return

    baseline = info.get('baseline') or {}
    base_pct = baseline.get('pct') or {}
    base_label = baseline.get('label', '')

    # Baselines puras por variante — usadas pra comparar buckets isolados
    # contra a régua correta. Bug corrigido 2026-05-29: antes todos os
    # buckets (Lead/Champion/Challenger) eram comparados contra a baseline
    # ponderada (~57% D9-D10 dominada pelo Champion model). O bucket
    # Challenger (~28% D9-D10 na régua dele) aparecia falsamente como -31pp.
    baseline_champion   = info.get('baseline_champion') or {}
    baseline_challenger = info.get('baseline_challenger') or {}

    keys = [f'D{i:02d}' for i in range(1, 11)]

    def _kpis(distribution: dict, n: int) -> dict | None:
        """Computa n, %D9-D10, avg_decil pra um bucket. None se vazio."""
        if n <= 0:
            return None
        n_d9_d10 = int(distribution.get('D09', 0) or 0) + int(distribution.get('D10', 0) or 0)
        pct_d9_d10 = n_d9_d10 / n * 100
        avg_decil = sum(
            int(k[1:]) * int(distribution.get(k, 0) or 0) for k in keys
        ) / n
        return {'n': n, 'pct_d9_d10': pct_d9_d10, 'avg_decil': avg_decil}

    def _ref_from_pct(pct: dict) -> dict | None:
        """{D01..D10: pct} → {'pct_d9_d10': X, 'avg': Y} ou None se vazio."""
        if not pct:
            return None
        return {
            'pct_d9_d10': float(pct.get('D09', 0) or 0) + float(pct.get('D10', 0) or 0),
            'avg':        sum(int(k[1:]) * float(pct.get(k, 0) or 0) for k in keys) / 100.0,
        }

    # Referências disponíveis pra cada tipo de bucket.
    ref_weighted   = _ref_from_pct(base_pct)
    ref_champion   = _ref_from_pct(baseline_champion.get('pct') or {})
    ref_challenger = _ref_from_pct(baseline_challenger.get('pct') or {})

    def _emoji_d9d10(delta_pp: float | None) -> str:
        """Δpp em %D9-D10: positivo = bom (D10 direction=positive). |Δ|≤2 = neutro."""
        if delta_pp is None:
            return '⚪'
        if delta_pp > 2: return '🟢'
        if delta_pp < -2: return '🔴'
        return '⚪'

    def _emoji_avg(delta_avg: float | None) -> str:
        """Δ no avg decil: mais alto = bom. Limiar 0.3 (≈ 3pp num decil)."""
        if delta_avg is None:
            return '⚪'
        if delta_avg > 0.3: return '🟢'
        if delta_avg < -0.3: return '🔴'
        return '⚪'

    # Buckets por fonte
    by_src = info.get('by_source') or {}
    meta_info = by_src.get('meta') or {}
    ggl_info  = by_src.get('google') or {}
    n_meta = int(meta_info.get('total', 0) or 0)
    n_ggl  = int(ggl_info.get('total', 0) or 0)

    # Buckets por optimization_goal
    by_og = info.get('by_optgoal') or {}
    og_lead_info = by_og.get('lead') or {}
    og_chmp_info = by_og.get('champion') or {}
    og_chal_info = by_og.get('challenger') or {}
    n_og_lead = int(og_lead_info.get('total', 0) or 0)
    n_og_chmp = int(og_chmp_info.get('total', 0) or 0)
    n_og_chal = int(og_chal_info.get('total', 0) or 0)
    show_og = (n_og_lead + n_og_chmp + n_og_chal) > 0

    title = f'*📊 Decis — {win_label}*'
    if base_label:
        title += f' vs *{base_label}*'
    rows = [title]
    # Score geral do lançamento — nota única da população (decil médio pela régua
    # do Challenger, scores_historicos). Só aparece na janela que tem o campo
    # (current_launch). É a população INTEIRA (todas as fontes), não só Meta.
    _sg = info.get('score_geral') or {}
    if _sg.get('decil_medio') is not None:
        rows.append(
            f"🎯 *Score geral ({_ab_bucket_label(_sg.get('modelo', 'Challenger'))}): "
            f"{_sg['decil_medio']:.1f}/10*  ·  {_sg.get('pct_d9_d10', 0):.0f}% em D9-D10"
            f"  ·  n={_sg.get('n', 0):,} ({_sg.get('populacao', 'todas as fontes')})"
        )
    # 3 réguas declaradas. Total/Meta usam Ponderada (peso A/B × ref). Lead/
    # Champion/Google usam Champion. Challenger usa Challenger. Cada linha
    # mostra inline qual régua usa pra evitar ambiguidade.
    rows.append('_🟢 bom · 🔴 ruim · ⚪ neutro/incerto_')
    ref_parts = []
    if ref_champion is not None:
        ref_parts.append(f'{_ab_bucket_label("Champion")}={ref_champion["pct_d9_d10"]:.1f}%/{ref_champion["avg"]:.1f}')
    if ref_challenger is not None:
        ref_parts.append(f'{_ab_bucket_label("Challenger")}={ref_challenger["pct_d9_d10"]:.1f}%/{ref_challenger["avg"]:.1f}')
    if ref_weighted is not None:
        ref_parts.append(f'Ponderada={ref_weighted["pct_d9_d10"]:.1f}%/{ref_weighted["avg"]:.1f}')
    if ref_parts:
        rows.append('_Refs %D9-D10/avg: ' + ' · '.join(ref_parts) + '_')
    rows.append('```')
    rows.append(
        f'{"Bucket":<18}  {"n":>5}   {"%D9-D10":>7}  {"Δ vs ref":>20}      {"Avg":>4}'
    )

    def _row(label: str, kpis: dict | None, ref: dict | None, ref_name: str = '') -> str:
        if kpis is None:
            return f'{label:<18}  {"—":>5}   {"—":>7}  {"—":>20}      {"—":>4}'
        pct = kpis['pct_d9_d10']
        avg = kpis['avg_decil']
        if ref is not None:
            d_pct = pct - ref['pct_d9_d10']
            e_pct = _emoji_d9d10(d_pct)
            delta_str = f'{e_pct} {d_pct:>+5.1f} ({ref_name} {ref["pct_d9_d10"]:.1f}%)'
            d_avg = avg - ref['avg']
            e_avg = _emoji_avg(d_avg)
            avg_str = f'{avg:>4.1f} {e_avg}'
        else:
            delta_str = ''
            avg_str = f'{avg:>4.1f}'
        return f'{label:<18}  {kpis["n"]:>5,}   {pct:>6.1f}%  {delta_str}      {avg_str}'

    # Bloco por fonte (Slack block 1)
    rows.append(_row('Total',  _kpis(dist, total),                                              ref_weighted,   'Ponderada'))
    rows.append(_row('Meta',   _kpis(meta_info.get('distribution') or {}, n_meta),              ref_weighted,   'Ponderada'))
    rows.append(_row('Google', _kpis(ggl_info.get('distribution') or {}, n_ggl),                ref_champion,   'jan_30'))
    rows.append('```')
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(rows)}})

    # Bloco por optimization_goal (Lead/Champion/Challenger) — a tag vem do NOME
    # da campanha (utm_campaign), lida localmente (campaign_classifier.bucket_from_utm),
    # SEM Meta API. Slack block 2 separado — evita truncamento silencioso quando o
    # bloco fica grande. Lead = campanhas de otimização padrão (sem evento ML);
    # Champion = LEADQUALIFIED; Challenger = LEADHQLB.
    if show_og:
        og_rows = ['```']
        og_rows.append(
            f'{"Bucket":<18}  {"n":>5}   {"%D9-D10":>7}  {"Δ vs ref":>20}      {"Avg":>4}'
        )
        og_rows.append(_row('Lead', _kpis(og_lead_info.get('distribution') or {}, n_og_lead), ref_champion, 'jan_30'))
        # Balde da campanha antiga LEADQUALIFIED (jan_30): só aparece se entregou lead.
        if n_og_chmp > 0:
            og_rows.append(_row(_ab_bucket_label('Champion'), _kpis(og_chmp_info.get('distribution') or {}, n_og_chmp), ref_champion, 'jan_30'))
        og_rows.append(_row(_ab_bucket_label('Challenger'), _kpis(og_chal_info.get('distribution') or {}, n_og_chal), ref_challenger, 'abr_28'))
        og_rows.append('```')
        B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(og_rows)}})


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
            new = ', '.join(_humanize_category(c) for c in (d.get('new_categories', []) or []))
            n = d.get('affected_count', 0); pct = d.get('percentage', 0)
            lines.append(f"    `{_humanize_feature(col)}`: {new}  ·  {n} leads ({pct:.1f}%)")
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


def _slack_unified_funnel(v: dict, B: list):
    """Funil completo numa história só: anúncio (Meta Insights) → captura →
    pipeline (TODAS as fontes, quebra fb/ggl/outr) → tracking FBP/FBC.

    Substitui _slack_funnel + _slack_traffic. Nada é eliminado: a camada
    pipeline conta todas as origens; Google aparece em `ggl` (não tem ad-data
    porque não passa pelo pixel/leads_capi — gap de captura do front)."""
    fm   = v['funnel']
    uf   = fm.get('unified_funnel', {}) or {}
    ufw  = uf.get('window', {}) or {}
    dq   = fm.get('data_quality', {}) or {}
    tr   = (v.get('traffic') or {}).get('dia_anterior', {}) or {}
    roll = dq.get('fbp_fbc_rolling', {}) or {}
    r7, r3, r1 = (roll.get('7d') or {}), (roll.get('3d') or {}), (roll.get('1d') or {})

    pp  = uf.get('pipeline', {}) or {}
    def stg(k): return pp.get(k, {}) or {}
    def brk(s):
        return f"fb {_n(s,'fb'):.0f} · ggl {_n(s,'ggl'):.0f} · outr {_n(s,'outr'):.0f}"

    # Funil de anúncio em DOIS blocos espelhados — Meta e Google — cada um com
    # Spend/Cliques + split por variante (Lead/Champion/Challenger) na mesma
    # forma. CPL real (spend ÷ leads reais) e conversão de LP. Leads reais =
    # TODOS os captados (Client/ledger, não respostas de pesquisa). Meta: CPL
    # com imposto (PIS/COFINS+ISS), LP = leads ÷ landing_page_views. Google:
    # sem imposto, LP = leads ÷ cliques. Colunas "ontem" (dia anterior) e "LF"
    # (acumulado do lançamento; omitida se a coleta não preencheu).
    def _rs(x):
        return (f"R$ {x:.2f}".replace('.', ',')) if x is not None else "R$ —"

    def _variante_rows(pv, pv_lf):
        """Linhas por variante. Um balde só aparece se tiver DADO real: leads
        ontem, OU um CPL de lançamento real (>0). Some o balde fantasma — ex.:
        campanha antiga desligada, 0 lead ontem e sem spend no LF (R$ — / 0,00)."""
        out = []
        for _vk in ('Lead', 'Champion', 'Challenger'):
            _vd = (pv or {}).get(_vk) or {}
            _vl = (pv_lf or {}).get(_vk) or {}
            _vn = _n(_vd, 'leads')
            _lf_cpl = _vl.get('cpl')
            if _vn <= 0 and (_lf_cpl is None or _lf_cpl == 0):
                continue
            _lbl = _ab_bucket_label(_vk)
            _conv = _vd.get('conv_lp')
            _conv_s = (f"{_conv:.1f}%".replace('.', ',')) if _conv is not None else "—"
            if pv_lf:
                out.append(f"{_lbl:<18}{_vn:>6,.0f}  CPL ontem {_rs(_vd.get('cpl'))} · LF {_rs(_lf_cpl)} · LP {_conv_s}")
            else:
                out.append(f"{_lbl:<18}{_vn:>6,.0f}   CPL {_rs(_vd.get('cpl'))} · LP {_conv_s}")
        return out

    # ── Meta ── (Meta Insights: spend/cliques + split por variante)
    lines = [
        "── Meta ──",
        f"Spend          R$ {_n(tr,'spend'):>10,.0f}",
        f"Cliques        {_n(tr,'clicks'):>13,.0f}",
    ]
    lines += _variante_rows(tr.get('por_variante') or {},
                            (v.get('traffic') or {}).get('por_variante_lf') or {})

    # ── Google ── (Google Ads API: MESMA forma do Meta — spend/cliques + split
    # por variante). Hoje tudo cai em 'Lead' (nenhuma campanha Google plugada no
    # A/B de modelo); Champion/Challenger aparecem quando o gestor ligar o sinal
    # ML no Google (basta preencher variant_goal_map no YAML).
    _gf = v.get('google_funnel') or {}
    if _gf and (_gf.get('total_spend') or _gf.get('por_campanha') or _gf.get('por_variante')):
        lines += [
            "── Google ──",
            f"Spend          R$ {(_gf.get('total_spend') or 0):>10,.0f}",
            f"Cliques        {(_gf.get('total_clicks') or 0):>13,.0f}",
        ]
        lines += _variante_rows(_gf.get('por_variante') or {}, _gf.get('por_variante_lf') or {})

    lines += [
        f"Pesquisa       {_n(stg('pesquisa'),'total'):>13,.0f}   {brk(stg('pesquisa'))}",
        f"Scoreado       {_n(stg('scoreado'),'total'):>13,.0f}   {brk(stg('scoreado'))}",
        f"CAPI enviado   {_n(stg('capi_enviado'),'total'):>13,.0f}",
        f"Aceito Meta    {_n(stg('aceito'),'total'):>13,.0f}",
    ]
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': (f"*🎬 Funil completo*  ·  _{ufw.get('label','dia anterior')} ({ufw.get('date_brt','?')}) BRT_\n"
                 f"```\n" + "\n".join(lines) + "\n```")}})

    trk = [
        "        7d      3d      1d",
        f"FBP   {_n(r7,'fbp_pct'):>6.1f}% {_n(r3,'fbp_pct'):>6.1f}% {_n(r1,'fbp_pct'):>6.1f}%",
        f"FBC   {_n(r7,'fbc_pct'):>6.1f}% {_n(r3,'fbc_pct'):>6.1f}% {_n(r1,'fbc_pct'):>6.1f}%",
        f"Phone {_n(uf,'phone_pct'):>6.1f}%   (sobre leads no banco)",
    ]
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': (f"*🎯 Tracking FBP/FBC*  ·  _% sobre leads capturados (leads_capi)_\n"
                 f"```\n" + "\n".join(trk) + "\n```")}})
    B.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': (
        "_Meta = Meta Insights · Google = Google Ads API (ambos: spend/cliques + CPL por variante, dia anterior + LF). "
        "Meta: CPL inclui imposto (12,15%), LP = leads÷landing_page_views. Google: sem imposto, LP = leads÷cliques. "
        "Pipeline = todas as fontes · fb = facebook-ads/ig/fb · ggl = google-ads · outr = resto. "
        f"leads_capi na janela: 7d={_n(r7,'n'):.0f} · 3d={_n(r3,'n'):.0f} · 1d={_n(r1,'n'):.0f}_"
    )}]})


def _slack_google_funnel(v: dict, B: list):
    """Funil Google (leitura da Google Ads API) — custo/cliques por campanha,
    CPL agregado (spend ÷ leads google do ledger) e contagem das NOSSAS ações
    de conversão (LeadQualified/LeadQualifiedHighQuality) por campanha.

    No-op se o funil veio ausente: flag `reporting_enabled` off, sem credencial
    GOOGLE_ADS_* em produção, ou o pull falhou (o handler em app.py degrada e
    não anexa `google_funnel`). Custo/cliques são reais; as conversões das
    nossas ações só sobem quando o Google casar o evento (depende do gclid)."""
    g = v.get('google_funnel') or {}
    camps = g.get('por_campanha') or []
    if not camps and not g.get('total_spend'):
        return

    def _rs(x):
        return (f"R$ {x:,.0f}".replace(',', '.')) if x is not None else "R$ —"

    def _cpl(x):
        return (f"R$ {x:.2f}".replace('.', ',')) if x is not None else "R$ —"

    def _conv_str(wv, hq):
        return f"LQ {wv:.0f} · LQHQ {hq:.0f}"

    _clicks = f"{int(g.get('total_clicks') or 0):,}".replace(',', '.')
    lines = [
        f"Spend total     {_rs(g.get('total_spend')):>12}",
        f"Cliques         {_clicks:>12}",
        f"CPL (agregado)  {_cpl(g.get('cpl_agregado')):>12}   ({int(g.get('n_leads') or 0)} leads google)",
        f"Nossas conv     {_conv_str(g.get('total_with_value') or 0, g.get('total_high_quality') or 0)}",
        "── Top campanhas (por spend) ──",
    ]
    for c in camps[:8]:
        nm = (c.get('campaign_name') or '?')[:42]
        _cs = _conv_str(c.get('conv_with_value') or 0, c.get('conv_high_quality') or 0)
        lines.append(f"{nm:<42} {_rs(c.get('spend')):>10} · {_cs}")

    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': (f"*🟦 Funil Google*  ·  _últimos 7 dias · Google Ads API_\n"
                 f"```\n" + "\n".join(lines) + "\n```")}})
    B.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': (
        "_Custo/cliques reais. Conversões das NOSSAS ações (LQ/LQHQ) só sobem quando o Google "
        "casar o evento — depende do gclid no payload. CPL = spend ÷ leads google do ledger (agregado)._"
    )}]})


def _slack_survey_response_rate(v: dict, B: list):
    """Taxa de resposta da pesquisa (cadastro→pesquisa) — SÓ grupo de dados.
    Número do dia anterior em destaque + mini-tendência dos últimos 7 dias.
    Omite o bloco se a métrica veio ausente (degradou no handler)."""
    rr = (v.get('funnel') or {}).get('survey_response_rate')
    if not rr:
        return
    serie = rr.get('serie') or []
    ontem = rr.get('ontem') or {}
    if not serie or not ontem:
        return

    def _taxa(t, dec=1):
        return (f"{t:.{dec}f}".replace('.', ',') + "%") if t is not None else "—"

    def _int_br(n):
        return f"{int(n or 0):,}".replace(',', '.')

    def _dia(iso):
        p = (iso or '').split('-')
        return f"{p[2]}/{p[1]}" if len(p) == 3 else (iso or '?')

    trend = " · ".join(_taxa(p.get('taxa'), 0) for p in serie)
    dias = rr.get('days', len(serie))
    lines = [
        f"Ontem ({_dia(ontem.get('dia'))}):  {_taxa(ontem.get('taxa'))}"
        f"   ({_int_br(ontem.get('n_resp'))} / {_int_br(ontem.get('n_cad'))} cadastros)",
        f"Últimos {dias}d:  {trend}   ·  méd {_taxa(rr.get('media_taxa'))}",
    ]
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': (f"*📋 Taxa de resposta da pesquisa*  ·  _cadastro→pesquisa (todas as fontes)_\n"
                 f"```\n" + "\n".join(lines) + "\n```")}})


def _slack_funnel(v: dict, B: list):
    fm = v['funnel']
    cap = fm.get('capture', {}) or {}
    sc  = fm.get('scoring', {}) or {}
    capi= fm.get('capi_sent', {}) or {}
    meta= fm.get('meta_response', {}) or {}
    dq  = fm.get('data_quality', {}) or {}
    win = fm.get('window', {}) or {}
    conv= fm.get('conversion', {}) or {}

    roll = dq.get('fbp_fbc_rolling', {}) or {}
    r7 = roll.get('7d', {}) or {}
    r3 = roll.get('3d', {}) or {}
    r1 = roll.get('1d', {}) or {}

    rows = [
        f"leads db (pesquisa)    {_n(cap,'total_database'):>7,}",
        f"Scoreados              {_n(sc,'total_scored'):>7,}",
        f"CAPI enviados          {_n(capi,'leads_sent'):>7,}   ({_n(capi,'send_rate'):.1f}%)  ·  {_n(capi,'estimated_events'):.0f} eventos",
        f"Aceitos Meta           {_n(meta,'success_count'):>7,}   (success 100%  ·  partial {_n(meta,'partial_count'):.0f}  ·  error {_n(meta,'error_count'):.0f})",
        f"Phone preenchido       {_n(dq,'phone_percentage'):>6.1f}%   (% sobre leads no banco)",
    ]
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': (f"*📊 Funil*  ·  _{win.get('start_brt','?')} → {win.get('end_brt','?')} BRT_\n"
                 f"```\n" + "\n".join(rows) + "\n```")}})

    track = [
        f"{'':<6}{'7d':>9}{'3d':>9}{'1d':>9}",
        f"{'FBP':<6}{_n(r7,'fbp_pct'):>8.1f}%{_n(r3,'fbp_pct'):>8.1f}%{_n(r1,'fbp_pct'):>8.1f}%",
        f"{'FBC':<6}{_n(r7,'fbc_pct'):>8.1f}%{_n(r3,'fbc_pct'):>8.1f}%{_n(r1,'fbc_pct'):>8.1f}%",
    ]
    B.append({'type': 'section', 'text': {'type': 'mrkdwn',
        'text': (f"*🎯 Tracking FBP/FBC*  ·  _% sobre leads Meta_\n"
                 f"```\n" + "\n".join(track) + "\n```")}})
    B.append({'type': 'context', 'elements': [
        {'type': 'mrkdwn', 'text': (
            f"_leads Meta na janela: 7d={_n(r7,'n'):.0f} · 3d={_n(r3,'n'):.0f} · 1d={_n(r1,'n'):.0f} · "
            "cada coluna = mesma métrica, janelas fixas terminando agora_"
        )}
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
        header = f"             Ontem        {lf_label:>8}     semana       mês          histórico"
        rows = [
            f"score      {g('ultimas_24h','score'):>8.4f}    {g('lf_referencia','score'):>8.4f}    {g('ultima_semana','score'):>8.4f}    {g('ultimo_mes','score'):>8.4f}    {g('historico','score'):>8.4f}",
            f"D9%        {g('ultimas_24h','d9'):>7.2f}%    {g('lf_referencia','d9'):>7.2f}%    {g('ultima_semana','d9'):>7.2f}%    {g('ultimo_mes','d9'):>7.2f}%    {g('historico','d9'):>7.2f}%",
            f"D10%       {g('ultimas_24h','d10'):>7.2f}%    {g('lf_referencia','d10'):>7.2f}%    {g('ultima_semana','d10'):>7.2f}%    {g('ultimo_mes','d10'):>7.2f}%    {g('historico','d10'):>7.2f}%",
            f"n leads    {g('ultimas_24h','count'):>8,}    {g('lf_referencia','count'):>8,}    {g('ultima_semana','count'):>8,}    {g('ultimo_mes','count'):>8,}    {g('historico','count'):>8,}",
        ]
    else:
        header = "             Ontem        semana       mês          histórico"
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
            f"{label:<10}  {_n(c,'vendas_total'):>6.1f}  "
            f"R$ {_n(c,'faturamento'):>13,.0f}  "
            f"R$ {_n(c,'faturamento_recebido'):>15,.0f}"
        )

    header_table = f"{'Cenário':<10}  {'Vendas':>6}  {'Fat. contratado':>16}  {'Recebido 1ª janela':>18}"

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
        f"{_bases_md(_n(inputs,'total_leads_meta'), _scored_n(rf))}  ·  ticket R$ {_n(inputs,'ticket_contracted'):,.0f}\n"
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
            f"{_bases_md(_n(lf_inputs,'total_leads_meta'), _scored_n(lf_ant))}\n"
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
    # CPL lead: meta_leads vem de 'offsite_conversion.fb_pixel_lead' (Insights),
    # equivalente à tabela `leads_capi`, NÃO à pesquisa preenchida (`Lead`).
    table = (
        f"```\n"
        f"              24h            lanç. atual     semana\n"
        f"Spend     R$ {g('ultimas_24h','spend'):>10,.0f}    R$ {g('periodo_query','spend'):>10,.0f}    R$ {g('ultima_semana','spend'):>10,.0f}\n"
        f"Leads     {g('ultimas_24h','meta_leads'):>13,}    {g('periodo_query','meta_leads'):>13,}    {g('ultima_semana','meta_leads'):>13,}\n"
        f"CPL lead  R$ {g('ultimas_24h','cpl'):>10,.2f}    R$ {g('periodo_query','cpl'):>10,.2f}    R$ {g('ultima_semana','cpl'):>10,.2f}\n"
        f"Clique→lead {g('ultimas_24h','ctr_lead'):>11.1f}%    {g('periodo_query','ctr_lead'):>11.1f}%    {g('ultima_semana','ctr_lead'):>11.1f}%\n"
        f"```"
    )
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': f"*📺 Tráfego Meta*\n{table}"}})


def _arm_delivery_counts(v: dict) -> dict:
    """Leads Meta por BRAÇO DE CAMPANHA (tag de optimization_goal no nome da
    campanha: LEADQUALIFIED→champion, LEADHQLB→challenger, resto→lead), lidos do
    alerta de drift por A/B (janela 'ontem').

    Diferente de `leads_scored_by_variant_24h`, que é roteamento de MODELO — onde o
    braço default/catch-all aparece sempre >0 porque engole todo lead sem tag
    (Google/orgânico/Lead). Aqui o número reflete a CAMPANHA realmente no ar. Usado
    pra decidir se um braço está entregando (n>0) e esconder o que não está
    ("o que não está scoreando some").

    Retorna {} se não houver o alerta (ex.: dados insuficientes) — nesse caso o
    chamador NÃO esconde nada (fallback seguro pra não ocultar dado real).
    """
    for a in (v.get('alerts') or []):
        if a.get('type') != 'audience_profile_drift_by_variant':
            continue
        d = a.get('details') or {}
        if d.get('window') == 'previous_day':
            return {
                'champion':   int(d.get('champion_n', 0) or 0),
                'challenger': int(d.get('challenger_n', 0) or 0),
                'lead':       int(d.get('lead_n', 0) or 0),
            }
    return {}


def _slack_ab(v: dict, B: list):
    op = v['ab_test']
    enabled = bool(op.get('ab_test_enabled', False))
    if not enabled:
        B.append({'type': 'section', 'text': {'type': 'mrkdwn',
            'text': '*🤖 A/B Test* — DESATIVADO'}})
        return
    by = op.get('leads_scored_by_variant_24h') or {}
    variants = op.get('ab_variants') or []

    # Quais braços estão REALMENTE entregando campanha. O leads_scored_by_variant
    # (roteamento de modelo) não serve: o braço default/catch-all aparece sempre >0
    # porque engole Google/orgânico/Lead. A verdade vem da contagem por tag de
    # campanha (_arm_delivery_counts). Mapa: variante com padrão de UTM
    # (routing_active) ↔ braço 'challenger'; default (sem padrão) ↔ braço 'champion'.
    counts = _arm_delivery_counts(v)
    def _arm(vv): return 'challenger' if vv.get('routing_active') else 'champion'
    delivering = [vv for vv in variants if counts.get(_arm(vv), 0) > 0] if counts else list(variants)

    # Investimento Meta por evento de otimização (ML vs Lead padrão). Independe de
    # quantos braços estão no ar — separado pra não confundir spend de campanha com
    # spend sob otimização do modelo (a maior parte está em adsets de evento Lead).
    def _invest_lines():
        ml = op.get('spend_ml_24h_brl')
        nonml = op.get('spend_nonml_24h_brl')
        out: list[str] = []
        if ml is not None and nonml is not None:
            total_meta = (ml or 0) + (nonml or 0)
            if total_meta > 0:
                out.append('')
                out.append(f"*Investimento Meta em captação (ontem):* R$ {_fmt_brl(total_meta)}")
                out.append(f"  • R$ {_fmt_brl(ml)} ({ml/total_meta*100:.0f}%) em adsets otimizando pelo *evento ML*")
                out.append(f"  • R$ {_fmt_brl(nonml)} ({nonml/total_meta*100:.0f}%) em adsets otimizando pelo *evento Lead padrão*")
        return out

    # Caso comparativo: 2+ braços com campanha no ar (teste de verdade rodando) OU
    # sem dado de campanha (fallback). Mantém o formato Champion × Challenger com %.
    if not counts or len(delivering) >= 2:
        by_spend = op.get('spend_by_variant_24h_brl') or {}
        if _ab_test_active(v):
            header = '*🤖 A/B Test* — ATIVO'
        else:
            sem = [_variant_label(vv.get('name', '?')) for vv in variants
                   if (by_spend.get(vv.get('name')) or 0) <= 0 or (by.get(vv.get('name')) or 0) <= 0]
            header = (f'*🤖 A/B Test* — ATIVO no back-end, *sem tráfego no {", ".join(sem)}*'
                      if sem else '*🤖 A/B Test* — ATIVO no back-end, *sem tráfego efetivo*')
        total = sum((by.get(vv.get('name')) or 0) for vv in delivering) or sum((n or 0) for n in by.values())
        lines = [header]
        for vv in delivering:
            label = _variant_label(vv.get('name', '?'))
            scored = by.get(vv.get('name')) or 0
            pct = (scored / total * 100) if total else 0
            lines.append(f"• *{label}* scoreou {scored:,} de {total:,} eventos ({pct:.1f}%) ontem")
        lines += _invest_lines()
        B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': "\n".join(lines)}})
        return

    # Caso braço único: não há comparação. O braço vivo é o modelo de produção
    # (decisão 23/06: a campanha LEADHQLB / abr_28 venceu e virou o Champion). Sem
    # "% de N" — não há contra o quê comparar. O braço sem campanha some (o default
    # jan_30 ainda scoreia leads sem tag, mas eles aparecem nas tabelas sob
    # Lead/Google/Outros, não como um braço Champion aqui).
    if delivering:
        vv = delivering[0]
        label = _variant_label(vv.get('name', '?'))
        scored = by.get(vv.get('name')) or 0
        lines = [
            '*🤖 Teste A/B — sem comparação ativa*',
            f"*{label}* é o modelo em produção · scoreou {scored:,} leads ontem",
            '_Sem Challenger rodando no momento._',
        ]
    else:
        lines = ['*🤖 Teste A/B* — sem tráfego efetivo nas campanhas A/B']
    lines += _invest_lines()
    B.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': "\n".join(lines)}})


def _ab_test_active(v: dict) -> bool:
    """True se o A/B Test está **efetivamente** rodando — não basta a flag
    `ab_test_enabled` (= configurado no back-end). Exige também:
      - Cada variant declarada em `ab_variants` ter spend > 0 nas últimas 24h.
      - Cada variant ter pelo menos 1 lead escoreado nas últimas 24h.

    Sem isso, ainda que o back-end aceite o roteamento, as tabelas comparativas
    Champion × Challenger ficariam com uma coluna vazia (—) — informação
    enganosa de que existe comparação quando na prática não há.

    Usada por _slack_audience_drift_by_variant_dm, render_slack_blocks_client
    e _slack_ab pra decidir suprimir tabelas e/ou ajustar o header do bloco.
    """
    op = v.get('ab_test') or {}
    if not op.get('ab_test_enabled', False):
        return False
    variants = op.get('ab_variants') or []
    if not variants:
        return False
    by_spend = op.get('spend_by_variant_24h_brl') or {}
    by_scored = op.get('leads_scored_by_variant_24h') or {}
    for vv in variants:
        name = vv.get('name')
        if not name:
            return False
        if (by_spend.get(name) or 0) <= 0:
            return False
        if (by_scored.get(name) or 0) <= 0:
            return False
    return True


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


def _slack_launch_fallback_notice_dm(v: dict, B: list):
    """Avisa no DM quando a janela do LF atual veio do fallback de terça BRT
    (`launches.yaml` desatualizado). No-op caso contrário.

    Renderizado SÓ no DM — vide chamada em `render_slack_blocks`. O digest
    do cliente (`render_slack_blocks_client`) não inclui esse aviso.
    """
    lr = v.get('launch_resolution') or {}
    if lr.get('source') != 'monday_heuristic':
        return
    lf_name  = lr.get('lf_name')   # pode ser None se nada foi inferido
    inferred = bool(lr.get('inferred'))
    label    = lr.get('label') or ''
    cap_start = lr.get('cap_start') or '?'

    if lf_name and inferred:
        msg = (
            f"⚠️ *Lançamento atual sem cadastro* — o sistema não encontrou o LF atual "
            f"no arquivo de lançamentos (`configs/launches.yaml`) e está usando "
            f"inferência (toda segunda começa um LF; captação detectada em {cap_start}). "
            f"Nome provável: *{lf_name}*. As tabelas e séries usam essa janela inferida "
            f"até o LF ser cadastrado."
        )
    else:
        msg = (
            f"⚠️ *Lançamento atual sem cadastro* — o sistema não encontrou o LF atual "
            f"no arquivo de lançamentos (`configs/launches.yaml`); janela inferida "
            f"a partir de {cap_start}. Tabelas e séries usam essa janela até o LF "
            f"ser cadastrado."
        )
    B.append({'type': 'context', 'elements': [{'type': 'mrkdwn', 'text': msg}]})
