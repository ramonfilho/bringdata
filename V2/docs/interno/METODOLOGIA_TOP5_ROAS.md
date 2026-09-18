# Top 5 ROAS atribuível 60d — metodologia canônica

**Última recalibragem:** 2026-05-14
**Top 5 atual:** `LF45, LF44, LF46, LF41, LF43`
**Script canônico:** `scripts/compute_top5_roas_attributable.py`
**Saídas:** `outputs/analysis/roas_attributable_{30,45,60}d.csv`

---

## Por que essa metodologia existe

Antes desta doc, "Top 5 ROAS" foi definido por 3 fontes diferentes que **discordavam**:

| Fonte | Top 5 que apontava |
|---|---|
| `configs/reference_audience_profiles/devclub.json` (antigo) | LF41, LF43, LF44, LF45, LF46, LF47 (Top 6, label "atribuível 60d") |
| `scripts/audience_quality_report.py:37` (antigo) | LF40, LF41, LF45, LF50, LF53 |
| `outputs/analysis/roas_realized.csv` (antigo) | LF41, LF40, LF45, LF50, LF44 (por `roas_realized` desc) |

A discordância existia porque cada fonte usava critério/janela diferente sem isso ficar explícito. Esta doc fecha a definição.

---

## Definição operacional

Para cada lançamento (LF) definido em `configs/launches.yaml`:

```
ROAS_60d(LF) = receita_atribuível(LF) / spend(LF)
```

Onde:

### Receita atribuível

Soma do valor de vendas em que:
- O comprador (matching por email **ou** telefone normalizado) coincide com um lead capturado no LF
- `sale_date ∈ (lead.capture_date, lead.capture_date + 60d]`
- O lead pertence ao LF pela regra **primeiro LF**: cada identidade (email ou telefone) é atribuída ao LF de captação mais antigo em que aparece. Evita double-count entre lançamentos.

### Valor da venda por plataforma (à vista)

| Plataforma | Valor usado | Por quê |
|---|---|---|
| Guru | valor cheio (`valor`) | parcelado já recebido em fluxo direto, ticket é o valor de fato |
| Hotmart | valor cheio (`valor`) | idem |
| Asaas | `payment.value` = primeira parcela recebida | parcelamento via boleto; só conta o que foi pago |
| TMB | `Ticket × 1/12` = primeira parcela | TMB tem 12 parcelas iguais (validado em 5.709 pedidos: ratio Valor/Ticket ≈ 0.0833) |

Status filtrado:
- Guru/Hotmart: `status='Aprovada'`
- Asaas: tudo no `asaas_realized.parquet` (já filtra primeira parcela paga via `refetch_asaas_realized.py`)
- TMB: `Data Efetivado not null AND Data Cancelado is null`

### Spend

`spend(LF)` = "Gasto Total" da aba **Performance Geral** do relatório individual mais recente em `outputs/validation/YYYY-MM/LFxx*.xlsx`. Gerado pelo time DevClub via Meta Insights API com filtro proprietário (curadoria de campanhas de marca, criativos descontinuados, etc.). **Não é equivalente** à query raw da Meta Insights API.

Spend-check em 2026-05-14: LF45 xlsx = R$ 108.750,63 vs Meta API raw (filtro CAP) = R$ 115.589,77 (+6.3% no raw). A diferença vem dos filtros internos do time. Confirmado em 2026-05-14 que o xlsx é a fonte oficial.

### Janela 60d

Default: 60 dias após captação individual. Estável: testes em 30/45/60 dias produzem **Top 5 idêntico** — só o ROAS absoluto muda.

---

## Fontes de dados

### Leads
- **Preferência por LF:** se `outputs/validation/arquivos_leads/[LFxx] Leads.xlsx` existe, usa esse (exportado pelo time DevClub, cobertura completa do LF)
- **Fallback:** `files/validation/cache/railway_leads_*.parquet` (LF49+ atualmente; Railway só tem dados ≥ 2026-02-18)

### Vendas (4 plataformas)
- `outputs/cache/raw_data_latest.pkl` — Guru + Hotmart
- `outputs/analysis/asaas_realized.parquet` — Asaas (já consolidado por `scripts/refetch_asaas_realized.py`)
- `data/devclub/pedidos_*.xlsx` — TMB

### Spend
- `outputs/validation/YYYY-MM/LFxx*.xlsx` — Performance Geral · Gasto Total
- Pega o arquivo mais recente por LF (max mtime)

### Normalização de identificadores
- Email: lowercase + strip
- Telefone: dígitos-só; remove prefixo `55` se ≥12 dígitos; mantém 10-11 dígitos

---

## Top 5 canônico (2026-05-14)

| # | LF | cap_start | cap_end | leads | compradores 60d | conv% | receita 60d | spend | ROAS |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **LF45** | 2026-02-03 | 2026-02-23 | 28.983 | 399 | 1.38% | R$ 323.328 | R$ 108.751 | **2.97x** |
| 2 | **LF44** | 2026-01-27 | 2026-02-03 | 11.522 | 159 | 1.38% | R$ 119.994 | R$ 43.936 | **2.73x** |
| 3 | **LF46** | 2026-02-24 | 2026-03-02 | 11.461 | 170 | 1.48% | R$ 134.346 | R$ 55.534 | **2.42x** |
| 4 | **LF41** | 2025-12-02 | 2025-12-08 | 4.409 | 63 | 1.43% | R$ 56.707 | R$ 26.589 | **2.13x** |
| 5 | **LF43** | 2026-01-13 | 2026-01-26 | 12.719 | 154 | 1.21% | R$ 157.723 | R$ 81.130 | **1.94x** |

LF47 ficou em 6º (1.75x) — distância do 5º é 0.19x, dentro da zona ruidosa. Em recalibragens futuras pode trocar.

Top 5 estável removendo o sinal de 2025: 4/5 em comum (LF41 → LF47).

---

## Caveats que importam

### 1. Poder preditivo do perfil de público é fraco

Backtest (`outputs/analysis/audience_quality_backtest.csv`, n=10 LFs) mostra que prever ROAS a partir do mix de público atinge:

- **Pearson ROAS = 0.30** (~10% da variância explicada)
- **MAPE 43%** (erro alto pra previsão absoluta)
- **Direção (acima/abaixo da baseline) = 60% de acerto** (vs 50% chute)

A baseline Top 5 serve como **sinal de alerta** ("público muito diferente do que costuma converter → investigar"), **não** como receita de sucesso ("público igual → ROAS igual"). 90% da variação de ROAS entre lançamentos vem de fatores fora do perfil (criativo, oferta, época, concorrência).

### 2. Causalidade reversa

Top 5 = lançamentos que deram mais dinheiro. Pode ser que o público foi melhor, OU que oferta/criativo/época estavam melhores. Replicar o público dos Top 5 num lançamento futuro **não garante** o mesmo ROAS — outros fatores podem ter sido determinantes.

### 3. Fronteira fuzzy

Distância entre 5º (LF43, 1.94x) e 6º (LF47, 1.75x) = 0.19x. Está dentro do ruído de medição. Em recalibragens futuras, a fronteira pode mexer.

### 4. Tempo

Top 5 atual cobre captações de dez/2025 a fev/2026. Produto, oferta, ambiente competitivo mudam ao longo do tempo. **Recalibrar a cada 3-4 lançamentos novos.** Quando LF55+ acumular dados completos, LF40/41 saem naturalmente da janela.

### 5. Matching imperfeito

Só 29% das vendas brutas (3.488 / 12.035) deram match com leads via email/telefone. O resto é:
- Vendas de leads pré-LF40 (sem arquivo histórico)
- Compradores que não preencheram pesquisa (afiliados, indicação direta)
- Email/telefone errados em algum lado

A não-cobertura é **uniforme entre LFs** (não viesa o ranking), mas baixa o número absoluto de receita atribuível.

### 6. Janela escolhida (60d)

60d é arbitrário, mas estável: 30/45/60d dão Top 5 idêntico. Lançamentos com ciclo de venda mais longo são sub-estimados; mais curtos, super-estimados.

---

## Como reproduzir

```bash
cd V2/
python -m scripts.compute_top5_roas_attributable                    # default 60d
python -m scripts.compute_top5_roas_attributable --window-days 30
python -m scripts.compute_top5_roas_attributable --window-days 45
```

Cada chamada gera `outputs/analysis/roas_attributable_{N}d.csv` com a tabela completa de todos os LFs ordenados por ROAS desc.

Pra regerar o `configs/reference_audience_profiles/devclub.json` com o Top 5 novo:

```bash
python -m scripts.build_reference_audience_profile \
  --launches LF45,LF44,LF46,LF41,LF43 \
  --label "Top 5 ROAS atribuível 60d"
```

---

## Cronograma de recalibragem

- **Próxima:** após 3 lançamentos novos com dados completos (esperado: LF55, LF56, LF57)
- **Quem dispara:** rodar `compute_top5_roas_attributable.py`, comparar com Top 5 atual
- **Quando mudar:** se a nova lista substituir 2+ LFs do Top 5 atual, regerar o `devclub.json` e a `audience_direction_map.json`

---

## Histórico

| Data | Top 5 | Motivo |
|---|---|---|
| 2026-05-14 | LF45, LF44, LF46, LF41, LF43 | Primeira definição canônica do projeto. Resolveu discordância entre 3 fontes anteriores (`devclub.json`, `audience_quality_report.py`, `roas_realized.csv`). |
