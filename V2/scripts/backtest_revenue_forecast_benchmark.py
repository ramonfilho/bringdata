"""
Backtest da previsão de faturamento — metodologia conversion_rate_benchmark (3 faixas).

Lançamentos: DEV19, LF43–LF48 (7 lançamentos de produção)
Exclui: LF40/LF41 (inconclusivos), LF42 (semana de Natal)

Metodologia: leave-one-out cross-validation com taxas pooled por faixa.
  Para cada lançamento i:
    - Agrupa os outros 6 em D1-5 / D6-9 / D10
    - Calcula taxa pooled de cada faixa (total_buyers / total_leads)
    - Aplica à distribuição de decis do lançamento i
    - Compara compradores estimados vs compradores rastreados reais
    - Escala para faturamento via tracking_rate mediana

Rodar: python scripts/backtest_revenue_forecast_benchmark.py
"""

import sys, os, statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from ml_evolution_report import (
    load_sheets_data, load_railway,
    compute_decil_lift, discover_periods, find_xlsx_for_period,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
INCLUDE    = ['DEV19', 'LF43', 'LF44', 'LF45', 'LF46', 'LF47', 'LF48']
TIER_D15   = [f'D{i}' for i in range(1, 6)]
TIER_D69   = [f'D{i}' for i in range(6, 10)]
TIER_D10   = ['D10']

TICKET          = 2_200.0   # valor contratado
TRACKING_RATE   = 0.528     # mediana histórica (matched / total) — LF42–LF47
GURU_TICKET     = 1_997.0   # preço real Guru
GURU_REALIZACAO = 0.87      # fator de realização Guru
PCT_CARTAO      = 0.469     # proporção cartão (mediana LF44–LF47)
FATOR_PESS      = 0.97
FATOR_OPT       = 1.03


def pool_tier(rows: list[dict], decils: list[str]) -> tuple[int, int, float]:
    """Retorna (total_leads, total_buyers, tc_pct) para um conjunto de decis."""
    tl = sum(r['leads']  for r in rows if r['decil'] in decils)
    tb = sum(r['buyers'] for r in rows if r['decil'] in decils)
    tc = tb / tl * 100 if tl > 0 else 0.0
    return tl, tb, tc


def load_data() -> dict:
    """Carrega distribuição de decis por lançamento via compute_decil_lift."""
    print("Carregando dados...")
    sheets_df = load_sheets_data()
    rail_df   = load_railway()
    periods   = discover_periods()

    results = {}
    for p in periods:
        name = p['name']
        if name not in INCLUDE:
            continue
        xlsx_path = find_xlsx_for_period(p['vendas_start'], p['vendas_end'])
        if xlsx_path is None:
            print(f"  {name}: xlsx não encontrado — ignorado")
            continue
        df = compute_decil_lift(xlsx_path, sheets_df, p['cap_start'], p['cap_end'], rail_df)
        if df.empty:
            print(f"  {name}: dados vazios — ignorado")
            continue
        rows = df.to_dict('records')
        results[name] = rows
        _, _, cr10 = pool_tier(rows, TIER_D10)
        _, _, cr69 = pool_tier(rows, TIER_D69)
        _, _, cr15 = pool_tier(rows, TIER_D15)
        total_leads  = sum(r['leads']  for r in rows)
        total_buyers = sum(r['buyers'] for r in rows)
        print(f"  {name}: {total_leads:,} leads | {total_buyers} compradores rastr. "
              f"| D1-5={cr15:.3f}% D6-9={cr69:.3f}% D10={cr10:.3f}%")

    return results


def run_backtest(results: dict):
    names = [n for n in INCLUDE if n in results]
    if len(names) < 3:
        print("Dados insuficientes para leave-one-out.")
        return

    print(f"\n{'='*76}")
    print(f"  BACKTEST — CONVERSION_RATE_BENCHMARK 3 FAIXAS (leave-one-out)")
    print(f"  Lançamentos: {', '.join(names)}")
    print(f"  Ticket R${TICKET:,.0f} | Tracking rate {TRACKING_RATE:.1%} | PCT cartão {PCT_CARTAO:.1%}")
    print(f"{'='*76}")

    # ── Estatísticas pooled globais ──────────────────────────────────────────
    all_rows = [r for n in names for r in results[n]]
    _, _, tc15_all = pool_tier(all_rows, TIER_D15)
    _, _, tc69_all = pool_tier(all_rows, TIER_D69)
    _, _, tc10_all = pool_tier(all_rows, TIER_D10)

    print(f"\n── TAXAS POOLED GLOBAIS ({', '.join(names)}) ────────────────────────────")
    print(f"  D1–D5  : {tc15_all:.3f}%")
    print(f"  D6–D9  : {tc69_all:.3f}%")
    print(f"  D10    : {tc10_all:.3f}%")
    print(f"  (referência — não usadas diretamente no LOO)")

    # ── Leave-one-out ────────────────────────────────────────────────────────
    print(f"\n── LEAVE-ONE-OUT ────────────────────────────────────────────────────────")
    hdr = f"  {'Launch':<7} {'Leads':>7} {'B.Real':>7} {'Faixa LOO (D15/D69/D10)':>28}  {'B.Est':>6} {'Err%':>7}  {'Fat.Real':>11} {'Fat.Est':>11} {'Err%':>7}"
    print(hdr)
    print(f"  {'-'*7} {'-'*7} {'-'*7} {'-'*28}  {'-'*6} {'-'*7}  {'-'*11} {'-'*11} {'-'*7}")

    erros_buyers = []
    erros_fat    = []
    dentro_faixa = 0

    for i, name in enumerate(names):
        outros_rows = [r for j, n in enumerate(names) if j != i for r in results[n]]

        # Taxas LOO das 3 faixas
        _, _, loo_tc15 = pool_tier(outros_rows, TIER_D15)
        _, _, loo_tc69 = pool_tier(outros_rows, TIER_D69)
        _, _, loo_tc10 = pool_tier(outros_rows, TIER_D10)

        # Distribuição do lançamento i
        rows_i = results[name]
        leads_D15 = sum(r['leads'] for r in rows_i if r['decil'] in TIER_D15)
        leads_D69 = sum(r['leads'] for r in rows_i if r['decil'] in TIER_D69)
        leads_D10 = sum(r['leads'] for r in rows_i if r['decil'] in TIER_D10)
        total_leads  = leads_D15 + leads_D69 + leads_D10
        real_matched = sum(r['buyers'] for r in rows_i)

        # Compradores estimados (matched)
        est_matched = (
            leads_D15 * (loo_tc15 / 100) +
            leads_D69 * (loo_tc69 / 100) +
            leads_D10 * (loo_tc10 / 100)
        )

        # Escala para total via tracking_rate → faturamento
        est_total   = est_matched / TRACKING_RATE
        real_total  = real_matched / TRACKING_RATE   # proxy (tracking_rate mediana)

        fat_est     = est_total * TICKET
        fat_real    = real_total * TICKET

        fat_est_pess = fat_est * FATOR_PESS
        fat_est_otim = fat_est * FATOR_OPT

        erro_b   = (est_matched - real_matched) / real_matched * 100 if real_matched > 0 else 0
        erro_fat = (fat_est - fat_real)         / fat_real     * 100 if fat_real     > 0 else 0

        erros_buyers.append(erro_b)
        erros_fat.append(erro_fat)

        ok = fat_est_pess <= fat_real <= fat_est_otim
        if ok:
            dentro_faixa += 1

        faixa_str = f"{loo_tc15:.2f}% / {loo_tc69:.2f}% / {loo_tc10:.2f}%"
        print(f"  {name:<7} {total_leads:>7,} {real_matched:>7}  {faixa_str:>28}  "
              f"{est_matched:>5.1f}  {erro_b:>+6.1f}%  "
              f"R${fat_real:>9,.0f}  R${fat_est:>9,.0f}  {erro_fat:>+6.1f}%  "
              f"{'✓' if ok else '✗'}")

    mae_b   = statistics.mean([abs(e) for e in erros_buyers])
    vies_b  = statistics.mean(erros_buyers)
    mae_f   = statistics.mean([abs(e) for e in erros_fat])
    vies_f  = statistics.mean(erros_fat)

    print(f"\n  MAE compradores rastreados : {mae_b:.1f}%  (viés {vies_b:+.1f}%)")
    print(f"  MAE faturamento (proxy)    : {mae_f:.1f}%  (viés {vies_f:+.1f}%)")
    print(f"  Dentro da faixa ±3%        : {dentro_faixa}/{len(names)}")

    # ── Benchmark: nova vs antiga ────────────────────────────────────────────
    print(f"\n── COMPARATIVO DE METODOLOGIA ──────────────────────────────────────────")
    print(f"  Metodologia anterior (backtest_revenue_forecast.py, LF42–LF47):")
    print(f"    MAE faturamento: 2.6%  | Viés: +1.4%  | Dentro ±3%: 4/6")
    print(f"  Metodologia nova (3 faixas produção, LOO):")
    print(f"    MAE faturamento: {mae_f:.1f}%  | Viés: {vies_f:+.1f}%  | Dentro ±3%: {dentro_faixa}/{len(names)}")
    print(f"\n  Nota: faturamento novo usa tracking_rate mediana ({TRACKING_RATE:.1%}) para escalar.")
    print(f"  Para comparação exata com o anterior, checar vendas_reais vs proxy.")

    # ── Distribuição por faixa ───────────────────────────────────────────────
    print(f"\n── DISTRIBUIÇÃO POR FAIXA (todos os lançamentos) ───────────────────────")
    print(f"  {'Launch':<7} {'Leads':>7} {'D1-5 leads':>11} {'D6-9 leads':>11} {'D10 leads':>10} {'%D10':>6}")
    print(f"  {'-'*7} {'-'*7} {'-'*11} {'-'*11} {'-'*10} {'-'*6}")
    for name in names:
        rows_i = results[name]
        l15 = sum(r['leads'] for r in rows_i if r['decil'] in TIER_D15)
        l69 = sum(r['leads'] for r in rows_i if r['decil'] in TIER_D69)
        l10 = sum(r['leads'] for r in rows_i if r['decil'] in TIER_D10)
        tot = l15 + l69 + l10
        pct10 = l10 / tot * 100 if tot > 0 else 0
        print(f"  {name:<7} {tot:>7,} {l15:>11,} {l69:>11,} {l10:>10,} {pct10:>5.1f}%")

    print(f"\n{'='*76}")


if __name__ == '__main__':
    data = load_data()
    if not data:
        print("Nenhum dado carregado. Verifique os caminhos dos arquivos.")
        sys.exit(1)
    run_backtest(data)
