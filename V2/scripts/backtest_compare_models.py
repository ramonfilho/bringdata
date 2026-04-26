#!/usr/bin/env python3
"""
backtest_compare_models.py

Backtest comparativo entre dois modelos sobre o mesmo dataset de um lançamento,
com cada modelo scorado pelo seu próprio pipeline de treino.

Fluxo em duas fases:

  FASE 1 — `--mode score` (rodar 2x, uma por worktree/pipeline):
    - Carrega leads do LF (capt window) via LeadDataLoader
    - Carrega vendas (Guru+TMB) via SalesDataLoader
    - Match leads↔vendas (email→telefone)
    - Score com o modelo escolhido (run_id MLflow)
    - Aplica decil_thresholds salvos no model_metadata.json (Opção B)
    - Imputa spend por lead via CampaignMetricsCalculator
    - Salva scored_<label>.parquet

  FASE 2 — `--mode compare` (rodar 1x, no main worktree):
    - Lê scored_<label>.parquet de ambos os modelos
    - Merge por email
    - Calcula métricas por decil para cada modelo
    - Calcula métricas comparativas (lift D10, top-30, top-50, ROAS)
    - Emite backtest.xlsx com múltiplas abas

Exemplo de uso:

    # 1. Score v4 (no main worktree atual, run-id Champion v4)
    python scripts/backtest_compare_models.py --mode score \\
        --lf LF52 --label v4 \\
        --run-id 60637bb98b94421b9c7579bb4ac1b1ad \\
        --output-dir files/validation/backtest_lf52/

    # 2. Score jan30 (no rollback worktree)
    git worktree add ../smart_ads_v2_rollback edf23e9
    cd ../smart_ads_v2_rollback
    python scripts/backtest_compare_models.py --mode score \\
        --lf LF52 --label jan30 \\
        --run-id d51757f5041c44b7ab1a056fce8c3c35 \\
        --output-dir ../bring_data/V2/files/validation/backtest_lf52/

    # 3. Comparar e emitir XLSX
    cd /Users/ramonmoreira/Desktop/bring_data
    python scripts/backtest_compare_models.py --mode compare \\
        --labels v4 jan30 \\
        --input-dir V2/files/validation/backtest_lf52/ \\
        --output V2/files/validation/backtest_lf52/backtest.xlsx
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # V2/
LAUNCHES_PATH = PROJECT_ROOT / "configs" / "launches.yaml"
DECIL_LABELS = [f"D{i:02d}" for i in range(1, 11)]  # D01..D10 — formato canônico
TOP30_DECILS = ["D08", "D09", "D10"]
TOP50_DECILS = ["D06", "D07", "D08", "D09", "D10"]


def _load_dotenv() -> None:
    """Carrega V2/.env em os.environ se existir e a var ainda não estiver setada.

    Parser minimalista: ignora comentários e linhas vazias, aceita aspas opcionais.
    Usado pra ter token Meta/Guru/Railway disponível sem precisar source no shell.
    """
    import os
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def load_launch_dates(lf: str) -> Dict[str, str]:
    with open(LAUNCHES_PATH) as f:
        launches = yaml.safe_load(f)
    if lf not in launches:
        raise ValueError(f"Lançamento {lf} não encontrado em {LAUNCHES_PATH}")
    return launches[lf]


def load_decil_thresholds(run_id: str, mlruns_root: Path) -> List[Tuple[str, float]]:
    """Lê os thresholds de decil do model_metadata.json e retorna lista
    ordenada [(label, threshold_min), ...] usada para bucketear scores.
    """
    candidates = list(mlruns_root.rglob(f"*/{run_id}/artifacts/model_metadata.json"))
    if not candidates:
        raise FileNotFoundError(
            f"model_metadata.json não encontrado para run_id={run_id} em {mlruns_root}"
        )
    with open(candidates[0]) as f:
        meta = json.load(f)
    thresholds = meta["decil_thresholds"]["thresholds"]

    # Ordena por threshold_min ascendente
    items = sorted(
        thresholds.items(), key=lambda kv: kv[1]["threshold_min"]
    )
    # Normaliza labels para formato canônico D01..D10 (caso o metadata tenha D1..D9)
    normalized = []
    for label, info in items:
        # extrai número do label (D1 → 1, D09 → 9, D10 → 10)
        num = int(label.lstrip("D"))
        canonical = f"D{num:02d}"
        normalized.append((canonical, float(info["threshold_min"])))
    return normalized


def score_to_decil(score: float, thresholds: List[Tuple[str, float]]) -> str:
    """Bucketea score num decil aplicando thresholds em ordem ascendente."""
    decil = thresholds[0][0]  # default: menor decil
    for label, t_min in thresholds:
        if score >= t_min:
            decil = label
        else:
            break
    return decil


# --------------------------------------------------------------------------- #
# Modo SCORE — carrega leads, vendas, scoreia, salva parquet
# --------------------------------------------------------------------------- #

def run_score_mode(args) -> None:
    """Executa FASE 1 — scoring + match + spend imputado."""
    lf_dates = load_launch_dates(args.lf)
    print(f"[score] LF={args.lf} cap={lf_dates['cap_start']}→{lf_dates['cap_end']} "
          f"vendas={lf_dates['vendas_start']}→{lf_dates['vendas_end']}")

    # Imports de módulos do projeto — feitos aqui pra cada worktree usar seu próprio
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.validation.data_loader import LeadDataLoader, SalesDataLoader
    from src.validation.matching import match_leads_to_sales
    from src.production_pipeline import LeadScoringPipeline

    # 1. Leads do período de captação — Railway (Sheets truncado desde 27/03)
    print("[score] carregando leads do Railway...")
    sales_loader = SalesDataLoader()
    leads_df = sales_loader.load_railway_leads(
        start_date=lf_dates["cap_start"],
        end_date=lf_dates["cap_end"],
    )
    print(f"[score]   {len(leads_df)} leads carregados do Railway")
    if len(leads_df) == 0:
        print("[score]   ⚠️  fallback Sheets (caso Railway esteja indisponível)...")
        leads_df = LeadDataLoader().load_leads_from_sheets(
            start_date=lf_dates["cap_start"],
            end_date=lf_dates["cap_end"],
        )
        print(f"[score]   Sheets fallback: {len(leads_df)} leads")

    # 2. Vendas do período de carrinho — Guru API + Hotmart API (TMB ignorado: requer files locais)
    print("[score] carregando vendas Guru API...")
    guru_df = sales_loader.load_guru_sales_from_api(
        start_date=lf_dates["vendas_start"],
        end_date=lf_dates["vendas_end"],
        save_excel=False,
    )
    print(f"[score]   Guru: {len(guru_df) if guru_df is not None else 0} vendas")

    print("[score] carregando vendas Hotmart API...")
    try:
        hotmart_df = sales_loader.load_hotmart_sales_from_api(
            start_date=lf_dates["vendas_start"],
            end_date=lf_dates["vendas_end"],
        )
        print(f"[score]   Hotmart: {len(hotmart_df) if hotmart_df is not None else 0} vendas")
    except Exception as e:
        print(f"[score]   ⚠️  Hotmart API falhou ({type(e).__name__}: {e}) — pulando")
        hotmart_df = None

    # Concatena Guru + Hotmart preservando schema comum (email, telefone, sale_value, sale_date, origem)
    parts = [df for df in (guru_df, hotmart_df) if df is not None and len(df) > 0]
    if not parts:
        raise RuntimeError("Nenhuma venda carregada de Guru nem Hotmart — abortando")
    sales_df = pd.concat(parts, ignore_index=True)
    print(f"[score]   total vendas consolidadas: {len(sales_df)}")

    # 3. Score: roda o LeadScoringPipeline forçando o run_id pedido
    print(f"[score] scoring com run_id={args.run_id}...")
    pipeline = LeadScoringPipeline(
        model_name=None,
        model_path=str(_resolve_model_path(args.run_id, args.mlruns_root)),
        client_id="devclub",
    )
    # `_score_with_pipeline` faz round-trip via xlsx temporário pra reusar `pipeline.run`
    leads_scored_df = _score_with_pipeline(pipeline, leads_df)

    # 4. Bucketing decil pelos thresholds salvos no MLflow (Opção B)
    thresholds = load_decil_thresholds(args.run_id, args.mlruns_root)
    print(f"[score] thresholds carregados: {len(thresholds)} faixas")
    leads_scored_df["decil"] = leads_scored_df["lead_score"].apply(
        lambda s: score_to_decil(s, thresholds) if pd.notna(s) else None
    )

    # 5. Match leads↔vendas (sem janela temporal de 30d — carrinho é curto e fechado)
    print("[score] matching leads↔vendas...")
    matched = match_leads_to_sales(
        leads_scored_df, sales_df, use_temporal_validation=False
    )

    # 6. Spend imputado por campanha (CPL = spend / leads_da_campanha)
    print("[score] imputando spend por lead...")
    matched = _attach_imputed_spend(matched, lf_dates)

    # 7. Salvar parquet
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = [
        "email", "campaign", "lead_score", "decil",
        "converted", "sale_value", "sale_origin", "match_method",
        "spend_imputado",
    ]
    cols_present = [c for c in cols if c in matched.columns]
    out_path = out_dir / f"scored_{args.label}.parquet"
    matched[cols_present].to_parquet(out_path, index=False)
    print(f"[score] ✅ salvo em {out_path} ({len(matched)} linhas)")


def _resolve_model_path(run_id: str, mlruns_root: Path) -> Path:
    """Encontra o diretório de artifacts do run_id no mlruns local."""
    candidates = list(mlruns_root.rglob(f"*/{run_id}/artifacts"))
    if not candidates:
        raise FileNotFoundError(f"Artifacts não encontrados para run_id={run_id}")
    return candidates[0]


def _score_with_pipeline(pipeline, leads_df: pd.DataFrame) -> pd.DataFrame:
    """Score leads_df reusando o flow padrão da LeadScoringPipeline (`pipeline.run`).

    Estratégia: serializar leads_df num xlsx temporário e chamar `pipeline.run`,
    que faz load → preprocess → predict de forma idêntica à produção. Garante
    paridade com o que cada worktree (main/rollback) produz em runtime.
    """
    import tempfile

    df = leads_df.copy()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        df.to_excel(tmp_path, index=False)
        scored = pipeline.run(filepath=tmp_path, with_predictions=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Uniformizar coluna de score
    if "lead_score" not in scored.columns:
        for alt in ("probability", "score", "prediction_proba"):
            if alt in scored.columns:
                scored["lead_score"] = scored[alt]
                break
        else:
            raise RuntimeError(
                "Nenhuma coluna de score encontrada no output da pipeline "
                f"(colunas: {list(scored.columns)[:20]})"
            )

    # Recuperar colunas que match_leads_to_sales exige (email, telefone, data_captura)
    # + campaign para spend imputation. Originais ficam em pipeline.original_data.
    aliases = {
        "email":        ["email", "E-mail", "e-mail", "E-Mail", "Email"],
        "telefone":     ["telefone", "Telefone", "Phone", "phone", "telephone"],
        "data_captura": ["data_captura", "Data", "data", "DATA", "createdAt", "Data Cadastro"],
        "campaign":     ["campaign", "Campaign", "utm_campaign"],
    }
    original = getattr(pipeline, "original_data", None)
    for canonical, candidates in aliases.items():
        if canonical in scored.columns:
            continue
        recovered = None
        for src_df in (original, df):
            if src_df is None:
                continue
            for c in candidates:
                if c in src_df.columns:
                    recovered = src_df[c].reset_index(drop=True)
                    break
            if recovered is not None:
                break
        if recovered is None:
            if canonical == "email":
                raise RuntimeError(
                    f"Coluna email não encontrada. Original cols: "
                    f"{list(original.columns)[:30] if original is not None else 'N/A'}"
                )
            # Outras colunas: deixar NaN (matching ainda funciona com email só)
            scored[canonical] = pd.NA
            continue
        # Alinhar índice (preprocess pode dropar; em geral Railway preserva 1:1)
        if len(recovered) != len(scored):
            n = min(len(recovered), len(scored))
            recovered = recovered.iloc[:n].reset_index(drop=True)
            scored = scored.iloc[:n].reset_index(drop=True)
        scored[canonical] = recovered.values

    # Normalizar email/telefone pra bater com vendas
    scored["email"] = scored["email"].astype(str).str.lower().str.strip()
    scored["telefone"] = scored["telefone"].astype(str).str.replace(r"\D", "", regex=True)
    scored.loc[scored["telefone"].isin(["", "nan", "<NA>"]), "telefone"] = pd.NA
    return scored


def _attach_imputed_spend(matched: pd.DataFrame, lf_dates: Dict) -> pd.DataFrame:
    """Adiciona coluna `spend_imputado` = spend_da_campanha / leads_da_campanha.

    Estratégia:
      1. Lê `meta_account_ids` de `configs/validation_config.yaml`
      2. Para cada conta, chama `MetaAdsIntegration.get_insights(level='campaign',
         since_date=cap_start, until_date=cap_end + 1 dia)` — Meta API trata
         `until` como exclusivo, então somamos 1 dia ao cap_end
      3. Constrói dict {campaign_name → spend_total}
      4. Conta leads por campanha no `matched` e calcula CPL = spend / n_leads
      5. Cada lead recebe o CPL da sua campanha como `spend_imputado`

    Se token Meta ausente, API falhar ou yaml não tiver `meta_account_ids`,
    deixa NaN e avisa — fase `compare` detecta e gera ROAS=NaN graciosamente.
    """
    matched = matched.copy()
    matched["spend_imputado"] = np.nan

    if "campaign" not in matched.columns:
        print("[score]   ⚠️  coluna 'campaign' ausente no matched — spend deixado NaN")
        return matched

    val_config_path = PROJECT_ROOT / "configs" / "validation_config.yaml"
    if not val_config_path.exists():
        print(f"[score]   ⚠️  {val_config_path} não encontrado — spend deixado NaN")
        return matched

    with open(val_config_path) as f:
        val_cfg = yaml.safe_load(f) or {}
    account_ids = val_cfg.get("meta_account_ids", [])
    if not account_ids:
        print("[score]   ⚠️  meta_account_ids vazio em validation_config.yaml — spend NaN")
        return matched

    try:
        from api.meta_integration import MetaAdsIntegration
    except Exception as e:
        print(f"[score]   ⚠️  import MetaAdsIntegration falhou ({type(e).__name__}: {e}) — spend NaN")
        return matched

    # Meta API: until é exclusivo na API. Somar 1 dia ao cap_end pra incluí-lo.
    from datetime import datetime, timedelta
    cap_start = lf_dates["cap_start"]
    cap_end_inclusive = (
        datetime.strptime(lf_dates["cap_end"], "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")

    import os
    meta_token = os.environ.get("META_ACCESS_TOKEN")
    if not meta_token:
        print("[score]   ⚠️  META_ACCESS_TOKEN ausente — spend NaN")
        return matched
    try:
        meta = MetaAdsIntegration(access_token=meta_token)
    except Exception as e:
        print(f"[score]   ⚠️  MetaAdsIntegration() falhou ({type(e).__name__}: {e}) — spend NaN")
        return matched

    spend_by_campaign: Dict[str, float] = {}
    for acc in account_ids:
        try:
            insights = meta.get_insights(
                account_id=acc,
                level="campaign",
                since_date=cap_start,
                until_date=cap_end_inclusive,
                fields=["campaign_name", "spend"],
            )
        except Exception as e:
            print(f"[score]   ⚠️  get_insights({acc}) falhou: {e}")
            continue
        for row in insights:
            name = row.get("campaign_name")
            try:
                spend = float(row.get("spend", 0) or 0)
            except (TypeError, ValueError):
                spend = 0.0
            if name:
                spend_by_campaign[name] = spend_by_campaign.get(name, 0.0) + spend
    print(f"[score]   spend coletado para {len(spend_by_campaign)} campanhas")

    if not spend_by_campaign:
        print("[score]   ⚠️  nenhum spend retornado pela Meta — deixando NaN")
        return matched

    leads_by_campaign = matched.groupby("campaign").size().to_dict()
    cpl_by_campaign = {
        name: (spend / leads_by_campaign[name])
        for name, spend in spend_by_campaign.items()
        if leads_by_campaign.get(name, 0) > 0
    }

    matched["spend_imputado"] = matched["campaign"].map(cpl_by_campaign)
    n_attributed = matched["spend_imputado"].notna().sum()
    print(f"[score]   spend imputado para {n_attributed}/{len(matched)} leads")
    return matched


# --------------------------------------------------------------------------- #
# Modo COMPARE — consolida e emite XLSX
# --------------------------------------------------------------------------- #

def run_compare_mode(args) -> None:
    """Executa FASE 2 — consolida parquets e emite XLSX com várias abas."""
    in_dir = Path(args.input_dir)
    parquets = {
        label: pd.read_parquet(in_dir / f"scored_{label}.parquet")
        for label in args.labels
    }
    for label, df in parquets.items():
        print(f"[compare] {label}: {len(df)} leads, "
              f"{df['converted'].sum()} conversões, "
              f"{df['spend_imputado'].notna().sum()} com spend")

    # Merge por email — só leads que aparecem em ambos os modelos
    merged = parquets[args.labels[0]][["email", "decil", "converted", "sale_value", "spend_imputado"]] \
        .rename(columns={"decil": f"decil_{args.labels[0]}"})
    for label in args.labels[1:]:
        df = parquets[label][["email", "decil"]].rename(columns={"decil": f"decil_{label}"})
        merged = merged.merge(df, on="email", how="inner")
    print(f"[compare] após merge: {len(merged)} leads em comum")

    # Tabelas por decil para cada modelo
    decile_tables = {label: _decile_table(merged, f"decil_{label}") for label in args.labels}

    # Summary comparativo
    summary = _summary_table(merged, args.labels)

    # Cross-tab decil × decil (concordância de ranqueamento)
    if len(args.labels) == 2:
        cross = pd.crosstab(
            merged[f"decil_{args.labels[0]}"],
            merged[f"decil_{args.labels[1]}"],
            margins=True, margins_name="Total",
        ).reindex(DECIL_LABELS + ["Total"], fill_value=0) \
         .reindex(columns=DECIL_LABELS + ["Total"], fill_value=0)
    else:
        cross = pd.DataFrame()

    # Params/metadata
    params = pd.DataFrame([
        {"key": "labels", "value": ", ".join(args.labels)},
        {"key": "n_leads_merged", "value": len(merged)},
        {"key": "n_conversions", "value": int(merged["converted"].sum())},
        {"key": "total_revenue", "value": float(merged["sale_value"].sum())},
        {"key": "total_spend",   "value": float(merged["spend_imputado"].sum(skipna=True))},
        {"key": "ressalva_1", "value": "Viés de seleção: leads foram capturados pelo Meta otimizando para o sinal do baseline."},
        {"key": "ressalva_2", "value": "Spend imputado: rateado por campanha (spend_total/n_leads_campanha) — não é spend observado por lead."},
        {"key": "ressalva_3", "value": "ROAS offline contrafactual: 'se o modelo X tivesse ranqueado, qual ROAS apareceria por decil?' — não é ROAS produzido por decisão online do Meta."},
    ])

    # Escreve XLSX com múltiplas abas
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="summary", index=True)
        for label, tab in decile_tables.items():
            tab.to_excel(writer, sheet_name=f"decile_{label}", index=True)
        if not cross.empty:
            cross.to_excel(writer, sheet_name="cross_tab", index=True)
        params.to_excel(writer, sheet_name="params", index=False)

    print(f"[compare] ✅ XLSX salvo em {out_path}")


def _decile_table(df: pd.DataFrame, decil_col: str) -> pd.DataFrame:
    """Métricas por decil para o modelo identificado por decil_col."""
    g = df.groupby(decil_col).agg(
        leads=("email", "count"),
        conversions=("converted", "sum"),
        revenue=("sale_value", "sum"),
        spend=("spend_imputado", lambda x: x.sum(skipna=True)),
    )
    g["conv_pct"] = g["conversions"] / g["leads"]
    g["roas"] = np.where(g["spend"] > 0, g["revenue"] / g["spend"], np.nan)
    overall_conv = df["converted"].sum() / len(df) if len(df) > 0 else 0
    g["lift"] = g["conv_pct"] / overall_conv if overall_conv > 0 else np.nan
    g["leads_pct"] = g["leads"] / g["leads"].sum()
    return g.reindex(DECIL_LABELS, fill_value=0).round(4)


def _summary_table(merged: pd.DataFrame, labels: List[str]) -> pd.DataFrame:
    """Métricas comparativas: lift D10, top-30 e top-50 (concentração + ROAS)."""
    rows = {}
    for label in labels:
        decil_col = f"decil_{label}"
        total_conv = merged["converted"].sum()
        total_revenue = merged["sale_value"].sum()
        total_spend = merged["spend_imputado"].sum(skipna=True)
        total_leads = len(merged)
        baseline_conv_pct = total_conv / total_leads if total_leads > 0 else 0

        d10 = merged[merged[decil_col] == "D10"]
        d10_conv_pct = d10["converted"].sum() / len(d10) if len(d10) > 0 else 0
        lift_d10 = d10_conv_pct / baseline_conv_pct if baseline_conv_pct > 0 else np.nan

        top30 = merged[merged[decil_col].isin(TOP30_DECILS)]
        top50 = merged[merged[decil_col].isin(TOP50_DECILS)]

        rows[label] = {
            "leads_total": total_leads,
            "conv_total": total_conv,
            "conv_pct_global": baseline_conv_pct,
            "leads_d10": len(d10),
            "leads_d10_pct": len(d10) / total_leads if total_leads else 0,
            "conv_d10": int(d10["converted"].sum()),
            "conv_pct_d10": d10_conv_pct,
            "lift_d10": lift_d10,
            "leads_top30_pct": len(top30) / total_leads if total_leads else 0,
            "conv_concentracao_top30": top30["converted"].sum() / total_conv if total_conv else 0,
            "roas_top30": top30["sale_value"].sum() / top30["spend_imputado"].sum(skipna=True)
                if top30["spend_imputado"].sum(skipna=True) > 0 else np.nan,
            "leads_top50_pct": len(top50) / total_leads if total_leads else 0,
            "conv_concentracao_top50": top50["converted"].sum() / total_conv if total_conv else 0,
            "roas_top50": top50["sale_value"].sum() / top50["spend_imputado"].sum(skipna=True)
                if top50["spend_imputado"].sum(skipna=True) > 0 else np.nan,
            "roas_global": total_revenue / total_spend if total_spend > 0 else np.nan,
        }
    return pd.DataFrame(rows).round(4)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--mode", choices=["score", "compare"], required=True)
    ap.add_argument("--lf", type=str, help="Identificador do lançamento (ex: LF52)")
    ap.add_argument("--label", type=str, help="Label curto do modelo (ex: v4, jan30)")
    ap.add_argument("--run-id", type=str, help="MLflow run_id do modelo")
    ap.add_argument("--mlruns-root", type=Path,
                    default=PROJECT_ROOT / "mlruns",
                    help="Diretório raiz do mlruns local")
    ap.add_argument("--output-dir", type=Path,
                    help="Diretório de saída dos parquets (modo score)")
    ap.add_argument("--labels", nargs="+", help="Labels a comparar (modo compare)")
    ap.add_argument("--input-dir", type=Path, help="Diretório com os parquets (modo compare)")
    ap.add_argument("--output", type=Path, help="Caminho do XLSX de saída (modo compare)")

    args = ap.parse_args()

    if args.mode == "score":
        for required in ["lf", "label", "run_id", "output_dir"]:
            if getattr(args, required) is None:
                ap.error(f"--{required.replace('_','-')} é obrigatório no modo score")
        run_score_mode(args)
    else:
        for required in ["labels", "input_dir", "output"]:
            if getattr(args, required) is None:
                ap.error(f"--{required.replace('_','-')} é obrigatório no modo compare")
        run_compare_mode(args)


if __name__ == "__main__":
    main()
