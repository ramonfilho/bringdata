"""
PROBE (descartável) — testa se o developer token atual consegue LER
relatório da conta DevClub via Google Ads API (GAQL).

Objetivo único: descobrir se o tier de acesso do nosso token serve pra
um pull de custo + conversões por campanha (espelho do funil Meta), ou
se esbarra no limite e exige o Basic access (a aplicação que foi recusada).

Read-only: só faz SELECT. Não muda nada. Pode apagar depois.

Uso:
  python V2/scripts/probe_google_ads_reporting.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")


def build_client():
    from google.ads.googleads.client import GoogleAdsClient

    cfg = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    login = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if login:
        cfg["login_customer_id"] = login.replace("-", "")
    return GoogleAdsClient.load_from_dict(cfg)


def run(client, customer_id, query, title):
    ga = client.get_service("GoogleAdsService")
    print(f"\n=== {title} ===")
    rows = 0
    for batch in ga.search_stream(customer_id=customer_id, query=query):
        for row in batch.results:
            yield row
            rows += 1
    if rows == 0:
        print("  (sem linhas — provavelmente sem dados/conversão na janela)")


def main():
    customer_id = os.environ["GOOGLE_ADS_CUSTOMER_ID"].replace("-", "")
    print(f"Conta DevClub: {customer_id} | login (MCC): "
          f"{os.environ.get('GOOGLE_ADS_LOGIN_CUSTOMER_ID')}")

    try:
        from google.ads.googleads.errors import GoogleAdsException
    except ImportError:
        print("ERRO: pacote google-ads não instalado.", file=sys.stderr)
        return 1

    client = build_client()

    # --- Query 1: custo + conversões por campanha (prova que reporting funciona) ---
    q1 = """
        SELECT campaign.id, campaign.name, campaign.status,
               metrics.cost_micros, metrics.clicks, metrics.conversions,
               metrics.all_conversions
        FROM campaign
        WHERE segments.date DURING LAST_7_DAYS
          AND metrics.cost_micros > 0
        ORDER BY metrics.cost_micros DESC
        LIMIT 15
    """

    # --- Query 2: conversões quebradas POR conversion action (acha o LQHQ) ---
    q2 = """
        SELECT campaign.name, segments.conversion_action_name,
               metrics.conversions, metrics.all_conversions
        FROM campaign
        WHERE segments.date DURING LAST_7_DAYS
          AND metrics.all_conversions > 0
        ORDER BY metrics.all_conversions DESC
        LIMIT 30
    """

    try:
        print("\n>>> Se chegar dados abaixo, o token JÁ serve pra reporting. <<<")
        for row in run(client, customer_id, q1, "TOP campanhas por custo (7d)"):
            custo = row.metrics.cost_micros / 1_000_000
            print(f"  {row.campaign.name[:50]:50} | R${custo:>9.2f} | "
                  f"cliques={row.metrics.clicks:>5} | conv={row.metrics.conversions:.1f} "
                  f"| all_conv={row.metrics.all_conversions:.1f}")

        for row in run(client, customer_id, q2, "Conversões por AÇÃO x campanha (7d)"):
            print(f"  {row.campaign.name[:38]:38} | "
                  f"{row.segments.conversion_action_name[:30]:30} | "
                  f"conv={row.metrics.conversions:.2f} | all={row.metrics.all_conversions:.2f}")

    except GoogleAdsException as ex:
        print(f"\n*** FALHA (request_id={ex.request_id}) ***", file=sys.stderr)
        for err in ex.failure.errors:
            print(f"  - {err.error_code}: {err.message}", file=sys.stderr)
        print("\nSe o erro for de quota/authorization (DEVELOPER_TOKEN_NOT_APPROVED, "
              "quota), é o tier de acesso — precisaria do Basic access.", file=sys.stderr)
        return 2

    print("\n>>> OK: reporting via Google Ads API funcionou com o token atual. <<<")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
