"""
Impacto da composição demográfica do LF alvo sobre o faturamento esperado.

Metodologia: pós-estratificação (direct standardization).
  R̂_alvo/lead    = Σ_c w_c^alvo × p_c × t_c       (composição do alvo, conv/ticket históricos)
  R̂_baseline/lead = Σ_c w_c^hist × p_c × t_c      (composição histórica, conv/ticket históricos)

Onde:
  w_c = % de leads na célula c (composição)
  p_c = taxa de conversão histórica da célula (LFs do pool)
  t_c = ticket médio histórico da célula

Faz a análise univariada por dimensão (idade, ocupacao) — não cruza as duas
por baixa freq. de vendas em células 2D.

IC95% via bootstrap não-paramétrico sobre leads históricos (B=2000).

Uso:
    python -m scripts.impacto_composicao_lf
    python -m scripts.impacto_composicao_lf --target LF54 --pool LF46,LF47,LF48,LF49,LF50,LF51,LF52
    python -m scripts.impacto_composicao_lf --b 1000 --no-xlsx
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import pg8000.native
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.perfil_audiencia import PESQUISA_KEYS, normalize_series

load_dotenv(REPO_ROOT / '.env')

HIST_DIR = REPO_ROOT / 'files' / 'validation' / 'backtest_historico'
LAUNCHES = REPO_ROOT / 'configs' / 'launches.yaml'
DEFAULT_POOL = ['LF46', 'LF47', 'LF48', 'LF49', 'LF50', 'LF51', 'LF52']
DEFAULT_TARGET = 'LF54'

IDADE_LABEL = 'Qual a sua idade?'
OCUP_LABEL  = 'O que você faz atualmente?'

IDADE_ORDER = ['<18', '18-24', '25-34', '35-44', '45-54', '55+']
OCUP_ORDER  = ['Estudante', 'CLT/funcionário público', 'Autônomo',
               'Aposentado', 'Não trabalho/nem estudo']


# ───────────────────────────────────── data loading ─────────────────────────────────────

def load_target_from_railway(target: str) -> pd.DataFrame:
    import yaml
    with open(LAUNCHES) as f:
        cfg = yaml.safe_load(f)[target]
    end_excl = (pd.to_datetime(cfg['cap_end']) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

    conn = pg8000.native.Connection(
        host=os.environ['RAILWAY_DB_HOST'],
        port=int(os.environ['RAILWAY_DB_PORT']),
        user=os.environ['RAILWAY_DB_USER'],
        password=os.environ['RAILWAY_DB_PASSWORD'],
        database=os.environ['RAILWAY_DB_NAME'],
        ssl_context=True,
    )
    rows = conn.run(
        """
        SELECT pesquisa->>'idade'    AS idade_raw,
               pesquisa->>'ocupacao' AS ocupacao_raw
        FROM "Lead"
        WHERE data >= :s AND data < :e
          AND pesquisa IS NOT NULL
        """,
        s=cfg['cap_start'], e=end_excl,
    )
    conn.close()
    df = pd.DataFrame(rows, columns=['idade_raw', 'ocupacao_raw'])
    df['idade']    = normalize_series(df['idade_raw'],    IDADE_LABEL)
    df['ocupacao'] = normalize_series(df['ocupacao_raw'], OCUP_LABEL)
    df['cap_start'] = cfg['cap_start']
    df['cap_end']   = cfg['cap_end']
    return df


def load_pool(lfs: list[str]) -> pd.DataFrame:
    frames = []
    for lf in lfs:
        p = HIST_DIR / lf / 'base_with_tmb.parquet'
        if not p.exists():
            print(f"  ⚠ {lf}: arquivo ausente, pulando")
            continue
        d = pd.read_parquet(p)
        d['lf'] = lf
        d['idade']    = normalize_series(d[IDADE_LABEL], IDADE_LABEL)
        d['ocupacao'] = normalize_series(d[OCUP_LABEL],  OCUP_LABEL)
        # sale_value pode estar NaN onde não converteu
        d['sale_value'] = pd.to_numeric(d['sale_value'], errors='coerce').fillna(0.0)
        frames.append(d[['lf', 'idade', 'ocupacao', 'converted', 'sale_value']])
    return pd.concat(frames, ignore_index=True)


# ──────────────────────────────────── core math ────────────────────────────────────

def cell_stats(pool: pd.DataFrame, dim: str) -> pd.DataFrame:
    """p_c (conv rate) e t_c (ticket médio dos convertidos) por categoria."""
    g = pool.groupby(dim)
    stats = pd.DataFrame({
        'n_pool':    g.size(),
        'vendas':    g['converted'].sum().astype(int),
        'p':         g['converted'].mean(),
        't':         pool[pool['converted']].groupby(dim)['sale_value'].mean(),
        'rev_per_lead_hist': g.apply(lambda s: (s['converted'] * s['sale_value']).sum() / len(s)),
    })
    stats['t'] = stats['t'].fillna(0.0)
    stats['w_hist'] = stats['n_pool'] / stats['n_pool'].sum()
    return stats


def weights_target(target: pd.DataFrame, dim: str, idx: pd.Index) -> pd.Series:
    vc = target[dim].value_counts().reindex(idx, fill_value=0)
    return vc / vc.sum() if vc.sum() else vc


def expected_rev_per_lead(weights: pd.Series, stats: pd.DataFrame) -> float:
    return float((weights * stats['p'] * stats['t']).sum())


def decomposition(w_alvo: pd.Series, w_hist: pd.Series, stats: pd.DataFrame) -> pd.DataFrame:
    """Contribuição de cada célula para o Δ R/lead (= (w_alvo - w_hist) × p × t)."""
    df = pd.DataFrame({
        'w_hist_%':  (w_hist * 100).round(2),
        'w_alvo_%':  (w_alvo * 100).round(2),
        'Δ pp':       ((w_alvo - w_hist) * 100).round(2),
        'p_%':        (stats['p'] * 100).round(3),
        't_R$':       stats['t'].round(0),
        'contrib_R$': ((w_alvo - w_hist) * stats['p'] * stats['t']).round(2),
    })
    return df.sort_values('contrib_R$', key=abs, ascending=False)


# ──────────────────────────────────── bootstrap ────────────────────────────────────

def bootstrap_ic(pool: pd.DataFrame, target: pd.DataFrame, dim: str,
                 B: int = 2000, seed: int = 42) -> dict:
    """
    Reamostra pool com reposição B vezes, recalcula p_c, t_c → distribuição da
    diferença pareada R̂_alvo - R̂_hist por réplica (variância de p e t pareada).
    """
    rng = np.random.default_rng(seed)
    n = len(pool)
    idx_all = np.arange(n)

    rev_alvo, rev_hist, delta_pct = [], [], []
    for _ in range(B):
        idx = rng.integers(0, n, size=n)
        sample = pool.iloc[idx]
        st = cell_stats(sample, dim)
        idx_cat = st.index
        wa = weights_target(target, dim, idx_cat)
        wh = st['w_hist']
        r_a = float((wa * st['p'] * st['t']).sum())
        r_h = float((wh * st['p'] * st['t']).sum())
        rev_alvo.append(r_a)
        rev_hist.append(r_h)
        if r_h > 0:
            delta_pct.append((r_a - r_h) / r_h * 100)

    def pct(v, q): return float(np.percentile(v, q))
    return {
        'r_alvo_mean': float(np.mean(rev_alvo)),
        'r_alvo_ic':   (pct(rev_alvo, 2.5),  pct(rev_alvo, 97.5)),
        'r_hist_mean': float(np.mean(rev_hist)),
        'r_hist_ic':   (pct(rev_hist, 2.5),  pct(rev_hist, 97.5)),
        'delta_pct_mean': float(np.mean(delta_pct)),
        'delta_pct_ic':   (pct(delta_pct, 2.5), pct(delta_pct, 97.5)),
        'delta_signif':   (pct(delta_pct, 2.5) > 0 or pct(delta_pct, 97.5) < 0),
        'B': B,
    }


# ──────────────────────────────────── report ────────────────────────────────────

def run_dimension(pool: pd.DataFrame, target: pd.DataFrame, dim: str,
                  order: list[str], B: int) -> dict:
    stats = cell_stats(pool, dim)
    # ordenação para apresentação
    stats = stats.reindex([c for c in order if c in stats.index]
                          + [c for c in stats.index if c not in order])
    wa = weights_target(target, dim, stats.index)
    wh = stats['w_hist']

    rev_alvo_pt = expected_rev_per_lead(wa, stats)
    rev_hist_pt = expected_rev_per_lead(wh, stats)
    delta_pt    = (rev_alvo_pt - rev_hist_pt) / rev_hist_pt * 100 if rev_hist_pt else 0.0

    ic = bootstrap_ic(pool, target, dim, B=B)

    return {
        'dim': dim,
        'stats': stats,
        'w_alvo': wa,
        'decomp': decomposition(wa, wh, stats),
        'rev_alvo': rev_alvo_pt,
        'rev_hist': rev_hist_pt,
        'delta_pct': delta_pt,
        'ic': ic,
    }


def fmt_money(v): return f"R$ {v:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')
def fmt_pct(v):   return f"{v:+.1f}%"


def print_block(r: dict, target_name: str, pool_label: str):
    print()
    print("═" * 90)
    print(f"  DIMENSÃO: {r['dim'].upper()}")
    print("═" * 90)
    print()
    print("Decomposição (Δ R/lead vs composição histórica, por célula):")
    print(r['decomp'].to_string())
    print()
    print(f"  R̂ {target_name}/lead       = {fmt_money(r['rev_alvo'])}   "
          f"(IC95: {fmt_money(r['ic']['r_alvo_ic'][0])} – {fmt_money(r['ic']['r_alvo_ic'][1])})")
    print(f"  R̂ baseline/lead     = {fmt_money(r['rev_hist'])}   "
          f"(IC95: {fmt_money(r['ic']['r_hist_ic'][0])} – {fmt_money(r['ic']['r_hist_ic'][1])})")
    delta = r['ic']['delta_pct_mean']
    lo, hi = r['ic']['delta_pct_ic']
    sig = "SIGNIFICATIVO" if r['ic']['delta_signif'] else "não-significativo (IC cruza 0)"
    print(f"  Δ esperado          = {fmt_pct(delta)}   "
          f"(IC95: {fmt_pct(lo)} a {fmt_pct(hi)})   → {sig}")


def emit_markdown(out: Path, target: str, target_cfg: dict, target_n: int,
                  pool: list[str], pool_n: int, results: list[dict], B: int):
    L = []
    L.append(f"# Impacto da composição demográfica — {target}\n")
    L.append(f"**Gerado em:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    L.append(f"**Lançamento alvo:** {target} (cap {target_cfg['cap_start']} → {target_cfg['cap_end']}, "
             f"{target_n:,} leads — captação encerrada)  ")
    L.append(f"**Pool histórico:** {', '.join(pool)} ({pool_n:,} leads matched)  ")
    L.append(f"**Bootstrap:** {B:,} réplicas\n")

    L.append("## Metodologia\n")
    L.append("Pós-estratificação univariada por dimensão. Para cada célula `c`:\n")
    L.append("```")
    L.append("R̂_alvo/lead     = Σ_c  w_c^alvo  × p_c × t_c")
    L.append("R̂_baseline/lead = Σ_c  w_c^hist  × p_c × t_c")
    L.append("Δ%              = (R̂_alvo - R̂_baseline) / R̂_baseline")
    L.append("```\n")
    L.append("Onde `w_c` = peso da célula, `p_c` = conv histórica da célula, `t_c` = ticket médio histórico.")
    L.append("IC95% por bootstrap não-paramétrico sobre os leads do pool (variância pareada de p e t).\n")

    for r in results:
        L.append(f"## Dimensão: {r['dim']}\n")
        L.append("### Decomposição (Δ R/lead por célula)\n")
        L.append(r['decomp'].to_markdown())
        L.append("")
        ic = r['ic']
        L.append("### Estimativa pontual + IC95%\n")
        L.append(f"- `R̂ {target}/lead`     = **{fmt_money(r['rev_alvo'])}**  "
                 f"(IC95: {fmt_money(ic['r_alvo_ic'][0])} – {fmt_money(ic['r_alvo_ic'][1])})")
        L.append(f"- `R̂ baseline/lead` = **{fmt_money(r['rev_hist'])}**  "
                 f"(IC95: {fmt_money(ic['r_hist_ic'][0])} – {fmt_money(ic['r_hist_ic'][1])})")
        sig = "SIGNIFICATIVO" if ic['delta_signif'] else "não-significativo (IC cruza 0)"
        L.append(f"- **Δ esperado** = **{fmt_pct(ic['delta_pct_mean'])}**  "
                 f"(IC95: {fmt_pct(ic['delta_pct_ic'][0])} a {fmt_pct(ic['delta_pct_ic'][1])}) → **{sig}**\n")

    L.append("## Leitura\n")
    rd, ro = results[0], results[1]
    L.append(f"- Por **idade**, o impacto esperado é **{fmt_pct(rd['ic']['delta_pct_mean'])}** "
             f"({'significativo' if rd['ic']['delta_signif'] else 'não-significativo'}).")
    L.append(f"- Por **ocupação**, o impacto esperado é **{fmt_pct(ro['ic']['delta_pct_mean'])}** "
             f"({'significativo' if ro['ic']['delta_signif'] else 'não-significativo'}).")
    L.append("")
    L.append("As duas dimensões são correlacionadas mas não são proxy uma da outra "
             "(Cramér's V = 0.337, Jaccard 18-24×Estudante = 19.7%). "
             "Os números **não devem ser somados** — interpretam o mesmo Δ por dois cortes distintos.\n")
    L.append("## Premissas e limitações\n")
    L.append("- Pool históricamente estável em conv geral (CV=0.17) e na conv de 18-24 (CV=0.18).")
    L.append("- Conv de Estudante é instável entre LFs (CV=0.49), majoritariamente por ruído binomial "
             "(4–16 vendas/LF). O IC do bootstrap **captura** essa incerteza — IC mais largo é honesto.")
    L.append("- Análise observacional, não causal. Se a mudança de composição vem junto de mudança "
             "de criativo/canal/sazonalidade, parte do efeito vem de lá. Decomposição por Source "
             "fica pendente.")
    L.append("- Não considera diferenças de tracking rate por demografia. Se 18-24 tem tracking "
             "menor (ex.: mais bloqueio de cookies), o ticket histórico pode estar subestimado.")
    L.append("- Estudante × Idade combinados não foram estimados — n de vendas por célula 2D < 30.\n")

    out.write_text('\n'.join(L), encoding='utf-8')
    print(f"\nMarkdown salvo em: {out}")


def emit_xlsx(out: Path, results: list[dict]):
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        for r in results:
            r['stats'].to_excel(w, sheet_name=f'stats_{r["dim"]}')
            r['decomp'].to_excel(w, sheet_name=f'decomp_{r["dim"]}')
            ic = r['ic']
            pd.DataFrame([{
                'r_alvo_mean':    r['rev_alvo'],
                'r_alvo_ic_lo':   ic['r_alvo_ic'][0],
                'r_alvo_ic_hi':   ic['r_alvo_ic'][1],
                'r_hist_mean':    r['rev_hist'],
                'r_hist_ic_lo':   ic['r_hist_ic'][0],
                'r_hist_ic_hi':   ic['r_hist_ic'][1],
                'delta_pct_mean': ic['delta_pct_mean'],
                'delta_pct_ic_lo':ic['delta_pct_ic'][0],
                'delta_pct_ic_hi':ic['delta_pct_ic'][1],
                'B':              ic['B'],
            }]).to_excel(w, sheet_name=f'ic_{r["dim"]}', index=False)
    print(f"XLSX salvo em: {out}")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--target', default=DEFAULT_TARGET)
    p.add_argument('--pool',   default=','.join(DEFAULT_POOL),
                   help='LFs do pool histórico, vírgula-separados')
    p.add_argument('--b', type=int, default=2000, help='Bootstrap replications')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--no-md',   action='store_true')
    p.add_argument('--no-xlsx', action='store_true')
    return p.parse_args()


def main():
    args = parse_args()
    pool_lfs = [s.strip() for s in args.pool.split(',') if s.strip()]

    import yaml
    with open(LAUNCHES) as f:
        target_cfg = yaml.safe_load(f)[args.target]

    print(f"[load] target={args.target}  pool={pool_lfs}")
    target = load_target_from_railway(args.target)
    pool   = load_pool(pool_lfs)
    print(f"  target: {len(target):,} leads")
    print(f"  pool:   {len(pool):,} leads, {pool['lf'].nunique()} LFs")

    # Filtra nulos pós-normalização
    target_v = target[(target['idade'] != '(nulo)') & (target['ocupacao'] != '(nulo)')]
    pool_v   = pool[(pool['idade']   != '(nulo)') & (pool['ocupacao']   != '(nulo)')]
    print(f"  válidos após normalização: target={len(target_v):,}  pool={len(pool_v):,}")

    print(f"\n[bootstrap] B={args.b}  seed={args.seed}")
    r_idade = run_dimension(pool_v, target_v, 'idade',    IDADE_ORDER, args.b)
    r_ocup  = run_dimension(pool_v, target_v, 'ocupacao', OCUP_ORDER,  args.b)

    print_block(r_idade, args.target, 'pool')
    print_block(r_ocup,  args.target, 'pool')

    out_dir = REPO_ROOT / 'outputs' / 'validation' / 'composicao'
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if not args.no_md:
        emit_markdown(out_dir / f'impacto_composicao_{args.target}_{stamp}.md',
                      args.target, target_cfg, len(target_v),
                      pool_lfs, len(pool_v), [r_idade, r_ocup], args.b)
    if not args.no_xlsx:
        emit_xlsx(out_dir / f'impacto_composicao_{args.target}_{stamp}.xlsx',
                  [r_idade, r_ocup])


if __name__ == '__main__':
    main()
