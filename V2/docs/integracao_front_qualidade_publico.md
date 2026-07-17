# API de Qualidade de Público - Guia de Integração

Documento único e atualizado dos endpoints de leitura (GET) que expõem a
qualidade do público do lançamento, prontos para consumo em dashboard.

Todos os endpoints são **somente leitura** (devolvem JSON, não escrevem nada),
**sem autenticação**, e retornam **dado demográfico agregado - sem PII**. Os
números são exatamente os mesmos do relatório diário (o cálculo é compartilhado
no servidor), então o dashboard bate com o relatório por construção.

**Base URL**

```
https://smart-ads-api-gazrm25mda-uc.a.run.app
```

**Formato de data:** `YYYY-MM-DD`, sempre em horário de Brasília (BRT).

---

## Duas dimensões, dois endpoints

| Quero ver… | Endpoint |
|---|---|
| Perfil do público **e** a nota do modelo, cruzados por fonte (Meta/Google) e por teste A/B | `GET /monitoring/audience-quality` |
| A nota do modelo **por criativo** (anúncio), ranqueada | `GET /monitoring/utm-quality` |

O primeiro é o principal para um painel de qualidade de público. O segundo
complementa com o recorte por criativo.

---

# 1. `GET /monitoring/audience-quality`

Reúne, num só JSON, as duas coisas que importam sobre a qualidade do lançamento:

- **`audience`** - as **características** do público (ocupação, idade, tem
  computador, etc.) comparadas ao perfil do comprador de referência (Top ROAS),
  em três cortes: geral, por fonte (Meta vs Google) e por teste A/B.
- **`model_score`** - a **nota do modelo** (distribuição de decis) do público,
  também por fonte e por teste A/B, com a nota geral do lançamento.

## Parâmetros

| Parâmetro | Obrigatório | Default | Descrição |
|---|---|---|---|
| `client_id` | Não | `devclub` | Cliente. |
| `date` | Não | hoje | `YYYY-MM-DD`. "Hoje" simulado - deixa `ontem`, `D-2` e o lançamento relativos a essa data. Útil para reabrir um dia passado. |

Retorna `400` se `date` estiver fora do formato `YYYY-MM-DD`.

> **Latência:** ~10 a 20s por chamada (várias consultas ao banco). **Cacheie no
> front** (o dado muda no máximo uma vez por dia).

## Estrutura da resposta

```
{
  "ok": true,
  "client_id": "devclub",
  "anchor_date": null,
  "audience":   { "general": {...}, "by_source": [...], "by_variant": [...] },
  "model_score": { "previous_day": {...}, "current_launch": {...} }
}
```

---

## 1.1. `audience` - características do público

Todas as comparações são contra a mesma referência: o perfil do comprador do
**Top ROAS** (`reference_pct`). Para cada característica, o campo `*_quality`
(`bom` 🟢 / `ruim` 🔴 / `neutro` ⚪) já vem pronto para colorir a célula.

### `audience.general` - visão geral (todas as fontes)

Uma linha por categoria de característica (24 no total). Comparações: `day`
(ontem), `prev_day` (anteontem) e `launch` (lançamento em captação).

```json
{
  "compared_window": "2026-07-16 BRT (último dia completo)",
  "reference_pool_label": "Top 5 ROAS atribuível 60d",
  "reference_pool_n": 42038,
  "launch_lf_name": "LF62",
  "launch_window": "LF62 2026-07-06→2026-07-19 (em captação)",
  "day_n_responses": 933,
  "prev_day_n_responses": 944,
  "launch_n_responses": 12932,
  "top_count": 24,
  "top_list": [
    {
      "feature_column": "O que você faz atualmente?",
      "feature_label": "Ocupação",
      "category": "Autônomo",
      "is_critical": true,
      "reference_pct": 24.6,
      "day_pct": 32.7,      "delta_pp": 8.1,        "day_quality": "neutro",
      "prev_day_pct": 34.1, "prev_day_delta_pp": 9.5,
      "launch_pct": 34.8,   "launch_delta_pp": 10.2, "launch_quality": "neutro",
      "today_pct": null,    "today_delta_pp": null,
      "direction": "uncertain"
    }
  ]
}
```

> Leitura do exemplo: entre os autônomos, o público de ontem (32,7%) e do
> lançamento (34,8%) está acima da referência de comprador (24,6%). São 24
> categorias como essa no `top_list`.

### `audience.by_source` - Meta vs Google

Lista com **duas entradas** (uma por janela): `window: "previous_day"` (ontem) e
`window` do lançamento atual. Cada linha do `top_list` traz a mesma característica
medida em cada fonte.

```json
[
  {
    "window": "previous_day",
    "window_label": "Ontem (dia BRT anterior)",
    "reference_pool_label": "Top 5 ROAS atribuível 60d",
    "meta_n": 697,
    "google_n": 203,
    "top_list": [
      {
        "feature_column": "O que você faz atualmente?",
        "feature_label": "Ocupação",
        "category": "Autônomo",
        "is_critical": true,
        "reference_pct": 24.6,
        "meta_pct": 35.7,  "meta_delta_pp": 11.1,  "meta_quality": "neutro",
        "google_pct": 23.2, "google_delta_pp": -1.4, "google_quality": "neutro",
        "direction": "uncertain"
      }
    ]
  }
]
```

> Leitura do exemplo: os autônomos vindos do Meta (35,7%) estão bem acima da
> referência; os vindos do Google (23,2%) estão em linha com ela.

### `audience.by_variant` - teste A/B (Lead / Champion / Challenger)

Mesma estrutura do `by_source`, com **duas entradas** (ontem + lançamento). Os
três buckets são as campanhas por objetivo de otimização: **Lead** (campanha
padrão), **Champion** e **Challenger** (campanhas com o evento de qualidade do
modelo). `winner` indica qual bucket está mais próximo do perfil de comprador.

```json
[
  {
    "window": "previous_day",
    "window_label": "Ontem (dia BRT anterior)",
    "lead_n": 136, "champion_n": 0, "challenger_n": 561,
    "top_list": [
      {
        "feature_column": "O que você faz atualmente?",
        "feature_label": "Ocupação",
        "category": "Autônomo",
        "is_critical": true,
        "reference_pct": 24.6,
        "lead_pct": 21.3,      "lead_delta_pp": -3.3,      "lead_quality": "neutro",
        "champion_pct": null,  "champion_delta_pp": null,  "champion_quality": null,
        "challenger_pct": 39.2, "challenger_delta_pp": 14.6, "challenger_quality": "neutro",
        "winner": "challenger",
        "direction": "uncertain"
      }
    ]
  }
]
```

> Leitura do exemplo: entre os autônomos, as campanhas Challenger trouxeram 39,2%
> vs 21,3% das campanhas Lead. `champion_*` veio `null` porque não houve campanha
> Champion na janela.

> Um bucket pode vir `null` (ex.: `champion_*`) quando não houve campanha desse
> tipo na janela. O front deve tratar `null` como "sem dado" (não zero).

---

## 1.2. `model_score` - a nota do modelo (decis)

A nota é a distribuição dos leads nos decis **D01 (pior) a D10 (melhor)**, na
régua única do modelo Challenger. Cada janela (`previous_day` = ontem;
`current_launch` = lançamento em captação) traz:

- `distribution` - contagem de leads por decil (Total, todas as fontes).
- `total` - leads na janela.
- `baseline_challenger` - a referência (Top ROAS): `pct` por decil. É a linha-alvo.
- `by_source` - a mesma distribuição separada em `meta` e `google`.
- `by_optgoal` - separada em `lead` / `champion` / `challenger` (teste A/B).
- `score_geral` (só no `current_launch`) - a nota resumida do lançamento.

```json
{
  "previous_day": {
    "window_label": "Ontem",
    "total": 933,
    "distribution":        { "D01": 34, "D02": 56, "D03": 70, "D04": 79, "D05": 71, "D06": 104, "D07": 129, "D08": 129, "D09": 127, "D10": 134 },
    "baseline_challenger": { "pct": { "D01": 3.19, "D02": 7.14, "D03": 6.13, "D04": 7.04, "D05": 16.21, "D06": 13.19, "D07": 9.31, "D08": 9.44, "D09": 17.14, "D10": 11.22 }, "n_leads": 49409, "label": "Top 5 ROAS atribuível 60d" },
    "by_source":  { "meta":   { "distribution": { "D01": 23, "D02": 50, "D03": 59, "D04": 61, "D05": 57, "D06": 84, "D07": 97, "D08": 88, "D09": 95, "D10": 83 }, "total": 697 },
                    "google": { "distribution": { "D01": 11, "D02": 6,  "D03": 11, "D04": 18, "D05": 11, "D06": 19, "D07": 30, "D08": 37, "D09": 29, "D10": 31 }, "total": 203 } },
    "by_optgoal": { "lead":       { "distribution": { }, "total": 136 },
                    "champion":   { "distribution": { }, "total": 0 },
                    "challenger": { "distribution": { "D01": 7, "D02": 25, "D03": 40, "D04": 47, "D05": 46, "D06": 71, "D07": 88, "D08": 79, "D09": 88, "D10": 70 }, "total": 561 } }
  },
  "current_launch": {
    "window_label": "LF62 (06/07→19/07 BRT)",
    "total": 12932,
    "distribution":        { "D01": 527, "D02": 820, "D03": 1103, "D04": 1092, "D05": 1163, "D06": 1473, "D07": 1707, "D08": 1720, "D09": 1679, "D10": 1648 },
    "baseline_challenger": { "pct": { "...": "..." }, "n_leads": 49409, "label": "Top 5 ROAS atribuível 60d" },
    "by_source":  { "meta": { "distribution": { }, "total": 10788 }, "google": { "distribution": { }, "total": 2144 } },
    "by_optgoal": { "lead": { }, "champion": { }, "challenger": { } },
    "score_geral": { "decil_medio": 6.33, "pct_d9_d10": 25.8, "n": 12932, "modelo": "Challenger", "populacao": "todas as fontes" }
  }
}
```

**Como ler a nota:**
- `score_geral.decil_medio` - a nota média do lançamento, de 1 a 10 (maior = melhor).
- `score_geral.pct_d9_d10` - % dos leads nos dois melhores decis (D9 e D10).
- Comparar `distribution` (em %) contra `baseline_challenger.pct` mostra se o
  público está acima ou abaixo do perfil de comprador, decil a decil.

---

# 2. `GET /monitoring/utm-quality`

Ranqueia os criativos (anúncios) por qualidade de lead num intervalo de datas.
Detalhe completo em [integracao_front_relatorio_criativo.md](integracao_front_relatorio_criativo.md).

## Parâmetros

| Parâmetro | Obrigatório | Observação |
|---|---|---|
| `start_date` | Sim | `YYYY-MM-DD`. Para um dia só, igual ao `end_date`. |
| `end_date` | Sim | Intervalo máximo de 90 dias. |
| `min_volume` | Não (20) | Ignora criativo com menos leads que isso. |
| `client_id` | Não (devclub) | - |

## O que renderizar

Pegue **`ranking.ranked`** - lista de criativos ordenada do pior para o melhor.
Cada item tem nome, nº de leads e a nota:

```json
{
  "utm": "dev-ad0027-vid-captacao",
  "n": 42,
  "avg_decil_combined": 6.3
}
```

Uma tabela com **nome + nota + nº de leads** já é o relatório. O split por modelo
A/B vem em `champion` / `challenger` dentro de cada criativo (opcional).

---

## Resumo para quem integra

- **Público (características)** → `audience-quality` → `audience` (`general`,
  `by_source`, `by_variant`).
- **Nota do modelo** → `audience-quality` → `model_score` (`previous_day`,
  `current_launch`).
- **Nota por criativo** → `utm-quality` → `ranking.ranked`.
- Tudo GET, sem auth, JSON, sem PII. Cacheie no front.

*Documento gerado a partir dos endpoints em produção, verificados ao vivo.*
