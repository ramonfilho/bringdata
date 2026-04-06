# Previsão de Faturamento por Lançamento

## O que é

Métrica que estima o faturamento total de um lançamento com base no volume de leads que chegam durante a semana de captação. Retorna três cenários (pessimista/base/otimista) com breakdown de vendas por plataforma de pagamento (Guru/TMB) e faturamento recebido na semana do carrinho.

Disponível em tempo real no endpoint de monitoramento. Atualiza automaticamente a cada chamada.

---

## Onde está no código

| Arquivo | O que faz |
|---|---|
| `src/monitoring/orchestrator.py` | Método `_generate_revenue_forecast()` — lógica de cálculo |
| `api/app.py` | Query Meta Ads API + chamada do método + campo `revenue_forecast` no response |
| `configs/clients/devclub.yaml` | Parâmetros calibrados (seção `business:`) |
| `src/core/client_config.py` | Dataclass `BusinessConfig` — defaults e tipos |
| `scripts/backtest_revenue_forecast.py` | Validação offline leave-one-out |

---

## Metodologia: Flat-Rate Leave-One-Out

### Visão geral

```
vendas_previstas = total_leads_meta × (conv_rastr_mediana / tracking_rate_mediana)
faturamento      = vendas_previstas × R$2.200
```

A taxa implícita `conv_rastr / tracking_rate` é algebricamente igual a `vendas_reais / leads_meta` — a taxa de conversão real sobre o total de leads da campanha.

### Por que flat-rate e não por decil

A abordagem por decil (D1–D5 / D6–D9 / D10 com taxas individuais) foi testada e descartada por três razões:

1. **Subestimativa sistemática**: usava leads no DB (apenas quem respondeu à pesquisa e foi pontuado), ignorando leads Meta que não chegam ao banco. Esses leads também compram.
2. **Taxa zero para D1–D6**: as taxas observadas em produção para decis baixos refletem o comportamento do test set, não do mundo real. Muitos compradores chegam por leads que o modelo classifica mal.
3. **MAE alto**: backtest LOO com metodologia por decil → MAE 31–41%. Flat-rate → **MAE 7,5%**.

### Population: leads Meta, não leads do banco

A população correta é o total de leads que entraram pela campanha Meta, independente de terem respondido à pesquisa. Obtido via Meta Ads API (campanha com "CAP" no nome, desde a terça-feira BRT):

```python
_rows_launch = meta.get_insights(
    fields=['campaign_name', 'actions'],
    since_date=launch_window_start,
    until_date=today,
    filtering=[{'field': 'campaign.name', 'operator': 'CONTAIN', 'value': 'CAP'}]
)
total_meta_leads = sum(
    int(a['value']) for r in _rows_launch
    for a in (r.get('actions') or [])
    if a['action_type'] == 'offsite_conversion.fb_pixel_lead'
)
```

Requer `META_ACCESS_TOKEN` configurado no Cloud Run (token vitalício, não expira).

---

## Parâmetros calibrados (`configs/clients/devclub.yaml`)

```yaml
business:
  ticket_contracted: 2200.0          # valor nominal contratado — base do faturamento previsto
  guru_ticket_price: 1997.0          # preço real no Guru (payment.gross via API)
  guru_realizacao_factor: 0.87       # ~13% cancelamentos/chargebacks Guru (back-calculado LF42–LF47)
  pct_cartao_historico: 0.469        # % cartão (Guru+Hotmart) — mediana LF44–LF47
  n_parcelas_boleto: 12              # entrada + 11 mensais (TMB/ASAAS)
  conv_rastr_mediana: 0.0065         # mediana LF42–LF47: vendas_matched / total_leads_meta
  tracking_rate: 0.528               # mediana LF42–LF47: vendas_matched / vendas_reais
  scenario_pessimistic_factor: 0.97  # piso — calibrado no CV real de 2% da conv. rate
  scenario_optimistic_factor: 1.03   # teto — calibrado no CV real de 2% da conv. rate
```

---

## Como o cálculo funciona

### 1. Janela de leads

A previsão usa **todos os leads da campanha CAP desde a terça-feira BRT mais recente** — não as últimas 24h. A terça marca o início de cada semana de captação do DevClub.

```python
days_since_tuesday = (now_brt.weekday() - 1) % 7
launch_window_start = now_brt.replace(hour=0, ...) - timedelta(days=days_since_tuesday)
```

### 2. Taxa real implícita

```
taxa_real = conv_rastr_mediana / tracking_rate
          = 0.65% / 52.8%
          = 1.231%
```

Derivação:
- `conv_rastr = vendas_matched / leads_meta`
- `tracking_rate = vendas_matched / vendas_reais`
- `conv_rastr / tracking_rate = vendas_reais / leads_meta` ✓

### 3. Vendas e cenários

```
vendas_base = total_leads_meta × 1.231%
pessimista  = vendas_base × 0.97
otimista    = vendas_base × 1.03
```

Fatores ±3% derivados do CV histórico da taxa de conversão (LF42–LF47).

### 4. Split Guru / TMB

```
vendas_guru = vendas_base × 46.9%   (cartão: Guru + Hotmart)
vendas_tmb  = vendas_base × 53.1%   (boleto: TMB + ASAAS)
```

Mediana LF44–LF47 (exclui LF42 por volume pequeno e LF43 por efeito pós-Dev19).

### 5. Faturamento contratado e recebido

**Faturamento contratado** = valor nominal da venda × R$2.200:
```
fat_contratado = vendas_totais × R$2.200
```

**Faturamento recebido** = caixa real na semana do carrinho:
```
fat_recebido = vendas_guru × R$1.997 × 0.87   (Guru: ticket real × fator realização)
             + vendas_tmb  × R$183,33           (TMB: 1ª parcela = R$2.200 / 12)
```

- `R$1.997`: preço real praticado no Guru (≠ R$2.200 nominal)
- `0.87`: fator de realização — absorve ~13% de cancelamentos e chargebacks no Guru (back-calculado de LF42–LF47 para fechar com Fat. Recebido real do cliente)
- `R$183,33`: entrada da parcela TMB/ASAAS

---

## Dataset de calibração

**6 lançamentos válidos: LF42, LF43, LF44, LF45, LF46, LF47** — todos com modelo jan30.

Dados autoritativos: `outputs/validation/historico/evolucao_ml_devclub_20260402_140902.xlsx`

| Lançamento | Leads Meta | Vendas matched | Vendas reais | conv_rastr | tracking_rate |
|---|---:|---:|---:|---:|---:|
| LF42 | 4.373 | 29 | 54 | 0,66% | 53,7% |
| LF43 | 14.734 | 94 | 161 | 0,64% | 58,4% |
| LF44 | 13.360 | 99 | 149 | 0,74% | 66,4% |
| LF45 | 27.615 | 201 | 386 | 0,73% | 52,1% |
| LF46 | 12.463 | 67 | 154 | 0,54% | 43,5% |
| LF47 | 13.812 | 86 | 175 | 0,62% | 49,1% |
| **Mediana** | — | — | — | **0,65%** | **52,8%** |

**Excluídos do conjunto de calibração:**
- LF40, LF41 — pré-ML
- DEV19 — campanha atípica (escala fora do padrão)
- **LF48** — outlier severo (+38% erro no LOO): taxa de conversão real 0,89% vs mediana histórica 1,23%; A/B com controle insuficiente (ROAS Ctrl=0,79×, flagged no arquivo de evolução)

**Benchmark do split cartão/boleto** calculado com LF44–LF47 apenas:
- LF42 excluído: amostra pequena (30 vendas rastreadas)
- LF43 excluído: efeito pós-Dev19 — 61,2% cartão vs cluster normal 42–51%

---

## Backtest leave-one-out (LOO)

Para cada lançamento i, usa a mediana dos outros 5 como taxas base. Não usa dados do próprio lançamento na calibração — evita vazamento de informação.

```python
para cada lançamento i:
    outros = todos exceto i
    conv_rastr_base  = mediana(vendas_matched / leads_meta  dos outros)
    tracking_base    = mediana(vendas_matched / vendas_reais dos outros)
    vendas_prev      = leads_meta_i × (conv_rastr_base / tracking_base)
    erro_i           = (vendas_prev - vendas_reais_i) / vendas_reais_i
```

### Resultado

| Launch | Leads Meta | Vendas Reais | Fat. Real | Previsto | Erro% |
|---|---:|---:|---:|---:|---:|
| LF42 | 4.373 | 54 | R$118.800 | R$117.869 | -0,8% |
| LF43 | 14.734 | 161 | R$354.200 | R$412.813 | +16,5% |
| LF44 | 13.360 | 149 | R$327.800 | R$360.104 | +9,9% |
| LF45 | 27.615 | 386 | R$849.200 | R$721.723 | -15,0% |
| LF46 | 12.463 | 154 | R$338.800 | R$338.579 | -0,1% |
| LF47 | 13.812 | 175 | R$385.000 | R$375.227 | -2,5% |

**MAE: 7,5% | Viés: +1,3%** (leve tendência a superestimar)

Para re-rodar: `python scripts/backtest_revenue_forecast.py`

---

## Estrutura do campo no response

```json
"revenue_forecast": {
  "cenario_pessimista": {
    "faturamento": 161855,
    "faturamento_recebido": 67108,
    "vendas_total": 73.6,
    "vendas_guru": 34.5,
    "vendas_tmb": 39.1
  },
  "cenario_base": {
    "faturamento": 166860,
    "faturamento_recebido": 69239,
    "vendas_total": 75.8,
    "vendas_guru": 35.6,
    "vendas_tmb": 40.3
  },
  "cenario_otimista": {
    "faturamento": 171866,
    "faturamento_recebido": 71197,
    "vendas_total": 78.1,
    "vendas_guru": 36.6,
    "vendas_tmb": 41.5
  },
  "inputs": {
    "total_leads_meta": 6161,
    "conv_rastr_mediana": 0.0065,
    "tracking_rate_usado": 0.528,
    "taxa_real_implicita": 1.231,
    "ticket_contracted": 2200.0,
    "pct_cartao_historico": 0.469,
    "metodologia": "flat-rate LOO LF42-LF47 MAE=7.5%",
    "launch_window_start_brt": "31/03/2026"
  },
  "expected_conversion": {
    "fonte": "DEV19–LF48",
    "distribuicao_leads": {
      "D1_D5": {"leads": 1634, "pct": 28.0},
      "D6_D9": {"leads": 2436, "pct": 41.7},
      "D10":   {"leads": 1767, "pct": 30.3},
      "total_db": 5837,
      "response_rate_pct": 94.7
    },
    "compradores_esperados": {
      "D1_D5": 9.0,
      "D6_D9": 32.3,
      "D10":   35.8,
      "total": 77.1,
      "taxa_media_corrigida": 1.320
    },
    "taxas_corrigidas": {
      "D1_D5": 0.549,
      "D6_D9": 1.326,
      "D10":   2.027,
      "tracking_rate_aplicado": 52.8
    },
    "taxa_implicita_por_meta_lead": 1.250
  }
}
```

---

## Expected Conversion — bottom-up por faixa

### O que é

Bloco diagnóstico dentro de `revenue_forecast` que estima compradores a partir da distribuição real de decis dos leads DB do lançamento em curso, aplicando taxas históricas de conversão por faixa.

Complementa o flat-rate (metodologia primária): enquanto o flat-rate usa uma taxa agregada sobre o total de leads Meta, o expected_conversion mostra como a composição da audiência se distribui pelos decis e o que isso implica em compradores — faixa por faixa.

### Janela de dados

Mesma janela do `revenue_forecast`: **desde a última terça-feira BRT** até o momento da chamada. Independente do parâmetro `hours` passado ao endpoint de monitoramento.

### Fórmulas

**Taxas corrigidas** (base: `devclub.yaml` → `conversion_rate_benchmark`):

```
taxa_corrigida_faixa = taxa_raw_faixa / tracking_rate
```

Onde `taxa_raw_faixa` = `vendas_matched / leads_DB` observada historicamente (DEV19–LF48).
A divisão pelo `tracking_rate` converte de "vendas rastreadas" para "vendas reais" — mesma base do flat-rate.

| Faixa | Taxa raw (matched/DB) | Taxa corrigida (reais/DB) |
|---|---|---|
| D1–D5 | 0,29% | 0,549% |
| D6–D9 | 0,70% | 1,326% |
| D10   | 1,07% | 2,027% |

**Compradores esperados por faixa:**

```
compradores_faixa = leads_DB_faixa × taxa_corrigida_faixa
```

**Taxa média ponderada (linha TOTAL):**

```
taxa_media_corrigida = total_compradores / total_db_leads × 100
```

**Taxa implícita por Meta lead** (mesmo denominador do flat-rate):

```
taxa_implicita_por_meta_lead = total_compradores / total_meta_leads × 100
```

### Comparação com flat-rate

Com as taxas corrigidas, o bottom-up converge com o flat-rate (~1,2–1,3% por Meta lead). A diferença residual (~1,5%) reflete calibrações em datasets ligeiramente diferentes (DEV19–LF48 vs LF42–LF47).

### Por que as taxas do PDF enviado ao cliente são menores

O relatório PDF de assertividade (`gerar_pdf_assertividade_decil.py`) usa a fórmula sem correção:

```
taxa_PDF = vendas_matched / leads_DB × 100
```

Isso subestima as taxas reais por um fator de `1 / tracking_rate ≈ 1,89×`. As taxas do PDF (~0,29% / ~0,70% / ~1,07%) representam apenas as vendas rastreadas. As taxas corrigidas usadas no endpoint (~0,55% / ~1,33% / ~2,03%) são mais próximas da realidade.

### Configuração

`conversion_rate_benchmark` em `configs/clients/devclub.yaml`:

```yaml
conversion_rate_benchmark:
  periodo_referencia: "DEV19–LF48"
  D1_D5: 0.0029    # taxa raw — corrigida pelo tracking_rate em runtime
  D6_D9: 0.0070
  D10:   0.0107
```

Se `conversion_rate_benchmark` não estiver configurado ou `decil_distribution` vier vazio, o bloco `expected_conversion` é omitido do response.

---

## Limitações conhecidas

- **Taxa histórica pode ficar desatualizada**: se a qualidade da audiência mudar significativamente (novo criativo, nova oferta, pós-evento massivo como Dev19), `conv_rastr_mediana` deixa de ser representativa. Recalibrar com `backtest_revenue_forecast.py` a cada 3–4 lançamentos.
- **LF48 excluído por ser outlier**: se o padrão de LF48 (baixa conversão, A/B com ctrl insuficiente) se repetir, o conjunto de calibração precisará ser revisado.
- **Split cartão/boleto**: CV de 10% mesmo com benchmark calibrado — não afeta o faturamento total, mas o breakdown Guru/TMB tem MAE ~14%.
- **Ticket fixo**: R$2.200 contratado — variações de preço por oferta ou cupom não são capturadas.
- **Janela começa sempre na terça**: se o lançamento tiver início diferente, ajustar `days_since_tuesday` em `api/app.py`.
