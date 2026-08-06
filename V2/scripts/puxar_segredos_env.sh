#!/usr/bin/env bash
# Puxa do Secret Manager os segredos que o `V2/.env` precisa e que NÃO podem estar
# versionados. Idempotente: só escreve a variável que estiver faltando, nunca
# sobrescreve valor já presente.
#
# Por que existe: em 05/08/2026 a senha do banco foi rotacionada e um token novo
# passou a guardar as rotas internas da API. Os dois vivem no Secret Manager e no
# `.env` local, que é gitignored de propósito. Consequência: **a outra máquina não
# tem nenhum dos dois**, e lá o treino do MLflow e as ferramentas internas falham
# com erro que não diz por quê. Este script resolve isso numa linha.
#
# Uso:
#   bash V2/scripts/puxar_segredos_env.sh            # escreve o que faltar
#   bash V2/scripts/puxar_segredos_env.sh --check    # só diz o que falta, não escreve
set -euo pipefail

PROJETO="smart-ads-451319"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$RAIZ/.env"
SO_CHECAR=false
[ "${1:-}" = "--check" ] && SO_CHECAR=true

# variável_do_env : nome_do_secret : como montar o valor
#   valor cru        -> a variável recebe o segredo direto
#   uri_mlflow       -> monta a URI de tracking com o segredo no meio
declare -a ITENS=(
  "API_INTERNAL_TOKEN:api-internal-token:cru"
  "MLFLOW_TRACKING_URI:mlflow-db-password:uri_mlflow"
)

MLFLOW_HOST="${LEDGER_DB_HOST:-104.197.138.129}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERRO: $ENV_FILE não existe. Crie o .env antes (ele guarda também as credenciais de banco)." >&2
  exit 1
fi

faltando=0
for item in "${ITENS[@]}"; do
  IFS=':' read -r var secret modo <<< "$item"

  if grep -qE "^${var}=" "$ENV_FILE"; then
    echo "  ${var}: já está no .env"
    continue
  fi

  faltando=$((faltando + 1))
  if [ "$SO_CHECAR" = true ]; then
    echo "  ${var}: FALTANDO (secret ${secret})"
    continue
  fi

  valor="$(gcloud secrets versions access latest --secret="$secret" --project="$PROJETO" 2>/dev/null || true)"
  if [ -z "$valor" ]; then
    echo "  ${var}: NÃO consegui ler o secret '${secret}'. Autentique com 'gcloud auth login' e rode de novo." >&2
    continue
  fi

  case "$modo" in
    cru)
      printf '\n# Puxado do Secret Manager (%s) por scripts/puxar_segredos_env.sh\n%s=%s\n' \
        "$secret" "$var" "$valor" >> "$ENV_FILE"
      ;;
    uri_mlflow)
      # sslmode=require cravado: a instância exige TLS desde 05/08/2026, e deixar o
      # default implícito permitiria cair em conexão não criptografada se o servidor
      # mudar de política.
      printf '\n# Puxado do Secret Manager (%s) por scripts/puxar_segredos_env.sh\n%s=postgresql+psycopg2://postgres:%s@%s:5432/mlflow?sslmode=require\n' \
        "$secret" "$var" "$valor" "$MLFLOW_HOST" >> "$ENV_FILE"
      ;;
  esac
  echo "  ${var}: escrito no .env"
done

if [ "$SO_CHECAR" = true ]; then
  [ "$faltando" -eq 0 ] && echo "tudo presente." || echo "$faltando variável(is) faltando."
  exit 0
fi
echo "pronto."
