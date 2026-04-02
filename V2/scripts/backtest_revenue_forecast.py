"""
Backtest da previsão de faturamento — LF42 a LF47 (modelo jan30).

Metodologia: leave-one-out cross-validation.
  Para cada lançamento i, usa a mediana dos outros 5 como taxa base.
  Roda a previsão e compara com o faturamento contratado real.

Ticket = R$2.200 (valor nominal, Guru e TMB).
Faturamento real = vendas_reais × R$2.200 (visão do dono do negócio).

Rodar: python scripts/backtest_revenue_forecast.py
"""

import sys, os, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Dados históricos — 6 lançamentos válidos (modelo jan30, LF42–LF47)
# Fonte: validation reports + Leads.xlsx
# ---------------------------------------------------------------------------

LANCAMENTOS = [
    {'nome': 'LF42', 'periodo': '22/12–28/12/2025', 'total_leads': 4_301,  'vendas_reais': 54,  'vendas_rastr': 29,  'cartao': 11, 'boleto': 19},
    {'nome': 'LF43', 'periodo': '02/02–08/02/2026', 'total_leads': 13_609, 'vendas_reais': 161, 'vendas_rastr': 94,  'cartao': 60, 'boleto': 38},
    {'nome': 'LF44', 'periodo': '09/02–15/02/2026', 'total_leads': 12_286, 'vendas_reais': 149, 'vendas_rastr': 99,  'cartao': 63, 'boleto': 61},
    {'nome': 'LF45', 'periodo': '02/03–08/03/2026', 'total_leads': 32_068, 'vendas_reais': 388, 'vendas_rastr': 201, 'cartao': 109,'boleto': 105},
    {'nome': 'LF46', 'periodo': '09/03–15/03/2026', 'total_leads': 12_903, 'vendas_reais': 157, 'vendas_rastr': 69,  'cartao': 30, 'boleto': 40},
    {'nome': 'LF47', 'periodo': '16/03–22/03/2026', 'total_leads': 14_243, 'vendas_reais': 174, 'vendas_rastr': 83,  'cartao': 36, 'boleto': 48},
]

TICKET       = 2_200.0   # valor contratado — base da previsão de faturamento
PCT_CARTAO   = 0.469     # proporção cartão mediana (LF44–LF47; exclui LF42 amostra pequena e LF43 efeito pós-Dev19)
FATOR_PESS   = 0.97      # piso de conversão histórica vs mediana
FATOR_OPT    = 1.03      # teto de conversão histórica vs mediana

# LF42 excluído do split: amostra pequena (30 vendas rastreadas) — estatisticamente pouco confiável
# LF43 excluído do split: efeito pós-Dev19 — base inundada com leads frescos distorceu audiência (61.2% cartão vs cluster 42–51%)
LANCAMENTOS_SPLIT = ['LF44', 'LF45', 'LF46', 'LF47']


def _med(vals):
    return statistics.median(vals)


def _prever(leads, conv_rastr_base, tracking_base, fator=1.0):
    """Vendas estimadas = leads × (conv_rastreada / tracking_rate) × fator."""
    return leads * (conv_rastr_base / tracking_base) * fator


def run_backtest():
    print("=" * 72)
    print(" BACKTEST — PREVISÃO DE FATURAMENTO (leave-one-out)")
    print(f" Ticket contratado: R${TICKET:,.0f} | Modelo: jan30 | LF42–LF47")
    print("=" * 72)

    conv_rastr  = [lf['vendas_rastr'] / lf['total_leads'] for lf in LANCAMENTOS]
    conv_real   = [lf['vendas_reais'] / lf['total_leads'] for lf in LANCAMENTOS]
    tracking    = [lf['vendas_rastr'] / lf['vendas_reais'] for lf in LANCAMENTOS]
    pct_cartao  = [(lf['cartao'] / (lf['cartao'] + lf['boleto'])) * 100 for lf in LANCAMENTOS]

    print("\n── ESTATÍSTICAS DOS 6 LANÇAMENTOS ──────────────────────────────────")
    print(f"  Conv. rastreada:  min={min(conv_rastr):.2%}  med={_med(conv_rastr):.2%}  max={max(conv_rastr):.2%}  CV={statistics.stdev(conv_rastr)/statistics.mean(conv_rastr):.0%}")
    print(f"  Conv. real:       min={min(conv_real):.2%}  med={_med(conv_real):.2%}  max={max(conv_real):.2%}  CV={statistics.stdev(conv_real)/statistics.mean(conv_real):.0%}")
    print(f"  Tracking rate:    min={min(tracking):.1%}  med={_med(tracking):.1%}  max={max(tracking):.1%}  CV={statistics.stdev(tracking)/statistics.mean(tracking):.0%}")
    print(f"  % Cartão:         min={min(pct_cartao):.1f}%  med={_med(pct_cartao):.1f}%  max={max(pct_cartao):.1f}%  CV={statistics.stdev(pct_cartao)/statistics.mean(pct_cartao):.0%}")

    # -------------------------------------------------------------------------
    # Leave-one-out: faturamento previsto vs real (ticket R$2.200)
    # -------------------------------------------------------------------------
    print(f"\n── LEAVE-ONE-OUT: Faturamento previsto vs Real (ticket R${TICKET:,.0f}) ────")
    print(f"  {'Launch':<6} {'Leads':>7} {'Vendas Reais':>13} {'Fat.Real':>11} {'Base':>11} {'Err%':>7} {'Pess':>11} {'Otim':>11}")
    print(f"  {'-'*6} {'-'*7} {'-'*13} {'-'*11} {'-'*11} {'-'*7} {'-'*11} {'-'*11}")

    erros = []
    dentro_faixa = 0

    for i, lf in enumerate(LANCAMENTOS):
        outros = [LANCAMENTOS[j] for j in range(len(LANCAMENTOS)) if j != i]

        conv_base = _med([o['vendas_rastr'] / o['total_leads'] for o in outros])
        track_base = _med([o['vendas_rastr'] / o['vendas_reais'] for o in outros])

        vendas_base = _prever(lf['total_leads'], conv_base, track_base, 1.0)
        vendas_pess = _prever(lf['total_leads'], conv_base, track_base, FATOR_PESS)
        vendas_otim = _prever(lf['total_leads'], conv_base, track_base, FATOR_OPT)

        fat_real = lf['vendas_reais'] * TICKET
        fat_base = vendas_base * TICKET
        fat_pess = vendas_pess * TICKET
        fat_otim = vendas_otim * TICKET

        erro = (fat_base - fat_real) / fat_real * 100
        erros.append(erro)

        ok = fat_pess <= fat_real <= fat_otim
        if ok:
            dentro_faixa += 1

        print(f"  {lf['nome']:<6} {lf['total_leads']:>7,} {lf['vendas_reais']:>8} vendas "
              f"R${fat_real:>9,.0f} "
              f"R${fat_base:>9,.0f} "
              f"{erro:>+7.1f}% "
              f"R${fat_pess:>9,.0f} "
              f"R${fat_otim:>9,.0f}  {'✓' if ok else '✗'}")

    mae  = statistics.mean([abs(e) for e in erros])
    vies = statistics.mean(erros)
    print(f"\n  MAE:              {mae:.1f}%")
    print(f"  Viés médio:       {vies:+.1f}%  ({'superestima' if vies > 0 else 'subestima'})")
    print(f"  Dentro da faixa:  {dentro_faixa}/{len(LANCAMENTOS)}")

    # -------------------------------------------------------------------------
    # Split Guru / TMB
    # -------------------------------------------------------------------------
    # Benchmark do split calculado apenas com LF44–LF47 (exclui LF42 e LF43 — ver comentário acima)
    lfs_split_ref = [lf for lf in LANCAMENTOS if lf['nome'] in LANCAMENTOS_SPLIT]
    pct_cartao_cv = statistics.stdev(
        [lf['cartao'] / (lf['cartao'] + lf['boleto']) for lf in lfs_split_ref]
    ) / statistics.mean(
        [lf['cartao'] / (lf['cartao'] + lf['boleto']) for lf in lfs_split_ref]
    )

    print(f"\n── SPLIT GURU / TMB (benchmark: {PCT_CARTAO:.1%} cartão — mediana LF44–LF47, CV={pct_cartao_cv:.0%}) ──")
    print(f"  {'Launch':<6} {'%Cartão Real':>13} {'Guru Prev.':>11} {'TMB Prev.':>11} {'Guru Real':>10} {'TMB Real':>10} {'Nota':>10}")
    print(f"  {'-'*6} {'-'*13} {'-'*11} {'-'*11} {'-'*10} {'-'*10} {'-'*10}")

    for i, lf in enumerate(LANCAMENTOS):
        outros = [LANCAMENTOS[j] for j in range(len(LANCAMENTOS)) if j != i]
        conv_base  = _med([o['vendas_rastr'] / o['total_leads'] for o in outros])
        track_base = _med([o['vendas_rastr'] / o['vendas_reais'] for o in outros])
        vendas_base = _prever(lf['total_leads'], conv_base, track_base)

        guru_prev = vendas_base * PCT_CARTAO
        tmb_prev  = vendas_base * (1 - PCT_CARTAO)
        guru_real = lf['vendas_reais'] * (lf['cartao'] / (lf['cartao'] + lf['boleto']))
        tmb_real  = lf['vendas_reais'] * (lf['boleto'] / (lf['cartao'] + lf['boleto']))
        pct_c = lf['cartao'] / (lf['cartao'] + lf['boleto']) * 100

        nota = ''
        if lf['nome'] == 'LF42':
            nota = '(excl.split-vol)'
        elif lf['nome'] == 'LF43':
            nota = '(excl.split-Dev19)'

        print(f"  {lf['nome']:<6} {pct_c:>12.1f}% {guru_prev:>10.1f}v {tmb_prev:>10.1f}v "
              f"{guru_real:>9.1f}v {tmb_real:>9.1f}v  {nota}")

    # -------------------------------------------------------------------------
    # Conclusão
    # -------------------------------------------------------------------------
    print(f"\n── CONCLUSÃO ────────────────────────────────────────────────────────")
    print(f"  Erro médio no faturamento contratado: {mae:.1f}%")
    if mae < 10:
        print(f"  ✓ Excelente — dentro do tolerável para uma previsão de lançamento.")
    elif mae < 20:
        print(f"  ✓ Bom — erro aceitável para planejamento de investimento.")
    else:
        print(f"  ⚠ Atenção — erro elevado. Investigar causas por lançamento.")

    print(f"\n  Faixas de cenário (±conv. rate):")
    print(f"    Fatores: pessimista={FATOR_PESS}x | base=1.00x | otimista={FATOR_OPT}x")
    print(f"    Traduzido: piso ≈ base × {FATOR_PESS} | teto ≈ base × {FATOR_OPT}")
    print(f"    Amplitude da faixa: {(FATOR_OPT - FATOR_PESS)*100:.0f}% em torno do base")
    print(f"\n  Split Guru/TMB: benchmark {PCT_CARTAO:.1%} cartão / {1-PCT_CARTAO:.1%} boleto (mediana LF44–LF47)")
    print(f"    CV do split (LF44–LF47): {pct_cartao_cv:.0%} — não afeta o faturamento total")
    print(f"    LF42 excluído do benchmark: amostra pequena (30 vendas rastreadas)")
    print(f"    LF43 excluído do benchmark: efeito pós-Dev19 (audiência atípica, {61.2:.1f}% cartão)")
    print("=" * 72)


if __name__ == '__main__':
    run_backtest()
