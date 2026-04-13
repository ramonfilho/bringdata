"""
Relatório: CPL e ROAS por Grupo de Decil — DevClub (DEV19–LF48)

Para cada grupo de decil calcula, por lançamento e em pool:
  - Leads (scored)   : volume no período com decil atribuído (Sheets/Railway)
  - % Leads          : proporção do grupo em relação ao total scored
  - TC benchmark (%) : taxa de conversão observada em produção (3-tier, n=7 lançamentos)
  - Ret/Lead (R$)    : TC_bench × ticket  — receita esperada por lead do grupo
  - CPL (R$)         : gasto_ml / leads_ml — custo por lead (uniforme entre decis)
  - CAC (R$)         : CPL / TC_bench      — custo para adquirir 1 comprador
  - ROAS             : Ret/Lead / CPL      — retorno por R$1 investido

Por que não usar cruzamento de emails?
  O match email-comprador (Guru/Hotmart) × email-pesquisa tem cobertura <20%
  e gera counts de buyers por decil estatisticamente ruidosos (~0–3 por decil
  em lançamentos com 15 000+ leads). As taxas benchmark são derivadas de
  observação direta em produção ao longo de DEV19–LF48, com p=0.002 e lift 3.7×
  entre D1-D5 e D10 — mais confiáveis que o match esparso de emails.

  Para ver a TC por decil via email matching, use ml_evolution_report.py.

Rodar:
  python scripts/relatorio_cpl_retorno_decil.py
"""

import sys
import statistics
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import yaml

from ml_evolution_report import (
    load_sheets_data,
    load_railway,
    parse_xlsx_report,
    find_xlsx_for_period,
)

# ---------------------------------------------------------------------------
# Parâmetros
# ---------------------------------------------------------------------------
TICKET        = 2_200.0   # R$ por venda
TRACKING_RATE = 0.528     # mediana histórica matched/total (LF42–LF47)

# Taxas de conversão benchmark — observadas em produção DEV19–LF48 (n=7)
# Fonte: backtest_revenue_forecast_benchmark.py + análise assertividade decil
BENCHMARK_TC = {
    'D1_D5': 0.0029,   # 0.29% — p=0.002 vs D10
    'D6_D9': 0.0070,   # 0.70%
    'D10':   0.0107,   # 1.07% — lift 3.7× vs D1-D5
}

INCLUDE = ['DEV19', 'LF43', 'LF44', 'LF45', 'LF46', 'LF47', 'LF48']

BASE           = Path(__file__).parent.parent
VALIDATION_DIR = BASE / 'outputs/validation'

# Períodos lidos de configs/launches.yaml — fonte canônica das datas
_LAUNCHES_YAML = BASE / 'configs/launches.yaml'
with open(_LAUNCHES_YAML) as _f:
    _LAUNCHES = yaml.safe_load(_f)

PERIODS = {
    n: (_LAUNCHES[n]['cap_start'], _LAUNCHES[n]['cap_end'])
    for n in INCLUDE if n in _LAUNCHES
}
XLSX_PATHS = {
    n: find_xlsx_for_period(_LAUNCHES[n]['vendas_start'], _LAUNCHES[n]['vendas_end'])
    for n in INCLUDE if n in _LAUNCHES
}

# Faixas canônicas
TIER_D15  = [f'D{i}' for i in range(1, 6)]
TIER_D69  = [f'D{i}' for i in range(6, 10)]
TIER_D10  = ['D10']
ALL_DECIS = [f'D{i}' for i in range(1, 11)]

TIER_KEY  = {d: 'D1_D5' for d in TIER_D15}
TIER_KEY.update({d: 'D6_D9' for d in TIER_D69})
TIER_KEY.update({d: 'D10' for d in TIER_D10})


# ---------------------------------------------------------------------------
# Normalização de decil
# ---------------------------------------------------------------------------

def _normalize_decil(v) -> str | None:
    if pd.isna(v):
        return None
    s = str(v).strip().upper()
    if s.startswith('D') and s[1:].isdigit():
        return f'D{int(s[1:])}'
    if s.isdigit():
        return f'D{int(s)}'
    return None


# ---------------------------------------------------------------------------
# Distribuição de leads por decil (Sheets + Railway)
# ---------------------------------------------------------------------------

def decil_distribution(sheets_df: pd.DataFrame, rail_df: pd.DataFrame,
                        cap_start: str, cap_end: str) -> dict:
    """
    Retorna {decil: n_leads} para o período de captação.
    Combina Sheets e Railway, deduplicando por email.
    """
    start = pd.Timestamp(cap_start)
    end   = pd.Timestamp(cap_end) + pd.Timedelta(days=1)

    frames = []

    if not sheets_df.empty:
        mask = (sheets_df['data'] >= start) & (sheets_df['data'] < end)
        sub  = sheets_df[mask][['email', 'decil']].copy()
        sub['decil_norm'] = sub['decil'].apply(_normalize_decil)
        frames.append(sub[['email', 'decil_norm']])

    if not rail_df.empty:
        mask = (rail_df['created_at'] >= start) & (rail_df['created_at'] < end)
        sub  = rail_df[mask][['email', 'decil']].copy()
        sub['decil_norm'] = sub['decil'].apply(_normalize_decil)
        if frames:
            # Railway complementa — não substitui emails já vistos em Sheets
            known_emails = frames[0]['email']
            sub = sub[~sub['email'].isin(known_emails)]
        frames.append(sub[['email', 'decil_norm']])

    if not frames:
        return {}

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates('email', keep='last')
    scored   = combined[combined['decil_norm'].notna()]

    return scored['decil_norm'].value_counts().to_dict()


# ---------------------------------------------------------------------------
# Carregamento por lançamento
# ---------------------------------------------------------------------------

def load_data(sheets_df, rail_df):
    data = {}
    for name in INCLUDE:
        xlsx_path = XLSX_PATHS.get(name)
        if xlsx_path is None or not xlsx_path.exists():
            print(f"  {name}: xlsx não encontrado — pulando")
            continue

        fin = parse_xlsx_report(xlsx_path)
        gasto_ml = fin.get('gasto_ml')
        leads_ml = fin.get('leads_ml')
        if not gasto_ml or not leads_ml:
            print(f"  {name}: dados financeiros ausentes — pulando")
            continue

        cap_start, cap_end = PERIODS[name]
        dist = decil_distribution(sheets_df, rail_df, cap_start, cap_end)
        total_scored = sum(dist.values())

        cpl          = gasto_ml / leads_ml
        vendas_total = fin.get('vendas_total')
        conv_real    = fin.get('conv_real')   # % conversão real do xlsx
        roas_ml      = fin.get('roas_ml')

        # TC real do xlsx (se disponível)
        tc_real_xlsx = None
        if vendas_total and leads_ml:
            tc_real_xlsx = vendas_total / leads_ml * 100

        data[name] = {
            'gasto_ml':      gasto_ml,
            'leads_ml':      leads_ml,
            'cpl':           cpl,
            'dist':          dist,        # {D1..D10: count} — scored leads
            'total_scored':  total_scored,
            'vendas_total':  vendas_total,
            'tc_real_xlsx':  tc_real_xlsx,
            'conv_real':     conv_real,
            'roas_ml':       roas_ml,
        }

        cov = f'{total_scored/leads_ml*100:.0f}%' if leads_ml else '?'
        print(f"  {name}: gasto=R${gasto_ml:,.0f} | leads_ml={leads_ml:,} | "
              f"CPL=R${cpl:.2f} | scored={total_scored:,} ({cov}) | "
              f"vendas={vendas_total or '?'}")
    return data


# ---------------------------------------------------------------------------
# Cálculo por faixa (benchmark-based)
# ---------------------------------------------------------------------------

def tier_metrics(tier_key: str, leads_tier: int, total_scored: int,
                 leads_ml: int, cpl: float) -> dict:
    """
    Calcula métricas para uma faixa usando TC benchmark.

    leads_tier    : leads com score nessa faixa (Sheets/Railway)
    total_scored  : total de leads com score no lançamento
    leads_ml      : total de leads ML (denominador do CPL)
    cpl           : gasto_ml / leads_ml
    """
    tc_bench = BENCHMARK_TC[tier_key]
    pct_leads = leads_tier / total_scored * 100 if total_scored > 0 else 0.0
    ret_lead  = tc_bench * TICKET
    cac       = cpl / tc_bench if tc_bench > 0 else None
    roas      = ret_lead / cpl if cpl > 0 else None
    # Estimativa de compradores para essa faixa (para o total do lançamento)
    # = leads_ml × (leads_tier/total_scored) × tc_bench
    buyers_est = leads_ml * (leads_tier / total_scored) * tc_bench if total_scored > 0 else 0
    return {
        'leads_scored': leads_tier,
        'pct_leads':    pct_leads,
        'tc_bench_pct': tc_bench * 100,
        'ret_lead':     ret_lead,
        'cpl':          cpl,
        'cac':          cac,
        'roas':         roas,
        'buyers_est':   buyers_est,
    }


def aggregate_tiers(data: dict, tier_key: str, tier_decis: list) -> dict:
    """Agrega múltiplos lançamentos para uma faixa."""
    total_leads_scored = 0
    total_leads_ml     = 0
    total_gasto        = 0
    total_buyers_est   = 0

    for rec in data.values():
        dist = rec['dist']
        leads_tier = sum(dist.get(d, 0) for d in tier_decis)
        total_leads_scored += leads_tier
        total_leads_ml     += rec['leads_ml']
        total_gasto        += rec['gasto_ml']
        if rec['total_scored'] > 0:
            total_buyers_est += (
                rec['leads_ml']
                * (leads_tier / rec['total_scored'])
                * BENCHMARK_TC[tier_key]
            )

    if total_leads_ml == 0:
        return {}

    cpl_pool  = total_gasto / total_leads_ml
    tc_bench  = BENCHMARK_TC[tier_key]
    ret_lead  = tc_bench * TICKET
    cac       = cpl_pool / tc_bench if tc_bench > 0 else None
    roas      = ret_lead / cpl_pool if cpl_pool > 0 else None

    # pct_leads via pool de scored
    total_scored_all = sum(rec['total_scored'] for rec in data.values())
    pct_leads = total_leads_scored / total_scored_all * 100 if total_scored_all > 0 else 0.0

    return {
        'leads_scored': total_leads_scored,
        'pct_leads':    pct_leads,
        'tc_bench_pct': tc_bench * 100,
        'ret_lead':     ret_lead,
        'cpl':          cpl_pool,
        'cac':          cac,
        'roas':         roas,
        'buyers_est':   total_buyers_est,
    }


# ---------------------------------------------------------------------------
# Impressão
# ---------------------------------------------------------------------------

W = 96

def _brl(v):
    if v is None: return '      n/d'
    return f'R${v:>8,.2f}'

def _roas(v):
    if v is None: return '  n/d'
    return f'{v:>5.2f}x'

def _flag(roas):
    if roas is None: return ''
    if roas >= 8:    return ' ★'
    if roas >= 3:    return ' ✓'
    if roas < 1:     return ' ✗'
    return ''

def print_header():
    print(f"  {'Faixa':<7} {'Leads':>7} {'%Leads':>7} {'TC bench':>9} {'Ret/Lead':>11} "
          f"{'CPL':>11} {'CAC':>11} {'ROAS':>7}  {'Comprad.est':>11}")
    print(f"  {'-'*7} {'-'*7} {'-'*7} {'-'*9} {'-'*11} {'-'*11} {'-'*11} {'-'*7}  {'-'*11}")

def print_row(label: str, m: dict):
    if not m:
        print(f"  {label:<7}   —")
        return
    buyers_str = f'{m["buyers_est"]:>10.1f}' if m.get('buyers_est') is not None else '         —'
    print(
        f"  {label:<7} {m['leads_scored']:>7,} {m['pct_leads']:>6.1f}% "
        f"{m['tc_bench_pct']:>8.3f}% "
        f"{_brl(m['ret_lead'])} "
        f"{_brl(m['cpl'])} "
        f"{_brl(m['cac'])} "
        f"{_roas(m['roas'])}{_flag(m['roas'])}  "
        f"{buyers_str}"
    )

def print_divider(char='-'):
    print(f"  {char * (W - 2)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print("Carregando dados (Sheets + Railway)...")
    sheets_df = load_sheets_data()
    rail_df   = load_railway()

    print("\nCarregando métricas por lançamento...")
    data = load_data(sheets_df, rail_df)

    if not data:
        print("Nenhum dado carregado.")
        return

    names   = [n for n in INCLUDE if n in data]
    cpls    = [data[n]['cpl'] for n in names]
    cpl_med = statistics.median(cpls)

    # ── Por lançamento ───────────────────────────────────────────────────────
    for name in names:
        rec = data[name]
        cpl = rec['cpl']
        dist = rec['dist']
        ts  = rec['total_scored']
        lml = rec['leads_ml']
        cov = f'{ts/lml*100:.0f}%' if lml else '?'

        tc_actual_str = (f'{rec["tc_real_xlsx"]:.3f}%'
                         if rec['tc_real_xlsx'] is not None else 'n/d')
        roas_actual_str = (f'{rec["roas_ml"]:.2f}x'
                           if rec.get('roas_ml') is not None else 'n/d')

        print(f'\n{"="*W}')
        print(f'  {name}')
        print(f'  Gasto ML: R${rec["gasto_ml"]:,.0f}  |  Leads ML: {lml:,}  |  CPL: R${cpl:.2f}')
        print(f'  Scored: {ts:,} ({cov} dos leads ML)  |  TC real xlsx: {tc_actual_str}  |  ROAS real: {roas_actual_str}')
        print(f'{"="*W}')
        print_header()

        # Faixas
        for tier_key, tier_decis, label in [
            ('D1_D5', TIER_D15, 'D1–D5'),
            ('D6_D9', TIER_D69, 'D6–D9'),
            ('D10',   TIER_D10, 'D10'),
        ]:
            leads_tier = sum(dist.get(d, 0) for d in tier_decis)
            if leads_tier == 0:
                print(f"  {label:<7}   — (sem cobertura de score)")
                continue
            m = tier_metrics(tier_key, leads_tier, ts, lml, cpl)
            print_row(label, m)

        # Total do lançamento (TC media ponderada pelos leads de cada faixa)
        print_divider()
        leads_d15 = sum(dist.get(d, 0) for d in TIER_D15)
        leads_d69 = sum(dist.get(d, 0) for d in TIER_D69)
        leads_d10 = sum(dist.get(d, 0) for d in TIER_D10)
        if ts > 0:
            tc_wavg = (
                leads_d15 / ts * BENCHMARK_TC['D1_D5'] +
                leads_d69 / ts * BENCHMARK_TC['D6_D9'] +
                leads_d10 / ts * BENCHMARK_TC['D10']
            )
            ret_lead_wavg = tc_wavg * TICKET
            cac_wavg      = cpl / tc_wavg if tc_wavg > 0 else None
            roas_wavg     = ret_lead_wavg / cpl if cpl > 0 else None
            buyers_est    = lml * tc_wavg
            m_total = {
                'leads_scored': ts,
                'pct_leads':    100.0,
                'tc_bench_pct': tc_wavg * 100,
                'ret_lead':     ret_lead_wavg,
                'cpl':          cpl,
                'cac':          cac_wavg,
                'roas':         roas_wavg,
                'buyers_est':   buyers_est,
            }
            print_row('TOTAL', m_total)

    # ── Pooled: todos os lançamentos ─────────────────────────────────────────
    print(f'\n{"="*W}')
    print(f'  POOLED — {", ".join(names)}')
    gasto_total = sum(data[n]['gasto_ml'] for n in names)
    leads_total = sum(data[n]['leads_ml'] for n in names)
    cpl_pool    = gasto_total / leads_total
    vendas_pool = sum(data[n]['vendas_total'] for n in names
                      if data[n].get('vendas_total') is not None)
    tc_pool_actual = vendas_pool / leads_total * 100 if leads_total and vendas_pool else None
    tc_pool_str = f'{tc_pool_actual:.3f}%' if tc_pool_actual else 'n/d'

    print(f'  Gasto total: R${gasto_total:,.0f}  |  Leads total: {leads_total:,}  |  CPL médio: R${cpl_pool:.2f}')
    print(f'  TC real (pool): {tc_pool_str}  |  Ticket: R${TICKET:,.0f}')
    print(f'{"="*W}')
    print_header()

    for tier_key, tier_decis, label in [
        ('D1_D5', TIER_D15, 'D1–D5'),
        ('D6_D9', TIER_D69, 'D6–D9'),
        ('D10',   TIER_D10, 'D10'),
    ]:
        m = aggregate_tiers(data, tier_key, tier_decis)
        m['cpl'] = cpl_pool
        m['cac'] = cpl_pool / BENCHMARK_TC[tier_key] if BENCHMARK_TC[tier_key] > 0 else None
        m['roas'] = (BENCHMARK_TC[tier_key] * TICKET) / cpl_pool
        print_row(label, m)

    # Total pool
    print_divider()
    scored_all = sum(rec['total_scored'] for rec in data.values())
    leads_d15_pool = sum(sum(data[n]['dist'].get(d, 0) for d in TIER_D15) for n in names)
    leads_d69_pool = sum(sum(data[n]['dist'].get(d, 0) for d in TIER_D69) for n in names)
    leads_d10_pool = sum(sum(data[n]['dist'].get(d, 0) for d in TIER_D10) for n in names)
    if scored_all > 0:
        tc_wavg_pool = (
            leads_d15_pool / scored_all * BENCHMARK_TC['D1_D5'] +
            leads_d69_pool / scored_all * BENCHMARK_TC['D6_D9'] +
            leads_d10_pool / scored_all * BENCHMARK_TC['D10']
        )
        buyers_est_pool = leads_total * tc_wavg_pool
        m_pool_total = {
            'leads_scored': scored_all,
            'pct_leads':    100.0,
            'tc_bench_pct': tc_wavg_pool * 100,
            'ret_lead':     tc_wavg_pool * TICKET,
            'cpl':          cpl_pool,
            'cac':          cpl_pool / tc_wavg_pool if tc_wavg_pool > 0 else None,
            'roas':         tc_wavg_pool * TICKET / cpl_pool if cpl_pool > 0 else None,
            'buyers_est':   buyers_est_pool,
        }
        print_row('TOTAL', m_pool_total)

    # ── Resumo executivo ─────────────────────────────────────────────────────
    print(f'\n{"="*W}')
    print(f'  RESUMO EXECUTIVO')
    print(f'  Benchmark: D1-D5={BENCHMARK_TC["D1_D5"]*100:.2f}% | '
          f'D6-D9={BENCHMARK_TC["D6_D9"]*100:.2f}% | '
          f'D10={BENCHMARK_TC["D10"]*100:.2f}%  (p=0.002, lift 3.7×, n=7 lançamentos)')
    print(f'{"="*W}')
    print(f'  {"Faixa":<7} {"TC bench":>9}  {"Ret/Lead":>11}  {"ROAS (CPL med R$%.2f)" % cpl_med:>22}  {"Interpretação"}')
    print(f'  {"-"*7} {"-"*9}  {"-"*11}  {"-"*22}  {"-"*35}')

    for tier_key, label in [('D1_D5', 'D1–D5'), ('D6_D9', 'D6–D9'), ('D10', 'D10')]:
        tc    = BENCHMARK_TC[tier_key]
        ret   = tc * TICKET
        roas  = ret / cpl_med
        interp = (
            'Leads de entrada — baixo retorno'  if tier_key == 'D1_D5' else
            'Leads intermediários — ROI positivo' if tier_key == 'D6_D9' else
            'Top leads — ROI máximo'
        )
        flag = _flag(roas)
        print(f'  {label:<7} {tc*100:>8.3f}%  {_brl(ret)}  {_roas(roas)}{flag:<2}  {" "*16}  {interp}')

    # Sanity check: TC implicada pelo benchmark vs TC real dos xlsx
    print(f'\n  Sanity check — TC implicada pelo benchmark vs TC real dos xlsx:')
    print(f'  (delta esperado < 0: benchmark calibrado em leads scored, xlsx usa leads_ml total)')
    print(f'  {"Lançamento":<8}  {"Cobertura":>10}  {"TC bench(pool)":>14}  {"TC real xlsx":>13}  '
          f'{"Delta":>8}  {"Obs"}')
    print(f'  {"-"*8}  {"-"*10}  {"-"*14}  {"-"*13}  {"-"*8}  {"-"*25}')
    for name in names:
        rec = data[name]
        dist = rec['dist']
        ts_n = rec['total_scored']
        lml_n = rec['leads_ml']
        cov_pct = ts_n / lml_n * 100 if lml_n else 0
        obs = ''
        if ts_n == 0:
            print(f'  {name:<8}  {"0% (gap)":>10}  {"—":>14}  '
                  f'{"—":>13}  {"—":>8}  sem dados de score')
            continue
        if cov_pct > 100:
            obs = 'Railway inclui pré-captação'
        ld15 = sum(dist.get(d, 0) for d in TIER_D15)
        ld69 = sum(dist.get(d, 0) for d in TIER_D69)
        ld10 = sum(dist.get(d, 0) for d in TIER_D10)
        pct_d10 = ld10 / ts_n * 100 if ts_n > 0 else 0
        if pct_d10 < 10 and ts_n > 1000:
            obs = f'⚠ D10 só {pct_d10:.0f}% — dist. atípica'
        tc_bench_impl = (
            ld15 / ts_n * BENCHMARK_TC['D1_D5'] +
            ld69 / ts_n * BENCHMARK_TC['D6_D9'] +
            ld10 / ts_n * BENCHMARK_TC['D10']
        ) * 100
        tc_real = rec.get('tc_real_xlsx')
        if tc_real is not None:
            delta = tc_bench_impl - tc_real
            delta_str = f'{delta:+.3f}%'
        else:
            delta_str = '  n/d'
        tc_real_str = f'{tc_real:.3f}%' if tc_real is not None else '        n/d'
        cov_str = f'{cov_pct:.0f}%'
        print(f'  {name:<8}  {cov_str:>10}  {tc_bench_impl:>13.3f}%  {tc_real_str:>13}  '
              f'{delta_str:>8}  {obs}')

    print(f'\n  Legenda: ★ ROAS ≥ 8×  |  ✓ ROAS ≥ 3×  |  ✗ ROAS < 1×')
    print(f'  TC benchmark: observada em produção DEV19–LF48 (n=7, consolidada por faixa)')
    print(f'  Comprad.est: estimativa de compradores = leads_ml × (leads_tier/scored) × TC_bench')
    print(f'  CPL uniforme por lançamento: Meta não diferencia spend por decil')
    print(f'{"="*W}\n')


if __name__ == '__main__':
    import io, sys as _sys

    OUTPUT_PATH = BASE / 'outputs/reports/relatorio_cpl_retorno_decil.txt'
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Captura stdout e imprime simultaneamente no terminal
    buf = io.StringIO()

    class _Tee:
        def write(self, s):
            _sys.__stdout__.write(s)
            buf.write(s)
        def flush(self):
            _sys.__stdout__.flush()

    _sys.stdout = _Tee()
    try:
        run()
    finally:
        _sys.stdout = _sys.__stdout__

    OUTPUT_PATH.write_text(buf.getvalue(), encoding='utf-8')
    print(f'\nRelatório salvo em: {OUTPUT_PATH}')
