"""
Cria as conversion actions do DevClub no Google Ads via API (passo único).

Por que via API: a conta foi migrada pro setup unificado e o UI loopa
todo "+ Create conversion action" pro conector Google Sheets, sem caminho
pra criar uma conversion action `UPLOAD_CLICKS` "pelada". A criação via
ConversionActionService (parte de MUTAÇÃO da Google Ads API — NÃO a
`UploadClickConversions`, que está sendo descontinuada) contorna isso.

Token descartável: o developer token / OAuth aqui serve SÓ pra esta
criação. Em runtime, o envio de evento usa a Data Manager API com
service account (ver V2/docs/google_ads_pendencias.md). Depois que as
duas conversion actions existirem, nada disto é mais necessário.

O que cria (idempotente — pula se já existir com o mesmo nome):
  - LeadQualified            -> evento value-weighted por decil (paridade Meta)
  - LeadQualifiedHighQuality -> só decis D9-D10

Ambas: type=UPLOAD_CLICKS (única coisa que a Data Manager API exige —
`productDestinationId` precisa apontar pra uma conversion action desse
tipo), status=ENABLED, valor por-conversão (não usa default fixo, igual
ao CAPI do Meta).

Pré-requisitos:
  pip install -r V2/scripts/requirements_google_ads_setup.txt
  V2/.env com:
    GOOGLE_ADS_DEVELOPER_TOKEN=...        # Google Ads > Admin > API Center (Explorer Access)
    GOOGLE_ADS_CLIENT_ID=...              # OAuth client "Desktop app" no GCP
    GOOGLE_ADS_CLIENT_SECRET=...
    GOOGLE_ADS_REFRESH_TOKEN=...          # gerado por google_ads_oauth_refresh_token.py
    GOOGLE_ADS_CUSTOMER_ID=6266441811     # ID da conta DevClub, só dígitos (sem traços)
    GOOGLE_ADS_LOGIN_CUSTOMER_ID=...      # opcional: ID do MCC, se acessar via gerenciador

Uso:
  python V2/scripts/create_google_ads_conversion_actions.py --dry-run   # valida, não grava
  python V2/scripts/create_google_ads_conversion_actions.py             # cria de fato

Ao final imprime o ID numérico de cada conversion action — esses IDs
viram `google_conversion_action_id_*` no bloco google_ads do
configs/clients/devclub.yaml.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# Categoria é só rótulo de agrupamento/relatório no Google Ads — NÃO afeta a
# ingestão pela Data Manager API (o que importa é type=UPLOAD_CLICKS). Se a
# versão da API não tiver QUALIFIED_LEAD, troque por "DEFAULT" (o script
# falha alto e claro antes de qualquer chamada de rede se o nome do enum
# não existir).
CATEGORY = "QUALIFIED_LEAD"

# Janelas e contagem alinhadas ao ciclo de lead do DevClub.
CLICK_THROUGH_LOOKBACK_DAYS = 30
VIEW_THROUGH_LOOKBACK_DAYS = 1

CONVERSION_ACTIONS = [
    {
        "name": "LeadQualified",
        "desc": "Lead pontuado pelo ML — valor proporcional ao decil (paridade com o evento do Meta).",
    },
    {
        "name": "LeadQualifiedHighQuality",
        "desc": "Lead de alta qualidade — só decis D9-D10.",
    },
]


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERRO: variável de ambiente {name} ausente em V2/.env", file=sys.stderr)
        sys.exit(1)
    return val


def build_client():
    from google.ads.googleads.client import GoogleAdsClient

    cfg = {
        "developer_token": _require_env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": _require_env("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": _require_env("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": _require_env("GOOGLE_ADS_REFRESH_TOKEN"),
        "use_proto_plus": True,
    }
    login_cid = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if login_cid:
        cfg["login_customer_id"] = login_cid.replace("-", "")
    return GoogleAdsClient.load_from_dict(cfg)


def find_existing(client, customer_id: str, name: str):
    """Retorna (resource_name, id) se já existir conversion action com esse nome."""
    ga_service = client.get_service("GoogleAdsService")
    query = (
        "SELECT conversion_action.resource_name, conversion_action.id, "
        "conversion_action.name, conversion_action.type "
        "FROM conversion_action "
        f"WHERE conversion_action.name = '{name}'"
    )
    for row in ga_service.search(customer_id=customer_id, query=query):
        ca = row.conversion_action
        return ca.resource_name, ca.id
    return None


def create_conversion_action(client, customer_id: str, name: str, dry_run: bool):
    existing = find_existing(client, customer_id, name)
    if existing:
        print(f"  [SKIP] '{name}' já existe — id={existing[1]} ({existing[0]})")
        return existing[1]

    service = client.get_service("ConversionActionService")
    op = client.get_type("ConversionActionOperation")
    ca = op.create

    ca.name = name
    ca.type_ = client.enums.ConversionActionTypeEnum.UPLOAD_CLICKS
    ca.category = getattr(client.enums.ConversionActionCategoryEnum, CATEGORY)
    ca.status = client.enums.ConversionActionStatusEnum.ENABLED
    ca.counting_type = (
        client.enums.ConversionActionCountingTypeEnum.ONE_PER_CLICK
    )
    ca.click_through_lookback_window_days = CLICK_THROUGH_LOOKBACK_DAYS
    ca.view_through_lookback_window_days = VIEW_THROUGH_LOOKBACK_DAYS

    # Valor por-conversão (cada evento carrega seu valor, igual ao CAPI do
    # Meta). always_use_default_value=False faz o valor enviado prevalecer;
    # default_value é só fallback se algum evento vier sem valor.
    ca.value_settings.default_value = 1.0
    ca.value_settings.currency_code = "BRL"
    ca.value_settings.always_use_default_value = False

    request = client.get_type("MutateConversionActionsRequest")
    request.customer_id = customer_id
    request.operations.append(op)
    request.validate_only = dry_run

    response = service.mutate_conversion_actions(request=request)

    if dry_run:
        print(f"  [DRY-RUN OK] '{name}' validado (nada gravado).")
        return None

    resource_name = response.results[0].resource_name
    ca_id = resource_name.split("/")[-1]
    print(f"  [CRIADO] '{name}' -> id={ca_id} ({resource_name})")
    return ca_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="valida via API (validate_only) sem criar nada",
    )
    args = parser.parse_args()

    customer_id = _require_env("GOOGLE_ADS_CUSTOMER_ID").replace("-", "")

    try:
        from google.ads.googleads.errors import GoogleAdsException
    except ImportError:
        print(
            "ERRO: pacote 'google-ads' não instalado. Rode:\n"
            "  pip install -r V2/scripts/requirements_google_ads_setup.txt",
            file=sys.stderr,
        )
        return 1

    client = build_client()

    mode = "DRY-RUN (nada será gravado)" if args.dry_run else "CRIAÇÃO REAL"
    print(f"Conta Google Ads: {customer_id} | Modo: {mode}\n")

    results = {}
    try:
        for spec in CONVERSION_ACTIONS:
            print(f"- {spec['name']}: {spec['desc']}")
            results[spec["name"]] = create_conversion_action(
                client, customer_id, spec["name"], args.dry_run
            )
    except GoogleAdsException as ex:
        print(f"\nFALHA Google Ads API (request_id={ex.request_id}):", file=sys.stderr)
        for err in ex.failure.errors:
            print(f"  - {err.error_code}: {err.message}", file=sys.stderr)
        return 1

    if not args.dry_run:
        print("\n" + "=" * 60)
        print("IDs para o bloco google_ads de configs/clients/devclub.yaml:")
        print(f"  google_conversion_action_id_with_value:    {results.get('LeadQualified')}")
        print(
            "  google_conversion_action_id_high_quality:  "
            f"{results.get('LeadQualifiedHighQuality')}"
        )
        print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
