# 📦 Meta API Client - Módulo de Extração

Módulo consolidado para extração de dados da Meta Marketing API, pronto para integração no pipeline de validação.

---

## 🎯 Características

✅ **Validado 100%** - Replica exatamente os relatórios manuais da Meta
✅ **Requisições ASYNC** - Evita rate limits
✅ **Filtros integrados** - Gasto > 0 e campanhas de captação (CAP)
✅ **Interface limpa** - Fácil de usar e integrar
✅ **Totalmente documentado** - Docstrings em todas as funções

---

## 🚀 Uso Básico

### 1. Como Módulo (Recomendado)

```python
from src.validation.meta_api_client import MetaAPIClient

# Inicializar cliente
client = MetaAPIClient()

# Extrair campanhas
df_campaigns = client.get_campaigns(
    date_start='2025-12-16',
    date_end='2026-01-12',
    apply_filters=True
)

# Extrair ad sets
df_adsets = client.get_adsets(
    date_start='2025-12-16',
    date_end='2026-01-12',
    apply_filters=True
)

# Extrair ads
df_ads = client.get_ads(
    date_start='2025-12-16',
    date_end='2026-01-12',
    apply_filters=True
)

# Ou extrair todos de uma vez
data = client.get_all_levels(
    date_start='2025-12-16',
    date_end='2026-01-12',
    apply_filters=True
)

# Acessar DataFrames
df_campaigns = data['campaigns']
df_adsets = data['adsets']
df_ads = data['ads']
```

### 2. Função Auxiliar (Uso Simples)

```python
from src.validation.meta_api_client import extract_meta_reports

# Extrair e salvar CSVs
data = extract_meta_reports(
    date_start='2025-12-16',
    date_end='2026-01-12',
    output_dir='files/validation/meta_reports/output',
    apply_filters=True
)
```

### 3. Uso Standalone (Linha de Comando)

```bash
# Últimos 7 dias (padrão)
python src/validation/meta_api_client.py

# Período específico
python src/validation/meta_api_client.py 2025-12-16 2026-01-12
```

---

## 📊 Dados Retornados

### DataFrame de Campanhas

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| Início dos relatórios | str | Data de início |
| Término dos relatórios | str | Data de fim |
| Nome da campanha | str | Nome da campanha |
| Identificação da campanha | str | ID da campanha |
| Valor usado (BRL) | float | Gasto em reais |
| Leads | int/str | Total de leads |
| Faixa A | int/str | Leads Faixa A |
| LeadQualified | int/str | Leads qualificados |
| LeadQualifiedHighQuality | int/str | Leads alta qualidade |
| Resultados | int/str | Total de resultados |
| Indicador de resultados | str | Tipo de evento principal |

### DataFrame de Ad Sets

Todas as colunas de Campanhas +
- Nome do conjunto de anúncios
- Identificação do conjunto de anúncios

### DataFrame de Ads

Todas as colunas de Ad Sets +
- Nome do anúncio
- Identificação do anúncio

---

## 🔑 Filtros Aplicados

Quando `apply_filters=True` (padrão):

### 1. Gasto > 0
Remove campanhas/adsets/ads sem investimento no período.

### 2. Nome contém "CAP"
Filtra apenas **campanhas de captação** (lead capture).
Exclui campanhas de remarketing, vendas, PPL, etc.

**Exemplos incluídos:**
- `DEVLF | CAP | FRIO | FASE 01...`
- `DEVLF | CAP | FRIO | FASE 04...`

---

## ⚙️ Configuração

### Token de Acesso

O token é importado automaticamente de `api/meta_config.py`:

```python
META_CONFIG = {
    "access_token": "EAAxxxxx...",
    "api_version": "v18.0",
}
```

### Conta de Anúncios

Por padrão usa a conta **Rodolfo Mori** (`act_188005769808959`).

Para usar outra conta:

```python
client = MetaAPIClient(account_id='act_123456789')
```

---

## 📈 Performance

| Operação | Tempo Médio |
|----------|-------------|
| Campanhas (4 semanas) | ~15-30s |
| Ad Sets (4 semanas) | ~20-40s |
| Ads (4 semanas) | ~20-40s |
| **Total (3 níveis)** | **~40-110s** |

---

## 🔧 Integração no Pipeline

### Exemplo: Script de Validação

```python
from src.validation.meta_api_client import MetaAPIClient
import pandas as pd

def validate_campaigns(date_start, date_end):
    """Valida campanhas comparando Meta API com Google Sheets."""

    # 1. Extrair dados da Meta
    client = MetaAPIClient()
    meta_campaigns = client.get_campaigns(date_start, date_end)

    # 2. Ler dados do Google Sheets
    sheets_data = pd.read_csv('sheets_export.csv')

    # 3. Comparar
    meta_ids = set(meta_campaigns['Identificação da campanha'])
    sheets_ids = set(sheets_data['campaign_id'])

    missing_in_sheets = meta_ids - sheets_ids
    missing_in_meta = sheets_ids - meta_ids

    # 4. Gerar relatório
    return {
        'total_meta': len(meta_campaigns),
        'total_sheets': len(sheets_data),
        'missing_in_sheets': len(missing_in_sheets),
        'missing_in_meta': len(missing_in_meta),
    }
```

---

## 🛠️ API Reference

### Classe `MetaAPIClient`

#### `__init__(account_id=None, api_version=None)`

Inicializa o cliente.

**Args:**
- `account_id` (str, optional): ID da conta de anúncios
- `api_version` (str, optional): Versão da API

#### `get_campaigns(date_start, date_end, apply_filters=True)`

Extrai dados de campanhas.

**Args:**
- `date_start` (str): Data de início (YYYY-MM-DD)
- `date_end` (str): Data de fim (YYYY-MM-DD)
- `apply_filters` (bool): Aplicar filtros

**Returns:**
- `pd.DataFrame`: Dados de campanhas

#### `get_adsets(date_start, date_end, apply_filters=True)`

Extrai dados de ad sets.

#### `get_ads(date_start, date_end, apply_filters=True)`

Extrai dados de ads.

#### `get_all_levels(date_start, date_end, apply_filters=True)`

Extrai todos os níveis de uma vez.

**Returns:**
- `dict`: `{'campaigns': df, 'adsets': df, 'ads': df}`

---

## 🔍 Troubleshooting

### Rate Limit

O módulo **já trata automaticamente** com:
- Requisições ASYNC
- Retry automático (até 3 tentativas)
- Backoff exponencial

### Token Expirado

Atualizar em `api/meta_config.py` e reiniciar.

### Dados Faltantes

Verificar:
1. Pixel está enviando eventos?
2. Eventos estão no Events Manager?
3. Período tem dados?

---

## 📚 Documentação Adicional

Ver: `TEST_META_API_README.md` para detalhes completos da validação.

---

## ✅ Validação

O módulo foi **100% validado** comparando com relatórios manuais:

| Nível | Manual | API | Match |
|-------|--------|-----|-------|
| Campanhas | 19 | 19 | ✅ |
| Ad Sets | 115 | 115 | ✅ |
| Ads | 168 | 168 | ✅ |

**Gastos**: R$ 176.998,32 (idêntico)
**Leads**: 27.532 (idêntico)
**Período**: 16/12/2025 - 12/01/2026
