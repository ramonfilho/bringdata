# Relatório de Qualidade de Criativo — Integração

Endpoint que rankeia os criativos (anúncios) por qualidade de lead, num intervalo de datas. Já está no ar.

## A chamada

```
GET https://smart-ads-api-gazrm25mda-uc.a.run.app/monitoring/utm-quality
      ?start_date=2026-06-17
      &end_date=2026-06-18
```

| Parâmetro | Obrigatório? | Observação |
|---|---|---|
| `start_date` | Sim | Formato `2026-06-17`. Para um dia só, mande igual ao `end_date`. |
| `end_date` | Sim | Intervalo máximo de 90 dias. |
| `min_volume` | Não (default 20) | Ignora criativo com menos leads que isso. |
| `top_n` | Não | Só afeta o post do Slack. Pode ignorar. |
| `client_id` | Não (default devclub) | — |

Só leitura — devolve JSON, não posta em lugar nenhum. Retorna `400` se faltar data ou o intervalo passar de 90 dias.

## O que você renderiza

Pegue **`ranking.ranked`** — uma lista de criativos, já ordenada do **pior pro melhor**. Cada item tem três coisas que importam:

```
{
  "utm": "dev-ad0027-vid-captacao",   // nome do criativo
  "n": 42,                            // quantos leads esse criativo trouxe
  "avg_decil_combined": 6.3           // a NOTA, de 1 a 10 (maior = melhor)
}
```

Uma tabela com **nome + nota + nº de leads** já é o relatório inteiro.

## Resposta (resumida)

```
{
  "ok": true,
  "window": { "label": "17/06 a 18/06", "n_total": 1522 },
  "ranking": {
    "ranked": [
      { "utm": "dev-ad0027-vid", "n": 42, "avg_decil_combined": 6.3 },
      { "utm": "dev-ad0160-vid", "n": 58, "avg_decil_combined": 5.1 }
    ]
  }
}
```

## Campos extras (use só se quiser — dá pra ignorar todos)

- **`window.label`** — texto pronto pro título, ex: `17/06 a 18/06`.
- **`champion` e `challenger`** (dentro de cada criativo) — a nota separada pelos dois modelos de IA que rodam em teste A/B. Cada um tem `n`, `avg_decil` e `pct_d9_d10` (% de leads top). Pode vir nulo. Use só se quiser mostrar o detalhe por modelo.
- **campos terminados em `_lf`** e **`window_lf`** — os mesmos números, mas calculados sobre o lançamento inteiro em vez do seu intervalo de datas. É comparação de tendência. Ignore se não precisar.
- **`source_hint`** — origem do tráfego (ex: `facebook-ads`). Só importa quando o `utm` vier como um número sem nome — aí você mostra algo tipo "criativo sem nome · facebook-ads".
- **`split_mode`, `worst`, `best`** — ignore. É coisa do post automático do Slack, não serve pro front.

> Resumo: o front só precisa de `start_date` e `end_date` na chamada, e de `ranking.ranked` na resposta. Todo o resto é opcional.
