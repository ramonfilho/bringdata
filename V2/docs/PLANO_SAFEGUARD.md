# Plano de Integridade — Smart Ads V2

**Criado:** 2026-04-16  
**Atualizado:** 2026-04-20  
**Status:** Em execução

Documento que consolida: audit de infraestrutura existente, gaps identificados, ordem de execução e plano de implementação.

Referências:
- Erros históricos: `docs/Erros_cometidos.md`
- Skills de investigação: `/investigate`, `/investigate-ab`, `/safeguard`

---

## Protocolo obrigatório por item (Tier 1, 2 e 3)

**Cada item é implementado, testado, commitado e deployado individualmente — nenhuma exceção.**

```
Para cada T1-x / T2-x / T3-x:

1. IMPLEMENTAR   — fazer a mudança no código
2. TESTAR        — rodar o(s) teste(s) específicos listados em "Como testar cada item"
                   O item só avança se os testes passarem
3. COMMITAR      — commit isolado descrevendo o item (ex: "safeguard(T1-1): encoding ordinal fail-loud")
4. DEPLOYAR      — deploy com --no-traffic → smoke test → canary → 100%
5. MARCAR        — atualizar status na tabela de "Status de implementação" para Concluído
```

**Por que deploy por item:** cada safeguard é uma mudança independente de comportamento em produção. Agrupar vários itens num único deploy torna impossível identificar qual mudança causou um problema. Deploy granular = rollback preciso.

---

## Ordem de execução

```
1. A/B PATCH (urgente — prazo 27/04)
   Patch no rollback worktree → deploy → 100% ML_MAR para o Challenger
   Não depende dos safeguards. Bloqueador de negócio.

2. TIER 1 — Bloqueadores de produção (antes da unificação de branches)
   Esses bugs podem se repetir silenciosamente no merge se não forem resolvidos primeiro.
   Implementar, testar e documentar cada um antes de tocar na unificação.

3. UNIFICAÇÃO DAS BRANCHES (edf23e9 → main)
   Com os checks de Tier 1 prontos, a unificação pode ser verificada automaticamente.
   A cada arquivo mergeado: rodar o parity check de encoding.

4. TIER 2 — Qualidade de dados
   Importantes, mas não bloqueiam a unificação.

5. TIER 3 — Observabilidade
   Melhorias de monitoramento e deploy. Implementar após a unificação estar estável.
```

---

## Gap Matrix — Auditoria completa

### BLOCO 1 — Encoding: treino vs produção

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| `apply_categorical_encoding()` | ✓ Existe | `src/features/encoding.py:64-365` | — |
| `_load_feature_registry()` | ✓ Existe | `src/core/encoding.py:37-100` | — |
| `test_encoding_overrides.py` | ✓ Existe | `scripts/test_encoding_overrides.py:160-223` | Adaptar para cobrir paridade geral, não só A/B |
| `parity_audit.py` (Medium) | ✓ Existe parcial | `tests/parity_audit.py:138-150` | Estender para encoding ordinal e UTM |
| Nomes de colunas ordinal | ✗ Bug ativo | `src/features/encoding.py:45,56` | Alinhar nome literal ('Qual a sua idade?') entre yaml e DataFrame — hardcoded com fallback silencioso para OHE |
| Snapshot encoding treino vs prod | ✗ Não existe | — | Criar: input fixo → output esperado → comparar |
| Verificação de features 100% zero | ✗ Não existe | — | Criar: alerta se feature crítica = 0 em > 95% dos leads |

**Ação prioritária (Tier 1):** estender `parity_audit.py` para comparar encoding coluna-a-coluna entre treino e produção. Rodar antes de qualquer merge de branch.

---

### BLOCO 2 — CAPI: integridade do sinal

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| `send_event_to_capi()` | ✓ Existe | `api/capi_integration.py:263-375` | — |
| `_check_capi_missing_rate()` | ✓ Existe | `src/monitoring/capi_monitor.py:45-129` | — |
| `_check_capi_rejection_rate()` | ⚠ Stub incompleto | `src/monitoring/capi_monitor.py:136-149` | Implementar query de eventos rejeitados vs aceitos |
| Verificação D1–D10 todos enviando | ✗ Não existe | — | Criar: alerta se qualquer decil = 0 eventos nas últimas 24h |
| Deduplicação antes de enviar | ✗ Não existe | — | Criar: check de email duplicado na fila antes do envio |
| Alerta `capiStatus` blocked/null | ✗ Não existe | — | Criar: alerta se blocked+null > 10% do volume do dia |
| Formato chaves D01 vs D1 | ⚠ Risco | `api/capi_integration.py:356-357` | Confirmar que lookup de `conversion_rates` usa mesmo formato que yaml |

**Ação prioritária (Tier 1):** criar verificação automática de que todos os decis D1–D10 estão gerando eventos de sucesso. Esse bug ficou 2 meses invisível.

---

### BLOCO 3 — Pipeline de dados: qualidade do dataset

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| Janela de conversão simétrica | ✓ Existe | `src/data_processing/conversion_window.py:13-93` | — |
| Ordem TMB → merge vendas | ✓ Correto em treino | `src/train_pipeline.py:400-430` | Confirmar que `production_pipeline.py` respeita mesma ordem |
| Deduplicação no treino | ✗ Stub `NotImplementedError` | `src/core/ingestion.py` | Implementar usando `remove_duplicates_per_sheet()` de `train_pipeline.py` |
| Cross-check dataset pós-filtro | ✗ Não existe | — | Criar: log de N leads por etapa (antes/depois de cada filtro) |
| Log de estatísticas por etapa | ✗ Não existe | — | Criar: ingestion → col_unify → janela → match → encoding: N registros, N positivos |

**Ação prioritária (Tier 2):** implementar `remove_duplicates_per_sheet()` em `src/core/ingestion.py` (hoje é `NotImplementedError`).

---

### BLOCO 4 — Infraestrutura e configuração

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| `ARG MODEL_PATH` no Dockerfile | ✓ Existe | `api/Dockerfile:45-52` | — |
| `stage_model_artifacts()` | ✓ Existe | `api/deploy_capi.sh:284-341` | — |
| `load_dotenv()` no treino | ✓ Existe | `src/train_pipeline.py:14-17` | — |
| `load_dotenv()` no app.py | ✗ Ausente | `api/app.py` | Verificar — Cloud Run injeta env vars, mas scripts locais precisam de `.env` |
| Verificação de Meta token freshness | ✗ Não existe | — | Criar: alerta quando token está a < 10 dias de expirar (60d ciclo) |
| Validação MODEL_PATH vs yaml | ✗ Não existe | — | Criar: `deploy_capi.sh` valida que path no yaml existe antes do build |
| MLflow experiment ID hardcoded | ✗ Risco não auditado | `src/` | Verificar: `grep -rn "experiment_id.*=.*[0-9]" V2/src/` |

**Ação prioritária (Tier 1):** verificar `app.py` — se `META_ACCESS_TOKEN` não está sendo carregado no startup, todos os envios CAPI falham silenciosamente no próximo restart do container.

---

### BLOCO 5 — Deploy: segurança e reversibilidade

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| Flag `--no-traffic` | ✓ Existe | `api/deploy_capi.sh:51` | — |
| Whitelist de branches | ✓ Existe | `api/deploy_capi.sh:68-128` | — |
| Referência a revisão anterior | ✓ Existe | `api/deploy_capi.sh:252-264` | — |
| Progressão de tráfego (canary) | ⚠ Parcial | `api/deploy_capi.sh` | Documentar fluxo explícito: 0% → 10% → 50% → 100% com comandos |
| Rollback automático | ✗ Não existe | — | Criar: health check pós-deploy + rollback automático se falhar |
| Script de validação pós-deploy | ✗ Não existe | — | Criar: 5 leads de teste → verificar score + decil + CAPI log |
| Proteção de branch main | ✗ Não existe | — | Configurar no GitHub: require PR + aprovação |

**Ação prioritária (Tier 3):** documentar o fluxo de canary explicitamente no `deploy_capi.sh` (comentário com os 3 comandos gcloud). Criar script de smoke test pós-deploy.

---

### BLOCO 10 — Autorização de processo: o deploy deveria acontecer?

Adicionado em 20/04/2026 após incidente: `main` deployada e com 100% do tráfego por horas sem verificação de pré-requisitos. O safeguard audita integridade técnica; este bloco audita se o deploy está autorizado pelo processo.

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| Branch autorizada para produção | ✗ Não verificado no safeguard | `api/deploy_capi.sh:68` | Adicionar ao safeguard: verificar se branch atual está em `AUTHORIZED_BRANCHES` |
| Pré-requisitos Tier 1 concluídos | ✗ Não verificado | `docs/PLANO_SAFEGUARD.md` | Verificar que nenhum T1-x está "Pendente" antes de deployar `main` |
| Parity check main vs produção | ✗ Não verificado no deploy | `tests/parity_audit.py` | Exigir `pytest parity_audit.py` passando antes de qualquer deploy de `main` |
| Gate de progressão de tráfego | ✗ Protocolo não documentado | — | Documentar: 0% → 10% (1h mínimo) → 50% (confirmação) → 100% (confirmação + rollback nomeado) |
| Trail de autorização de deploy | ✗ Não existe | — | Criar: cada mudança de split de tráfego deve ser registrada com motivo e autorização |

**Ação prioritária (Tier 1 novo):** o deploy de `main` em produção causou degradação de sinal. Adicionar verificação de branch + parity check como gate obrigatório antes de qualquer deploy não-rollback.

---

### BLOCO 6 — Fuso horário

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| `datetime.now(timezone.utc)` no capi_monitor | ✓ Correto | `src/monitoring/capi_monitor.py:59` | — |
| `datetime.now()` sem timezone — treino | ✗ Risco | `src/train_pipeline.py:77` | Converter para `datetime.now(timezone.utc)` |
| `datetime.now()` sem timezone — pipeline | ✗ Risco | `src/production_pipeline.py:55` | Converter |
| `datetime.now()` sem timezone — orchestrator | ✗ Risco | `src/monitoring/orchestrator.py:63-64, 400` | Converter |
| `datetime.now()` sem timezone — validação | ✗ Risco | `src/validation/analyze_tmb_inadimplencia.py` | Converter |
| Constante central de timezone | ✗ Não existe | — | Criar: `from src.core.utils import UTC` importado por todos |

**Ação prioritária (Tier 1):** criar constante central `UTC = timezone.utc` em `src/core/utils.py` e substituir todos os `datetime.now()` sem timezone. O Cloud Run roda em UTC — discrepância com São Paulo é 3h, o suficiente para perder leads nas bordas do dia.

---

### BLOCO 7 — Monitoramento: alertas automáticos

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| `MonitoringOrchestrator` | ✓ Existe | `src/monitoring/orchestrator.py:88-350` | — |
| `DataQualityMonitor` (drift) | ✓ Existe | `src/monitoring/data_quality.py` | — |
| `OperationalMonitor` | ✓ Existe | `src/monitoring/operational_monitor.py` | — |
| `CAPIQualityMonitor` | ✓ Existe parcial | `src/monitoring/capi_monitor.py` | Implementar rejection_rate |
| `send_slack_alert()` | ✓ Existe | `src/validation/slack_notifier.py` | — |
| Thresholds no `config.py` | ✓ Existe | `src/monitoring/config.py` | — |
| Alerta D10% out-of-range | ⚠ Lógica complexa | `src/monitoring/orchestrator.py` | Simplificar: alerta se D10% < 15% ou > 50% |
| Thresholds hardcoded | ⚠ Hardcoded | `src/monitoring/operational_monitor.py` | Mover para `ClientConfig` |
| Alerta decil com 0 eventos | ✗ Não existe | — | Criar em `CAPIQualityMonitor` |
| Relatório diário consolidado | ✗ Não existe | — | Criar: N alertas HIGH/MEDIUM/LOW por dia |

**Ação prioritária (Tier 1):** adicionar em `CAPIQualityMonitor` a verificação de que nenhum decil tem 0 eventos nas últimas 24h. Esse foi o bug do D9 que ficou 2 meses invisível.

---

### BLOCO 8 — Grupo controle e feedback loop

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| `fair_campaign_comparison.py` | ✓ Existe | `src/validation/fair_campaign_comparison.py` | — |
| `campaign_classifier.py` | ✓ Existe | `src/validation/campaign_classifier.py` | — |
| Importance weighting no treino | ✗ Não existe | `src/train_pipeline.py` | Criar: leads de grupo controle com peso 2x no treino |
| Identificação de leads controle | ✗ Não existe | — | Criar: filtro por campanha sem ML no dataset de treino |
| Log de proporção controle/tratamento | ✗ Não existe | — | Criar: logar % de leads controle no dataset antes do treino |

**Ação prioritária (Tier 2):** mapear quais campanhas são grupo controle (sem ML) e garantir que leads dessas campanhas estão no dataset de treino com peso maior. Retreino pendente para corrigir viés acumulado.

---

### BLOCO 9 — Relatório de validação

| Item | Status | Onde está | O que fazer |
|---|---|---|---|
| `validate_ml_performance.py` | ✓ Existe | `src/validation/validate_ml_performance.py:15-100` | — |
| `CampaignMetricsCalculator` | ✓ Existe | `src/validation/metrics_calculator.py` | — |
| `validate_tmb_sales_freshness()` | ✓ Existe | `src/validation/validate_ml_performance.py:105-150` | — |
| Limite 10.000 registros | ✗ Bug | `src/validation/generate_taxa_resposta_csv.py`, `capi_events_counter.py` | Remover limite ou alertar se query retorna exatamente 10.000 |
| Filtro de vendas não aprovadas | ✗ Ausente explícito | `src/validation/validate_ml_performance.py` | Verificar se filtragem vem do datasource ou precisa ser adicionada |
| Cross-check total vs fonte primária | ✗ Não existe | — | Criar: assert total_leads_relatório ≈ total_Meta_Ads ± 5% |
| Reconciliação de run_id | ✗ Não existe | — | Criar: verificar que `leadScore` e `decil` vieram do modelo ativo no momento |

**Ação prioritária (Tier 2):** remover limite de 10.000 registros ou adicionar alerta explícito. Lançamentos grandes (> 10k leads) estavam sendo truncados silenciosamente.

---

## Resumo por Tier

### Tier 1 — Bloqueadores (implementar antes da unificação de branches)

| # | Item | Arquivo | Ação |
|---|---|---|---|
| T1-1 | Encoding ordinal: nomes de coluna | `src/features/encoding.py:45,56` | Alinhar literal do yaml com nome real no DataFrame |
| T1-2 | CAPI: alerta decil com 0 eventos | `src/monitoring/capi_monitor.py` | Adicionar verificação de D1–D10 com eventos > 0 |
| T1-3 | CAPI: deduplicação antes do envio | `api/capi_integration.py` | Check de email duplicado na fila |
| T1-4 | Timezone: `datetime.now()` sem UTC | 4 arquivos | Criar constante UTC + substituir |
| T1-5 | Monitoramento: D10% out-of-range | `src/monitoring/orchestrator.py` | Alerta se D10% < 15% ou > 50% |
| T1-6 | `app.py` sem `load_dotenv` | `api/app.py` | Verificar se `META_ACCESS_TOKEN` carrega no Cloud Run |
| T1-7 | Parity audit de encoding | `tests/parity_audit.py` | Estender para ordinal + UTM + snapshot |
| T1-8 | Branch autorizada + gate de processo | `api/deploy_capi.sh`, safeguard | Verificar branch em AUTHORIZED_BRANCHES + parity audit passando antes de qualquer deploy de `main` |
| T1-9 | Protocolo de progressão de tráfego | `docs/` | Documentar e enforçar: 0%→10%(1h)→50%(confirmação)→100%(confirmação) |

### Tier 2 — Qualidade de dados

| # | Item | Arquivo | Ação |
|---|---|---|---|
| T2-1 | Deduplicação no treino | `src/core/ingestion.py` | Implementar (hoje é `NotImplementedError`) |
| T2-2 | Log de N registros por etapa | `src/train_pipeline.py` | Logar antes/depois de cada filtro |
| T2-3 | Importance weighting grupo controle | `src/train_pipeline.py` | Implementar pesos maiores para leads de controle |
| T2-4 | Limite 10.000 em queries de validação | `src/validation/` | Remover ou alertar se hit |
| T2-5 | Filtro vendas não aprovadas | `src/validation/validate_ml_performance.py` | Confirmar ou adicionar filtro explícito |

### Tier 3 — Observabilidade

| # | Item | Arquivo | Ação |
|---|---|---|---|
| T3-1 | Progressão de canary documentada | `api/deploy_capi.sh` | Documentar fluxo 0% → 10% → 100% |
| T3-2 | Script de smoke test pós-deploy | novo | 5 leads → score → decil → CAPI log |
| T3-3 | Proteção de branch main | GitHub | Configurar require PR + aprovação |
| T3-4 | Verificação token Meta (60d) | novo script | Alerta se < 10 dias para expirar |
| T3-5 | Relatório diário consolidado | `src/monitoring/` | N alertas HIGH/MEDIUM/LOW por dia |
| T3-6 | Validação MODEL_PATH vs yaml | `api/deploy_capi.sh` | Build falha claro se divergência |
| T3-7 | Reconciliação run_id no relatório | `src/validation/` | Assert que leadScore veio do modelo ativo |

---

## Como testar cada item

Após implementar qualquer item, o teste mínimo é:

**Tier 1 (encoding/CAPI/timezone):**
```bash
cd V2/
python scripts/test_encoding_overrides.py --limit 200   # T1-1, T1-7
python -m pytest tests/parity_audit.py -v               # T1-7
python -c "from src.core.utils import UTC; print(UTC)"  # T1-4
```

**Tier 1 (monitoramento):**
```bash
python -c "
from src.monitoring.orchestrator import MonitoringOrchestrator
m = MonitoringOrchestrator()
result = m.run_daily_check()
print(result)
"
```

**Tier 2 (deduplicação):**
```bash
python -c "
from src.core.ingestion import remove_duplicates_per_sheet
# Se não lança NotImplementedError, está implementado
print('OK')
"
```

**Tier 3 (smoke test pós-deploy):**
```bash
curl -X POST https://smart-ads-api-12955519745.us-central1.run.app/predict/single \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","campaign":"TEST",...}'
# Verificar: leadScore != null, decil entre 1-10, capiStatus registrado
```

---

## Status de implementação

| Item | Status | Responsável | Data |
|---|---|---|---|
| T1-1 Encoding ordinal | Concluído | | 2026-04-20 |
| T1-2 CAPI decil 0 eventos | Pendente | | |
| T1-3 CAPI deduplicação | Pendente | | |
| T1-4 Timezone UTC | Pendente | | |
| T1-5 D10% alerta | Pendente | | |
| T1-6 app.py load_dotenv | Pendente | | |
| T1-7 Parity audit encoding | Pendente | | |
| T1-8 Branch autorizada + gate de processo | Pendente | | Adicionado 20/04/2026 pós-incidente |
| T1-9 Protocolo progressão de tráfego | Pendente | | Adicionado 20/04/2026 pós-incidente |
| T2-1 Deduplicação treino | Pendente | | |
| T2-2 Log por etapa | Pendente | | |
| T2-3 Importance weighting | Pendente | | |
| T2-4 Limite 10k queries | Pendente | | |
| T2-5 Filtro vendas aprovadas | Pendente | | |
| T3-1 Canary documentado | Pendente | | |
| T3-2 Smoke test pós-deploy | Pendente | | |
| T3-3 Branch protection | Pendente | | |
| T3-4 Token Meta alerta | Pendente | | |
| T3-5 Relatório consolidado | Pendente | | |
| T3-6 MODEL_PATH validação | Pendente | | |
| T3-7 Reconciliação run_id | Pendente | | |
