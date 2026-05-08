# Plano de Integridade — Smart Ads V2 (Catálogo Técnico)

**Criado:** 2026-04-16
**Atualizado:** 2026-04-27
**Papel:** **catálogo técnico** dos itens de safeguard. Especifica o que cada T1-X / T2-X / T3-X faz, como implementar, como testar.

> **Status canônico e prioridade vivem em `PLANO_EXECUCAO.md`.** Este documento descreve o "como" de cada item; o "quando" é definido lá. Quando houver conflito, o PLANO_EXECUCAO vence. Ao concluir um item, atualizar o status nas tabelas internas deste arquivo (linhas 437+) E remover o item da seção correspondente do PLANO_EXECUCAO (passa para "Concluído").

Documento que consolida: audit de infraestrutura existente, gaps identificados, especificação por item, plano de implementação técnica.

Referências:
- Roadmap (sequência de execução): `docs/PLANO_EXECUCAO.md`
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

## Checklist antes de deployar `main` (pré-unificação)

Antes de executar `FORCE_DEPLOY=true ./deploy_capi.sh --force-deploy` para subir a branch `main` em produção, confirmar manualmente cada item. Não é gate automatizado — é responsabilidade de processo.

**Tier 1 obrigatório:**
- [ ] T1-1 (encoding fail-loud) — Concluído
- [ ] T1-2 (CAPI alerta decil zero) — Concluído
- [ ] T1-3 (CAPI deduplicação) — Concluído
- [ ] T1-4 (timezone UTC) — Concluído
- [ ] T1-5 (D10% alerta) — Pulado ou Concluído
- [ ] T1-6 (app.py load_dotenv) — Pulado ou Concluído
- [ ] T1-7 (parity audit) — Concluído, audit passou
- [ ] T1-8 (gate de parity no deploy) — Concluído
- [ ] T1-9 (protocolo progressão de tráfego) — Concluído
- [ ] T1-10 (feature coverage check) — Concluído
- [ ] T1-11 (validador pré-encoding de features) — Concluído
- [ ] T1-12 (smoke de paridade pipeline-modelo no treino) — **Backlog** (29/04/2026)

**Gates automáticos que o script roda:**
1. `check_authorized_branch()` — bloqueia se branch não-rollback sem `FORCE_DEPLOY=true`
2. `check_parity_audit()` — bloqueia se `parity_audit.py` detectar divergência treino × produção

**Gates manuais (responsabilidade humana):**
- Checklist acima revisado com status atual no arquivo
- `--no-traffic` usado no primeiro deploy (nova revisão recebe 0%)
- Smoke test pós-deploy: 5 leads → score + decil + CAPI log OK
- Progressão de tráfego conforme T1-9 (0% → 10% → 50% — parar aqui para DEV20)

**Em caso de dúvida:** se qualquer item acima não puder ser confirmado, a resposta certa é **não deployar** e resolver primeiro.

---

## Validador pré-encoding de features [T1-11]

**Problema que resolve:** o check de T1-10 roda **dentro** de `apply_encoding`, após OHE já ter convertido tudo em `_True/_False`. Isso cobre sumiço de feature mas não cobre:

- Features pré-OHE (nome `nome_valido`, `idade` como string categórica, etc.) estarem ausentes ou com tipo errado
- Valores fora do domínio conhecido do treino (nova categoria `"prefiro_nao_dizer"` em `idade` que o modelo nunca viu)
- Taxa alta de nulo numa feature crítica (silenciosamente vira 0 no encoding)
- Inconsistência entre o que `feature_engineering` produz e o que `apply_encoding` espera consumir

O cheiro desse tipo de falha é o mesmo do bug histórico `Medium_Linguagem_programacao` — feature zerada por semanas sem ninguém saber. T1-10 cobre o sintoma (OHE column missing); T1-11 cobre a causa-raiz (raw feature missing/malformed antes do encoding).

### Arquitetura

**Peça A — `src/core/feature_validator.py` (novo):**

Função `validate_pre_encoding(df, model_run_id, config)` chamada em `production_pipeline.py` **entre** `feature_engineering` e `apply_encoding`. Para cada feature pré-OHE esperada pelo modelo ativo (derivada do `feature_registry.json`):

- **Existência:** a coluna está no DataFrame
- **Tipo:** dtype bate com o esperado (bool para `nome_valido`, string categórica para `idade`, numérico para `nome_comprimento`)
- **Não-nulo:** taxa de valores não-nulos acima de um mínimo (ex: ≥ 80%)
- **Domínio:** para categóricas, valores observados ⊆ universo do treino; para numéricas, dentro de range plausível

Emite **1 log estruturado JSON por batch**, com `event=feature_validator`, severity proporcional às issues encontradas. Retorna um objeto `ValidationResult` que `production_pipeline.py` pode consumir para decidir continuar ou abortar o batch.

**Peça B — endpoint `GET /monitoring/feature-report` (novo em `api/app.py`):**

Consulta os logs do Cloud Run filtrando por `jsonPayload.event="feature_validator"` nas últimas N horas (default 24h, configurável por query param), agrega e retorna:

```json
{
  "window": {"start": "...", "end": "...", "hours": 24},
  "revision": "smart-ads-api-00357-lar",
  "total_batches": 288,
  "batches_with_issues": 3,
  "issues_by_feature": {
    "nome_valido": {"count": 3, "type": "missing_column", "example_batches": [...]},
    "idade": {"count": 1, "type": "new_category", "value": "prefiro_nao_dizer"}
  },
  "overall_status": "WARN"
}
```

Consultável por `curl`, por integração Slack, ou por job automatizado. Substitui a necessidade de parsear logs manualmente.

**Peça C — critérios de promoção formalizados (integrar em T1-9):**

Antes, "top-5 features não zeradas" era verificação manual. Com T1-11 implementado, vira consulta objetiva ao endpoint:

- `batches_with_issues == 0` E `overall_status in [OK, INFO]` por 24h → autorizado progredir 10% → 50%
- Qualquer `ERROR` em feature com importância ≥ 5% → bloqueia progressão

### Log format (contrato)

```json
{
  "event": "feature_validator",
  "timestamp": "2026-04-21T15:30:00Z",
  "model_run_id": "d51757f5041c44b7ab1a056fce8c3c35",
  "revision": "smart-ads-api-00357-lar",
  "batch_size": 47,
  "features_checked": 15,
  "issues": [
    {"feature": "nome_valido", "problem": "missing_column", "importance": 0.023},
    {"feature": "idade", "problem": "new_category", "value": "prefiro_nao_dizer", "importance": 0.012}
  ],
  "severity": "ERROR"
}
```

Filtro Cloud Run Logs Explorer:
- Ver só erros: `jsonPayload.event="feature_validator" AND jsonPayload.severity="ERROR"`
- Ver só uma feature: `jsonPayload.issues.feature="nome_valido"`

### Relação com outros itens

- **T1-10:** não substitui. Continua rodando dentro do encoding. T1-11 é a camada anterior que pega o problema mais cedo no pipeline.
- **T2-7 (validador pós-deploy automatizado):** passa a consumir `/monitoring/feature-report` como uma de suas entradas. T1-11 é pré-requisito de T2-7 real.
- **T1-9 (progressão de tráfego):** ganha critério objetivo para 10% → 50% via endpoint.

---

## Protocolo de progressão de tráfego [T1-9]

Cada deploy no Cloud Run segue a progressão abaixo. Cada etapa exige **tempo mínimo de observação E critérios objetivos cumpridos** — não avançar sem ambos.

### Etapas padrão

| De | Para | Tempo mínimo | Critérios objetivos |
|---|---|---|---|
| Build | 0% (`--no-traffic`) | — | Smoke test 5 leads: score retorna, decil atribuído, CAPI log sem 5xx |
| 0% | 10% | 1 hora | Taxa de 5xx na nova rev < 1%; top-5 features do modelo não zeradas nos smoke test leads |
| 10% | 50% | 24 horas | `funnel_metrics.capi_sent.send_rate` ≥ 90%; `meta_response.acceptance_rate` ≥ 85%; nenhum decil com 0 eventos CAPI (alerta via T1-2); `lead_quality_metrics.ultimas_24h.d10` não diverge de `ultimo_mes` em mais de 10pp; **`/monitoring/feature-report?hours=24` retorna `batches_with_issues=0` e `overall_status ∈ {OK, INFO}` (via T1-11)** |
| 50% | 100% | Caso a caso — ver abaixo | Caso a caso — ver abaixo |

### 50% → 100% — dois cenários

**(a) Unificação main → produção (caso atual, único):** aguardar o ciclo do DEV20 fechar (a partir de 17/05/2026). O critério aqui **é** ROAS, apesar da latência de ~21 dias, porque a janela de validação é única e a decisão é irreversível. Ver `AB_TEST.md` → "Estratégia de deploy — 50/50".

**(b) Deploys normais (retreinos mensais, patches, fixes):** 1 semana em 50% sem regressão operacional:
- `funnel_metrics.capi_sent.send_rate` estável (±5pp do baseline da revisão anterior)
- Taxa de 5xx não aumentou vs revisão anterior (comparar via Cloud Run metrics)
- Feature coverage não degradou (top-5 features do modelo não zeradas em > 5% dos leads)

ROAS **não é critério** para o caminho (b) — o ciclo de 15-21 dias do DevClub paralisaria deploys normais se fosse exigido.

### O que NÃO é critério de bloqueio

| Sinal | Por que não bloqueia |
|---|---|
| D10% absoluto alto (> 20-30%) | Constante histórica do projeto por feedback loop — não específico ao deploy |
| Features novas/não reconhecidas | Esperado em retreinos quando dados reais mudam; gera alerta mas não regressão |
| Alertas HIGH genéricos do orchestrator | Muitos HIGH são drift de dados externos (Meta API, Sheets) alheios ao deploy |
| Divergência absoluta entre revisões em métricas de negócio | Se a nova revisão for melhor (ex: ROAS maior), não bloqueia — a comparação é "não regrediu" |

### Rollback nomeado

**Antes de cada etapa de progressão**, documentar por escrito:
- **Qual revisão é o rollback?** nome exato (ex: `smart-ads-api-00269-jjn`)
- **Comando pronto para colar:**

```bash
gcloud run services update-traffic smart-ads-api --region us-central1 \
    --to-revisions <ROLLBACK_REVISION>=100
```

- **Tempo de reversão esperado:** < 2 minutos (Cloud Run propagação)
- **Onde observar o resultado do rollback:** logs do Cloud Run, monitoring endpoint, Railway

### Comandos de referência

```bash
# Ver split atual
gcloud run services describe smart-ads-api --region us-central1 \
    --project smart-ads-451319 --format="value(spec.traffic)"

# Progressão gradual (exemplo 0% → 10%)
gcloud run services update-traffic smart-ads-api --region us-central1 \
    --project smart-ads-451319 \
    --to-revisions NEW_REV=10,OLD_REV=90

# Rollback imediato (100% para a revisão antiga)
gcloud run services update-traffic smart-ads-api --region us-central1 \
    --project smart-ads-451319 \
    --to-revisions OLD_REV=100
```

### Observação sobre o feature coverage check

Até T1-10 ser implementado, o check de "top-5 features não zeradas" é responsabilidade **manual** — rodar uma consulta no banco pós-deploy para verificar que as features críticas (cartão de crédito, nome_comprimento, dia_semana, tem_computador) não estão zeradas em proporção anormal dos leads recentes.

Com T1-10, esse check roda automaticamente em `src/core/encoding.py` **antes** do fill com 0, emitindo alerta HIGH se > 5% dos leads têm alguma top-5 feature zerada.

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
| ~~Verificação de Meta token freshness~~ | ✅ Não aplicável | — | Token é System User vitalício, não expira. Item cancelado. |
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

### BLOCO 11 — Exceções silenciosas (T2-6)

Descoberto em 2026-04-21 durante investigação do T1-9. Pontos onde `except: pass`, `except Exception: pass` ou `except Exception: return {}` engolem erros sem log — se a operação falhar, ninguém fica sabendo.

| Arquivo | Linha | Padrão | Problema | Severidade |
|---|---|---|---|---|
| `src/monitoring/orchestrator.py` | 219-220 | `except Exception: pass` (db.rollback) | Transação abortada não avisa — estado inconsistente no banco | MÉDIA |
| `src/monitoring/orchestrator.py` | 315 | `except: continue` (gspread row parse) | Linhas puladas silenciosamente — funil de leads fica incompleto | MÉDIA |
| `api/app.py` | 1638-1640 | `except Exception: return {}` (Railway CAPI lookup) | FBP/FBC indisponíveis retornam dict vazio sem log — CAPI qualidade degradada | ALTA |
| `api/app.py` | 2263-2264 | `except Exception as _sfm_e: logger.warning` | Já tem log, OK mas warning baixo | BAIXA |
| `api/app.py` | 2596-2597 | `except Exception: logger.warning` (revenue_forecast) | Já tem log, OK | BAIXA |

**Ação (Tier 2):** converter os 3 primeiros para `except Exception as e: logger.error(f"[falha silenciosa CORRIGIDA] ...") + raise` ou `+ return default` com log. Os 2 últimos já estão adequados (têm logger).

**Por que Tier 2 e não Tier 1:** esses pontos não são bloqueadores ativos de produção — são pontos onde se algo der errado, ficamos cegos. Não impedem a unificação das branches.

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
| T1-9 | Protocolo de progressão de tráfego | `docs/` | Documentar e enforçar: 0%→10%(1h)→50%(confirmação)→100%(confirmação). **Especial:** no deploy de main unificado, parar em 50/50 durante o DEV20 para não expor o cliente a 100% antes de ROAS validado. Ver `AB_TEST.md` → "Estratégia de deploy — 50/50". |
| T1-10 | Feature coverage check (fail-loud) | `src/core/encoding.py` | Antes do fill com 0, verificar se top-N features (importância ≥ 1%) estão zeradas em mais de X% dos leads. Alerta HIGH se sim. Evita degradação silenciosa como `Medium_Linguagem_programacao`. |
| T1-11 | Validador pré-encoding de features | `src/core/feature_validator.py` (novo) + `production_pipeline.py` + `api/app.py` | Após feature_engineering e antes do apply_encoding, validar que cada feature pré-OHE esperada pelo modelo ativo existe no DataFrame com o tipo e valores dentro do domínio conhecido. Gera log estruturado JSON por batch + endpoint `/monitoring/feature-report` que agrega últimas N horas. Critério de promoção de tráfego formalizado nessa métrica. |
| T1-12 | Smoke de paridade pipeline-modelo no treino | `src/train_pipeline.py` (final) + opcionalmente `model/training_model.py` | **Motivação**: hoje T1-10/T1-11 protegem em runtime. Mas o modelo é registrado no MLflow sem nenhum check de "esse modelo, com o pipeline atual, scoreia sem perder feature". Bug silencioso possível: registrar modelo cujo `feature_names_in_` não casa exatamente com o que `apply_encoding` produz no main code → primeiro deploy descobre. **Implementação**: ao final do `train_pipeline` (após salvar modelo, antes de `--set-active`), rodar amostra de ~100 leads via `production_pipeline.run` com o modelo recém-treinado e verificar (a) `set(model.feature_names_in_) ⊆ set(produced_columns)`, (b) score sem NaN no intervalo [0,1], (c) decis cobrem D01–D10. Falha ⇒ aborta `--set-active` e log loud. Reusa lógica de `scripts/smoke_test_revision.py`. **Custo**: ~30s adicionais por treino. **Status**: backlog, sem prazo. Implementar em sessão futura quando próximo retreino for feito. |
| T1-13 | `audience_profile_drift` — drift de perfil de público vs Top 5 ROAS | `src/monitoring/data_quality.py` (novo método em `DataQualityMonitor`) + `configs/clients/devclub/reference_audience_profile.json` (snapshot) + `src/monitoring/orchestrator.py` (incluir no daily-check) | **🔴 PRIORIDADE MÁXIMA — registrado em PLANO_EXECUCAO.md (sequela 08/05/2026) e como erro em `registro_erros_ml.md` § V.4.** **Motivação**: o monitoring atual só compara distribuições contra `distribuicoes_esperadas.json` capturado no TREINO; não há check contra um perfil de audiência **winner** (Top 5 ROAS histórico). Drift de público no LF54 (08/05/2026) deveria ter sido detectado automaticamente — não foi. **Especificação**: (1) **Snapshot estático fixo** em `configs/clients/devclub/reference_audience_profile.json` agregando proporções do pool Top 5 ROAS = LF40, LF41, LF44, LF45, LF47 (n=39.771 leads, via Sheets). NÃO é rolling — atualização do Top 5 é manual e infrequente, anexa a "fechamento de lançamento". (2) **Categorias canônicas**: reaproveitar `UNIFICATION` de `scripts/perfil_audiencia.py` (idade, ocupação, faixa salarial unificadas; binárias diretas). (3) **Janela comparada**: ÚLTIMO DIA COMPLETO (BRT 00:00→23:59 anterior a hoje); NÃO o LF acumulado nem o dia parcial. (4) **Threshold**: alerta `audience_profile_drift` se `|Δpp| ≥ 5` em qualquer categoria canônica; **severity HIGH** se ≥ 5pp em alguma das 5 features socioeconômicas críticas (computador, gênero, ocupação CLT, programação, cartão); **severity MEDIUM** caso contrário. (5) **Pré-encoding e independente de modelo** — NÃO precisa `_iter_active_variants` (não é per-variant). (6) **Output**: alerta no `/monitoring/daily-check/railway` com `type=audience_profile_drift` + lista de categorias com Δpp + reference_pool_label. **Artefatos de apoio**: [scripts/perfil_audiencia.py](../scripts/perfil_audiencia.py) (lógica reaproveitável), [docs/perfil_audiencia_dev20.md](perfil_audiencia_dev20.md), [docs/perfil_audiencia_lf54.md](perfil_audiencia_lf54.md). **Esforço**: ~1h implementação + 1-2 ciclos de produção pra calibrar threshold. **Sem dependências bloqueadoras**. |

### Tier 2 — Qualidade de dados

| # | Item | Arquivo | Ação |
|---|---|---|---|
| T2-1 | Deduplicação no treino | `src/core/ingestion.py` | Implementar (hoje é `NotImplementedError`) |
| T2-2 | Log de N registros por etapa | `src/train_pipeline.py` | Logar antes/depois de cada filtro |
| T2-3 | Importance weighting grupo controle | `src/train_pipeline.py` | Implementar pesos maiores para leads de controle |
| T2-4 | Limite 10.000 em queries de validação | `src/validation/` | Remover ou alertar se hit |
| T2-5 | Filtro vendas não aprovadas | `src/validation/validate_ml_performance.py` | Confirmar ou adicionar filtro explícito |
| T2-6 | Eliminar exceções silenciosas críticas | múltiplos | Converter `except: pass` e `except Exception: return {}` em `logger.error` nos pontos listados abaixo |
| T2-7 | Validador pós-deploy automatizado | novo | Script que consulta `/monitoring/daily-check` após deploy e retorna go/no-go baseado nos critérios de T1-9 (send_rate, 5xx, divergência D10%). Elimina dependência de disciplina humana na progressão de tráfego. |
| T2-8 | Alerta de feature importance-alta com variance baixa em produção | `src/monitoring/orchestrator.py` | Para cada feature com importance ≥ 1% no modelo ativo, disparar alerta quando a variance em produção cair abaixo de um limiar (feature quase-constante: >95% de leads no mesmo valor, ou 100% zerada). Complementa T1-10 (coverage após encoding) cobrindo o caso "categoria sumiu do mix de tráfego, não do encoding". Gatilho para retreino por drift. |

### Tier 3 — Observabilidade

| # | Item | Arquivo | Ação |
|---|---|---|---|
| T3-1 | Progressão de canary documentada | `api/deploy_capi.sh` | Documentar fluxo 0% → 10% → 100% |
| T3-2 | Script de smoke test pós-deploy | novo | 5 leads → score → decil → CAPI log |
| T3-3 | Proteção de branch main | GitHub | Configurar require PR + aprovação |
| ~~T3-4~~ | ~~Verificação token Meta~~ | — | **CANCELADO 2026-04-23** — token é System User vitalício, não expira. Premissa original errada. |
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
| T1-2 CAPI decil 0 eventos | Concluído | | 2026-04-20 |
| T1-3 CAPI deduplicação | Concluído | | 2026-04-20 |
| T1-4 Timezone UTC | Concluído | | 2026-04-20 |
| T1-5 D10% alerta | Pulado | | Alertas só aparecem no endpoint — usuário consulta manualmente. Sem notificação proativa, o item não agrega valor além do que já existe. Reavaliar junto com T3-5 (Slack). |
| T1-6 app.py load_dotenv | Pulado | | Cloud Run injeta env vars antes do startup. capi_integration.py já tem guards explícitos (if not ACCESS_TOKEN → logger.error + return error). Falha ruidosa, não silenciosa. |
| T1-7 Parity audit encoding | Concluído | | 2026-04-21 — snapshot regenerado com dataset mar24, audit compara 67k linhas × 51 colunas, 0 divergências |
| T1-8 Branch autorizada + gate de processo | Concluído | | 2026-04-21 — Gate A (parity audit) automatizado no deploy_capi.sh. Checklist de Tier 1 adicionado como responsabilidade de processo. |
| T1-9 Protocolo progressão de tráfego | Concluído | | 2026-04-21 — tabela de critérios objetivos documentada, diferencia caso unificação (ROAS via DEV20) de deploys normais (send_rate / 5xx / feature coverage). |
| T1-10 Feature coverage check | Concluído | | 2026-04-21 — (1) check fail-loud em core/encoding.py antes do fill com 0 (ERROR ≥5%, WARNING ≥1%); (2) smoke_test_revision.py valida sobre leads reais do Railway; (3) Gate B automático no deploy_capi.sh bloqueia se encontrar ERROR; (4) deploy agora usa --tag para URL direta da revisão canary. |
| T1-11 Validador pré-encoding de features | Concluído | | 2026-04-23 — Peça A (src/core/feature_validator.py + schema JSON + integração em production_pipeline.py, 7/7 testes passam) em commit 361fc62; Peça B (endpoint GET /monitoring/feature-report em api/app.py com agregação de logs e recomendação de ação) em commit ba43d30; Peça C (critérios de promoção formalizados) já estava integrada em T1-9 antes. |
| T2-1 Deduplicação treino | Concluído | | 2026-04-23 — 3 funções implementadas em src/core/ingestion.py (filter_sheets, remove_duplicates_per_sheet, consolidate_datasets). Assinatura config-driven. 5 campos novos em IngestionConfig + configs/clients/devclub.yaml. data_processing/ingestion.py preservado (backward compat). T1-7 passa. |
| T2-2 Log por etapa | Concluído | | 2026-04-28 — função helper `_log_step_count` em train_pipeline.py (6 pontos) e production_pipeline.py (2 pontos). Formato `[step] N=X | Δ=±Y (±%)`. Commit 8b46645. |
| T2-3 Importance weighting | Concluído | | 2026-04-28 — `_compute_control_weights` em train_pipeline.py com inverso de frequência + alpha. Flags `--control-group-weights`, `--control-alpha`, `--train-ratio`. Sweep mostrou efeito interno marginal mas D9+D10 ML lift 6.88× CTRL na investigação externa. Commits c03d645 + f8dc4f7. |
| T2-4 Limite 10k queries | Concluído | | 2026-04-28 — limites subiram de 10k para 100k (generate_taxa_resposta_csv.py) e 200k (capi_events_counter.py); ambos com detecção de truncamento (log ERROR se response == limite). Commit a578408. |
| T2-5 Filtro vendas aprovadas | Concluído | | 2026-04-28 — confirmado já implementado: `include_canceled` (default False) em load_guru_sales (linha 684), load_tmb_sales (linha 872), load_hotpay_sales, load_guru_sales_from_api (linha 1225). validate_ml_performance.py:1387 só permite `include_canceled=True` em relatório de fechamento. Sem mudança de código. |
| T2-6 Eliminar exceções silenciosas | Concluído | | 2026-04-28 — orchestrator.py:219 (db.rollback) → logger.error com exc_info; orchestrator.py:315 (parse de linha gspread) → contador de skips com logger.warning agregado no fim do loop. app.py:1638-1640 confirmado: já tinha logger.error desde commit anterior. Restantes (linhas 2263, 2596) já tinham logger e foram classificados BAIXA no BLOCO 11. |
| T2-7 Validador pós-deploy automatizado | Concluído | | 2026-04-23 — scripts/progression_gate.py consome /monitoring/feature-report (T1-11) + /monitoring/daily-check/railway, consolida em PROMOTE/HOLD/ROLLBACK, executa gcloud run services update-traffic se --execute. Commit 42990b8. |
| T2-8 Alerta feature importance-alta variance baixa | Concluído | | 2026-04-29 — verificação confirma que `check_distribution_drift` (existente em `monitoring/data_quality.py`) já detecta o caso operacional do `Medium_Linguagem_programacao` (treino 14,5% → produção 0% gera drift HIGH). Cobertura sobreposta. Único ganho marginal seria ordenar a saída do alerta por feature_importance para destacar os casos high-impact primeiro — fica como melhoria opcional de UX, não como item separado. |
| T3-1 Canary documentado | Concluído | | 2026-04-29 — bloco de instrução inline em `deploy_capi.sh` (após Gate B do smoke test) com os 3 comandos `update-traffic` para 10% → 50% → 100% e referência aos critérios objetivos de T1-9. Substitui o print único "Para promover: ... =100" que ia direto pra 100%. |
| T3-2 Smoke test pós-deploy | Concluído | | Já implementado em 2026-04-21 como Gate B do T1-10: `scripts/smoke_test_revision.py` integrado em `deploy_capi.sh:542-556` aborta o deploy automaticamente se features críticas estiverem ausentes. Cobre o requisito original (5 leads → score → decil → CAPI log) com leads reais do Railway. |
| T3-3 Branch protection | Adiável | | 2026-04-29 — branch protection e rulesets do GitHub não disponíveis em repo privado de conta Free (HTTP 403 "Upgrade to GitHub Pro"). Como há um único colaborador (`ramonfilho`, admin), o risco real (`push --force` ou delete acidental) é baixo. Reativar o item quando: (a) plano subir para Pro/Team, (b) repo virar público, ou (c) um segundo colaborador entrar. |
| T3-4 Token Meta alerta | **CANCELADO** | | 2026-04-23 — token é System User vitalício, não expira |
| T3-5 Relatório consolidado | Concluído | | 2026-04-29 — `_generate_operational_routines_summary()` adicionado em `monitoring/orchestrator.py`. Bloco "Rotinas operacionais (T3-5)" no log do `run_daily_check` mostra: run_id ativo, status A/B test, Cloud Run revision/service, último scoring + lag, e contadores 24h (recebidos / scoreados / CAPI enviados). Saída também inclusa no dict de retorno. |
| T3-6 MODEL_PATH validação | Concluído | | 2026-04-29 — `validate_model_loaded` em novo `src/core/startup_checks.py` (commit a1213f9). Verifica `predictor.model is not None` e `predictor.feature_names` populado após `load_model()`. Falha ⇒ `RuntimeError` no startup, API não aceita tráfego. Integrado em `production_pipeline.LeadScoringPipeline.__init__`. |
| T3-7 Reconciliação run_id | Concluído | | 2026-04-29 — mesma função do T3-6. Lê `mlflow_run_id` direto do `configs/active_models/{client}.yaml` como fonte independente e compara com `predictor.mlflow_run_id` em runtime. Detecta cenário "imagem Docker baked com run_id A mas YAML aponta para B". Mesmo check para variantes A/B. |
