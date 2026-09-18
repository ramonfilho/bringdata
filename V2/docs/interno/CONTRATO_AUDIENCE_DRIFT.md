# Drift de público — endpoint para dashboard

GET de leitura única que devolve o JSON do drift de público (audiência atual vs Top 5 ROAS). 24 linhas, uma por categoria. Mesmo cômputo do digest do Slack, sem filtro de magnitude. Sem autenticação.

## Chamada

`GET https://smart-ads-api-12955519745.us-central1.run.app/monitoring/audience-drift`

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `client_id` | string | `devclub` | Cliente. Lê o snapshot de baseline correspondente. |
| `date` | string (`YYYY-MM-DD`) | hoje | "Hoje" simulado — `day_*`, `prev_day_*` e `launch_*` ficam relativos. |

`400` se `date` estiver fora do formato `YYYY-MM-DD`.

## Exemplo de resposta

```json
{
  "compared_window": "2026-05-26 BRT (último dia completo)",
  "compared_window_kind": "previous_full_brt_day",
  "reference_pool_label": "Top 5 ROAS atribuível 60d",
  "reference_pool_n": 42038,
  "day_n_responses": 1187,
  "prev_day_n_responses": 836,
  "today_window": "",
  "today_n_responses": 0,
  "launch_window": "LF57 2026-05-25→2026-05-31 (em captação)",
  "launch_n_responses": 2448,
  "launch_lf_name": "LF57",
  "launch_cap_start": "2026-05-25",
  "launch_cap_end": "2026-05-31",
  "top_threshold_pp": 2.0,
  "top_count": 24,
  "top_list": [
    {
      "feature_column": "Tem computador/notebook?",
      "feature_label": "Tem Computador",
      "category": "Não",
      "is_critical": true,
      "reference_pct": 13.4,
      "day_pct": 28.4,
      "delta_pp": 15.0,
      "day_quality": "ruim",
      "prev_day_pct": 24.6,
      "prev_day_delta_pp": 11.3,
      "launch_pct": 27.1,
      "launch_delta_pp": 13.8,
      "launch_quality": "ruim",
      "today_pct": null,
      "today_delta_pp": null,
      "direction": "very_negative"
    }
  ]
}
```

## Schema de uma linha

| Campo | Tipo | Descrição |
|---|---|---|
| `feature_column` | string | Slug PT-Long do campo da pesquisa. |
| `feature_label` | string | Rótulo curto para exibição. |
| `category` | string | Valor da categoria (ex: `Sim`, `18-24`). |
| `is_critical` | bool | Feature crítica pro lift, segundo o snapshot. |
| `reference_pct` | float | % no Top 5 ROAS (baseline). |
| `day_pct` / `delta_pp` / `day_quality` | float / float / enum | Ontem completo BRT. |
| `prev_day_pct` / `prev_day_delta_pp` | float | Anteontem (D-2). |
| `launch_pct` / `launch_delta_pp` / `launch_quality` | float / float / enum | Lançamento ativo, `cap_start` até agora. |
| `today_pct` / `today_delta_pp` | nullable | Hoje parcial. Sempre `null` neste endpoint. |
| `direction` | enum | `positive` / `very_positive` / `negative` / `very_negative` / `uncertain` / `insufficient_data`. |

`quality` ∈ `{bom, ruim, neutro}` é a regra de cor pré-computada, derivada de `direction × sinal(Δpp)`:

| direction | Δpp > 0 | Δpp < 0 |
|---|---|---|
| `positive` / `very_positive` | `bom` (🟢) | `ruim` (🔴) |
| `negative` / `very_negative` | `ruim` (🔴) | `bom` (🟢) |
| `uncertain` / `insufficient_data` | `neutro` (⚪) | `neutro` (⚪) |

## Notas operacionais

- `top_count` é sempre 24 (todas as categorias do snapshot). `top_threshold_pp: 2.0` no metadata é informativo — indica o cut do digest do Slack, mas o endpoint não filtra.
- Datas anteriores a **23/05/2026** retornam `top_list: []` — o ledger `registros_ml` só começou nessa data. Front deve mostrar estado vazio.
- Latência: 3-5s por chamada (4 queries ao Railway). Sem cache no back; se chamar com alta frequência, cacheie no front.
- Sem PII. Dado é demográfico agregado.
