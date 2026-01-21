# 🧪 Teste de Extração via Meta Marketing API

## Objetivo

Verificar se conseguimos obter os mesmos dados dos relatórios CSV exportados manualmente, mas via **Marketing API da Meta**.

Se conseguirmos obter com a mesma granularidade, **não precisamos** implementar download automático de emails. Caso contrário, precisaremos automatizar via email.

## 📋 Pré-requisitos

### 1. Instalar SDK do Facebook

```bash
pip install facebook-business
```

### 2. Obter Token de Acesso

1. Acesse: https://developers.facebook.com/tools/explorer/
2. Selecione o App **Smart Ads** (ou crie um novo)
3. Clique em **Generate Access Token**
4. Selecione as permissões necessárias:
   - `ads_read`
   - `ads_management`
5. Gere o token (ele será algo como `EAAxxxxx...`)

### 3. Configurar Token

**Opção A - Variável de ambiente (recomendado):**
```bash
export META_ACCESS_TOKEN='EAAxxxxx...'
```

**Opção B - Editar o script:**
Edite a linha 36 do arquivo `test_meta_api_reports.py`:
```python
ACCESS_TOKEN = 'SEU_TOKEN_AQUI'
```

## 🚀 Como Executar

```bash
cd /Users/ramonmoreira/Desktop/smart_ads/V2
python src/validation/test_meta_api_reports.py
```

## 📊 O que o script faz?

1. **Conecta na Meta Marketing API** usando suas credenciais
2. **Extrai insights** nos 3 níveis:
   - Campanhas
   - Conjuntos de anúncios (Ad Sets)
   - Anúncios (Ads)
3. **Busca métricas customizadas**:
   - Leads
   - Faixa A
   - LeadQualified
   - LeadQualifiedHighQuality
4. **Formata os dados** no mesmo padrão dos CSVs manuais
5. **Salva 3 arquivos CSV** de teste:
   - `test_api_campaigns.csv`
   - `test_api_adsets.csv`
   - `test_api_ads.csv`

## ✅ Como Validar

### 1. Compare os arquivos gerados com os manuais

```bash
# Arquivos de teste (gerados pela API)
ls -lh files/validation/meta_reports/test_api_*.csv

# Arquivos manuais (baixados da interface)
ls -lh files/validation/meta_reports/09:12\ -\ 15:12/*.csv
```

### 2. Verifique as colunas

**Colunas esperadas:**

**Campanhas:**
- Início dos relatórios
- Término dos relatórios
- Nome da campanha
- Identificação da campanha
- Orçamento do conjunto de anúncios
- Tipo de orçamento
- Valor usado (BRL)
- Leads
- Faixa A
- LeadQualified
- LeadQualifiedHighQuality

**Ad Sets (todas acima +):**
- Nome do conjunto de anúncios
- Identificação do conjunto de anúncios

**Ads (todas acima +):**
- Nome do anúncio
- Identificação do anúncio

### 3. Compare os valores

**Script auxiliar de comparação:**

```python
import pandas as pd

# Ler arquivo manual
df_manual = pd.read_csv('files/validation/meta_reports/09:12 - 15:12/Ads---Rodolfo-Mori-Campanhas-9-de-dez-de-2025-15-de-dez-de-2025.csv')

# Ler arquivo da API
df_api = pd.read_csv('files/validation/meta_reports/test_api_campaigns.csv')

# Comparar
print("Manual shape:", df_manual.shape)
print("API shape:", df_api.shape)

# Verificar se há sobreposição de campanhas
manual_campaigns = set(df_manual['Identificação da campanha'].unique())
api_campaigns = set(df_api['Identificação da campanha'].unique())

print(f"Campanhas em comum: {len(manual_campaigns & api_campaigns)}")
print(f"Somente no manual: {len(manual_campaigns - api_campaigns)}")
print(f"Somente na API: {len(api_campaigns - manual_campaigns)}")
```

## 🎯 Decisão

### ✅ Se a API funcionar bem:
- **Implementar extração via API** no script de validação
- **Não precisar** de download automático de emails
- **Mais confiável** e em tempo real

### ❌ Se a API tiver limitações:
- **Implementar download via email** conforme planejado
- Usar Gmail API para capturar emails programados
- Extrair links de download e baixar XLSXs

## 🔧 Troubleshooting

### Erro: "Token inválido"
- Gere um novo token no Graph API Explorer
- Verifique se tem as permissões corretas

### Erro: "Account ID inválido"
- Verifique se o ID está correto: `act_188005769808959`
- Confirme que tem acesso à conta de anúncios

### Erro: "Campos não encontrados"
- Alguns campos podem ter nomes diferentes na API
- Consulte a documentação: https://developers.facebook.com/docs/marketing-api/insights

### Dados vazios em eventos customizados
- Verifique se os eventos estão configurados no Pixel
- Confirme que há dados no período selecionado
- Ajuste o parsing de `actions` no código

## 📚 Documentação Oficial

- **Marketing API**: https://developers.facebook.com/docs/marketing-api
- **Insights API**: https://developers.facebook.com/docs/marketing-api/insights
- **Facebook Business SDK**: https://github.com/facebook/facebook-python-business-sdk

## 🤝 Próximos Passos

Após validar que a API funciona:

1. Integrar no script de validação principal
2. Automatizar coleta diária/semanal
3. Comparar com dados do Google Sheets
4. Gerar relatórios de discrepâncias
