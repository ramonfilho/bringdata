# Plano de Execução — Smart Ads V2

**Atualizado:** 2026-04-20  
**Horizonte:** Abril → Junho 2026

Documento mestre de execução. Une os três trabalhos em andamento em uma sequência única com dependências explícitas.

Documentos de referência:
- `docs/AB_TEST.md` — arquitetura, janela válida e análise estatística do teste A/B
- `docs/PLANO_SAFEGUARD.md` — audit completo de infraestrutura, gap matrix e itens de implementação
- `docs/PLANO_REFACTOR_MLOPS.md` — refactor para multi-cliente (Option B, Shared Core Layer)
- `docs/Erros_cometidos.md` — erros históricos que motivam os safeguards

---

## Estado atual (16/04/2026)

| Componente | Estado |
|---|---|
| **Código em produção** | edf23e9 (05/03/2026) — rollback `00269-jjn`, sem A/B test |
| **Canary ativo** | `00270-q2m` com 10% de tráfego — main com A/B test, encoding_overrides correto |
| **Modelo Champion** | jan30 (`d51757f5`) — treinado 30/01/2026, dados até 04/11/2025 |
| **Modelo Challenger** | mar24 (`a859c68b`) — treinado 24/03/2026 |
| **Janela A/B válida (LF51)** | 01/04 → 13/04/2026 — dados limpos do Challenger disponíveis |
| **Prazo do teste A/B** | ~~27/04/2026~~ → após 17/05/2026 — janela LF51 insuficiente, decisão migrada para DEV20 |
| **Branch main** | Não está em produção — produz resultado diferente de edf23e9 (discrepância a eliminar) |

---

## Três trabalhos e suas dependências

```
TRABALHO A — A/B PATCH          TRABALHO B — SAFEGUARDS           TRABALHO C — UNIFICAÇÃO
(prazo 27/04)                   (ver PLANO_SAFEGUARD.md)          (edf23e9 → main)
      │                                    │                               │
      │                          ┌─────────┴──────────┐                   │
      │                     Tier 1 (7 itens)     Tier 2+3 (12 itens)      │
      │                     antes da unificação   após unificação          │
      │                          │                    │                    │
      └──────────────────────────┼────────────────────┼────────────────────┘
                                 │                    │
                         UNIFICAÇÃO SEGURA      SISTEMA COMPLETO
```

**Regra de dependência:**
- A não depende de B nem C — pode rodar agora, em paralelo
- C depende de B (Tier 1) — não unificar branches sem os checks de paridade prontos
- B (Tier 2+3) pode acontecer após C — constrói sobre código unificado

---

## Fase 1 — A/B patch + resultado do teste
**Prazo:** sistema em produção antes de 21/04/2026 (início da captação DEV20) | decisão após 17/05/2026 (fim do carrinho)

### Objetivo
Garantir que ML_MAR recebe 100% do Challenger com código e modelo corretos durante toda a captação do DEV20, e coletar dados suficientes para a decisão de promoção.

**Calendário DEV20:**
- Captação: 21/04 → 04/05/2026
- Carrinho aberto: 11/05 → 17/05/2026
- Resultados disponíveis para decisão: após 17/05/2026

> **Contexto:** o prazo original de 27/04 foi baseado na janela de conversão do LF51, que fechou sem volume estatisticamente suficiente (Champion 0,24% vs Challenger 0,17%, p=0,52). A decisão migra para o DEV20.

### Trabalho

**1.1 — Patch no rollback worktree**

O rollback (`smart_ads_v2_rollback/`, edf23e9) precisa receber A/B routing mínimo. 8 arquivos identificados:

| # | Arquivo | Ação |
|---|---|---|
| 1 | `configs/active_models/devclub.yaml` | Criar — bloco `ab_test` com jan30 + mar24 |
| 2 | `configs/active_model.yaml` | Modificar — `mlflow_run_id` explícito |
| 3 | `src/core/client_config.py` | Modificar — dataclasses `ABTestConfig` |
| 4 | `src/production_pipeline.py` | Modificar — `get_ab_variant()` + roteamento UTM |
| 5 | `api/capi_integration.py` | Modificar — `event_name_override` como parâmetro |
| 6 | `api/app.py` | Modificar — roteamento A/B no webhook |
| 7 | `api/Dockerfile` | Modificar — `MODEL_PATH=mlruns_build` |
| 8 | `api/deploy_capi.sh` | Modificar — `stage_model_artifacts()` |

**1.2 — Deploy da nova revisão**
- Build + push da imagem a partir do rollback patcheado
- Deploy com `--no-traffic`
- Smoke test: 5 leads ML_MAR → verificar `LeadQualifiedCha` nos logs
- Promover para 100% | Canary `00270-q2m` → 0%

**1.3 — Monitoramento durante DEV20 (21/04–04/05)**

Acompanhar via Meta Ads Manager durante toda a captação:
- Campanhas ML_MAR HLQC: `LeadQualifiedChaHighQuality` recebendo eventos?
- Volume de `LeadQualifiedCha` crescendo proporcionalmente ao gasto?

Query de sanidade no Railway durante a captação:
```sql
SELECT
    CASE WHEN campaign ILIKE '%ML_MAR%' THEN 'Challenger' ELSE 'Champion' END AS variante,
    COUNT(*) AS leads,
    ROUND(AVG(decil::numeric), 2) AS decil_medio,
    ROUND(AVG("leadScore")::numeric, 4) AS score_medio
FROM "Lead"
WHERE "createdAt" >= '2026-04-21 03:00:00'  -- início captação DEV20 (00:00 BRT)
  AND decil IS NOT NULL
GROUP BY 1;
```

**1.4 — Decisão de promoção (após 17/05)**

Ver critério em `docs/AB_TEST.md` — seção "Critério de promoção":
- ROAS Challenger ≥ ROAS Champion → promover mar24 como Champion
- ROAS inferior com p > 0.05 → manter jan30, investigar retreino com dados novos
- ROAS inferior com p < 0.05 → jan30 permanece Champion, mar24 descartado

---

## Fase 2 — Safeguards Tier 1 (pré-requisito da unificação)
**Referência completa:** `docs/PLANO_SAFEGUARD.md` — seção "Tier 1 — Bloqueadores"

**Objetivo:** ter verificação automatizada antes de qualquer merge de branch, para não repetir o DT-12 e os bugs de divergência treino/produção.

**Protocolo por item:** implementar → testar → commitar → deployar individualmente. Ver protocolo completo em `docs/PLANO_SAFEGUARD.md` — seção "Protocolo obrigatório por item".

### 7 itens a implementar

| ID | Item | Arquivo | Por que agora |
|---|---|---|---|
| T1-1 | Encoding ordinal: alinhar nomes de coluna | `src/features/encoding.py:45,56` | Causa raiz do DT-12 — ordinal falha silenciosamente |
| T1-2 | CAPI: alerta decil com 0 eventos | `src/monitoring/capi_monitor.py` | D9 ficou 2 meses invisível sem esse check |
| T1-3 | CAPI: deduplicação antes do envio | `api/capi_integration.py` | Reprocessamento pode duplicar eventos ao Meta |
| T1-4 | Timezone: `datetime.now()` → UTC em 4 arquivos | `src/`, `api/` | Cloud Run é UTC — discrepância de 3h silenciosa |
| T1-5 | Monitoramento: alerta D10% < 15% ou > 50% | `src/monitoring/orchestrator.py` | Colapso de D10 não dispara nenhum alerta hoje |
| T1-6 | Verificar `app.py` carregando `META_ACCESS_TOKEN` | `api/app.py` | Token ausente no startup = CAPI silenciosamente morto |
| T1-7 | Parity audit: estender para encoding ordinal + UTM | `tests/parity_audit.py` | Instrumento para validar cada arquivo da unificação |

### Como verificar que Tier 1 está completo

```bash
cd V2/
python scripts/test_encoding_overrides.py --limit 200   # T1-1
python -m pytest tests/parity_audit.py -v               # T1-7
python -c "
from src.monitoring.orchestrator import MonitoringOrchestrator
m = MonitoringOrchestrator()
print(m.run_daily_check())
"                                                         # T1-2, T1-5
```

Todos os testes passando = Fase 2 concluída, Fase 3 pode começar.

---

## Fase 3 — Unificação de branches
**Pré-requisito:** Fase 2 concluída (Tier 1 dos safeguards)

### Objetivo concreto (revisto em 2026-04-21)

Trazer para a branch `main` o comportamento funcional do rollback `edf23e9` que é necessário para os dois modelos em produção (Champion jan30 e Challenger mar24) funcionarem corretamente quando servidos pela pipeline refatorada da main. Concretamente:

**Para o Champion (jan30) — 8 features ausentes em main:**
- `nome_valido_True/False`, `email_valido_True/False`, `telefone_valido_True/False` — derivam do `feature_engineering` do rollback, não existem em `src/core/feature_engineering.py`
- `telefone_comprimento_4`, `telefone_comprimento_10` — OHE de `telefone_comprimento` que no rollback vira categórica e em main é numérica

**Para o Challenger (mar24) — 13 features ausentes em main, resolvidas por config:**
- 6 OHE de idade + 5 OHE de salário — resolvidos via **Opção A** (ver abaixo)
- `Medium_Linguagem_de_programa_o` — nome bugado pelo regex antigo; main já corrige via `column_name_corrections` mas o registry do mar24 tem o nome antigo. Resolver no retreino do mar24
- `Medium_Lookalike_2_Cadastrados_DEV_2_0_Interesses` — investigar caso específico

### Decisão arquitetural — Opção A para encoding de idade/salário

Decisão tomada em 2026-04-21 sobre como representar idade e faixa salarial no encoding:

- **Default do cliente (`configs/clients/devclub.yaml`):** idade e salário como **OHE** (remover de `ordinal_variables`)
- **Champion (jan30):** mantém `encoding_overrides` com ordinal — é como foi treinado
- **Challenger (mar24):** herda o default (OHE) — é como foi treinado

Racional: o default representa "o encoding mais comum nos modelos atuais e futuros"; overrides representam exceções explícitas de uma variante específica. Alternativa (manter ordinal como default e adicionar override OHE para mar24) foi rejeitada porque exige que o `merge_encoding` suporte "anular override do base", o que aumenta complexidade.

### Pré-requisitos antes do primeiro porte

1. **Golden snapshot do monitoring capturado** — salvar resultado de `/monitoring/daily-check/railway?hours=720` rodado contra a revisão atual (`00269-jjn`, rollback em 100%) em `V2/docs/monitoring_golden_snapshot.json`. Sem ele, não há referência para detectar regressão em observabilidade durante a unificação.
2. **Aplicar Opção A no `configs/clients/devclub.yaml`** — remover idade/salário de `ordinal_variables`, regenerar snapshots de parity com o config novo, confirmar que T1-7 passa.
3. **Documentação do Momento 1** commitada antes de qualquer mudança de código.

### Ordem de portes planejada

| # | Arquivo | O que porta | Validação |
|---|---|---|---|
| 1 | `configs/clients/devclub.yaml` | Opção A — remover idade/salário de ordinal_variables; regenerar snapshots | T1-7 passa com snapshots novos |
| 2 | `src/core/feature_engineering.py` | Criação das 3 features `nome_valido`, `email_valido`, `telefone_valido` | T1-7 + T1-11 passam; Champion ganha as 6 features derivadas |
| 3 | `src/core/feature_engineering.py` ou `src/core/preprocessing.py` | Manter `telefone_comprimento` como categórica (não numérica), para OHE derivar `telefone_comprimento_4/10` | T1-7 + T1-11 passam; Champion ganha as 2 features restantes |
| 4+ | A descobrir conforme a unificação avança | — | — |

### Protocolo de porte (inalterado)

Para cada arquivo portado de edf23e9 → main:

1. **Rodar parity audit antes:** `python3 V2/tests/parity_audit.py --function utm --function encoding`
2. **Aplicar a mudança** no código + atualizar devclub.yaml se necessário
3. **Rodar parity audit depois:** mesmo comando
4. **Rodar T1-11 (validador pré-encoding)** contra o snapshot e contra amostra real do Railway
5. **Se qualquer gate falhar:** reverter commit, registrar FAIL na tabela de Log de portes abaixo, NÃO prosseguir para próximo porte
6. **Se todos passarem:** commit isolado + push + registro OK no Log de portes

### Log de portes — Fase 3

| Data | Arquivo | De | Para | T1-7 antes | T1-7 depois | T1-11 | Status | Observação |
|---|---|---|---|---|---|---|---|---|
| 2026-04-23 | `configs/clients/devclub.yaml` | ordinal idade/salário | OHE idade/salário (Opção A) | OK (51 cols) | OK (60 cols, 0 divergências) | n/a (é mudança de config, não envolve encoding de features derivadas) | ✅ OK | Gap do Challenger de 13 features caiu para 2 (`Medium_Linguagem_de_programa_o`, `Medium_Lookalike_2_Cadastrados_DEV_2_0_Interesses`) — casos específicos de nome/categoria para portes futuros. Champion continua com ordinal via override — comportamento preservado. |
| 2026-04-23 | `src/core/feature_engineering.py` + `client_config.py` + `configs/clients/devclub.yaml` | `nome_valido`/`email_valido`/`telefone_valido` não criadas | Criadas via flag `create_valido_features=true` (portado do rollback edf23e9) | OK (60 cols) | OK (66 cols, 0 divergências) | Testes unitários + integração com 67k leads reais (99.9% de validade nas 3 features) | ✅ OK | Gap do Champion caiu de 8 para 2 features (`telefone_comprimento_4`, `telefone_comprimento_10`) — ambas requerem retreino do Champion com dados atuais. Challenger continua com as mesmas 2 ausentes do porte anterior. |

### Retreinos coordenados — 2026-04-23

Após portes #1 e #2, as 4 features ainda ausentes nos feature_registries (2 do Champion + 2 do Challenger) eram casos que só resolvem com retreino (`telefone_comprimento_4/10` do Champion, mismatch de normalização de nome do Medium no Challenger). Executei retreino coordenado dos dois modelos com a pipeline atual:

### Evolução dos retreinos (2026-04-23)

Durante o dia foram feitos 5 retreinos em sequência, cada um corrigindo um gap descoberto no anterior:

| Geração | Fontes | Dataset | Positivos | Janela limite | Champion AUC | Challenger AUC | Status |
|---|---|---|---|---|---|---|---|
| v0 originais (jan30/mar24) | Sheets + Guru (velhos) | ~110k / 67k | ~415 | — | 0.7311 | 0.7372 | Produção atual |
| v1 cache 03/03 | Sheets + Guru | 67k | 415 | 2026-03-06 | 0.724 | 0.728 | MLflow apenas |
| v2 fresh 06/03 | Sheets + Guru (fresh) | 72k | 430 | 2026-03-06 | 0.743 | 0.756 | MLflow apenas |
| v3 + Hotmart | Sheets + Guru + Hotmart | 72k | 430 | 2026-03-06 | 0.743 | 0.756 | Hotmart não moveu ponteiro |
| **v4 + Railway (final)** | **Sheets + Guru + Hotmart + Railway** | **192k** | **1,104** | **2026-04-02** | **0.748** | **0.745** | **✅ Candidato ao deploy** |

Run IDs finais (v4, 2026-04-23):
- Champion: `60637bb98b94421b9c7579bb4ac1b1ad`
- Challenger: `7d08ae0302da420aa99559d4d4f55025`

Observações sobre v4:
- **2.6× mais positivos** que as gerações anteriores (1,104 vs 430) — muito mais robusto estatisticamente
- **Janela de treino alcançou 2026-04-02** (vs 2026-03-06) — capta o período pós-explosão Hotmart em março
- AUC similar a v2/v3 mas Top 3 decis subiu de 62.8% → 67.3% e Monotonia de 66.7% → 77.8%
- **Compatibilidade snapshot: 60 features esperadas, 0 ausentes** em ambos os modelos. T1-7 parity audit passa.

Gaps resolvidos em v4:
- Hotmart carregado (219 vendas em 2024-12-30 → 2026-04-23, 131 em março)
- Railway carregado (109,284 leads desde 2026-02-18 via webhook)
- Dedup cross-source por email (118k duplicatas removidas, Railway prioritário sobre Sheets/Excel)
- Threshold de missing rate ajustado (50% para `investiu_curso_online` e `interesse_programacao` — features adicionadas depois na pesquisa; cutoff posterior reduz missing real a ~1%)
- Sheets truncado em 27/03 não bloqueia mais — Railway estende a data máxima para 23/04

---

### Retreinos coordenados — 2026-04-23 (primeira rodada, obsoleta)

> **Obsoleto:** esta seção registra a primeira rodada de retreino (v1 — cache 03/03) antes das descobertas sobre Hotmart, Railway e Sheets truncado. Substituído pelos modelos v4 acima.

| Modelo | Run ID antigo | Run ID novo | AUC antigo | AUC novo | Lift antigo | Lift novo | Compat snapshot |
|---|---|---|---|---|---|---|---|
| Champion (jan30) | `d51757f5...` | `d67bf550e51243b19d83687c4e7d9613` | 0.7311 | 0.724 | 2.65× | 3.4× ↑ | ✅ 0 features ausentes |
| Challenger (mar24) | `a859c68b...` | `97bf18cde3d44129aa1eb58798d744f8` | 0.7372 | 0.728 | 3.26× | 3.4× | ✅ 0 features ausentes |

Ambos os novos runs produziram feature_registries de 65 features, **100% compatíveis** com o output atual do encoding (66 colunas — snapshot tem 1 feature extra ignorada pelos modelos).

AUC caiu ligeiramente (~0.007–0.009) pela uniformização de dataset e pipeline entre os dois modelos. Lift máximo subiu no Champion (2.65 → 3.4) — indica melhor separação nos decis altos. Monotonia caiu (88.9% → 66–78%) — vale observação durante canary mas não é bloqueador imediato (o Meta otimiza por ROAS, não monotonia).

**Ação pendente antes do deploy:** atualizar `configs/active_models/devclub.yaml`:
- `guru_jan30.run_id` → `d67bf550e51243b19d83687c4e7d9613`
- `guru_mar24.run_id` → `97bf18cde3d44129aa1eb58798d744f8`
- **Remover `encoding_overrides` do `guru_jan30`** — Champion novo foi treinado com OHE (default Opção A), não mais ordinal. Manter override quebraria o scoring.

### Estado atual — 2026-04-23

**Produção:**
- 100% do tráfego no rollback `00269-jjn` (Champion jan30 ORIGINAL, sem A/B routing)
- A/B test não está ativo — Challenger mar24 não recebe tráfego
- DEV20 captação em andamento desde 21/04, janela fecha em 04/05

**Código:**
- Porte #1 (Opção A encoding) ✅
- Porte #2 (valido features) ✅
- Retreinos coordenados ✅
- Commits locais feitos e pushados

**Pendente antes do deploy:**
- **T1-11 (validador pré-encoding de features)** — ÚNICO bloqueador restante. Garantia de monitoramento em produção da chegada, processamento e uso das features corretas pelos modelos. Documentado em `PLANO_SAFEGUARD.md`, arquitetura em 3 peças.
- Atualização do `active_models/devclub.yaml` com novos run_ids (listado acima)

**Por que T1-11 bloqueia:** sem ele, pós-deploy, não temos visibilidade automática de quando uma feature crítica está ausente, com tipo errado ou fora do domínio conhecido do treino. A pipeline preencheria com 0 e ninguém saberia. T1-10 detecta isso só DEPOIS do encoding (colunas OHE sumirem); T1-11 detecta ANTES (causa raiz). Sem essa camada, o deploy em 10% seria cego.

### Resultado esperado

Após a unificação, o deploy **não** vai direto para 100%. O target é **50/50** — main unificada e rollback `edf23e9` cada um com metade do tráfego. Decisão tomada em 21/04/2026; rationale completo em `AB_TEST.md` → seção "Estratégia de deploy — 50/50 em vez de 100%".

- **Durante o 50/50:** o A/B test só roda na metade da main (rollback não tem código de roteamento). Amostra efetiva do A/B cai pela metade no DEV20.
- **Pré-requisitos para o 50/50:** Tier 1 completo + parity audit passando + smoke test pós-deploy + Fase 3 unificação concluída + T1-11 implementado.
- **Subir para 100%:** só após 3 dias sem alerta HIGH + ROAS por variante consolidado no DEV20.

O edf23e9 só é aposentado de verdade quando main está a 100%.

---

## Fase 4 — Safeguards Tier 2 + 3 e documentação
**Referência completa:** `docs/PLANO_SAFEGUARD.md` — seções "Tier 2" e "Tier 3"

Implementar sobre o código unificado. 12 itens restantes, nenhum é bloqueador de produção.

Destaques:

**Tier 2 (qualidade de dados):**
- `src/core/ingestion.py` — implementar deduplicação (hoje é `NotImplementedError`)
- `src/train_pipeline.py` — importance weighting para grupo controle
- `src/validation/` — remover limite de 10.000 registros

**Tier 3 (observabilidade):**
- Smoke test automatizado pós-deploy
- Progressão de canary documentada no `deploy_capi.sh`
- Alerta de token Meta a < 10 dias de expirar
- Branch protection no GitHub

---

## Fase 5 — Retreino e novo ciclo A/B
**Condição de entrada:** resultado do teste A/B disponível (pós 17/05/2026, carrinho DEV20 fechado) + código unificado

### Se Challenger vencer (ROAS mar24 ≥ ROAS jan30)
```bash
python -m src.train_pipeline --activate-run a859c68b
```
Atualizar `devclub.yaml`: mar24 → Champion, criar próximo Challenger com dados mais recentes.

### Se Champion mantiver (ROAS jan30 ≥ ROAS mar24)
Retreinar jan30 com dados novos (incluindo lançamentos pós-setembro/2025 que o modelo nunca viu).
O modelo jan30 tem dados até 04/11/2025 — já são 5 meses de audiência não observada.

Ver critério completo em `docs/AB_TEST.md` — seção "Critério de promoção".

---

## Visão consolidada de datas

| Data | Marco |
|---|---|
| 20/04/2026 (hoje) | Canary `00271-cv7` a 10%, rollback `00269-jjn` a 90% |
| 21/04–04/05 | **DEV20 captação** — sistema com A/B test ativo em produção |
| ~20–25/04 | Fase 2: Tier 1 dos safeguards (9 itens) |
| ~28/04–05/05 | Fase 3: Unificação de branches com parity audit |
| 11/05–17/05 | **DEV20 carrinho aberto** — coleta final de dados do teste |
| após 17/05 | Fase 1 decisão: ROAS consolidado → promover ou manter Champion |
| Maio–Jun/2026 | Fase 4: Tier 2+3 + retreino com decisão do teste |

---

## Pendências herdadas do Refactor MLOps

Esta seção lista os itens abertos do `PLANO_REFACTOR_MLOPS.md` que não estão cobertos pelas Fases 1–5 acima. São organizados por urgência em relação ao onboarding de Cliente B.

**Referência:** `docs/PLANO_REFACTOR_MLOPS.md` — seções "Divergências residuais", "Dívida Técnica" e "Fases 3b, 4, 5".

---

### Pré-condições para onboarding de Cliente B (bloqueadores)

Estes itens devem ser concluídos **antes** de iniciar a Fase 3b do refactor (onboarding do segundo cliente). São independentes dos dados do cliente e podem ser feitos em paralelo com as Fases 1–4 deste plano.

| ID | Item | Arquivo | Descrição |
|---|---|---|---|
| R1 / DT-8 | Features fantasmas em produção | `src/production_pipeline.py` | `production_pipeline.py` cria `nome_valido`, `email_valido`, `telefone_valido` — features que `core/feature_engineering.py` não cria e o modelo nunca viu. Remover o bloco de criação das 3 features. Não requer retreino. |
| R2 / DT-10 | Hardcodes de modelo em treino | `src/train_pipeline.py:~763,~788` | `PESOS_COMPRADOR` e `DEFAULT_HYPERPARAMS` reimplementados inline apesar de existirem em `devclub.yaml`. Para Cliente B, o treino usaria pesos DevClub sem aviso. Substituir por `client_config.model.buyer_weights` e `client_config.model.hyperparameters`. Rodar Camada 2 (AUC ±0.5%) para confirmar. |
| R3 / DT-9 | Encoding ordinal: aliases transitórios | `configs/clients/devclub.yaml`, `src/core/encoding.py` | Verificar se `'idade'` e `'faixa_salarial'` ainda existem como aliases em `encoding.ordinal_variables`. O checklist pós-retreino (item 4, Fase 2) mandou removê-los mas não foi marcado como feito. Se o alias curto está no YAML mas o df chega com o nome longo, o encoding ordinal é silenciosamente pulado. |

### Dívida técnica ativa (não bloqueadores imediatos)

Itens que não bloqueiam produção hoje mas devem ser endereçados antes de escalar para 3+ clientes.

| ID | Prioridade | Item | Arquivo | Descrição |
|---|---|---|---|---|
| DT-12 | Alta | Encoding por variante A/B (`encoding_overrides`) | `src/core/client_config.py`, `src/core/encoding.py`, `src/production_pipeline.py`, `api/app.py`, `configs/active_models/devclub.yaml` | Jan30 recebe `Qual_a_sua_idade = 0` para todos os leads (ordinal falha silenciosamente) porque foi promovido a Champion após o fix de OHE para mar24. Solução: `ABTestVariantConfig.encoding_overrides` + `merge_encoding()` em `core/encoding.py`. **Nota:** o `PLANO_EXECUCAO.md` Fase 1 (A/B patch no rollback) não cobre esta divergência de encoding — é trabalho adicional no mesmo conjunto de arquivos. |
| DT-7 | Baixa | Threshold de Medium calculado sobre janela errada | `src/core/medium.py` | O threshold de 2.5% é calculado sobre o dataset completo antes do corte temporal, fazendo campanhas históricas inativas entrarem no feature registry e gerarem alertas falsos no monitoramento. Fix: calcular threshold sobre dados pós-cutoff. |
| DT-2 | Baixa | Ausência de testes unitários em `src/core/` | `tests/core/` | Toda validação atual é integration test (~10–20 min). Sem testes unitários, qualquer mudança em `core/utm.py`, `core/medium.py` ou `core/encoding.py` requer pipeline completo por cliente. **Condição para não adiar mais:** antes de qualquer mudança em `core/` com dois clientes ativos. |
| R4 | Baixa | Guard de coluna Medium ausente em produção | `src/production_pipeline.py` | `train_pipeline.py` tem `if 'Medium' in df.columns` antes de chamar `medium.unify_medium`; produção sempre chama sem guard. Se Medium desaparecer do formulário, produção quebrará enquanto treino continuaria silenciosamente. |
| R5 / DT-11 | Baixa | Imports dinâmicos em monitoring | `src/monitoring/orchestrator.py` | Imports de `core/` estão dentro do corpo de `run_daily_check()` em vez do topo do arquivo. Erro de import só aparece quando o monitoramento roda, não na inicialização. Fix: mover 5 imports para o topo. |

### Golden snapshot de monitoramento (lacuna de observabilidade)

O golden snapshot do monitoring (`docs/monitoring_golden_snapshot.json`) **não foi capturado antes do deploy** de 26/03/2026. A lacuna documenta-se aqui para não ser esquecida.

- **O que fazer:** rodar `MonitoringOrchestrator.run_daily_check(reference_date=date(2026, 3, 15), dry_run=True)` com data fixa e salvar output em `docs/monitoring_golden_snapshot.json`.
- **Quando:** antes da próxima mudança estrutural em `core/preprocessing.py` ou `core/feature_engineering.py`, e obrigatoriamente antes do onboarding de Cliente B com monitoramento ativo.
- **Referência:** `PLANO_REFACTOR_MLOPS.md` — seção "Fase 2 — Pendente — validação do monitoramento".

### Retreino com importance weighting (prazo vencido)

- **Status:** prazo original 15/04/2026 vencido sem execução. Dados da campanha de controle disponíveis desde 15/03/2026.
- **O que fazer:** retreinar com pesos maiores para leads da campanha de controle e pesos menores para leads D10 sobre-representados; implementar como hook no `retraining_orchestrator.py`.
- **Onde está documentado:** `PLANO_REFACTOR_MLOPS.md` — bloco de ação urgente no topo do documento.
- **Incorporado a:** Fase 5 deste plano (retreino pós-resultado A/B).

### Gatilho de retreino por drift de públicos (identificado 22/04/2026)

- **Observação:** 5 das 6 categorias Medium do treino `jan30` sumiram do tráfego em produção. `Medium_Linguagem_programacao` (rank #6 no modelo, 5,31% da importância) = 0 para 100% dos leads. `Medium_Aberto` virou quase-constante (1 em 70% dos leads vs 14,5% no treino). `Medium_Lookalike_2pct_Cadastrados` = 0 para 100%.
- **Impacto:** grupo `Medium_*` pesa 7,95% da importância total. A feature top do grupo está cega; as outras duas perderam poder discriminativo. Consistente com o drift de D10 observado (esperado 10%) e com o cluster 3 do `Erros_cometidos.md` (Medium_Linguagem_programacao zerada em 13/04 por causa distinta — encoding).
- **Evolução do D10 ao longo da semana:** histórico 29,5% → último mês 30,4% → última semana 34,1% → 22/04 32,7% → 23/04 **34,7%**. Tendência de aceleração, não estabilização.
- **Evidência:** `/monitoring/daily-check` 22/04/2026 — alertas `distribution_drift HIGH` em Medium e `score_distribution_change HIGH` em D10.
- **O que fazer:** retreinar com dados pós-01/04/2026 (quando a composição atual de públicos estabilizou) antes de esperar o fechamento do A/B test. O feature registry do novo modelo refletirá o mix atual.
- **Pré-requisitos:** idealmente após fix de DT-13 (brecha de `utm_term`) para não arrastar ruído pro treino novo; e após decisão sobre tratamento de `Source='org'` (hoje cai em `Outros`).
- **Prioridade:** média — não bloqueia deploys imediatos, mas o modelo está operando com 7,95% da sua massa de decisão cega. Reavaliar a cada ciclo de investigação.
- **Referência cruzada:** `INVESTIGACAO_BAIXO_DESEMPENHO.md`, `PLANO_REFACTOR_MLOPS.md` §11 DT-13, `PLANO_SAFEGUARD.md` T2-8.

### Fases futuras do refactor (sem prazo imediato)

| Fase | Condição de entrada | Referência |
|---|---|---|
| **3b — Onboarding Cliente B** | R1, R2, R3 resolvidos + dados do cliente disponíveis | `PLANO_REFACTOR_MLOPS.md` §7 Fase 3b + `ROADMAP_MLOPS_MATURIDADE.md` item 11 |
| **Validação de dados pré-treino** (`src/core/validation.py`) | Antes do segundo cliente | `PLANO_REFACTOR_MLOPS.md` §12 "Caminho para Nível 2" |
| **Quality gate automático pós-treino** (Sprint 2 do `retraining_orchestrator.py`) | Qualquer momento | `PLANO_REFACTOR_MLOPS.md` §12 "Caminho para Nível 2" |
| **4 — EDA Generator** (`src/eda/generate_client_config.py`) | Após `devclub.yaml` e `clientb.yaml` escritos manualmente | `PLANO_REFACTOR_MLOPS.md` §7 Fase 4 + `ROADMAP_MLOPS_MATURIDADE.md` item 12 |
| **5 — NLP** (`src/nlp/`) | Sem data — campo de texto livre no formulário | `PLANO_REFACTOR_MLOPS.md` §7 Fase 5 |

---

## Skills disponíveis

| Skill | Quando usar |
|---|---|
| `/investigate` | Investigar por que um lançamento foi ruim — números históricos e causas conceituais |
| `/investigate-ab` | Verificar se o teste A/B está tecnicamente válido — roteamento, eventos, janela limpa |
| `/safeguard` | Auditoria completa de integridade — encoding, CAPI, deploy, timezone, monitoramento |
| `/plan-integrator` | Ler todos os docs, reconciliar status e emitir prioridade global atualizada |

