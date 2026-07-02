# Decisão de arquitetura — gasto por modelo (`meta_insights`) para ROAS no relatório

> Registro da decisão tomada com `/sw-architect` + `/data-architect` (01/07/2026),
> na frente do **relatório de performance de modelo** (`V2/src/validation/model_performance.py`).
> Contexto do por quê ROAS ficou fora da v1: `V2/docs/AB_TEST.md` (ROAS é o veredito
> final, medido no Ads Manager por variante) e a consolidação: `V2/docs/CONSOLIDACAO_CLOUDSQL.md`
> (a tabela `analytics.meta_insights` já existe **vazia**; decisão 25/06 = popular
> retroativamente com script separado).

## O problema
O relatório já tem **receita por modelo** (soma de `sale_value` das vendas casadas,
de graça, sem Meta API). Falta o **gasto por modelo** pra compor ROAS = receita ÷ gasto.
O gasto não está no banco — a `meta_insights` está criada e vazia.

## A pergunta que decidiu tudo
Como o gasto (que é por **campanha**) vira gasto por **modelo** (Champion `jan_30` /
Challenger `abr_28`)?

**Resposta (confirmada em `src/core/ab_arm.py`):** o braço de uma campanha é decidido
pelos **marcadores no NOME da campanha** — `leadhqlb`/`hqlb`/`ml_mar` → Challenger;
`leadqualified`/`ml` → Champion; `score`/`faixa`/lead-puro → Controle. O `ab_arm.py`
já é a régua única disso. Então o gasto por campanha mapeia pro braço reusando essa régua.

## Decisões

### 1. Granularidade da linha: **campanha × dia basta**
O marcador do braço vive no `campaign_name`, que a DDL já guarda. Não precisa
`adset`/`optimization_goal`. Guardar o **nome cru**; **NÃO** gravar o braço derivado
na tabela (duplicaria o mapeamento e deixaria divergir) — o braço é derivado na
leitura, via `ab_arm`.

### 2. Atribuição gasto→modelo: **reusar `ab_arm.py`**, não criar classificador
Mesma régua que classifica lead → coerência por construção. Três baldes:
Champion / Challenger / **Controle** (lead puro). Gasto de Controle **não entra** no
ROAS dos dois modelos — vira linha própria, explícita (nunca dropar calado).

**⚠ Risco a provar antes de publicar ROAS:** a receita hoje agrupa por
`registros_ml.variant` (verdade de produção do scoring); o gasto agruparia por
marcador-de-nome. Eixos correlatos, não idênticos. **Passo 1 obrigatório = auditar no
ledger o cruzamento `variant` × marcador da campanha.** Se baterem, ROAS por modelo é
limpo; se divergirem em X%, o ROAS carrega esse ruído.

### 3. Idempotência: **UPSERT que SOBRESCREVE** (≠ do `sales_store`)
Uma venda é imutável (`sales_store` faz `ON CONFLICT DO NOTHING`); um dia de gasto
**não é final** — a Meta reescreve gasto/leads de um dia por ~28 dias (janela de
atribuição). Então o store do `meta_insights` faz `ON CONFLICT DO UPDATE` na chave
`(client_id, account_id, campaign_id, insight_date)`, atualizando `spend`/`leads`/`cpl`
+ `ingested_at`. E o ETL **re-puxa sempre os últimos ~28 dias**, não só dias novos.

### 4. Curado vs bruto: a tabela guarda o **BRUTO** da Meta, rotulado
A `meta_insights` É "gasto Meta API" (bruto). Não temos a lógica do filtro curado do
cliente; reproduzir seria um segundo palpite que diverge. O "Gasto Total" curado é
por-LF (grão agregado, outro nível) e continua no caminho do Top5/xlsx — **não misturar
grãos nem conceitos**. Consequência: o ROAS do relatório (gasto bruto) fica ~6,3%
diferente do ROAS curado do Top5 → **rotular "ROAS (gasto Meta bruto)"**. O `cpl`/`leads`
da tabela são contagem interna da Meta; o ROAS mistura NOSSA receita casada ÷ gasto Meta.

### 5. Onde o código encaixa
- `src/validation/meta_insights_store.py` — espelho do `sales_store`, mas **upsert-overwrite**. Grava.
- `src/validation/etl_meta_insights.py` — espelho do `etl_sales`: puxa Meta Insights
  (`level=campaign`, `time_increment=1`, paginado por período), CLI, backfill retroativo.
  **Teto de janela** (desde o início do A/B, não "10 anos") + rate-limit/retry.
- `src/data/meta_reader.py` — lê no shape canônico (gasto por campanha×dia); o relatório
  **injeta** esse reader e agrupa por balde do `ab_arm`. Composição única = o job decide o reader.
- Proveniência `source='meta_api'`; rollback = `DELETE FROM meta_insights WHERE ...`
  + relatório volta a não mostrar ROAS. Minutos.

### 6. Cobertura obrigatória antes de "pronto"
Dry-run com auditoria: cada campanha/conta contabilizada, cobertura temporal
**contínua** (sem dia-buraco) da janela do A/B até hoje, e o total somado batendo com
o Ads Manager (prova de que nenhuma campanha ficou de fora).

## Ordem de execução recomendada
1. **Auditar o eixo** `variant × marcador` no ledger — barato; decide se ROAS por modelo é limpo.
2. Se limpo: construir store(upsert-overwrite) + etl(backfill + re-pull 28d) + reader, gasto bruto rotulado.
3. Relatório junta via `ab_arm`, ROAS rotulado "bruto", Controle explícito.
4. Rollback = `DELETE` por `source` + esconder ROAS.

## O que a v1 do relatório já entrega sem isso
Receita por modelo (coluna `receita R$`), sem Meta API. ROAS entra quando o gasto
estiver no banco pelo caminho acima.
