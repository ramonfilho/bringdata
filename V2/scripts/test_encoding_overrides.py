"""
test_encoding_overrides.py — Teste local do DT-12 com dados reais do Railway.

Busca leads recentes do Railway, particiona por variante A/B (ML_JAN / ML_MAR),
roda cada grupo pelo pipeline com o encoding correto e verifica se:

  - jan30: Qual_a_sua_idade e Atualmente_qual_a_sua_faixa_salarial são numéricos (0-5 / 0-4)
  - mar24: colunas _18_24_anos, _25_34_anos... presentes; sem coluna única de idade

Nenhum dado é enviado para a Meta.

Uso:
    cd V2/
    python scripts/test_encoding_overrides.py
    python scripts/test_encoding_overrides.py --limit 200 --days 3
"""

import sys
import os
import argparse
import logging
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # garante que imports relativos do src/ resolvem corretamente

logging.basicConfig(level=logging.WARNING, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Buscar leads reais do Railway
# ---------------------------------------------------------------------------

def fetch_railway_leads(limit: int = 100, days: int = 7) -> list[dict]:
    import pg8000.native
    import json

    # Credenciais — lê de env ou usa defaults de config.sh
    host     = os.environ.get("RAILWAY_DB_HOST", "shortline.proxy.rlwy.net")
    port     = int(os.environ.get("RAILWAY_DB_PORT", "11594"))
    database = os.environ.get("RAILWAY_DB_NAME", "railway")
    user     = os.environ.get("RAILWAY_DB_USER", "postgres")
    password = os.environ.get("RAILWAY_DB_PASSWORD", "THxguXxQPZaSWIzquYRiLlVhJBnPoRGu")

    conn = pg8000.native.Connection(
        host=host, port=port, database=database, user=user, password=password
    )

    rows = conn.run(
        f"""
        SELECT id, data, "nomeCompleto", email, telefone, pesquisa,
               source, medium, campaign, content, term,
               "remoteIp", "userAgent", fbc, fbp, "pageUrl"
        FROM "Lead"
        WHERE "leadScore" IS NOT NULL
          AND "createdAt" >= NOW() - INTERVAL '{days} days'
        ORDER BY "createdAt" DESC
        LIMIT {limit}
        """
    )
    conn.close()

    col_names = [
        "id", "data", "nomeCompleto", "email", "telefone", "pesquisa",
        "source", "medium", "campaign", "content", "term",
        "remoteIp", "userAgent", "fbc", "fbp", "pageUrl",
    ]
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


# ---------------------------------------------------------------------------
# 2. Particionar por variante A/B
# ---------------------------------------------------------------------------

def split_by_variant(leads: list[dict], ab_cfg) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {"guru_jan30": [], "guru_mar24": [], "no_variant": []}

    for lead in leads:
        utms = {
            "utm_campaign": lead.get("campaign"),
            "utm_content":  lead.get("content"),
            "utm_source":   lead.get("source"),
            "utm_medium":   lead.get("medium"),
            "utm_term":     lead.get("term"),
        }
        matched = ab_cfg.match_variant(utms)
        if matched is None:
            groups["no_variant"].append(lead)
            continue
        name = next(n for n, v in ab_cfg.variants.items() if v is matched)
        groups[name].append(lead)

    return groups


# ---------------------------------------------------------------------------
# 3. Rodar pipeline para um grupo
# ---------------------------------------------------------------------------

def run_pipeline_for_group(
    leads: list[dict],
    pipeline,
    predictor_ov,
    encoding_overrides,
    group_label: str,
) -> pd.DataFrame | None:
    from api.railway_mapping import railway_lead_to_sheets_row

    sheets_rows = []
    for lead in leads:
        try:
            row = railway_lead_to_sheets_row(lead)
            if row:
                sheets_rows.append(row)
        except Exception as e:
            logger.warning(f"Erro ao mapear lead {lead.get('email')}: {e}")

    if not sheets_rows:
        print(f"  [{group_label}] Nenhum lead mapeado com sucesso.")
        return None

    group_df = pd.DataFrame(sheets_rows)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        group_df.to_csv(tmp, index=False)
        temp_file = tmp.name

    try:
        result = pipeline.run(
            temp_file,
            with_predictions=True,
            predictor_override=predictor_ov,
            encoding_overrides=encoding_overrides,
        )
    finally:
        os.remove(temp_file)

    return result


# ---------------------------------------------------------------------------
# 4. Verificar features de encoding
# ---------------------------------------------------------------------------

def check_encoding_features(df: pd.DataFrame, variant_name: str) -> bool:
    print(f"\n  --- Verificação de encoding ({variant_name}) ---")

    idade_ordinal     = "Qual_a_sua_idade"
    salario_ordinal   = "Atualmente_qual_a_sua_faixa_salarial"
    idade_ohe_prefix  = "Qual_a_sua_idade_"
    salario_ohe_prefix = "Atualmente_qual_a_sua_faixa_salarial_"

    has_ordinal_idade   = idade_ordinal in df.columns
    has_ordinal_salario = salario_ordinal in df.columns
    ohe_idade_cols   = [c for c in df.columns if c.startswith(idade_ohe_prefix)]
    ohe_salario_cols = [c for c in df.columns if c.startswith(salario_ohe_prefix)]

    ok = True

    if variant_name == "guru_jan30":
        # Espera ordinal
        if has_ordinal_idade:
            vals = df[idade_ordinal].describe()
            print(f"  ✅ {idade_ordinal}: min={vals['min']:.0f} max={vals['max']:.0f} mean={vals['mean']:.2f}")
            if df[idade_ordinal].eq(0).all():
                print(f"  ⚠️  TODOS os valores são 0 — ordinal encoding pode não ter funcionado")
                ok = False
        else:
            print(f"  ❌ {idade_ordinal} ausente (esperado para jan30)")
            ok = False

        if has_ordinal_salario:
            vals = df[salario_ordinal].describe()
            print(f"  ✅ {salario_ordinal}: min={vals['min']:.0f} max={vals['max']:.0f} mean={vals['mean']:.2f}")
            if df[salario_ordinal].eq(0).all():
                print(f"  ⚠️  TODOS os valores são 0 — ordinal encoding pode não ter funcionado")
                ok = False
        else:
            print(f"  ❌ {salario_ordinal} ausente (esperado para jan30)")
            ok = False

        if ohe_idade_cols:
            print(f"  ⚠️  OHE de idade ainda presente (inesperado para jan30): {ohe_idade_cols[:3]}")

    else:
        # Espera OHE
        if ohe_idade_cols:
            print(f"  ✅ OHE idade ({len(ohe_idade_cols)} colunas): {ohe_idade_cols[:3]}...")
        else:
            print(f"  ❌ Nenhuma coluna OHE de idade (esperado para mar24)")
            ok = False

        if ohe_salario_cols:
            print(f"  ✅ OHE salário ({len(ohe_salario_cols)} colunas): {ohe_salario_cols[:3]}...")
        else:
            print(f"  ❌ Nenhuma coluna OHE de salário (esperado para mar24)")
            ok = False

        if has_ordinal_idade:
            print(f"  ⚠️  Coluna ordinal de idade presente (inesperado para mar24)")

    # Scores
    if "lead_score" in df.columns:
        s = df["lead_score"].describe()
        print(f"  Score: min={s['min']:.4f} max={s['max']:.4f} mean={s['mean']:.4f} n={int(s['count'])}")

    return ok


# ---------------------------------------------------------------------------
# 5. Teste sintético para jan30 (quando não há leads reais com UTM ML_JAN)
# ---------------------------------------------------------------------------

def run_real_data_as_jan30(pipeline, no_variant_leads: list[dict]) -> bool:
    """
    Testa jan30 com leads reais do Railway que não têm UTM ML_JAN.

    O survey é idêntico entre campanhas — só o UTM difere. Portanto leads
    no_variant têm os mesmos campos de idade/salário e servem para validar
    que encoding_overrides produz ordinal correto com dados reais.
    """
    from api.railway_mapping import railway_lead_to_sheets_row

    print(f"\n[guru_jan30] UTM ML_JAN sem tráfego real — testando com {len(no_variant_leads)} leads "
          f"reais do Railway (mesma estrutura de survey, UTM diferente).")

    sheets_rows = []
    for lead in no_variant_leads:
        try:
            row = railway_lead_to_sheets_row(lead)
            if row:
                sheets_rows.append(row)
        except Exception as e:
            logger.warning(f"Erro ao mapear lead {lead.get('email')}: {e}")

    if not sheets_rows:
        print("  Nenhum lead mapeado com sucesso.")
        return False

    group_df = pd.DataFrame(sheets_rows)

    # Mostrar distribuição de idade/salário reais para confirmar que não são nulos
    col_idade   = "Qual a sua idade?"
    col_salario = "Atualmente, qual a sua faixa salarial?"
    if col_idade in group_df.columns:
        dist = group_df[col_idade].value_counts().to_dict()
        print(f"  Distribuição real de idade ({group_df[col_idade].notna().sum()} preenchidos): {dict(list(dist.items())[:4])}...")
    if col_salario in group_df.columns:
        dist = group_df[col_salario].value_counts().to_dict()
        print(f"  Distribuição real de salário ({group_df[col_salario].notna().sum()} preenchidos): {dict(list(dist.items())[:4])}...")

    variant      = pipeline._ab_test_config.variants["guru_jan30"]
    predictor_ov = pipeline.get_variant_predictor("guru_jan30")
    enc_overrides = variant.encoding_overrides

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        group_df.to_csv(tmp, index=False)
        temp_file = tmp.name

    try:
        result = pipeline.run(
            temp_file,
            with_predictions=True,
            predictor_override=predictor_ov,
            encoding_overrides=enc_overrides,
        )
    finally:
        os.remove(temp_file)

    if result is None or len(result) == 0:
        print("  Pipeline retornou vazio.")
        return False

    ok = check_encoding_features(result, "guru_jan30")

    if "Qual_a_sua_idade" in result.columns:
        valores = sorted(result["Qual_a_sua_idade"].dropna().unique().tolist())
        print(f"  Valores ordinais de idade encontrados: {valores} (esperado: subconjunto de 0-5)")

    if "Atualmente_qual_a_sua_faixa_salarial" in result.columns:
        valores = sorted(result["Atualmente_qual_a_sua_faixa_salarial"].dropna().unique().tolist())
        print(f"  Valores ordinais de salário encontrados: {valores} (esperado: subconjunto de 0-4)")

    return ok


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Teste local do DT-12 com dados reais")
    parser.add_argument("--limit", type=int, default=150, help="Leads a buscar do Railway (default: 150)")
    parser.add_argument("--days",  type=int, default=7,   help="Janela de dias (default: 7)")
    args = parser.parse_args()

    print(f"\n=== Teste DT-12: encoding_overrides por variante A/B ===")
    print(f"    Buscando até {args.limit} leads dos últimos {args.days} dias...")

    # Carregar config e pipeline
    from core.client_config import ABTestConfig
    from src.production_pipeline import LeadScoringPipeline

    pipeline = LeadScoringPipeline(client_id="devclub")
    ab_cfg   = pipeline._ab_test_config

    if not ab_cfg or not ab_cfg.enabled:
        print("ERRO: A/B test não está habilitado em devclub.yaml")
        sys.exit(1)

    # Buscar leads
    leads = fetch_railway_leads(limit=args.limit, days=args.days)
    print(f"    {len(leads)} leads recuperados do Railway")

    # Particionar
    groups = split_by_variant(leads, ab_cfg)
    for name, group in groups.items():
        print(f"    {name}: {len(group)} leads")

    results = {}
    all_ok = True

    for vname in ["guru_jan30", "guru_mar24"]:
        group = groups[vname]

        variant      = ab_cfg.variants[vname]
        predictor_ov = pipeline.get_variant_predictor(vname)
        enc_overrides = variant.encoding_overrides

        if not group:
            if vname == "guru_jan30":
                # Fallback: usa leads reais no_variant (survey idêntico, UTM diferente)
                no_variant = groups.get("no_variant", [])
                if not no_variant:
                    print(f"\n[{vname}] Sem leads reais disponíveis para teste.")
                    continue
                ok = run_real_data_as_jan30(pipeline, no_variant)
                if not ok:
                    all_ok = False
                results[vname] = True  # marcador de presença
            else:
                print(f"\n[{vname}] Sem leads neste grupo — verifique os UTMs no Railway")
            continue

        print(f"\n[{vname}] Rodando pipeline para {len(group)} leads...")
        result = run_pipeline_for_group(group, pipeline, predictor_ov, enc_overrides, vname)

        if result is None or len(result) == 0:
            print(f"  Pipeline retornou vazio para {vname}")
            all_ok = False
            continue

        results[vname] = result
        ok = check_encoding_features(result, vname)
        if not ok:
            all_ok = False

    print("\n" + ("=" * 50))
    if all_ok and results:
        print("✅  Todos os checks passaram — encoding_overrides funcionando corretamente")
    elif not results:
        print("⚠️  Nenhum grupo teve leads suficientes para testar")
    else:
        print("❌  Alguns checks falharam — revisar antes de fazer deploy")
    print()


if __name__ == "__main__":
    main()
