# Monitoring API — Documentação para Front-end

## Endpoint

```
GET /monitoring/daily-check/railway
```

**Base URL:** `https://smart-ads-api-gazrm25mda-uc.a.run.app`

---

## Parâmetros

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `hours` | int | Não | Janela em horas (padrão: 24). Ex: `?hours=12` |
| `start_date` | string | Não | Data início no formato `YYYY-MM-DD`. Ex: `?start_date=2026-02-01` |
| `end_date` | string | Não | Data fim no formato `YYYY-MM-DD`. Ex: `?end_date=2026-02-20` |

> Se `start_date` e `end_date` forem passados, `hours` é ignorado. As datas são interpretadas em horário de Brasília (BRT).

---

## Estrutura do Response

```json
{
  "total_alerts": 4,
  "alerts_by_severity": {
    "HIGH": 3,
    "MEDIUM": 0,
    "LOW": 1
  },
  "alerts_by_category": {
    "data_quality": 4,
    "operational": 0,
    "capi_quality": 0
  },
  "alerts": [...],
  "critical_summary": "texto resumido para exibição",
  "timestamp": "2026-02-20T10:01:13.161890",
  "funnel_metrics": {...},
  "lead_quality_metrics": {...}
}
```

---

## alerts — Lista de Alertas

Cada alerta tem a seguinte estrutura:

```json
{
  "type": "distribution_drift",
  "severity": "HIGH",
  "category": "data_quality",
  "message": "texto resumido (para logs/Slack)",
  "details": { ... },
  "timestamp": "2026-02-20T10:01:13+00:00",
  "metric_value": 0.452,
  "threshold": 0.15
}
```

**`severity`** pode ser: `HIGH`, `MEDIUM`, `LOW`

---

### Tipos de alerta e como ler o `details`

#### `distribution_drift` — Distribuição de categorias mudou

```json
"details": {
  "column": "Medium",
  "changes": [
    {
      "categoria": "aberto",
      "treino": 0.144,
      "producao": 0.597,
      "diff": 0.452
    },
    {
      "categoria": "linguagem de programacao",
      "treino": 0.330,
      "producao": 0.013,
      "diff": 0.317
    }
  ]
}
```

> ⚠️ Usar `details.changes` para exibir as categorias — **não** o campo `message`. O `message` é para logs/Slack.

#### `category_drift` — Categoria nova nunca vista no treino

```json
"details": {
  "column": "Source",
  "new_categories": ["ig", "manychat"],
  "affected_count": 41,
  "percentage": 5.4
}
```

#### `missing_rate_high` — Coluna com muitos dados faltando

```json
"details": {
  "column": "Você já fez/faz/pretende fazer faculdade?",
  "missing_count": 358,
  "total_rows": 358,
  "missing_rate": 1.0
}
```

#### `score_distribution_change` — Distribuição de decis mudou

```json
"details": {
  "changes": [
    {
      "decil": "D10",
      "esperado": 0.10,
      "atual": 0.40,
      "diff": 0.30
    }
  ],
  "total_leads": 358
}
```

#### `extra_unexpected_features` — Features novas após encoding

```json
"details": {
  "extra_count": 5,
  "extra_features": ["Source_ig", "Source_manychat"],
  "total_expected": 52,
  "total_received": 57
}
```

---

## funnel_metrics

```json
"funnel_metrics": {
  "window": {
    "start_brt": "19/02/2026 00:00",
    "end_brt": "20/02/2026 23:59"
  },
  "capture": {
    "total_database": 1058,
    "total_scored": 1058
  },
  "data_quality": {
    "fbp_percentage": 96.2,
    "fbc_percentage": 92.9,
    "phone_percentage": 100.0
  },
  "scoring": {
    "total_scored": 1058,
    "avg_score": 0.419,
    "decil_distribution": {
      "D10": 303, "D09": 132, "D08": 86, "D07": 112,
      "D06": 46,  "D05": 19,  "D04": 14, "D03": 14,
      "D02": 20,  "D01": 9
    }
  },
  "capi_sent": {
    "leads_sent": 524,
    "send_rate": 49.5,
    "estimated_events": 681
  },
  "meta_response": {
    "success_count": 524,
    "error_count": 0,
    "acceptance_rate": 100.0
  },
  "conversion": {
    "total_with_survey": 1058, - DEPRECADO
    "survey_rate": 100.0  - DEPRECADO
  }
}
```

---

## lead_quality_metrics

```json
"lead_quality_metrics": {
  "historico":     { "score": 0.419, "d9": 17.6, "d10": 40.3, "count": 1104 },
  "ultimo_mes":    { "score": 0.419, "d9": 17.6, "d10": 40.3, "count": 1104 },
  "ultima_semana": { "score": 0.419, "d9": 17.6, "d10": 40.3, "count": 1104 },
  "ultimas_24h":   { "score": 0.419, "d9": 16.1, "d10": 40.1, "count": 849  }
}
```

> `score` = score médio (0 a 1). `d9` e `d10` = % de leads nos decis 9 e 10 (os melhores leads).

---

## Exemplos de chamada

```
# Últimas 12 horas
GET /monitoring/daily-check/railway?hours=12

# Dia específico
GET /monitoring/daily-check/railway?start_date=2026-02-20&end_date=2026-02-20

# Semana
GET /monitoring/daily-check/railway?start_date=2026-02-14&end_date=2026-02-20

# Mês inteiro
GET /monitoring/daily-check/railway?start_date=2026-02-01&end_date=2026-02-28
```
