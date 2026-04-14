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
import hashlib
import logging
import os
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import pg8000.native
from dotenv import load_dotenv

# Paths
ROOT = Path(__file__).parent.parent
VALIDATION_DIR = ROOT / "outputs" / "validation"
CLOUD_SQL_BACKUP = ROOT / "data" / "backups" / "cloud-sql-final-export-20260225.sql"

load_dotenv(ROOT / ".env")

# Meta CAPI — lidos do .env
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
META_PIXEL_ID     = os.environ.get("META_PIXEL_ID", "1937807493703815")

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
    """
    Lê aba 'Detalhes das Conversões' de todos os relatórios de validação.

    Suporta estrutura atual: outputs/validation/YYYY-MM/LFxx - DD:MM a DD:MM.xlsx
    lancamento_filter: nome parcial do arquivo xlsx (ex: 'LF49') ou None para todos.
    """
    # Varrer pastas YYYY-MM (e também raiz para compatibilidade com formato antigo "DD:MM - DD:MM")
    SKIP_DIRS = {"historico", "arquivos_leads", "feedback_loop", "meta_features_test", "serie_temporal"}
    month_dirs = sorted([
        f for f in VALIDATION_DIR.iterdir()
        if f.is_dir() and f.name not in SKIP_DIRS
    ])

    all_dfs = []

    for folder in month_dirs:
        reports = sorted(folder.glob("*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True)

        for report in reports:
            # Filtro por lançamento: compara com nome do arquivo
            if lancamento_filter and lancamento_filter not in report.stem:
                continue

            try:
                xl = pd.ExcelFile(report)
                if "Detalhes das Conversões" not in xl.sheet_names:
                    continue

                df = pd.read_excel(report, sheet_name="Detalhes das Conversões", header=1, skiprows=[2])
                # Detectar se o Excel tem as colunas FBP/FBC (geradas após o fix)
                # ou o formato antigo (sem fbp/fbc)
                if len(df.columns) >= 12:
                    df.columns = [
                        "trackeado", "email", "telefone", "fbp", "fbc",
                        "id_campanha", "nome_campanha", "grupo",
                        "data_captura", "data_venda", "valor_venda", "fonte_venda"
                    ]
                else:
                    df.columns = [
                        "trackeado", "email", "telefone", "id_campanha", "nome_campanha",
                        "grupo", "data_captura", "data_venda", "valor_venda", "fonte_venda"
                    ]
                    df["fbp"] = None
                    df["fbc"] = None
                df = df[df["email"].notna() & (df["email"] != "E-mail Comprador")].copy()
                df["lancamento"] = report.stem  # ex: "LF49 - 30:03 a 05:04"
                all_dfs.append(df)
                logger.info(f"  {report.stem}: {len(df)} compradores")

            except Exception as e:
                logger.warning(f"  {report.name}: erro ao ler — {e}")

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined["email"] = combined["email"].str.strip().str.lower()

    # Deduplicar por email (mantém compra mais recente se repetiu em lançamentos)
    combined = combined.sort_values("data_venda", ascending=False)
    combined = combined.drop_duplicates(subset=["email"], keep="first")

    return combined


# ---------------------------------------------------------------------------
# 2. Carregar FBP/FBC da tabela leads_capi do Cloud SQL (via proxy local)
# ---------------------------------------------------------------------------

CLOUDSQL_HOST     = os.environ.get("DB_HOST", "127.0.0.1")
CLOUDSQL_PORT     = int(os.environ.get("DB_PORT", "5433"))
CLOUDSQL_DB       = os.environ.get("DB_NAME", "bring_data")
CLOUDSQL_USER     = os.environ.get("DB_USER", "postgres")
CLOUDSQL_PASSWORD = os.environ.get("DB_PASSWORD") or os.environ.get("CLOUDSQL_PASSWORD", "SmartAds2026DB!")


def load_cloudsql_capi_data() -> dict:
    """
    Lê FBP/FBC diretamente da tabela leads_capi no Cloud SQL via proxy local.
    Fallback: parseia o arquivo de backup .sql se o proxy não estiver disponível.
    """
    import psycopg2

    logger.info("Carregando FBP/FBC da tabela leads_capi (Cloud SQL)...")

    try:
        conn = psycopg2.connect(
            host=CLOUDSQL_HOST,
            port=CLOUDSQL_PORT,
            dbname=CLOUDSQL_DB,
            user=CLOUDSQL_USER,
            password=CLOUDSQL_PASSWORD,
            connect_timeout=5,
        )
        cursor = conn.cursor()
        cursor.execute(
            "SELECT LOWER(email), fbp, fbc, name, phone "
            "FROM leads_capi "
            "WHERE email IS NOT NULL AND (fbp IS NOT NULL OR fbc IS NOT NULL)"
        )
        result = {}
        for email, fbp, fbc, nome, telefone in cursor.fetchall():
            if email and email not in result:
                result[email] = {"fbp": fbp, "fbc": fbc, "nome": nome, "telefone": telefone}
        cursor.close()
        conn.close()
        logger.info(f"  {len(result)} leads com FBP/FBC na tabela leads_capi")
        return result

    except Exception as e:
        logger.warning(f"Cloud SQL indisponível ({e}) — usando backup .sql local")

    # Fallback: backup .sql
    if not CLOUD_SQL_BACKUP.exists():
        logger.warning(f"Backup também não encontrado: {CLOUD_SQL_BACKUP}")
        return {}

    with open(CLOUD_SQL_BACKUP, "r", encoding="utf-8") as f:
        content = f.read()

    start_marker = "COPY public.leads_capi ("
    start = content.find(start_marker)
    if start == -1:
        logger.warning("Tabela leads_capi não encontrada no backup.")
        return {}

    header_start = content.index("(", start) + 1
    header_end = content.index(")", header_start)
    columns = [c.strip() for c in content[header_start:header_end].split(",")]

    data_start = content.index("FROM stdin;\n", start) + len("FROM stdin;\n")
    data_end = content.index("\n\\.", data_start)
    data_block = content[data_start:data_end]

    df = pd.read_csv(StringIO(data_block), sep="\t", header=None, names=columns,
                     na_values=["\\N"], low_memory=False)
    df["email"] = df["email"].str.strip().str.lower()
    df = df[df["email"].notna()]

    result = {}
    for _, row in df.iterrows():
        email = row["email"]
        if email not in result:
            result[email] = {
                "fbp":      row.get("fbp")   if pd.notna(row.get("fbp"))   else None,
                "fbc":      row.get("fbc")   if pd.notna(row.get("fbc"))   else None,
                "nome":     row.get("name")  if pd.notna(row.get("name"))  else None,
                "telefone": row.get("phone") if pd.notna(row.get("phone")) else None,
            }

    logger.info(f"  {len(result)} leads únicos no backup Cloud SQL (fallback)")
    return result


# ---------------------------------------------------------------------------
# 3. Carregar FBP/FBC do Railway (por período de captação)
# ---------------------------------------------------------------------------

def load_railway_capi_data(cap_start: str, cap_end: str) -> dict:
    """
    Busca FBP/FBC no Railway pelo período de captação do lançamento.
    Usa named parameters (:start_date, :end_date_excl) — mesma abordagem
    do validate_ml_performance.py, que funciona com pg8000.native.
    """
    end_excl = (pd.to_datetime(cap_end) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    logger.info(f"Buscando leads no Railway (captação {cap_start} a {cap_end})...")

    try:
        conn = pg8000.native.Connection(
            host=os.environ.get('RAILWAY_DB_HOST', 'shortline.proxy.rlwy.net'),
            port=int(os.environ.get('RAILWAY_DB_PORT', '11594')),
            database=os.environ.get('RAILWAY_DB_NAME', 'railway'),
            user=os.environ.get('RAILWAY_DB_USER', 'postgres'),
            password=os.environ['RAILWAY_DB_PASSWORD'],
        )
        rows = conn.run(
            """
            SELECT LOWER(email), name, phone, fbp, fbc
            FROM leads_capi
            WHERE created_at >= :start_date
              AND created_at <  :end_date_excl
              AND email IS NOT NULL
            """,
            start_date=cap_start,
            end_date_excl=end_excl,
        )
        conn.close()

        result = {}
        for email, nome, telefone, fbp, fbc in rows:
            if email and email not in result:
                result[email] = {"fbp": fbp, "fbc": fbc, "nome": nome, "telefone": telefone}

        with_cookies = sum(1 for v in result.values() if v.get("fbp"))
        logger.info(f"  {len(result)} leads encontrados | {with_cookies} com FBP/FBC")
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

        # Prioridade FBP/FBC: Excel (novo) > Railway > Cloud SQL > sem cookies
        fbp_from_excel = row.get("fbp") if pd.notna(row.get("fbp", pd.NA)) else None
        fbc_from_excel = row.get("fbc") if pd.notna(row.get("fbc", pd.NA)) else None

        railway_entry  = railway_data.get(email, {})
        cloudsql_entry = cloudsql_data.get(email, {})

        if fbp_from_excel:
            capi = {"fbp": fbp_from_excel, "fbc": fbc_from_excel,
                    "nome": railway_entry.get("nome") or cloudsql_entry.get("nome"),
                    "telefone": railway_entry.get("telefone") or cloudsql_entry.get("telefone")}
            stats["railway"] += 1  # conta como railway (já veio do Railway via pipeline)
        elif railway_entry.get("fbp"):
            capi = railway_entry
            stats["railway"] += 1
        elif cloudsql_entry.get("fbp"):
            capi = cloudsql_entry
            stats["cloudsql"] += 1
        else:
            capi = railway_entry or cloudsql_entry or {}
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


def _hash(value: str) -> str | None:
    if not value:
        return None
    return hashlib.sha256(str(value).lower().strip().encode("utf-8")).hexdigest()


def call_endpoint(sales: list, dry_run: bool, test_event_code: str = None) -> dict:
    """Envia eventos Purchase diretamente ao Meta CAPI usando token do .env."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.serverside.event import Event
    from facebook_business.adobjects.serverside.event_request import EventRequest
    from facebook_business.adobjects.serverside.user_data import UserData
    from facebook_business.adobjects.serverside.custom_data import CustomData
    from facebook_business.adobjects.serverside.action_source import ActionSource

    if not META_ACCESS_TOKEN:
        logger.error("META_ACCESS_TOKEN não encontrado no .env")
        return {"total": len(sales), "enviados": 0, "anomalias": 0, "erros": len(sales)}

    FacebookAdsApi.init(access_token=META_ACCESS_TOKEN)

    results = {"total": len(sales), "enviados": 0, "anomalias": 0, "erros": 0}

    for sale in sales:
        email     = sale.get("email", "")
        telefone  = sale.get("telefone")
        nome      = sale.get("nome")
        fbp       = sale.get("fbp")
        fbc       = sale.get("fbc")
        valor     = float(sale.get("valor_venda") or 0)
        sale_date = sale.get("sale_date", "")

        has_cookies = bool(fbp or fbc)
        if not has_cookies:
            results["anomalias"] += 1

        try:
            purchase_ts = int(pd.to_datetime(sale_date).timestamp())
        except Exception:
            logger.warning(f"Data inválida para {email}: {sale_date}")
            results["erros"] += 1
            continue

        if dry_run:
            logger.info(
                f"[DRY RUN] Purchase: {email} | R$ {valor:.2f} | "
                f"fbp={'sim' if has_cookies else 'não'}"
            )
            results["enviados"] += 1
            continue

        try:
            first_name, last_name = None, None
            if nome:
                parts = str(nome).strip().split(" ", 1)
                first_name = parts[0] if parts else None
                last_name  = parts[1] if len(parts) > 1 else None

            user_data = UserData(
                emails=[_hash(email)] if email else None,
                phones=[_hash(telefone)] if telefone else None,
                first_names=[_hash(first_name)] if first_name else None,
                last_names=[_hash(last_name)]   if last_name  else None,
                fbp=fbp,
                fbc=fbc,
            )
            custom_data = CustomData(value=valor, currency="BRL")
            event = Event(
                event_name="Purchase",
                event_time=purchase_ts,
                event_id=f"purchase_{email}_{purchase_ts}",
                user_data=user_data,
                custom_data=custom_data,
                action_source=ActionSource.PHYSICAL_STORE,
            )

            params = {
                "events":       [event],
                "pixel_id":     META_PIXEL_ID,
                "access_token": META_ACCESS_TOKEN,
            }
            if test_event_code:
                params["test_event_code"] = test_event_code

            EventRequest(**params).execute()
            results["enviados"] += 1

        except Exception as e:
            logger.error(f"Erro ao enviar Purchase para {email}: {e}")
            results["erros"] += 1

    return results


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Envia eventos Purchase históricos ao Meta CAPI."
    )
    parser.add_argument("--lancamento", metavar="PASTA", help="Enviar só um lançamento (ex: '09:03 - 15:03')")
    parser.add_argument("--cap-start", metavar="YYYY-MM-DD", help="Início da captação (para lookup Railway)")
    parser.add_argument("--cap-end",   metavar="YYYY-MM-DD", help="Fim da captação (para lookup Railway)")
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
    if args.cap_start and args.cap_end:
        railway_data = load_railway_capi_data(args.cap_start, args.cap_end)
    else:
        logger.warning("--cap-start/--cap-end não fornecidos — Railway ignorado. Use para recuperar FBP/FBC.")
        railway_data = {}
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
