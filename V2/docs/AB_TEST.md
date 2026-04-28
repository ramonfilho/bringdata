# Teste A/B Champion/Challenger — Documentação Operacional

**Atualizado:** 2026-04-27
**Status atual:** ⏸ **SUSPENSO desde 27/04/2026**

> **Pré-requisito para retomar:** validação out-of-sample do Champion v4 (`60637bb98b94421b9c7579bb4ac1b1ad`, retreinado 23/04 com dados até 02/04) nos últimos lançamentos que ele nunca viu — teste válido para confirmar se a performance prevista se materializa em dados reais. Enquanto não houver essa leitura, **não se executa A/B test** (sem patch no rollback, sem deploy de Challenger, sem promoção, sem novo ciclo). Lançamentos elegíveis: pós-02/04/2026 (LF51 final + DEV20 quando coletado). Decisão de retomada depende dos resultados dessa validação.
>
> O conteúdo deste documento permanece como referência operacional do design A/B — quando o teste for retomado, esta é a arquitetura a executar.

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

## ~~Estratégia de deploy — 50/50 em vez de 100%~~ (SUBSTITUÍDA — 2026-04-27)

> **Status:** SUBSTITUÍDA por **canary direto** (10% → 50% → 100%) com critério puramente técnico. Decisão de 27/04/2026 — o A/B test está suspenso (ver topo do documento), então o gancho "ROAS por variante consolidado no DEV20" deixa de existir como gatilho de promoção, e o 50/50 perde o objetivo de coletar amostra A/B em paralelo. O conteúdo original abaixo permanece como referência histórica da decisão de 21/04.
>
> **Pré-requisito adicional (mais alto que qualquer canary):** validação out-of-sample do Champion v4 (`60637bb9…`) nos lançamentos não vistos. Sem essa validação, **nenhuma porcentagem de tráfego** vai para a main — o YAML em main já está configurado para servir v4 (`configs/active_models/devclub.yaml` com `mlflow_run_id: 60637bb9…` e `ab_test.enabled: false` desde 23/04), portanto deployar 10% antes da validação significa servir v4 não validado a 10% dos leads. Não fazer.

### Nova estratégia — canary direto (a executar quando a validação OOS for favorável)

| Estágio | Tráfego main | Tráfego rollback | Critério para avançar |
|---|---|---|---|
| 1. Smoke | 0% (--no-traffic) | 100% | 5 leads sintéticos → score + decil + CAPI log OK |
| 2. Canary | 10% | 90% | 24h sem alerta HIGH; paridade observada vs rollback; nenhum decil com 0 eventos |
| 3. Meio | 50% | 50% | 48h sem alerta HIGH; golden snapshot estável; ROAS observacional não regride |
| 4. Final | 100% | 0% | (ou rollback rápido se algum critério falhar) |

**Comando de canary inicial (quando autorizado):**
```bash
gcloud run services update-traffic smart-ads-api --region us-central1 \
    --to-revisions <revision-main-unificada>=10,smart-ads-api-00269-jjn=90
```

---

### ~~Conteúdo original (21/04/2026) — 50/50 com gancho A/B~~

A revisão com o A/B test ativo (branch `main` unificada) seria promovida a **50% do tráfego**, não 100%. Os outros 50% permaneceriam no rollback (`edf23e9`).

**Motivação:** proteger o cliente de exposição total à revisão nova antes da confirmação empírica de paridade. Mesmo com o parity audit passando coluna-a-coluna em `tests/parity_audit.py`, qualquer divergência não detectada pelo audit se manifestaria como queda de ROAS — e com 50/50 pelo menos metade do volume seguiria com a versão em produção conhecida enquanto a nova era validada em condições reais.

**Impacto no A/B test (cancelado pela suspensão de 27/04):**
- Apenas a metade na revisão unificada executaria o roteamento Champion/Challenger (ML_MAR → mar24)
- A metade no rollback enviaria tudo ao Champion jan30 — não tem código do A/B
- Amostra efetiva do A/B cairia pela metade — consideração obsoleta com A/B suspenso

**Pré-requisitos antes do 50/50:**
1. Tier 1 dos safeguards concluído (`docs/PLANO_SAFEGUARD.md`) — ✅ 11/11 em 23/04
2. `python V2/tests/parity_audit.py` passa coluna-a-coluna contra os snapshots regenerados
3. Smoke test pós-deploy: 5 leads → score + decil + CAPI log OK

**Critério (original) para subir para 100%:**
- Nenhum alerta HIGH no monitoramento por 3 dias consecutivos após 50/50
- ROAS por variante coletado no DEV20 permite comparação estatística confiável ← obsoleto
- Nenhuma regressão operacional (decis com 0 eventos, capiStatus blocked/null > 10%, etc.)

**Comando de deploy:**
```bash
gcloud run services update-traffic smart-ads-api --region us-central1 \
    --to-revisions <revision-main-unificada>=50,smart-ads-api-00269-jjn=50
```
