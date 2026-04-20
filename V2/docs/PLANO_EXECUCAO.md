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

### Objetivo
Trazer o que é funcional e correto do edf23e9 (05/03/2026, em produção) para a branch main, eliminando a discrepância de encoding/scoring que faz os dois produzirem resultados diferentes.

### Protocolo de merge por arquivo

Para cada arquivo trazido do edf23e9 para main:

1. **Rodar parity audit antes:** `python -m pytest tests/parity_audit.py -v`
2. **Aplicar a mudança**
3. **Rodar parity audit depois:** mesmo comando
4. **Se output diferente:** a mudança introduziu divergência — investigar antes de continuar
5. **Se output igual:** seguro prosseguir

### Arquivos prioritários a inspecionar (divergência conhecida)

| Arquivo | Divergência confirmada | Resolução esperada |
|---|---|---|
| `src/features/encoding.py` | `binary_top3` (edf23e9) vs OHE (main) para Medium | Manter `binary_top3` — edf23e9 correto |
| `src/production_pipeline.py` | Ordinal encoding built-in (edf23e9) vs `encoding_overrides` yaml (main) | Avaliar qual é mais sustentável para multi-cliente |
| `configs/active_model.yaml` | Sem A/B test (edf23e9) vs com A/B test (main) | main correto — manter estrutura main |

### Resultado esperado
Após a unificação: main em produção, edf23e9 aposentado, uma única fonte de verdade.

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

