# Teste A/B Champion/Challenger — Documentação Operacional

**Atualizado:** 2026-04-20
**Status atual:** ativo — aguardando próximo lançamento (DEV20) para coleta de dados válidos

---

## O que é e por que existe

O teste A/B permite validar um novo modelo ML em produção antes de promovê-lo.
A métrica final é **ROAS no Meta Ads Manager** — não AUC. Um modelo com AUC maior pode ser pior economicamente se rankear leads de forma diferente dos compradores reais.

**Princípio**: cada variante usa seu próprio modelo e envia um **evento CAPI com nome diferente**. O Meta atribui compras a cada evento separadamente — ROAS por variante fica visível direto no Ads Manager.

---

## Arquitetura

```
Lead preenche formulário
        ↓
API /predict/single ou /predict/batch
        ↓
pipeline.get_ab_variant(lead_utms)  ← lê utm_campaign, utm_content, etc.
        ↓
    Match UTM?
   /          \
 Sim          Não
  ↓            ↓
Variante    Champion (fallback — serve TODO tráfego sem UTM explícito)
específica
        ↓
Modelo da variante processa o lead
        ↓
Evento CAPI enviado com o nome da variante
        ↓
Meta atribui compras ao evento → ROAS por variante visível no Ads Manager
```

**Roteamento por UTM**: OR logic — basta 1 campo UTM casar (case-insensitive, substring).
Leads sem match vão ao Champion por fallback. Não há tráfego "fora do teste".

---

## Teste atual — DevClub (31/03/2026 →)

| | Champion | Challenger |
|---|---|---|
| **Nome interno** | guru_jan30 | guru_mar24 |
| **MLflow run** | `d51757f5` | `a859c68b` |
| **Treinado em** | 30/01/2026 | 24/03/2026 |
| **UTM pattern** | *(fallback — qualquer UTM sem ML_MAR)* | `utm_campaign LIKE '%ML_MAR%'` |
| **Evento CAPI principal** | `LeadQualified` | `LeadQualifiedCha` |
| **Evento CAPI alta qualidade** | `LeadQualifiedHighQuality` | `LeadQualifiedChaHighQuality` |
| **Envia LQ para** | D07–D10 (com valor) | D07–D10 (com valor) |
| **Envia LQHQ para** | D09–D10 | D09–D10 |

### Volume observado (31/03 → 06/04/2026)

| Fonte | Champion | Challenger |
|---|---|---|
| Railway (responderam pesquisa) | 11.179 | 1.264 |
| Meta (total captados — form fill) | ~12.654 eventos | ~1.628 eventos |

O Challenger rodou com ~10% do volume do Champion neste período.

> **Nota Meta**: Meta conta eventos, não leads únicos. Um lead D9/D10 gera 2 eventos
> (LQ + LQHQ). O total de eventos Meta é maior que o total de leads Railway.

---

## Configuração

Arquivo: `configs/active_models/devclub.yaml`, bloco `ab_test`.

```yaml
ab_test:
  enabled: true          # false = A/B desativado, usa só o active_model
  variants:
    guru_jan30:           # nome interno da variante (livre)
      run_id: <mlflow_run_id>
      utm_pattern:        # OR logic — basta 1 campo casar
        utm_campaign: "ML_JAN"
        utm_content: "ML_JAN"
      capi_event_name: LeadQualified
      capi_event_name_high_quality: LeadQualifiedHighQuality
      conversion_rates:
        D01: 0.0
        ...
        D07: 0.0081
        D10: 0.0175
      encoding_overrides:   # opcional — só necessário se o modelo usou encoding diferente
        ordinal_variables:
          "Qual a sua idade?": [...]
    guru_mar24:
      run_id: <mlflow_run_id>
      utm_pattern:
        utm_campaign: "ML_MAR"
      capi_event_name: LeadQualifiedCha
      capi_event_name_high_quality: LeadQualifiedChaHighQuality
      conversion_rates: { ... }
```

**Para ativar**: `enabled: true` + alinhar `utm_pattern` com o gestor de tráfego.
**Para desativar**: `enabled: false` — a API volta a usar o `active_model` sem roteamento.

### Pré-condição Meta (antes de ativar challenger novo)

Os event names precisam existir no Meta Events Manager **antes** de serem usados como objetivo de otimização nas campanhas. Criar via API ou interface do Ads Manager.

---

## Como ler os resultados

### No Meta Ads Manager

Comparar ROAS diretamente entre as campanhas do Champion e do Challenger:
- Campanhas Champion otimizam para `LeadQualified` / `LeadQualifiedHighQuality`
- Campanhas Challenger otimizam para `LeadQualifiedCha` / `LeadQualifiedChaHighQuality`

O Meta atribui compras a cada evento separadamente → ROAS por variante é nativo.

### No Railway

```sql
-- Leads com pesquisa respondida, por variante (período a definir)
SELECT
    CASE WHEN campaign LIKE '%ML_MAR%' THEN 'Challenger' ELSE 'Champion' END AS variante,
    decil,
    COUNT(*) AS leads
FROM "Lead"
WHERE "createdAt" >= '2026-XX-XX' AND "createdAt" < '2026-XX-XX'
GROUP BY 1, 2 ORDER BY 1, 2;
```

### Script de diagnóstico

```bash
cd V2/
python scripts/test_encoding_overrides.py --limit 200
python scripts/dt12_impact_analysis.py --limit 500
```

---

## Critério de promoção

> **Promover Challenger quando:** ROAS Challenger ≥ ROAS Champion após **1 lançamento completo** com janela de conversão fechada (≥ 27 dias após o fim do carrinho).

AUC retrospectivo como critério secundário de sanidade — se ROAS equivalente mas AUC do Challenger for significativamente menor, investigar antes de promover.

> **Nota 28/04/2026:** enquanto o A/B online estiver suspenso, o critério de promoção foi substituído pelo **backtest offline pré-promoção** descrito mais abaixo. ROAS por variante via Meta Ads Manager não é mais coletável porque ambos modelos disparam o mesmo event name.

### Como promover

1. Retreinar o Champion com o `run_id` do Challenger:
   ```bash
   python -m src.train_pipeline --activate-run <run_id_challenger>
   ```
2. Atualizar `configs/active_models/devclub.yaml`:
   - Mover o `run_id` do Challenger para `active_model`
   - Atualizar o `run_id` do Champion no bloco `ab_test` para o novo modelo
   - Criar próximo Challenger para o ciclo seguinte
3. Atualizar `conversion_rates` do novo Champion com as taxas observadas no teste.
4. Avisar o gestor de tráfego para criar campanhas do novo Challenger com novo UTM.

---

## Backtest offline pré-promoção (28/04/2026 →)

> **Substitui o critério online enquanto o A/B test está suspenso.** Candidato Champion deve mostrar discriminação ≥ Champion atual em backtest sobre lançamentos OOS antes de virar canary em produção.

### Contexto

A/B online via UTM foi suspenso em 27/04/2026 (canary Cloud Run substituiu o mecanismo de roteamento). Como ambos modelos passam a disparar o mesmo event name (`LeadQualified` / `LeadQualifiedHighQuality`), Meta Ads Manager não diferencia ROAS por variante.

Necessário método offline pra avaliar candidatos antes da promoção. Primeira aplicação: **v4** (`60637bb98b94421b9c7579bb4ac1b1ad`, treinado 23/04/2026) **vs jan30** (`d51757f5041c44b7ab1a056fce8c3c35`, Champion atual em produção).

### Metodologia

**Lançamentos elegíveis (OOS para v4, cutoff treino 02/04/2026):**
- LF52 (cap 07-12/04, vendas 17-24/04) — carrinho fechado
- LF53 (cap 13-20/04, vendas 27/04-03/05) — carrinho aberto, D2 quando feito
- LF51 parcial (cap 03-06/04, vendas 13-19/04) — só leads pós-cutoff via override de `cap_start`

**Filtros aplicados:**
- Excluir leads com UTM `ML_MAR` (durante A/B ativo, esses leads foram scoreados por mar24, não pelo Champion da época)
- Janela de conversão: matching de leads ↔ vendas dentro do período de captação + vendas (sem temporal validation; carrinho curto e fechado)

**Fontes de venda combinadas:**
- Guru API (cartão à vista)
- Hotmart API (cartão parcelado)
- Asaas API (boleto à vista) — adicionada em 28/04 ao detectar que vendas boleto não vinham do TMB
- TMB local (`contas_a_receber_*.xlsx`) — apenas vendas Crédito Acessível parcelado

**Score:**
- v4: rescore via `LeadScoringPredictor(mlflow_run_id=...)` aplicado ao base_dataset
- jan30: lido direto da tabela `Lead` do Railway via coluna `decil` (decisão atribuída em runtime pela produção). Evita problema de pipeline mismatch (jan30 foi scorado em produção pelo código do momento, não pelo pipeline atual)

**Métrica principal:** % de conversão D9 e D10 acima da média do lançamento (lift).

### Resultado primário — Pooled OOS (cap 03/04→27/04, vendas 13/04→28/04)

> **Métrica primária da decisão de promoção.** Pool único de leads OOS para v4 (todos capturados após cutoff de treino 02/04/2026), matched contra todas as vendas disponíveis no período. Evita distorções de janela apertada por LF específico.

**Setup:** 32.179 leads únicos (sem ML_MAR), 173 conversões matched, baseline 0,54%.

| Métrica | v4 | jan30 |
|---|---|---|
| conv% D9 | 0,78% | 0,63% |
| **conv% D10** | **0,92%** | 0,75% |
| **D9 acima média** | **+44%** | +18% |
| **D10 acima média** | **+71%** | +40% |
| **D9+D10 acima média** | **+59%** | +33% |
| ROAS top-30 | 2,11 | 1,84 |
| ROAS top-50 | 1,94 | 1,74 |
| ROAS global | 1,48 | 1,48 |

**v4 separa ~2× melhor que jan30 em D9 e D10.** Resultado robusto a 173 conversões.

### Recorte secundário — por lançamento (mostra robustez do pooled)

| LF | Modelo | n_conv | baseline | conv% D9 | conv% D10 | D10 acima |
|---|---|---|---|---|---|---|
| LF51 parcial | v4 | 40 | 0,68% | 0,76% | 1,29% | +89% |
| LF51 parcial | jan30 | 40 | 0,68% | 0,65% | 0,89% | +30% |
| LF52 | v4 | 57 | 0,68% | 1,26% | 1,45% | +112% |
| LF52 | jan30 | 57 | 0,68% | 1,08% | 0,93% | +36% |
| LF53 D2 carrinho | v4 | 52 | 0,52% | 0,81% | 0,56% | **+8%** ⚠ |
| LF53 D2 carrinho | jan30 | 52 | 0,52% | 0,66% | 0,76% | +44% |

O "v4 quebra no LF53" desaparece no pooled. Razão: leads capturados no LF53 (cap 13-20/04) ainda não tiveram tempo de comprar — carrinho abriu 27/04. No recorte por-LF, o numerador dos decis altos do v4 fica artificialmente baixo. No pooled, esses leads são contabilizados quando comprarem em qualquer carrinho posterior.

### Conclusão (28/04/2026)

- **v4 é candidato legítimo a promoção** — discrimina ~2× melhor que jan30 no pooled OOS com 173 conversões
- Recorte por-LF tem variabilidade que **não reflete falha estrutural** — é artefato de janela curta no LF53
- Recomendação: refazer pooled OOS após carrinho LF53 fechar (03/05) pra confirmar resultado com volume final, então decidir promoção

**Pré-requisitos antes de canary v4 em produção:**
1. Pooled OOS pós-LF53 fechado mantém v4 ≥ jan30 nas 3 métricas (D9, D10, D9+D10)
2. TMB atualizado (lag de ~5 dias resolvido até lá)
3. Smoke test paridade jan30 ainda passa

### Reprodutibilidade

- Script: `V2/scripts/backtest_compare_models.py` (3 modos: `prepare-dataset`, `score`, `compare`)
- Módulo de carga: `V2/src/validation/backtest_data.py` (`load_match_spend_for_lf`)
- Datasets persistidos em: `V2/files/validation/backtest_lf{51_partial,52,53}/`
- Comandos exatos no docstring do script
- Arquivos TMB local em `V2/data/devclub/contas_a_receber_*.xlsx` (gerados manualmente)

### Próximas iterações

- 04/05: refazer LF53 com carrinho fechado
- Se LF53 fechado mantiver v4 ≥ jan30 nas 3 métricas (D9, D10, D9+D10): considerar canary v4
- Se não: documentar viés Asaas e planejar retreino v5 com mix corrigido

---

## Auditoria de paridade — pipeline online vs offline (28/04/2026)

> **Contexto:** antes de decidir arquitetura de roteamento UTM pro canary v4, foi necessário confirmar se o pipeline `main` produzia output idêntico ao pipeline `rollback edf23e9` quando servindo o mesmo modelo (jan30). A preocupação era "rodar modelo antigo com código novo" introduzindo viés silencioso.

### Setup

- Sample: 5.000 leads OOS (cap 03/04 → 27/04, sem ML_MAR), estratificado por dia de captação
- Mesmo modelo: jan30 (`d51757f5...`)
- Worktree do rollback recriado em `../smart_ads_v2_rollback` apontando pro commit `edf23e9`
- Bateria de 9 camadas: paridade element-wise, estatística, decil, boundary D9/D10, edge cases, cross-val produção, estabilidade temporal, reprodutibilidade, robustez do mecanismo de override

### Achado #1 — Encoding override é decisivo

Sem aplicar `encoding_overrides` para jan30 ao chamar `pipeline.run()`, **96% dos leads** divergem (paridade falha catastroficamente: a feature ordinal `Qual_a_sua_idade` fica em 0 pra todos os 500 leads de teste).

Com encoding_overrides aplicado corretamente: **98,4% match exato (<0,001)** e **99,6% match de decil**.

Em produção, `app.py` linhas 902-918 já extrai o override correto via `ab_variant.encoding_overrides` quando `ab_test.enabled: true`. Pra teste offline foi necessário reconstruir o EncodingConfig manualmente (config foi removido do active_models/devclub.yaml quando A/B foi suspenso em 27/04).

### Achado #2 — Paridade main vs rollback (com override)

Bateria com 5.000 leads (com override aplicado):

| Camada | Resultado | Critério rigoroso | Passa? |
|---|---|---|---|
| Element-wise (abs_diff) | 96% <0,001; máx 0,17 | 99,9% <0,001 | ❌ |
| Estatística (Spearman) | ρ = 0,9986 | >0,999 | ❌ |
| Decil operacional | 98,3% mesmo decil | ≥99,5% | ❌ |
| **Boundary D9/D10 (LQHQ)** | **0,17% divergem** | <0,5% | ✅ |
| Cross-val produção | 89,9% main+ovr | ≥99% | ❌ |
| Estabilidade temporal | pior dia 96,2% | ≥99% | ❌ |

**Sob critério "exaustivo e implacável", paridade não foi comprovada.** Mas a magnitude operacional é pequena: ~2% dos leads jan30 servidos por main code receberiam decil deslocado em ±1 (raramente ±2), e apenas 0,17% mudariam de decisão LQ vs LQHQ.

### Achado #3 — Divergência INTRÍNSECA pipeline online vs offline (~6%)

Investigação revelou que mesmo o **rollback rescorando offline** não bate 100% com `decil_production` gravado no Railway (que foi atribuído pelo rollback rodando online em produção).

Estratificado por janela de captação:

| Janela | n | rollback rescore ↔ prod online | main+ovr ↔ prod online |
|---|---|---|---|
| Pré-rollback (cap < 13/04) | 2.073 | 85,0% | 85,0% |
| **Puro rollback (cap 13-22/04)** | 2.036 | **94,2%** | 93,7% |
| Canary v4 ativo (cap 23-27/04) | 992 | 93,1% | 92,5% |

**Mesmo pipeline (rollback), mesmo modelo (jan30), mesmo lead — rescore offline ≠ scoring online em ~6% dos casos.** Distribuição da `score_diff` em puro rollback:

- Mediana: zero (5,5e-17 = float precision noise)
- p25: 0 | p75: 0,003
- Máximo: 0,41 (cauda)

Padrão: 70% dos leads tem rescore IDÊNTICO ao online; 30% tem diff variável, sendo a maioria <0,003. **Algo no fluxo runtime de produção (webhook → app.py → score) não é replicado quando rescore-se offline em batch.**

Hipóteses ainda não testadas (issue aberta):

1. **Cache de cliente desatualizado** — algum lookup em runtime que escreve estado distinto
2. **FBP/FBC ou enriquecimento** — produção pode buscar dados que rescore offline não tem
3. **Reprocessing de leads** — alguns podem ter sido scoreados, sale_date corrigida, e re-scoreados
4. **Timestamp `Data` vs `createdAt`** — Data armazenada vs momento real de scoring online
5. **Race condition / state online** — múltiplas requests competindo

**Esta divergência intrínseca não é causada pelo main code** — é uma propriedade do fluxo online vs offline. Promover main+ovr adiciona ~0,5pp adicional sobre essa base de 6%.

### Achado #4 — Não é causa principal da degradação treino → produção

A queda de lift D10 de 3,58 (treino) → 1,71 (produção real) **não é dominantemente explicada** por essa divergência rescore↔online:

- Mediana zero significa que pra maioria dos leads o score é idêntico
- A cauda da diff (máx 0,41) afeta poucos leads; impacto agregado no lift seria pequeno
- A causa principal continua sendo **otimização Meta comprimindo distribuição** (corroborado por LFs históricos com mesmo padrão de degradação)

### Decisão arquitetural — 28/04/2026

Sob as restrições operacionais ditas pelo cliente:

- Não usar single revisão main + UTM (preocupação inicial sobre paridade)
- Não usar cross-revision RPC (complexidade)
- Não exigir mudança no front-end
- Latência tolerável desde que sem custo significativo

E à luz dos achados:

- Paridade main+ovr ≡ rollback é **praticamente equivalente** dentro da margem intrínseca de ~6% que existe em qualquer comparação rescore↔online
- Promover main+ovr introduz apenas ~0,5pp adicional de divergência sobre o baseline rollback rescore vs prod
- Shift de ~2% no decil é aceitável pelo cliente (decisão registrada)

**Decisão:** Arquitetura 1 (single revisão main com UTM routing) volta como caminho viável pra promoção do v4. Substitui a recomendação inicial de "Arquitetura 5 (proxy)".

**Pré-requisitos pra promoção:**
1. Reativar `ab_test.enabled: true` em `active_models/devclub.yaml`
2. Reconstruir variants com `encoding_overrides` corretos pra jan30 (preservados em git history em commit `c32e5f0`)
3. Coordenar com gestor: criar evento `LeadQualifiedV4` no Meta Events Manager + campanha com UTM `ML_V4`
4. Canary 10% main → 50% → 100% conforme Fase 3 do `PLANO_EXECUCAO.md`
5. Smoke test em canary: 5 leads jan30 reais, verificar decil distribution similar à atual
6. Investigação aberta: causa raiz da divergência intrínseca rescore↔online (~6%) — separada da decisão atual

### Reprodutibilidade da auditoria

- Worktree de teste: `git worktree add ../smart_ads_v2_rollback edf23e9`
- Sample: `/tmp/parity_5k_sample.xlsx` (5.000 leads do pooled OOS estratificados por dia)
- Scripts ad-hoc usados (não persistidos como módulo) — refazer requer recriar via histórico desta investigação ou via instrumentação de `tests/parity_audit.py`

---

## Problema conhecido — DT-12 (encoding_overrides)

O jan30 (Champion atual) foi treinado com **ordinal encoding** para idade e faixa salarial, mas por um bug silencioso na época do treino recebeu OHE acidental. Em produção, sem o `encoding_overrides`, essas features chegam zeradas ao modelo jan30.

**Status**: corrigido via `encoding_overrides` no `devclub.yaml` — jan30 recebe o encoding ordinal correto em runtime.

**Impacto no teste**: o jan30 estava em desvantagem estrutural antes da correção. Os resultados a partir de 31/03/2026 já têm o fix aplicado.

Ver: `PLANO_REFACTOR_MLOPS.md` seção DT-12 para detalhes completos.

---

## Quando NÃO usar A/B

- Volume do Challenger < 15% do Champion por mais de 2 lançamentos consecutivos: investigar UTM antes de concluir qualquer coisa.
- Janela de conversão ainda aberta (< 27 dias após fim do carrinho): ROAS parcial, não conclusivo.
- Challenger com problema técnico confirmado (encoding, feature drift, etc.): pausar antes de comparar.

---

## Janela de dados válidos para análise

### Período limpo (dados confiáveis)

| Evento | Data/hora (BRT) | O que mudou |
|---|---|---|
| A/B test ativado em produção | 31/03/2026 | Leads ML_MAR passam pelo Challenger |
| encoding_overrides aplicado ao Champion | 01/04/2026 | jan30 recebe ordinal correto para ML_JAN |
| **Rollback deployado** (sem A/B test) | **~13/04/2026 19:33 BRT** | ML_MAR passa a ser roteado para jan30 — eventos CAPI errados |
| Canary promovido a 100% | 14/04/2026 | A/B test restaurado corretamente para todos |

**Janela válida para análise retrospectiva (Challenger):** `01/04/2026 00:00 BRT` → `13/04/2026 19:33 BRT`

- Dados de 03/31 têm volume baixo (32 leads) e o encoding_overrides ainda não estava no Champion — excluir da análise principal.
- Dados de 04/14 são descartados inteiros por segurança — rollback estava ativo durante parte do dia.
- Dados a partir da promoção a 100% (14/04) voltam a ser válidos para análise prospectiva.

> **Query Railway para janela limpa:**
> ```sql
> WHERE "createdAt" >= '2026-04-01 03:00:00'   -- 00:00 BRT = 03:00 UTC
>   AND "createdAt" <  '2026-04-13 22:33:56'   -- momento do rollback (UTC)
> ```

---

## ~~Próximo passo — patch no rollback~~ (CANCELADO 2026-04-21)

> **Status:** CANCELADO. Esta rota (ab-patch na branch `rollback/edf23e9-ab-patch`, commit `c0e09d0`) foi descartada em favor da unificação estratégica da Fase 3 do `PLANO_EXECUCAO.md`.
>
> **Motivo da rejeição:** o patch carregaria adiante a pipeline não refatorada do rollback (sem `src/core/`), criando um caminho paralelo que depois precisaria ser abandonado para destravar multi-cliente (Fase 3b em diante). Unificar `edf23e9` → `main` mantém uma pipeline só, evolutiva.
>
> **Onde ler o que substituiu:** `docs/PLANO_EXECUCAO.md` → Fase 3 "Unificação de branches" (revista em 2026-04-21).
>
> **O que a ab-patch oferecia (para referência):** A/B routing sobre a pipeline do rollback — preservava as features `_valido_*` que Champion precisa. A unificação na main precisa **portar** essas features em vez de reaproveitar a pipeline antiga.

O conteúdo original do plano da ab-patch está preservado abaixo como histórico:

| # | Arquivo | Mudança (NÃO EXECUTAR — rota cancelada) |
|---|---|---|
| 1 | `configs/active_models/devclub.yaml` | CRIAR — bloco `ab_test` com jan30 + mar24 |
| 2 | `configs/active_model.yaml` | MODIFICAR — `mlflow_run_id` explícito |
| 3 | `src/core/client_config.py` | MODIFICAR — dataclasses `ABTestConfig` |
| 4 | `src/production_pipeline.py` | MODIFICAR — `get_ab_variant()` + roteamento UTM |
| 5 | `api/capi_integration.py` | MODIFICAR — `event_name_override` como parâmetro |
| 6 | `api/app.py` | MODIFICAR — roteamento A/B no webhook |
| 7 | `api/Dockerfile` | MODIFICAR — `MODEL_PATH=mlruns_build` |
| 8 | `api/deploy_capi.sh` | MODIFICAR — `stage_model_artifacts()` |

Leads não-ML_MAR → jan30 (Champion, código edf23e9 sem mudança de comportamento).
Leads ML_MAR → mar24 (Challenger, código novo só na lógica de roteamento).

Após deploy: canary (00270-q2m) vai a 0%, nova revisão vai a 100%.

---

## Encoding por variante A/B (decisão arquitetural 2026-04-21)

**Contexto:** Champion jan30 e Challenger mar24 foram treinados com encodings diferentes para idade e salário:
- **Champion (jan30):** ordinal (coluna única `Qual_a_sua_idade` numérica)
- **Challenger (mar24):** OHE (uma coluna por categoria: `Qual_a_sua_idade_18_24_anos` etc.)

**Decisão (Opção A):** o **default** do cliente em `configs/clients/devclub.yaml` é **OHE** para idade e salário. A variante que difere do default declara explicitamente via `encoding_overrides`:

| Variante | encoding_overrides em `active_models/devclub.yaml` | Comportamento efetivo |
|---|---|---|
| `guru_jan30` (Champion) | `ordinal_variables` com `"Qual a sua idade?"` + `"Atualmente, qual a sua faixa salarial?"` | Ordinal (como treinado) |
| `guru_mar24` (Challenger) | Sem `encoding_overrides` | OHE (como treinado) |

**Por que assim:** o default representa "o encoding mais comum nos modelos atuais e futuros". Overrides representam exceções declaradas explicitamente por variante. A alternativa (default ordinal + override OHE em mar24) exigiria que `merge_encoding` suportasse "anular override do base", o que é mais complexo.

**Para cliente B no futuro:** escolher o default que bate com o encoding da maioria dos modelos esperados. Variantes exceções declaram override.

**Arquivo de referência:** `src/core/encoding.py` → função `merge_encoding()`.

---

## Análise estatística — LF51 (captação 30/03–06/04, vendas 13/04–19/04)

| Grupo | Leads | Conversões | Taxa |
|---|---|---|---|
| Champion | 11.463 | 28 | 0,24% |
| Challenger | 3.004 | 5 | 0,17% |

- **Qui-quadrado (χ²):** 0,63 — p = 0,43
- **Fisher's Exact:** p = 0,52 — Odds Ratio = 1,47

**Conclusão:** diferença de +47% na taxa de conversão a favor do Champion, mas sem significância estatística (p > 0,05 em ambos os testes). Para detectar essa diferença com 80% de poder seriam necessários ~57.000 leads por grupo. O volume atual é insuficiente para qualquer decisão baseada em conversões.

---

## Próximo lançamento — DEV20

O prazo original de 27/04/2026 não é mais viável: a janela de conversão do LF51 já fechou sem volume suficiente para decisão, e o próximo lançamento (DEV20) ainda está em captação.

**Calendário do DEV20:**

| Fase | Período |
|---|---|
| Captação de leads | 21/04/2026 → 04/05/2026 |
| Carrinho aberto (vendas) | 11/05/2026 → 17/05/2026 |
| Resultados disponíveis | após 17/05/2026 (carrinho fechado + janela de atribuição) |

**O sistema precisa estar em produção com o A/B test ativo durante toda a captação (21/04–04/05).** Leads captados fora do sistema não entram na comparação.

**Nova data de decisão:** após o fechamento do carrinho em 17/05/2026, quando o ROAS de cada variante estiver consolidado no Meta Ads Manager.

> **Query Railway para análise do DEV20 (usar após 17/05):**
> ```sql
> WHERE "createdAt" >= '2026-04-21 03:00:00'   -- 00:00 BRT = 03:00 UTC
>   AND "createdAt" <  '2026-05-05 03:00:00'   -- fim da captação
> ```

---

## Eventos CAPI `LeadQualifiedCha` / `LeadQualifiedChaHighQuality` — DESCONTINUADOS (13/04/2026)

Os dois eventos específicos do Challenger (`LeadQualifiedCha` e `LeadQualifiedChaHighQuality`) **pararam de ser enviados** desde o rollback executado em **13/04/2026**. Quando o rollback (`edf23e9`) foi deployado a 100%, ele não tem código de A/B routing interno — enviou todos os eventos como `LeadQualified` / `LeadQualifiedHighQuality`, independentemente do UTM do lead.

Essa situação **foi mantida conscientemente a partir de 23/04/2026**, quando o Champion v4 (novo código + novo dataset) foi deployado em 10% com `ab_test.enabled: false` — arquitetura simplificada onde o split de tráfego Cloud Run decide qual modelo scora, sem roteamento por UTM:

| Período | Event name | Motivo |
|---|---|---|
| Antes de 13/04/2026 | `LeadQualifiedCha` / `LeadQualifiedChaHighQuality` para leads ML_MAR; `LeadQualified` / `LeadQualifiedHighQuality` para o resto | A/B test via UTM no código main pre-rollback |
| **13/04/2026 →** | **Apenas `LeadQualified` / `LeadQualifiedHighQuality` para todos os leads** | Rollback sem A/B + decisão de manter simplificado no deploy de 23/04 |

**Implicação no Meta Ads:** campanhas configuradas para otimizar `LeadQualifiedCha` não recebem mais eventos do evento que otimizam desde 13/04. Elas ficaram 10 dias sem sinal quando o rollback estava a 100%, e continuam sem sinal na nova arquitetura. Consequências:

- O Meta pode ter degradado o aprendizado dessas campanhas — cabe ao **gestor de tráfego reconfigurar as campanhas ML_MAR** no Ads Manager para otimizar `LeadQualified` se quiser manter o tráfego segmentado por UTM.
- Ou retirar o UTM ML_MAR das campanhas (já que não serve mais ao A/B por UTM).
- Sem nenhuma ação no Meta, as campanhas com UTM ML_MAR continuam rodando mas sem a otimização CAPI adequada.

**Não há ação técnica pendente do lado do nosso código** — a arquitetura funciona, a escolha de modelo é feita pelo Cloud Run, os eventos CAPI chegam no Meta corretamente (com nomes default). A ação é puramente operacional, no Ads Manager.

Para análises retrospectivas: qualquer comparação Champion × Challenger via eventos CAPI no Meta deve usar a janela **31/03–13/04/2026** como único período em que os eventos `Cha` foram enviados. Depois de 13/04, não há diferenciação de evento por variante.

---

## Estratégia de deploy — 50/50 em vez de 100% (decisão 21/04/2026)

A revisão com o A/B test ativo (branch `main` unificada) será promovida a **50% do tráfego**, não 100%. Os outros 50% permanecem no rollback (`edf23e9`).

**Motivação:** proteger o cliente de exposição total à revisão nova antes da confirmação empírica de paridade. Mesmo com o parity audit passando coluna-a-coluna em `tests/parity_audit.py`, qualquer divergência não detectada pelo audit se manifestaria como queda de ROAS — e com 50/50 pelo menos metade do volume segue com a versão em produção conhecida enquanto a nova é validada em condições reais.

**Impacto no A/B test:**
- Apenas a metade na revisão unificada executa o roteamento Champion/Challenger (ML_MAR → mar24)
- A metade no rollback envia tudo ao Champion jan30 — não tem código do A/B
- Amostra efetiva do A/B cai pela metade — considerar no cálculo de significância estatística do DEV20

**Pré-requisitos antes do 50/50:**
1. Tier 1 dos safeguards concluído (`docs/PLANO_SAFEGUARD.md`)
2. `python V2/tests/parity_audit.py` passa coluna-a-coluna contra os snapshots regenerados
3. Smoke test pós-deploy: 5 leads → score + decil + CAPI log OK

**Critério para subir para 100%:**
- Nenhum alerta HIGH no monitoramento por 3 dias consecutivos após 50/50
- ROAS por variante coletado no DEV20 permite comparação estatística confiável
- Nenhuma regressão operacional (decis com 0 eventos, capiStatus blocked/null > 10%, etc.)

**Comando de deploy:**
```bash
gcloud run services update-traffic smart-ads-api --region us-central1 \
    --to-revisions <revision-main-unificada>=50,smart-ads-api-00269-jjn=50
```
