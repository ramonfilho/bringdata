"""Deriva thresholds_roas_v1 (D01–D10) testando múltiplas janelas de CPL.

Bloco F/3b do EVENTOS_E_DECIS_PLANO — produz o JSON que vai pra
`configs/active_models/devclub.yaml` em `variants.<x>.roas_v1.thresholds`.

Metodologia:
  1. Carrega snapshot 120d `analise_roas_matched.parquet` (119k leads,
     233 vendas matched, 87 dias úteis).
  2. Aplica `IsotonicCalibrator` do Champion sobre cada `leadScore` raw
     → `prob_calibrada`.
  3. Pra cada janela W ∈ {7, 14, 30, 60, 120}:
       a. Reconstrói série temporal diária por adset agregando
          `spend_adset_day` e `n_leads_in_adset_day` (group by
          (adset_id, captura_date).first()).
       b. Pra cada (adset_id, captura_date), computa CPL_W rolling:
          `sum(spend nos W dias ANTERIORES) / sum(leads nos W dias ANTERIORES)`.
          Janela exclui o dia do lead pra evitar look-ahead leakage.
       c. Junta com leads → `cpl_window` por lead.
       d. `retorno_esperado = prob_calib × ticket_avista ÷ cpl_window`.
       e. qcut em 10 decis → tabela de % vendas e ROAS realizado por decil.
       f. Salva thresholds em `outputs/roas/roas_v1_thresholds_W{W}.json`.
  4. Tabela comparativa: lift no top decil + ROAS realizado D9+D10 por janela.

`ticket_avista` vem do business config — espelho do que `analise_roas_a_vista.py`
usa pra projetar ganho líquido aos stakeholders. Não é o "ticket contratado"
(R$ 2.200) — é o cash que efetivamente entra na semana do carrinho
(cartão líquido + 1ª parcela do boleto ≈ R$ 829).

Uso:
  python scripts/derive_roas_v1_thresholds.py \\
      --parquet /Users/.../bring_data-roas/V2/outputs/roas/analise_roas_matched.parquet \\
      --calibrator V2/mlruns/1/d51757f5041c44b7ab1a056fce8c3c35-calibrated-isotonic/artifacts/calibrator.pkl \\
      --output-dir V2/outputs/roas \\
      --windows 7,14,30,60,120
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Adicionar V2 ao path pro joblib.load resolver src.model.calibration.IsotonicCalibrator
_V2_ROOT = Path(__file__).resolve().parent.parent
if str(_V2_ROOT) not in sys.path:
    sys.path.insert(0, str(_V2_ROOT))

import joblib
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("derive_roas_v1_thresholds")


def _load_business_constants(client_config_path: Path) -> dict:
    """Pega ticket_avista do business config (espelho do analise_roas_a_vista.py)."""
    import yaml
    biz = yaml.safe_load(open(client_config_path)).get("business", {})
    pct_cartao = biz.get("pct_cartao_historico", 0.469)
    pct_boleto = 1.0 - pct_cartao
    guru_ticket = biz.get("guru_ticket_price", 1997.0)
    realizacao = biz.get("guru_realizacao_factor", 0.87)
    ticket_cont = biz.get("ticket_contracted", 2200.0)
    n_parcelas = biz.get("n_parcelas_boleto", 12)
    parcela_boleto = ticket_cont / n_parcelas
    ticket_avista = pct_cartao * guru_ticket * realizacao + pct_boleto * parcela_boleto
    return {
        "ticket_avista": ticket_avista,
        "pct_cartao": pct_cartao,
        "guru_ticket": guru_ticket,
        "realizacao": realizacao,
        "ticket_contracted": ticket_cont,
        "n_parcelas": n_parcelas,
        "tracking_rate": biz.get("tracking_rate", 0.528),
    }


def _build_adset_daily_series(df: pd.DataFrame) -> pd.DataFrame:
    """Reconstrói série temporal diária por adset: 1 linha por (adset, date) com
    spend e leads daquele dia. Múltiplos leads do mesmo dia compartilham o
    mesmo (spend_adset_day, n_leads_in_adset_day) — pegamos o primeiro.
    """
    daily = (
        df.dropna(subset=["matched_adset_id"])
          .groupby(["matched_adset_id", "captura_date"], as_index=False)
          .agg(
              spend_day=("spend_adset_day", "first"),
              leads_day=("n_leads_in_adset_day", "first"),
          )
    )
    # Ordena por adset + data pra rolling
    daily["captura_date"] = pd.to_datetime(daily["captura_date"])
    daily = daily.sort_values(["matched_adset_id", "captura_date"]).reset_index(drop=True)
    return daily


def _compute_rolling_cpl(daily: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Pra cada (adset, date), CPL_W = sum(spend nos W dias ANTERIORES) /
    sum(leads nos W dias ANTERIORES). Exclui o dia do lead.

    Implementação: por adset, indexa por data, faz reindex pra preencher dias
    vazios, aplica rolling com fechamento "left" (exclui dia atual). Pra
    ad sets que rodaram poucos dias e cuja janela cai antes do início do
    histórico → CPL_W é NaN (lead será descartado pra evitar viés).
    """
    rows = []
    for adset_id, g in daily.groupby("matched_adset_id"):
        g = g.set_index("captura_date").sort_index()
        # Reindex diário pra rolling não pular dias sem dado
        full_idx = pd.date_range(g.index.min(), g.index.max(), freq="D")
        g = g.reindex(full_idx)
        # Rolling W dias ANTERIORES (closed='left' exclui o dia atual)
        spend_W = g["spend_day"].fillna(0).rolling(window=window_days, min_periods=1, closed="left").sum()
        leads_W = g["leads_day"].fillna(0).rolling(window=window_days, min_periods=1, closed="left").sum()
        cpl_W = np.where(leads_W > 0, spend_W / leads_W, np.nan)
        g_out = pd.DataFrame({
            "matched_adset_id": adset_id,
            "captura_date": g.index,
            f"cpl_W{window_days}": cpl_W,
            f"leads_W{window_days}": leads_W,
        })
        rows.append(g_out)
    return pd.concat(rows, ignore_index=True)


def _build_thresholds_dict(cuts: pd.Series) -> dict:
    """qcut produziu IntervalIndex com 10 buckets. Extrai threshold_min/max
    no schema do `atribuir_decil_por_threshold` (D01–D10).
    """
    intervals = cuts.cat.categories
    thresholds = {}
    for i, iv in enumerate(intervals, start=1):
        thresholds[f"D{i:02d}"] = {
            "threshold_min": float(iv.left if i > 1 else 0.0),
            "threshold_max": float(iv.right if i < 10 else 1e9),
        }
    return thresholds


def _run_window(
    df: pd.DataFrame,
    daily: pd.DataFrame,
    W: int,
    ticket_avista: float,
    tracking_rate: float,
    output_dir: Path,
) -> dict:
    """Computa CPL_W, retorno_esperado, decis, lift, ROAS. Salva thresholds.
    Devolve sumário pra tabela comparativa.
    """
    logger.info(f"\n=== Window W={W} dias ===")
    rolling = _compute_rolling_cpl(daily, W)
    df_w = df.copy()
    df_w["captura_date"] = pd.to_datetime(df_w["captura_date"])
    df_w = df_w.merge(rolling, on=["matched_adset_id", "captura_date"], how="left")
    cpl_col = f"cpl_W{W}"

    n_total = len(df_w)
    cobertura = df_w[cpl_col].notna().sum()
    logger.info(f"  cobertura CPL_W{W}: {cobertura:,}/{n_total:,} ({cobertura/n_total*100:.1f}%)")

    valid = df_w[df_w[cpl_col].notna() & (df_w[cpl_col] > 0)].copy()
    valid["retorno_esperado"] = valid["prob_calibrada"] * ticket_avista / valid[cpl_col]

    # qcut em 10 decis (label 1..10 = D01..D10)
    valid["decil_W"] = pd.qcut(
        valid["retorno_esperado"], q=10, labels=False, duplicates="drop"
    ) + 1
    # Schema compatível: nome D01..D10
    valid["decil_W_str"] = "D" + valid["decil_W"].astype(int).astype(str).str.zfill(2)

    # Tabela por decil
    grp = valid.groupby("decil_W").agg(
        n_leads=("lead_id", "size"),
        n_vendas=("converted", "sum"),
        retorno_mean=("retorno_esperado", "mean"),
        cpl_mean=(cpl_col, "mean"),
        spend_total=(cpl_col, "sum"),  # proxy: soma dos CPLs (ROAS exato requer cost por lead)
    )
    grp["pct_vendas"] = grp["n_vendas"] / grp["n_vendas"].sum() * 100
    grp["lift"] = grp["pct_vendas"] / 10  # baseline uniforme = 10%/decil

    # ROAS realizado por decil — replica a fórmula do PDF (a vista + tracking_rate)
    grp_roas = valid.groupby("decil_W").apply(lambda g: pd.Series({
        "vendas_real_estim": g["converted"].sum() / tracking_rate,
        "receita_avista_estim": (g["converted"].sum() / tracking_rate) * ticket_avista,
        "cost_total": g[cpl_col].sum(),
    }))
    grp_roas["ROAS_avista"] = np.where(
        grp_roas["cost_total"] > 0, grp_roas["receita_avista_estim"] / grp_roas["cost_total"], 0
    )

    print("\n  decil | n_leads | n_vendas | %_vendas | lift  | CPL_mean | retorno_mean | ROAS_à_vista")
    print("  " + "-" * 88)
    for d in range(1, 11):
        n_leads = grp["n_leads"].get(d, 0)
        n_vendas = grp["n_vendas"].get(d, 0)
        pct = grp["pct_vendas"].get(d, 0.0)
        lift = grp["lift"].get(d, 0.0)
        cpl = grp["cpl_mean"].get(d, 0.0)
        ret = grp["retorno_mean"].get(d, 0.0)
        roas = grp_roas["ROAS_avista"].get(d, 0.0)
        print(f"  D{d:02d}   | {n_leads:>7,} | {n_vendas:>8} | {pct:>7.2f}% | {lift:>5.2f} | R${cpl:>6.2f} | {ret:>11.3f} | {roas:>10.3f}×")

    # Métricas resumidas
    pct_top10 = grp["pct_vendas"].get(10, 0)
    pct_top20 = grp["pct_vendas"].get(10, 0) + grp["pct_vendas"].get(9, 0)
    pct_top30 = pct_top20 + grp["pct_vendas"].get(8, 0)
    roas_d10 = grp_roas["ROAS_avista"].get(10, 0)
    roas_d9_d10 = (grp_roas["receita_avista_estim"].get(9, 0) + grp_roas["receita_avista_estim"].get(10, 0)) / \
                  max(grp_roas["cost_total"].get(9, 0) + grp_roas["cost_total"].get(10, 0), 1e-9)
    roas_d8_d10 = (grp_roas["receita_avista_estim"].get(8, 0) + grp_roas["receita_avista_estim"].get(9, 0) + grp_roas["receita_avista_estim"].get(10, 0)) / \
                  max(grp_roas["cost_total"].get(8, 0) + grp_roas["cost_total"].get(9, 0) + grp_roas["cost_total"].get(10, 0), 1e-9)

    # Thresholds pra YAML
    cuts = pd.qcut(valid["retorno_esperado"], q=10, retbins=True, duplicates="drop")
    thresholds = _build_thresholds_dict(cuts[0])
    out_path = output_dir / f"roas_v1_thresholds_W{W}.json"
    out_path.write_text(json.dumps({
        "window_days": W,
        "ticket_avista": ticket_avista,
        "n_leads_used": len(valid),
        "n_vendas_used": int(valid["converted"].sum()),
        "thresholds": thresholds,
    }, indent=2))
    logger.info(f"  thresholds salvos em {out_path}")

    return {
        "W": W,
        "cobertura_pct": cobertura/n_total*100,
        "n_leads_used": len(valid),
        "pct_vendas_D10": pct_top10,
        "pct_vendas_D9_D10": pct_top20,
        "pct_vendas_D8_D10": pct_top30,
        "lift_D10": grp["lift"].get(10, 0),
        "ROAS_D10": roas_d10,
        "ROAS_D9_D10": roas_d9_d10,
        "ROAS_D8_D10": roas_d8_d10,
        "thresholds_path": str(out_path),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parquet", required=True)
    p.add_argument("--calibrator", required=True)
    p.add_argument("--output-dir", default="outputs/roas")
    p.add_argument("--client-config", default="configs/clients/devclub.yaml")
    p.add_argument("--windows", default="7,14,30,60,120")
    args = p.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"carregando parquet {args.parquet}")
    df = pd.read_parquet(args.parquet)
    logger.info(f"  {len(df):,} leads | {df['converted'].sum()} vendas matched")

    # Aplicar calibrador no leadScore
    logger.info(f"carregando calibrador {args.calibrator}")
    calib = joblib.load(args.calibrator)
    df["prob_calibrada"] = calib.transform(df["leadScore"].values)
    logger.info(f"  prob_calib: min={df['prob_calibrada'].min():.6f} mean={df['prob_calibrada'].mean():.6f} max={df['prob_calibrada'].max():.6f}")

    # Business constants
    biz = _load_business_constants(Path(args.client_config))
    logger.info(f"  ticket_avista: R$ {biz['ticket_avista']:.2f}  tracking_rate: {biz['tracking_rate']}")

    daily = _build_adset_daily_series(df)
    logger.info(f"  série temporal: {len(daily):,} (adset, date) pares de {daily['matched_adset_id'].nunique()} adsets")

    windows = [int(w) for w in args.windows.split(",")]
    summaries = []
    for W in windows:
        try:
            s = _run_window(df, daily, W, biz["ticket_avista"], biz["tracking_rate"], output_dir)
            summaries.append(s)
        except Exception as e:
            logger.error(f"  W={W} falhou: {e}")

    # Tabela comparativa final
    print("\n" + "=" * 130)
    print("COMPARATIVA FINAL — qual janela maximiza concentração de vendas / ROAS no topo?")
    print("=" * 130)
    print(f"  W  | cobertura | n_leads  | %vendas D10 | %vendas D9+D10 | %vendas D8+D10 | lift D10 | ROAS D10 | ROAS D9+D10 | ROAS D8+D10")
    print("  " + "-" * 130)
    for s in summaries:
        print(f"  {s['W']:>3}d | {s['cobertura_pct']:>7.1f}% | {s['n_leads_used']:>7,}  | "
              f"{s['pct_vendas_D10']:>9.2f}%  | {s['pct_vendas_D9_D10']:>11.2f}%   | {s['pct_vendas_D8_D10']:>11.2f}%   | "
              f"{s['lift_D10']:>6.2f}   | {s['ROAS_D10']:>6.2f}×  | {s['ROAS_D9_D10']:>8.2f}×   | {s['ROAS_D8_D10']:>8.2f}×")

    # Salva sumário
    summary_path = output_dir / "roas_v1_windows_comparison.json"
    summary_path.write_text(json.dumps(summaries, indent=2))
    print(f"\nsumário salvo em {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
