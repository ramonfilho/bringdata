"""
dt12_impact_analysis.py — Quantifica impacto do bug DT-12 em produção.

Busca leads reais do Railway (não-ML_MAR), roda o modelo jan30 duas vezes:
  1. Com encoding correto (ordinal para idade/salário) — estado APÓS o fix
  2. Com encoding bugado (OHE default → colunas ordinais ficam 0) — estado ANTES do fix

Compara scores, correlação de ranking e distribuição por decil.

Uso:
    cd V2/
    python scripts/dt12_impact_analysis.py
    python scripts/dt12_impact_analysis.py --limit 500 --days 7
"""

import sys
import os
import argparse
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s - %(message)s")

import pandas as pd
import numpy as np


def fetch_leads(limit: int, days: int) -> list[dict]:
    import pg8000.native

    host     = os.environ.get("RAILWAY_DB_HOST", "shortline.proxy.rlwy.net")
    port     = int(os.environ.get("RAILWAY_DB_PORT", "11594"))
    database = os.environ.get("RAILWAY_DB_NAME", "railway")
    user     = os.environ.get("RAILWAY_DB_USER", "postgres")
    password = os.environ.get("RAILWAY_DB_PASSWORD", "THxguXxQPZaSWIzquYRiLlVhJBnPoRGu")

    conn = pg8000.native.Connection(
        host=host, port=port, database=database, user=user, password=password
    )
    rows = conn.run(f"""
        SELECT id, data, "nomeCompleto", email, telefone, pesquisa,
               source, medium, campaign, content, term,
               "remoteIp", "userAgent", fbc, fbp, "pageUrl"
        FROM "Lead"
        WHERE "leadScore" IS NOT NULL
          AND "createdAt" >= NOW() - INTERVAL '{days} days'
          AND (campaign NOT ILIKE '%ML_MAR%' OR campaign IS NULL)
        ORDER BY "createdAt" DESC
        LIMIT {limit}
    """)
    conn.close()

    col_names = ["id","data","nomeCompleto","email","telefone","pesquisa",
                 "source","medium","campaign","content","term",
                 "remoteIp","userAgent","fbc","fbp","pageUrl"]
    leads = []
    for row in rows:
        lead = dict(zip(col_names, row))
        if isinstance(lead.get("pesquisa"), str):
            try:
                lead["pesquisa"] = json.loads(lead["pesquisa"])
            except Exception:
                lead["pesquisa"] = {}
        leads.append(lead)
    return leads


def leads_to_df(leads: list[dict]) -> pd.DataFrame:
    from api.railway_mapping import railway_lead_to_sheets_row
    rows = []
    for lead in leads:
        try:
            row = railway_lead_to_sheets_row(lead)
            if row:
                rows.append(row)
        except Exception:
            pass
    return pd.DataFrame(rows)


def run_pipeline(df: pd.DataFrame, pipeline, predictor_ov, enc_overrides) -> pd.Series | None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        df.to_csv(tmp, index=False)
        tmp_path = tmp.name
    try:
        result = pipeline.run(
            tmp_path,
            with_predictions=True,
            predictor_override=predictor_ov,
            encoding_overrides=enc_overrides,
        )
    finally:
        os.remove(tmp_path)
    if result is None or len(result) == 0:
        return None
    return result["lead_score"] if "lead_score" in result.columns else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--days",  type=int, default=7)
    args = parser.parse_args()

    print(f"\n=== DT-12 Impact Analysis ===")
    print(f"Buscando {args.limit} leads não-ML_MAR dos últimos {args.days} dias...\n")

    from src.production_pipeline import LeadScoringPipeline

    pipeline  = LeadScoringPipeline(client_id="devclub")
    ab_cfg    = pipeline._ab_test_config
    variant   = ab_cfg.variants["guru_jan30"]
    predictor = pipeline.get_variant_predictor("guru_jan30")
    enc_fix   = variant.encoding_overrides   # ordinal (correto)
    enc_bug   = None                          # OHE default (bugado)

    leads = fetch_leads(args.limit, args.days)
    print(f"  Leads recuperados: {len(leads)}")

    df = leads_to_df(leads)
    print(f"  Leads mapeados:    {len(df)}")

    # Verificar preenchimento de idade/salário
    col_i = "Qual a sua idade?"
    col_s = "Atualmente, qual a sua faixa salarial?"
    for col in [col_i, col_s]:
        if col in df.columns:
            n = df[col].notna().sum()
            print(f"  {col}: {n}/{len(df)} preenchidos ({100*n/len(df):.0f}%)")

    print("\nRodando modelo com encoding CORRETO (fix)...")
    scores_fix = run_pipeline(df, pipeline, predictor, enc_fix)
    if scores_fix is None:
        print("ERRO: pipeline (fix) retornou vazio"); return

    print("Rodando modelo com encoding BUGADO (zeros em idade/salário)...")
    scores_bug = run_pipeline(df, pipeline, predictor, enc_bug)
    if scores_bug is None:
        print("ERRO: pipeline (bug) retornou vazio"); return

    n = min(len(scores_fix), len(scores_bug))
    sf = scores_fix.iloc[:n].reset_index(drop=True)
    sb = scores_bug.iloc[:n].reset_index(drop=True)

    # Correlação de ranking
    from scipy.stats import spearmanr
    rho, _ = spearmanr(sf, sb)

    print(f"\n{'='*50}")
    print(f"  N leads:          {n}")
    print(f"  Spearman ρ:       {rho:.4f}  (1.0 = ranking idêntico)")
    print(f"\n  Score médio:      fix={sf.mean():.4f}  bug={sb.mean():.4f}  Δ={sf.mean()-sb.mean():+.4f}")
    print(f"  Score mediana:    fix={sf.median():.4f}  bug={sb.median():.4f}  Δ={sf.median()-sb.median():+.4f}")
    print(f"  Desvio padrão:    fix={sf.std():.4f}   bug={sb.std():.4f}   Δ={sf.std()-sb.std():+.4f}")
    print(f"  Score máx:        fix={sf.max():.4f}  bug={sb.max():.4f}  Δ={sf.max()-sb.max():+.4f}")
    print(f"  Score mín:        fix={sf.min():.4f}  bug={sb.min():.4f}  Δ={sf.min()-sb.min():+.4f}")

    # Decil pelo quantil simples (sem thresholds do modelo)
    def to_decil(s: pd.Series) -> pd.Series:
        labels = [f"D{i:02d}" for i in range(1, 11)]
        return pd.qcut(s, q=10, labels=labels, duplicates="drop")

    decil_fix = to_decil(sf)
    decil_bug = to_decil(sb)

    changed = (decil_fix != decil_bug).sum()
    print(f"\n  Leads que mudaram de decil: {changed}/{n} ({100*changed/n:.1f}%)")

    print(f"\n  Distribuição por decil (fix vs bug):")
    dist_fix = decil_fix.value_counts().sort_index()
    dist_bug = decil_bug.value_counts().sort_index()
    print(f"  {'Decil':<8} {'Fix':>6} {'Bug':>6} {'Δ':>6}")
    for d in sorted(set(dist_fix.index) | set(dist_bug.index)):
        f = dist_fix.get(d, 0)
        b = dist_bug.get(d, 0)
        print(f"  {str(d):<8} {f:>6} {b:>6} {f-b:>+6}")

    # Top decil (D10): quem é promovido/rebaixado
    top_fix = set(sf.nlargest(n // 10).index)
    top_bug = set(sb.nlargest(n // 10).index)
    promoted   = len(top_fix - top_bug)
    demoted    = len(top_bug - top_fix)
    print(f"\n  Top 10% (D10 equivalente):")
    print(f"    Promovidos pelo fix (não estavam no top): {promoted}")
    print(f"    Rebaixados pelo fix (saíram do top):      {demoted}")

    print(f"\n{'='*50}")
    print(f"  Fix aplicado em: 01/04/2026 — commit 795770f (15:51 BRT)")
    print(f"  Antes do fix: colunas ordinais de idade/salário preenchidas com 0")
    print(f"  Após o fix:   encoding ordinal correto aplicado via encoding_overrides")
    print()


if __name__ == "__main__":
    main()
