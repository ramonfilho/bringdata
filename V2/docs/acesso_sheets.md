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

### 5. Planilha Atual em Produção

**Nome:** `[LF] Pesquisa - Mai25`

**ID:** `1VYti8jX277VNMkvzrfnJSR_Ko8L1LQFDdMEeD6D8_Vo`

**Total de abas:** 14

**Aba principal:**
- Nome: `[LF] Pesquisa`
- GID: 0
- Leads: ~55,000

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
