# Como Acessar Google Sheets em Produção

Este documento explica como foi configurado o acesso aos dados do Google Sheets a partir do código Python.

## Método Utilizado: Application Default Credentials (ADC)

### 1. Autenticação

O projeto usa **Google Cloud Application Default Credentials** que já estavam configuradas localmente.

**Arquivo de credenciais:**
```
/Users/ramonmoreira/.config/gcloud/application_default_credentials.json
```

**Projeto Google Cloud:**
```
smart-ads-451319
```

**Service Account Email:**
```
smart-ads-451319@appspot.gserviceaccount.com
```

### 2. Permissões Necessárias

As credenciais foram reautenticadas com os escopos necessários:

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/spreadsheets,\
https://www.googleapis.com/auth/drive
```

**Escopos utilizados:**
- `cloud-platform`: Acesso geral ao Google Cloud
- `spreadsheets`: Leitura e escrita em Google Sheets
- `drive`: Acesso a arquivos no Google Drive

### 3. Compartilhamento da Planilha

A planilha foi compartilhada com o email da service account:

**Email:** `smart-ads-451319@appspot.gserviceaccount.com`

**Permissão:** Editor (para leitura e eventual escrita)

### 4. Código Python para Acesso

#### Instalação de Dependências

```bash
pip install gspread google-auth
```

#### Código Básico

```python
import gspread
from google.auth import default
import pandas as pd

# Autenticar usando ADC
credentials, project = default()
gc = gspread.authorize(credentials)

# Abrir planilha por URL
url = "https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo/edit"
sheet = gc.open_by_url(url)

# Listar todas as abas
worksheets = sheet.worksheets()
for ws in worksheets:
    print(f"Aba: {ws.title} | GID: {ws.id}")

# Ler dados de uma aba específica
worksheet = sheet.worksheets()[0]  # Primeira aba
valores = worksheet.get_all_values()

# Converter para DataFrame
headers = valores[0]
dados = valores[1:]
df = pd.DataFrame(dados, columns=headers)
```

#### Acesso a Abas Específicas por GID

```python
# Via CSV (método alternativo para planilhas públicas)
gid = 0  # ID da aba
url_csv = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
df = pd.read_csv(url_csv)
```

### 5. Planilhas

As definições canônicas estão em `src/validation/data_loader.py` (linhas 66–67):

```python
PRODUCAO_SHEETS_URL = 'https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo'  # [LF] Pesquisa - Produção
BACKUP_SHEETS_URL   = 'https://docs.google.com/spreadsheets/d/1OqNYA5zU9ix1uf52ovRYIdLhcugzwgfKOheKxE_zgvE'  # [LF] Pesquisa - Backup
```

Variáveis de ambiente que sobrescrevem os defaults:
- `GOOGLE_SHEETS_URL` → produção (default: `PRODUCAO_SHEETS_URL`)
- `SECONDARY_SHEETS_URL` → backup (default: `BACKUP_SHEETS_URL`)

Cada planilha tem seus dados de leads na **aba 0** (`[LF] Pesquisa`). A aba 1 existe em cada planilha mas é usada apenas para consulta — não é carregada no treino.

O pipeline de treino (`train_pipeline.py`) carrega **ambas** as planilhas (produção + backup), sempre aba 0 de cada:
- `num_sheets_api=1` → aba 0 apenas
- `include_secondary=True` (default no `LeadDataLoader`) → carrega produção + backup

#### Planilha de Produção (`PRODUCAO_SHEETS_URL`)

**ID:** `1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo`

**URL:** `https://docs.google.com/spreadsheets/d/1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo`

**Nome:** `[LF] Pesquisa - Produção`

**Aba de dados:** aba 0 (`[LF] Pesquisa`)

Usada por: pipeline de treino, monitoring (`data_drift_detection.py`), API (`app.py`).

#### Planilha de Backup (`BACKUP_SHEETS_URL`)

**ID:** `1OqNYA5zU9ix1uf52ovRYIdLhcugzwgfKOheKxE_zgvE`

**URL:** `https://docs.google.com/spreadsheets/d/1OqNYA5zU9ix1uf52ovRYIdLhcugzwgfKOheKxE_zgvE`

**Nome:** `[LF] Pesquisa - Backup`

**Aba de dados:** aba 0 (`[LF] Pesquisa`)

### 6. Limitações e Considerações

#### Quotas do Google Sheets API

- **Read requests:** 300 por minuto por projeto
- **Write requests:** 300 por minuto por projeto

Para evitar rate limits:
```python
import time

# Adicionar delay entre requests
time.sleep(1)  # 1 segundo entre chamadas
```

#### Duplicatas em Headers

A planilha tem colunas duplicadas (Pontuação, Score, Faixa). Para lidar com isso:

```python
# NÃO usar get_all_records() - falha com duplicatas
# valores = worksheet.get_all_records()  # ❌ Erro!

# USAR get_all_values() - funciona sempre
valores = worksheet.get_all_values()  # ✅ OK
headers = valores[0]
dados = valores[1:]
df = pd.DataFrame(dados, columns=headers)
```

### 7. Troubleshooting

#### Erro: "insufficient authentication scopes"

**Solução:** Reautenticar com escopos corretos (ver seção 2)

#### Erro: "Permission denied"

**Solução:** Verificar se planilha foi compartilhada com o email da service account

#### Erro: "header row contains duplicates"

**Solução:** Usar `get_all_values()` ao invés de `get_all_records()`

### 8. Alternativas

#### Método CSV (sem autenticação)

Para planilhas públicas:

```python
import pandas as pd

sheet_id = "1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo"
gid = 0
url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

df = pd.read_csv(url)
```

**Vantagens:**
- Sem necessidade de autenticação
- Mais rápido
- Sem quotas da API

**Desvantagens:**
- Apenas leitura
- Planilha deve ser pública
- Não lista abas automaticamente

## Referências

- [gspread Documentation](https://docs.gspread.org/)
- [Google Sheets API Quotas](https://developers.google.com/sheets/api/limits)
- [Google Cloud ADC](https://cloud.google.com/docs/authentication/application-default-credentials)

---

## Calendário de lançamentos (LF) — caminho OFICIAL

**Pergunta típica:** "quando começou/terminou a captação da LF61?"

**Fonte canônica:** planilha **PC FORMULÁRIOS**, aba **`LF's`** (id `1gZlXL9-S-LmQceTdJy9MAYfqUrXySVNiY-Z6W5i_B3U`).
Em conflito de data, **a planilha vence** — não existe camada de override no yaml.

**NÃO** abra a planilha na mão, **não** baixe CSV, **não** peça screenshot e **não**
infira data por heurística de segunda-feira (a LF62 tem captação de 2 semanas — um
chute semanal erra). Use a ferramenta:

```bash
cd V2 && set -a; source .env; set +a           # .env traz a service account (obrigatório)

python -m src.data.launch_calendar --dry-run   # ver as datas e reconciliar com o yaml
python -m src.data.launch_calendar --sync      # regenerar configs/launches.yaml
python -m src.data.launch_calendar --check     # cruzar com o ledger (LF não cadastrado / dia órfão)
```

- `configs/launches.yaml` é **gerado**. Não editar à mão: data errada se corrige **na planilha**.
- A curadoria que a planilha não tem (`excluded_from_reference` dos outliers do Top 5,
  `notes`) é **preservada** no sync.
- **403 `ACCESS_TOKEN_SCOPE_INSUFFICIENT`?** É a credencial pessoal do `gcloud`, que não
  tem escopo de Sheets. O `.env` aponta pra service account correta — carregue-o.
- Leitura é **API pura** (`gspread.get_all_values()`, lê a aba inteira sem truncar).
  O `read_file_content` do conector Drive **trunca na ~LF50** — isso é limite do leitor,
  **não** da planilha.

**Depois de cadastrar um LF novo:** cheque o buraco de decil no ledger e rode
`scripts/backfill_dual_decil_from_scores_historicos.py` (a janela nova pode cair antes
da escrita dupla online). Detalhe em `plano_decis_dois_modelos_ledger.md`.

*Ferramenta: `V2/src/data/launch_calendar.py` (PR #45, na main desde 10/07/2026).*
