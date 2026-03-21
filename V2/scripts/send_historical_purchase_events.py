"""
Script para envio retroativo de eventos Purchase ao Meta CAPI.

Lê compradores de todos os relatórios de validação em outputs/validation/,
cruza com FBP/FBC do Railway e do backup Cloud SQL, e envia ao endpoint CAPI.

Uso:
    # Dry run (recomendado primeiro)
    python V2/scripts/send_historical_purchase_events.py --dry-run

    # Teste com código Meta
    python V2/scripts/send_historical_purchase_events.py --test-event-code TEST51740

    # Produção
    python V2/scripts/send_historical_purchase_events.py

    # Só um lançamento específico
    python V2/scripts/send_historical_purchase_events.py --lancamento "09:03 - 15:03"
"""

import argparse
import json
import logging
import os
import sys
import urllib.request
from io import StringIO
from pathlib import Path

import pandas as pd
import pg8000.native
from dotenv import load_dotenv

# Paths
ROOT = Path(__file__).parent.parent
VALIDATION_DIR = ROOT / "outputs" / "validation"
CLOUD_SQL_BACKUP = ROOT / "data" / "backups" / "cloud-sql-final-export-20260225.sql"
API_URL = "https://smart-ads-api-12955519745.us-central1.run.app/capi/send_purchase_events"

load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Carregar compradores dos relatórios de validação
# ---------------------------------------------------------------------------

def load_all_buyers(lancamento_filter: str = None) -> pd.DataFrame:
    """Lê aba 'Detalhes das Conversões' de todos os relatórios de validação."""
    folders = sorted([f for f in VALIDATION_DIR.iterdir() if f.is_dir() and ":" in f.name])
    all_dfs = []

    for folder in folders:
        if lancamento_filter and folder.name != lancamento_filter:
            continue

        reports = sorted(folder.glob("*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not reports:
            continue
        latest = reports[0]

        try:
            xl = pd.ExcelFile(latest)
            if "Detalhes das Conversões" not in xl.sheet_names:
                continue

            df = pd.read_excel(latest, sheet_name="Detalhes das Conversões", header=1, skiprows=[2])
            df.columns = [
                "trackeado", "email", "telefone", "id_campanha", "nome_campanha",
                "grupo", "data_captura", "data_venda", "valor_venda", "fonte_venda"
            ]
            df = df[df["email"].notna() & (df["email"] != "E-mail Comprador")].copy()
            df["lancamento"] = folder.name
            all_dfs.append(df)
            logger.info(f"  {folder.name}: {len(df)} compradores ({latest.name})")

        except Exception as e:
            logger.warning(f"  {folder.name}: erro ao ler — {e}")

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined["email"] = combined["email"].str.strip().str.lower()

    # Deduplicar por email (mantém compra mais recente se repetiu em lançamentos)
    combined = combined.sort_values("data_venda", ascending=False)
    combined = combined.drop_duplicates(subset=["email"], keep="first")

    return combined


# ---------------------------------------------------------------------------
# 2. Carregar FBP/FBC do backup Cloud SQL (arquivo .sql local)
# ---------------------------------------------------------------------------

def load_cloudsql_capi_data() -> dict:
    """
    Parseia o backup Cloud SQL e retorna dict {email: {fbp, fbc, nome, telefone}}.
    """
    logger.info("Carregando FBP/FBC do backup Cloud SQL...")

    if not CLOUD_SQL_BACKUP.exists():
        logger.warning(f"Backup não encontrado: {CLOUD_SQL_BACKUP}")
        return {}

    with open(CLOUD_SQL_BACKUP, "r", encoding="utf-8") as f:
        content = f.read()

    # Extrair o bloco COPY da tabela leads_capi
    start_marker = "COPY public.leads_capi ("
    start = content.find(start_marker)
    if start == -1:
        logger.warning("Tabela leads_capi não encontrada no backup.")
        return {}

    # Pegar cabeçalho das colunas
    header_start = content.index("(", start) + 1
    header_end = content.index(")", header_start)
    columns = [c.strip() for c in content[header_start:header_end].split(",")]

    # Pegar linhas de dados (entre FROM stdin; e \.)
    data_start = content.index("FROM stdin;\n", start) + len("FROM stdin;\n")
    data_end = content.index("\n\\.", data_start)
    data_block = content[data_start:data_end]

    # Parsear com pandas
    df = pd.read_csv(
        StringIO(data_block),
        sep="\t",
        header=None,
        names=columns,
        na_values=["\\N"],
        low_memory=False,
    )

    df["email"] = df["email"].str.strip().str.lower()
    df = df[df["email"].notna()]

    # Montar dict de lookup
    result = {}
    for _, row in df.iterrows():
        email = row["email"]
        if email not in result:
            result[email] = {
                "fbp": row.get("fbp") if pd.notna(row.get("fbp")) else None,
                "fbc": row.get("fbc") if pd.notna(row.get("fbc")) else None,
                "nome": row.get("name") if pd.notna(row.get("name")) else None,
                "telefone": row.get("phone") if pd.notna(row.get("phone")) else None,
            }

    logger.info(f"  {len(result)} leads únicos no backup Cloud SQL")
    return result


# ---------------------------------------------------------------------------
# 3. Carregar FBP/FBC do Railway
# ---------------------------------------------------------------------------

def load_railway_capi_data(emails: list) -> dict:
    """Busca FBP/FBC no Railway para a lista de emails fornecida."""
    logger.info(f"Buscando {len(emails)} emails no Railway...")

    try:
        conn = pg8000.native.Connection(
            host=os.environ["RAILWAY_DB_HOST"],
            port=int(os.environ["RAILWAY_DB_PORT"]),
            database=os.environ["RAILWAY_DB_NAME"],
            user=os.environ["RAILWAY_DB_USER"],
            password=os.environ["RAILWAY_DB_PASSWORD"],
        )

        placeholders = ", ".join([f"${i+1}" for i in range(len(emails))])
        rows = conn.run(
            f'SELECT LOWER(email), "nomeCompleto", telefone, fbp, fbc '
            f'FROM "Lead" WHERE LOWER(email) = ANY(ARRAY[{placeholders}])',
            *emails,
        )
        conn.close()

        result = {}
        for row in rows:
            email, nome, telefone, fbp, fbc = row
            if email and email not in result:
                result[email] = {
                    "fbp": fbp,
                    "fbc": fbc,
                    "nome": nome,
                    "telefone": telefone,
                }

        logger.info(f"  {len(result)} emails encontrados no Railway")
        return result

    except Exception as e:
        logger.warning(f"Erro ao conectar Railway: {e}")
        return {}


# ---------------------------------------------------------------------------
# 4. Construir payload e enviar
# ---------------------------------------------------------------------------

def build_payload(buyers_df: pd.DataFrame, railway_data: dict, cloudsql_data: dict) -> list:
    """Monta lista de sales para o endpoint, enriquecendo com FBP/FBC."""
    sales = []
    stats = {"railway": 0, "cloudsql": 0, "sem_cookies": 0}

    for _, row in buyers_df.iterrows():
        email = row["email"]

        # Prioridade: Railway > Cloud SQL > sem cookies
        capi = railway_data.get(email) or cloudsql_data.get(email) or {}

        if capi.get("fbp"):
            if email in railway_data:
                stats["railway"] += 1
            else:
                stats["cloudsql"] += 1
        else:
            stats["sem_cookies"] += 1

        sale_date = row.get("data_venda")
        sale_date_str = (
            sale_date.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(sale_date, "strftime")
            else str(sale_date)
        )

        nome = capi.get("nome") or row.get("nome_campanha")  # fallback
        telefone = capi.get("telefone") or row.get("telefone")

        item = {
            "email": email,
            "valor_venda": float(row.get("valor_venda") or 0),
            "sale_date": sale_date_str,
        }
        if nome and str(nome) != "nan":
            item["nome"] = str(nome)
        if telefone and str(telefone) != "nan":
            item["telefone"] = str(telefone)
        if capi.get("fbp"):
            item["fbp"] = capi["fbp"]
        if capi.get("fbc"):
            item["fbc"] = capi["fbc"]

        sales.append(item)

    logger.info(f"  FBP/FBC Railway: {stats['railway']}")
    logger.info(f"  FBP/FBC Cloud SQL: {stats['cloudsql']}")
    logger.info(f"  Sem cookies: {stats['sem_cookies']}")

    return sales


def call_endpoint(sales: list, dry_run: bool, test_event_code: str = None) -> dict:
    payload = {"sales": sales, "dry_run": dry_run}
    if test_event_code:
        payload["test_event_code"] = test_event_code

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Envia eventos Purchase históricos ao Meta CAPI."
    )
    parser.add_argument("--lancamento", metavar="PASTA", help="Enviar só um lançamento (ex: '09:03 - 15:03')")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem enviar ao Meta")
    parser.add_argument("--test-event-code", metavar="CODIGO", help="Código de teste do Meta")
    args = parser.parse_args()

    # 1. Carregar compradores
    logger.info("=== Carregando compradores dos relatórios de validação ===")
    buyers_df = load_all_buyers(lancamento_filter=args.lancamento)
    if buyers_df.empty:
        logger.error("Nenhum comprador encontrado.")
        sys.exit(1)
    logger.info(f"Total: {len(buyers_df)} compradores únicos em {buyers_df['lancamento'].nunique()} lançamentos")

    # 2. Carregar FBP/FBC
    emails = buyers_df["email"].tolist()
    railway_data = load_railway_capi_data(emails)
    cloudsql_data = load_cloudsql_capi_data()

    # 3. Construir payload
    logger.info("=== Construindo payload ===")
    sales = build_payload(buyers_df, railway_data, cloudsql_data)
    logger.info(f"Total para envio: {len(sales)} eventos")

    if args.dry_run:
        logger.info("DRY RUN — nenhum evento será enviado ao Meta.")
    if args.test_event_code:
        logger.info(f"Modo de teste: test_event_code={args.test_event_code}")

    # 4. Enviar em lotes de 500 (limite recomendado da Meta CAPI)
    batch_size = 500
    total_result = {"total": 0, "enviados": 0, "anomalias": 0, "erros": 0}

    for i in range(0, len(sales), batch_size):
        batch = sales[i:i + batch_size]
        logger.info(f"Enviando lote {i // batch_size + 1} ({len(batch)} eventos)...")
        try:
            result = call_endpoint(batch, dry_run=args.dry_run, test_event_code=args.test_event_code)
            for key in total_result:
                total_result[key] += result.get(key, 0)
        except Exception as e:
            logger.error(f"Erro no lote {i // batch_size + 1}: {e}")
            total_result["erros"] += len(batch)

    # 5. Resultado final
    print("\n" + "=" * 50)
    print("RESULTADO FINAL")
    print("=" * 50)
    print(f"  Total enviado:   {total_result['total']}")
    print(f"  Enviados:        {total_result['enviados']}")
    print(f"  Anomalias:       {total_result['anomalias']}  (sem FBP/FBC no Railway)")
    print(f"  Erros:           {total_result['erros']}")
    print(f"  Dry run:         {args.dry_run}")
    print("=" * 50)


if __name__ == "__main__":
    main()
