"""
Gera o refresh_token OAuth2 do Google Ads (passo único, descartável).

Contexto: a criação das conversion actions do DevClub é feita via Google Ads
API (ConversionActionService). Em runtime o envio de evento NÃO usa este
caminho — usa a Data Manager API com service account. Este token serve só
para a criação one-time das conversion actions.

Pré-requisitos:
  pip install google-auth-oauthlib
  - Um OAuth client tipo "Desktop app" criado no Google Cloud Console
    (APIs & Services > Credentials), no projeto onde a Google Ads API
    está habilitada.

Uso:
  GOOGLE_ADS_CLIENT_ID=...  GOOGLE_ADS_CLIENT_SECRET=...  \
      python V2/scripts/google_ads_oauth_refresh_token.py

Faz login no navegador com a conta que tem acesso à conta Google Ads do
DevClub (Rodolfo Mori / 626-644-1811) e imprime o refresh_token. Cole o
valor em V2/.env como GOOGLE_ADS_REFRESH_TOKEN.
"""

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

# Escopo único da Google Ads API.
SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main() -> int:
    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "ERRO: defina GOOGLE_ADS_CLIENT_ID e GOOGLE_ADS_CLIENT_SECRET no "
            "ambiente antes de rodar.",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    # access_type=offline + prompt=consent força a emissão de um refresh_token.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    print("\n" + "=" * 60)
    print("Refresh token gerado. Cole em V2/.env:")
    print(f"\nGOOGLE_ADS_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
