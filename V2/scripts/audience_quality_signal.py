"""
Métrica final de qualidade de audiência via score do modelo Challenger.

Para cada LF (referência + atuais):
  - score_mean      : média do lead_score do Challenger
  - pct_d10         : % leads em D10
  - pct_d9_d10      : % leads em D9 ou D10

Baseline = média ponderada (por leads) do Top5 ROAS realized:
  [LF40, LF41, LF45, LF50, LF53fp]

Sinal final para LF atual:
  Δscore_mean = (score_LF_atual - score_baseline) / score_baseline × 100%
  Δpct_d9_d10 = pct_LF_atual - pct_baseline (em pp)

Interpretação:
  - Δscore > +5% e Δpct_d9_d10 > +3pp  → audiência ACIMA do padrão histórico bom
  - Δscore entre -5% e +5%             → audiência DENTRO do padrão
  - Δscore < -5% ou Δpct_d9_d10 < -5pp → audiência ABAIXO do padrão

NOTA: o score do RF (0–1) é ranking, NÃO probabilidade calibrada (calib_ratio
~60×). Comparações ABSOLUTAS de score não fazem sentido. Comparações RELATIVAS
(LF atual vs LFs históricos sob o mesmo modelo) são válidas e robustas — é
exatamente isto que medimos aqui.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
VAL_DIR = REPO_ROOT / 'files' / 'validation'

# Top5 ROAS realized — referência fixa (decidida na sessão de 09-10/05/2026)
REFERENCE_LFS = [
    ('LF40', 'backtest_lf40'),
    ('LF41', 'backtest_lf41'),
    ('LF45', 'backtest_lf45'),
    ('LF50', 'backtest_lf50'),
    ('LF53fp', 'backtest_lf53fp'),  # first peak (3 dias) — primeiro pico de vendas
]

# Atuais — alvo da predição
TARGET_LFS = [
    ('LF54', 'backtest_lf54'),
    ('DEV20', 'backtest_dev20'),
]

# Sanity LFs — para validar que a métrica é estável vs outros LFs históricos
SANITY_LFS = [
    ('LF52', 'backtest_lf52'),
]

ALL_LFS = REFERENCE_LFS + TARGET_LFS + SANITY_LFS


def load_scored(folder: str) -> pd.DataFrame:
    p = VAL_DIR / folder / 'scored_abr28.parquet'
    return pd.read_parquet(p)


def metrics(df: pd.DataFrame) -> dict:
    n = len(df)
    return {
        'n_leads': n,
        'score_mean': df['lead_score'].mean(),
        'score_median': df['lead_score'].median(),
        'pct_d10': (df['decil'] == 'D10').sum() / n * 100,
        'pct_d9_d10': df['decil'].isin(['D09', 'D10']).sum() / n * 100,
        'pct_d8_d10': df['decil'].isin(['D08', 'D09', 'D10']).sum() / n * 100,
    }


def main():
    rows = []
    print('═' * 80)
    print('  MÉTRICAS POR LF (modelo Challenger abr28)')
    print('═' * 80)
    print(f'  {"LF":<8} {"n_leads":>9}  {"score_mean":>11}  {"%D10":>6}  {"%D9-D10":>8}  {"%D8-D10":>8}')
    print('-' * 80)

    by_group = {}
    for kind, lfs in [('REF', REFERENCE_LFS), ('TARGET', TARGET_LFS), ('SANITY', SANITY_LFS)]:
        for label, folder in lfs:
            df = load_scored(folder)
            m = metrics(df)
            m['lf'] = label
            m['kind'] = kind
            rows.append(m)
            tag = {'REF': '★', 'TARGET': '◆', 'SANITY': '·'}[kind]
            print(f'  {tag} {label:<6} {m["n_leads"]:>9,}  '
                  f'{m["score_mean"]:>11.4f}  '
                  f'{m["pct_d10"]:>5.1f}%  '
                  f'{m["pct_d9_d10"]:>7.1f}%  '
                  f'{m["pct_d8_d10"]:>7.1f}%')

    res = pd.DataFrame(rows).set_index('lf')

    # Dois baselines:
    #   FULL      = todos os 5 REFs
    #   CLEAN     = exclui LF40/LF41 (schema Sheets antigo distorce decis Challenger)
    refs = res[res['kind'] == 'REF']
    refs_clean = refs.drop(['LF40', 'LF41'], errors='ignore')

    def _wavg(df):
        w = df['n_leads']
        return {
            'score_mean': (df['score_mean'] * w).sum() / w.sum(),
            'pct_d10':    (df['pct_d10'] * w).sum() / w.sum(),
            'pct_d9_d10': (df['pct_d9_d10'] * w).sum() / w.sum(),
            'pct_d8_d10': (df['pct_d8_d10'] * w).sum() / w.sum(),
            'n':          int(w.sum()),
        }

    bl_full = _wavg(refs)
    bl_clean = _wavg(refs_clean)

    print('-' * 80)
    print(f'  BASELINE FULL (Top5 ROAS realized, n={bl_full["n"]:,}):')
    print(f'    score_mean: {bl_full["score_mean"]:.4f}  '
          f'%D10: {bl_full["pct_d10"]:.1f}%  '
          f'%D9-D10: {bl_full["pct_d9_d10"]:.1f}%  '
          f'%D8-D10: {bl_full["pct_d8_d10"]:.1f}%')
    print(f'  BASELINE CLEAN (excl. LF40/LF41 — anomalia de scoring), n={bl_clean["n"]:,}):')
    print(f'    score_mean: {bl_clean["score_mean"]:.4f}  '
          f'%D10: {bl_clean["pct_d10"]:.1f}%  '
          f'%D9-D10: {bl_clean["pct_d9_d10"]:.1f}%  '
          f'%D8-D10: {bl_clean["pct_d8_d10"]:.1f}%')
    print()
    baseline = bl_full  # após correção de schema (training_mode=True), FULL é confiável

    # Sinal: Δ relativo para cada LF (TARGET + SANITY)
    print('═' * 90)
    print('  SINAL DE QUALIDADE DE AUDIÊNCIA — LF atual vs Baseline Top5 ROAS realized')
    print('═' * 90)
    print(f'  {"LF":<8} {"Δscore_%":>9}  {"Δ%D10_pp":>10}  {"Δ%D9-D10_pp":>13}  {"Δ%D8-D10_pp":>13}  Sinal')
    print('-' * 90)

    for label in [lf for lf, _ in TARGET_LFS + SANITY_LFS]:
        r = res.loc[label]
        d_score_pct = (r['score_mean'] - baseline['score_mean']) / baseline['score_mean'] * 100
        d_d10 = r['pct_d10'] - baseline['pct_d10']
        d_d9_d10 = r['pct_d9_d10'] - baseline['pct_d9_d10']
        d_d8_d10 = r['pct_d8_d10'] - baseline['pct_d8_d10']

        # Classificação heurística
        if d_score_pct > 5 and d_d9_d10 > 3:
            sinal = '↑ ACIMA do padrão'
        elif d_score_pct < -5 or d_d9_d10 < -5:
            sinal = '↓ ABAIXO do padrão'
        else:
            sinal = '→ DENTRO do padrão'

        print(f'  {label:<8} {d_score_pct:>+8.2f}%  {d_d10:>+9.2f}pp  {d_d9_d10:>+12.2f}pp  '
              f'{d_d8_d10:>+12.2f}pp  {sinal}')

    print()
    print('Notas:')
    print('  - Score do RF é ranking (0–1), não probabilidade calibrada.')
    print('    Calib ratio ~60× — usar só como comparação RELATIVA.')
    print('  - LF52 é sanity check: ROAS realized 2.46 é "ok-bom", deve ficar')
    print('    DENTRO do padrão sob o mesmo modelo.')
    print('  - Histórica das LFs ref já incorporadas na média ponderada.')
    print()

    out = REPO_ROOT / 'outputs' / 'analysis' / 'audience_quality_signal.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out)
    print(f'→ CSV salvo em: {out.relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
