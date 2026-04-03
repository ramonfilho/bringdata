# Previsão de Faturamento por Lançamento

## O que é

Métrica que estima o faturamento total de um lançamento com base na qualidade e volume dos leads que chegam durante a semana de captação. Retorna três cenários (pessimista/base/otimista) com breakdown de vendas por plataforma de pagamento (Guru/TMB).

Disponível em tempo real no endpoint de monitoramento. Atualiza automaticamente a cada chamada.

---

## Onde está no código

| Arquivo | O que faz |
|---|---|
| `src/monitoring/orchestrator.py` | Método `_generate_revenue_forecast()` — lógica de cálculo |
| `api/app.py` | Query Railway + chamada do método + campo `revenue_forecast` no response |
| `configs/clients/devclub.yaml` | Parâmetros calibrados (seção `business:`) |
| `scripts/backtest_revenue_forecast.py` | Validação offline leave-one-out |

---

## Parâmetros calibrados (`configs/clients/devclub.yaml`)

```yaml
business:
  ticket_contracted: 2200.0          # valor nominal contratado — base do faturamento previsto
  pct_cartao_historico: 0.469        # % cartão (Guru+Hotmart) — mediana LF44–LF47
  scenario_pessimistic_factor: 0.97  # piso — calibrado no CV real de 2% da conv. rate
  scenario_optimistic_factor: 1.03   # teto — calibrado no CV real de 2% da conv. rate
  tracking_rate: 0.528               # mediana de rastreamento histórica LF42–LF47
  conversion_rates:                  # taxas rastreadas por decil (base do modelo)
    D07: 0.0081
    D08: 0.0081
    D09: 0.0157
    D10: 0.0175
```

---

## Como o cálculo funciona

### 1. Janela de leads

A previsão usa **todos os leads pontuados desde a terça-feira BRT mais recente** — não as últimas 24h. A terça marca o início de cada semana de captação do DevClub.

Query separada em `api/app.py` (não interfere na janela de 24h do monitoramento):

```python
days_since_tuesday = (now_brt.weekday() - 1) % 7
launch_window_start = now_brt.replace(hour=0, ...) - timedelta(days=days_since_tuesday)
```

### 2. Correção do viés de rastreamento

Só ~52,8% das compras reais são rastreadas (matched por email/telefone). A taxa rastreada é corrigida antes de aplicar ao volume de leads:

```
taxa_real = taxa_rastreada / tracking_rate
```

Suposição documentada: tracking rate uniforme entre decis. Não verificado empiricamente (dados por decil não disponíveis nos xlsx históricos).

### 3. Grupos de decis

- **D07–D10**: taxa individual por decil
- **D01–D06**: agrupados como bloco único com taxa média — volume histórico insuficiente para taxas individuais confiáveis

### 4. Cenários

```
pessimista = taxa_real × 0.97
base       = taxa_real × 1.00
otimista   = taxa_real × 1.03
```

Fatores derivados do CV real de 2% da taxa de conversão observada em LF42–LF47.

### 5. Faturamento

```
faturamento = vendas_totais × R$2.200
```

O ticket é o valor **contratado** (R$2.200), igual para Guru e TMB. Inadimplência do boleto (TMB) é risco operacional separado — não entra na previsão.

### 6. Split Guru / TMB

```
vendas_guru = vendas_totais × 0.469   (cartão: Guru + Hotmart)
vendas_tmb  = vendas_totais × 0.531   (boleto: TMB + ASAAS)
```

O split cartão/boleto não é previsível antecipadamente — depende da audiência da campanha. O benchmark de 46,9% é a mediana histórica. MAE do split individual ~14% (não afeta o faturamento total).

---

## Dataset de calibração

Lançamentos válidos: **LF42, LF43, LF44, LF45, LF46, LF47** — todos com modelo jan30.

Excluídos:
- LF40, LF41 — pré-ML
- DEV19 — campanha atípica
- LF48 — modelo diferente + exclusão intencional de evento
- LF49 — modelo challenger (análise pendente)

### Benchmark do split cartão/boleto

`pct_cartao_historico` calculado com **LF44–LF47 apenas**:

- **LF42 excluído**: amostra pequena (30 vendas rastreadas) — estatisticamente pouco confiável
- **LF43 excluído**: efeito pós-Dev19 — lançamento logo após evento massivo que inundou a base com leads frescos, distorceu a proporção para 61,2% cartão vs cluster normal de 42–51%

Com LF44–LF47: CV do split cai de 18% → 10%.

---

## Resultado do backtest (leave-one-out)

Para cada lançamento, usa a mediana dos outros 5 como base de taxas.

| Launch | Leads | Prev. Vendas | Real Vendas | Err.% | Prev. Fat. | Real Fat. |
|---|---:|---:|---:|---:|---:|---:|
| LF42 | 4.301 | 52,0v | 54v | -3,6% | R$114.486 | R$118.800 |
| LF43 | 13.609 | 164,7v | 161v | +2,3% | R$362.250 | R$354.200 |
| LF44 | 12.286 | 148,7v | 149v | -0,2% | R$327.034 | R$327.800 |
| LF45 | 32.068 | 402,6v | 388v | +3,8% | R$885.766 | R$853.600 |
| LF46 | 12.903 | 162,0v | 157v | +3,2% | R$356.400 | R$345.400 |
| LF47 | 14.243 | 178,8v | 174v | +2,8% | R$393.413 | R$382.800 |

**MAE: 2,6% | Viés: +1,4%** (leve tendência a superestimar)

Para re-rodar: `python scripts/backtest_revenue_forecast.py`

---

## Estrutura do campo no response

```json
"revenue_forecast": {
  "cenario_pessimista": {
    "faturamento": 198088,
    "vendas_total": 90.0,
    "vendas_guru": 42.2,
    "vendas_tmb": 47.8
  },
  "cenario_base": {
    "faturamento": 204214,
    "vendas_total": 92.8,
    "vendas_guru": 43.5,
    "vendas_tmb": 49.3
  },
  "cenario_otimista": {
    "faturamento": 210341,
    "vendas_total": 95.6,
    "vendas_guru": 44.8,
    "vendas_tmb": 50.8
  },
  "inputs": {
    "total_leads_pontuados": 5397,
    "ticket_contracted": 2200.0,
    "pct_cartao_historico": 0.469,
    "tracking_rate_usado": 0.528,
    "launch_window_start_brt": "31/03/2026"
  }
}
```

---

## Limitações conhecidas

- **Tracking rate uniforme entre decis**: assumido, não verificado empiricamente. Erro potencial de ±23% em D10 caso a suposição não se sustente.
- **Split cartão/boleto**: CV de 10% mesmo com benchmark calibrado. MAE do split individual ~14%.
- **Ticket fixo**: R$2.200 contratado — variações de preço por oferta ou cupom não são capturadas.
- **Janela começa sempre na terça**: se o lançamento tiver início diferente, ajustar a lógica em `api/app.py` (busca por `days_since_tuesday`).
- **Lançamento pós-evento massivo** (ex: pós-Dev19): esperar proporção cartão maior que o benchmark — o split TMB/Guru será menos preciso nesses casos.
