# Índice de Documentação — Bring Data V2

**Atualizado:** 2026-04-16
**Propósito:** mapa de todos os documentos da pasta `docs/`, seus papéis, status e como se relacionam.

---

## Prioridade global de execução (16/04/2026)

| Cor | Item | Referência |
|---|---|---|
| 🔴 | A/B patch no rollback worktree (prazo 27/04) | `PLANO_EXECUCAO.md` Fase 1 |
| 🔴 | Safeguards Tier 1 — 7 itens bloqueadores (antes da unificação) | `PLANO_SAFEGUARD.md` Tier 1 |
| 🟡 | Decisão de promoção A/B (após 27/04) | `AB_TEST.md` seção "Critério de promoção" |
| 🟡 | Unificação de branches edf23e9 → main | `PLANO_EXECUCAO.md` Fase 3 |
| 🟡 | Importance weighting — prazo 15/04 vencido, próximo ciclo | `PLANO_REFACTOR_MLOPS.md` bloco URGENTE |
| 🟢 | Safeguards Tier 2+3 — 12 itens (após unificação) | `PLANO_SAFEGUARD.md` Tier 2+3 |
| 🟢 | Retreino + novo ciclo A/B | `PLANO_EXECUCAO.md` Fase 5 |
| 🟢 | Pré-condições para Cliente B (DT-8, DT-9, DT-10) | `PLANO_EXECUCAO.md` Pendências do Refactor |
| ⚪ | Onboarding Cliente B | aguardando dados do cliente |
| ⚪ | Token Meta permanente (system user) | aguardando acesso ao Business Manager |

---

## Visão geral da estrutura

A documentação se divide em cinco camadas:

```
ESTRATÉGIA          → onde o projeto vai (visão de longo prazo)
PLANEJAMENTO        → o que está sendo feito agora e em que ordem
OPERACIONAL         → como executar tarefas específicas
REFERÊNCIA TÉCNICA  → como o sistema funciona hoje
HISTÓRICO           → decisões passadas, migrações concluídas
```

---

## Camada 1 — Estratégia

### `bring_data_02_execução.md`
**Papel:** visão de negócio, roadmap de escala (Fases 1/2/3 do produto), moat competitivo, backlog de features. Também contém o script de venda e o checklist de onboarding comercial.
**Status:** ativo. Renomeado de `adsmarter_02_execução.md` para `bring_data_02_execução.md` conforme rebrand.
**Relação:** é o "porquê" de tudo. O plano de refactor e o roadmap MLOps são consequências das decisões aqui.
**Ação sugerida:** revisar após Cliente B onboarding.

### `swot_bringdata.md`
**Papel:** análise SWOT completa com dados de mercado, forças, fraquezas, oportunidades e ameaças. Inclui síntese estratégica e prioridades.
**Status:** ativo. Criado em março/2026.
**Relação:** complementa `bring_data_02_execução.md` com profundidade competitiva. Referencia W1 (feedback loop) e W2 (token Meta) como riscos críticos.

### `bring_data_produto.md`
**Papel:** script de reunião comercial — estrutura da conversa de vendas, quebra de objeções, fechamento.
**Status:** ativo.
**Relação:** instrumento de execução comercial. Derivado das forças documentadas no SWOT.

---

## Camada 2 — Planejamento

### `PLANO_EXECUCAO.md`
**Papel:** documento mestre de execução para Abril–Junho 2026. Define os 3 trabalhos em andamento (A/B patch, Safeguards, Unificação de branches) com sequência de dependências explícita e datas-alvo.
**Status:** ativo. Criado em 16/04/2026.
**Relação:** orquestra `AB_TEST.md`, `PLANO_SAFEGUARD.md` e `PLANO_REFACTOR_MLOPS.md` numa sequência única. É a referência de "o que fazer agora e em que ordem".

### `PLANO_REFACTOR_MLOPS.md`
**Papel:** plano de execução do refactor MLOps (Fases 1–5). Decisões arquiteturais, o que foi mudado, por quê, e o que falta. Contém varredura completa de 153 hardcodes mapeados.
**Status:** ⚠️ parcialmente completo.
- Fases 1, 2, 3a, 3c → ✅ concluídas
- Fase 3b (Cliente B) → bloqueada por dados do cliente
- Fase 4 (EDA Generator) → após Cliente B estável
- Item 19 (deploy do refactor) → ✅ **CONCLUÍDO em 24/03/2026** (ver `CHECKLIST_DEPLOY_REFACTOR.md`)
- Seção 12 ("Caminho para Nível 3") → substituída pela referência ao `ROADMAP_MLOPS_MATURIDADE.md`
- Ação urgente de importance weighting (prazo 15/04/2026) → pendente
**Relação:** é o "como chegamos aqui". Referencia o checklist de deploy e o roadmap de maturidade.

### `PLANO_SAFEGUARD.md`
**Papel:** audit completo de infraestrutura, gap matrix com 9 blocos (encoding, CAPI, pipeline, infra, deploy, timezone, monitoramento, grupo controle, validação) e tabela de status por tier de prioridade (Tier 1/2/3 — 19 itens no total).
**Status:** ativo. Criado em 16/04/2026. Todos os 19 itens pendentes de implementação.
**Relação:** filho do `PLANO_EXECUCAO.md` (Fases 2 e 4). Referencia `Erros_cometidos.md` como motivação. Skills `/safeguard` e `/investigate` consomem esse documento.

### `arquivo/CHECKLIST_DEPLOY_REFACTOR.md`
**Papel:** runbook operacional de uso único para o merge e deploy da branch `refactor/mlops-core`.
**Status:** ✅ **ARQUIVADO.** Concluído em 24/03/2026. Todos os 15 itens executados. Revisão `00254-dh5` em produção com 100% de tráfego.
**Relação:** filho direto do `PLANO_REFACTOR_MLOPS.md` (item 19). Mantido como registro histórico do deploy.

### `CHECKLIST_ONBOARDING_NEW_CLIENT.md`
**Papel:** runbook para onboarding de novo cliente — criar YAML, inspecionar dados brutos, treinar modelo, verificar MLflow, deploy.
**Status:** ativo. Pronto para uso quando Cliente B chegar.
**Relação:** filho do `PLANO_REFACTOR_MLOPS.md` Fase 3b. Depende de `configs/templates/client_template.yaml`.

### `ROADMAP_MLOPS_MATURIDADE.md`
**Papel:** guia de longo prazo mapeando os níveis de maturidade MLOps para o contexto do Bring Data. 18 itens organizados em fases (imediata → pós-deploy → Cliente B → 2–4 clientes → 5+ clientes), cada um com condição de desbloqueio explícita.
**Status:** ✅ **existe** (criado). Itens 1–5 da fase imediata: itens 1–5 concluídos (deploy refactor), itens 6–9 pendentes.
**Relação:** é o "para onde vamos". Referenciado pela seção 12 do plano de refactor e pelo `PLANO_EXECUCAO.md`.

---

---

## Camada 3 — Operacional (runbooks)

### `acesso_sql.md`
**Papel:** como conectar ao PostgreSQL local e em produção (Cloud SQL Proxy, Railway).
**Status:** ativo, provavelmente atualizado.

### `acesso_sheets.md`
**Papel:** como acessar Google Sheets via ADC (Application Default Credentials).
**Status:** ativo.

### `MLFLOW.md`
**Papel:** acesso ao MLflow — URLs, credenciais de tracking, como criar experimentos.
**Status:** ativo. Complementa `MIGRACAO_MLFLOW_GCS.md` (histórico).

### `monitoring-api.md`
**Papel:** documentação dos endpoints de monitoring para o front-end.
**Status:** ativo enquanto a API de monitoring estiver sendo consumida externamente.

### `revenue_forecast.md`
**Papel:** documentação completa da feature de previsão de faturamento por lançamento — metodologia, parâmetros calibrados, backtest, estrutura do response e limitações conhecidas.
**Status:** ativo. Implementado em abril/2026. MAE 2,6% validado em LF42–LF47.

### `instrucoes_dev_frontend_capi.md` e `instrucao_frontend_fbp_fbc.txt`
**Papel:** instruções para o dev front-end sobre CAPI e captura de FBP/FBC.
**Status:** ativo (entregue a terceiros).

---

---

## Camada 4 — Referência técnica (como o sistema funciona hoje)

### `ARQUITETURA_SISTEMA_COMPLETA.md`
**Papel:** visão geral de toda a arquitetura — pipelines, componentes, fluxo de dados, decisões de design.
**Status:** ⚠️ **parcialmente desatualizado**. Última atualização: 2026-03-24 (pós-deploy do refactor). Reflete `src/core/` e multi-cliente, mas não reflete o estado atual das branches (rollback em produção, canary ativo, A/B test) — foi atualizado antes do rollback de 13/04.
**Relação:** é o documento de referência central (lido no início de toda sessão). Para o estado atual de branches e testes A/B, consultar `PLANO_EXECUCAO.md` e `AB_TEST.md`.
**Ação sugerida:** atualizar para refletir que o rollback edf23e9 está em produção e o A/B test está ativo via canary.

### `AB_TEST.md`
**Papel:** documentação operacional do teste A/B champion/challenger — arquitetura de roteamento, configuração, teste atual (jan30 vs mar24), critério de promoção, como ler resultados, problema DT-12, janela de dados válidos, próximos passos (patch no rollback).
**Status:** ativo. Criado em 2026-04-09. Atualizado com análise estatística de LF51 e janela de dados válidos.

### `SISTEMA_VALIDACAO_ML.md`
**Papel:** documenta o sistema de validação — como `validate_ml_performance.py` funciona, métricas calculadas.
**Status:** ativo, atualizado em 2026-03-17.

### `analise_valor_ml_devclub.md`
**Papel:** análise de valor real do ML para DevClub (LF40→LF46), responde se o sistema gera ROAS genuíno.
**Status:** snapshot — válido para o período analisado, não atualizado automaticamente.

### `INVESTIGACAO_BAIXO_DESEMPENHO.md`
**Papel:** investigação completa da queda do D10 de ~42% (P1) para ~30% (P3). Documenta hipóteses testadas, causas confirmadas (mudança LQHQ→LQ em 10/03, crash P2 por TMB All + encoding quebrado), análise do gap residual e rollback executado em 13/04/2026.
**Status:** ativo. Última atualização: 2026-04-13. Investigação encerrada — todas as hipóteses testadas, nenhuma pendente de verificação.
**Relação:** documenta o contexto que motivou o rollback e o A/B test atual. Referenciado por `AB_TEST.md` e `PLANO_EXECUCAO.md`.

### `Erros_cometidos.md`
**Papel:** registro honesto de 13 erros com impacto real — encoding, deploy sem canary, feedback loop, timezone, valor CAPI incorreto, relatório com contagens erradas. Cada erro tem causa raiz e lição.
**Status:** ativo. Documento vivo — adicionar novos erros conforme ocorrem.
**Relação:** é a motivação de cada item do `PLANO_SAFEGUARD.md`. Leitura obrigatória antes de qualquer mudança de infraestrutura.

### `modelo_producao_devclub_15mar2026_interno.txt`
**Papel:** documentação interna do modelo em produção (run `2a98e51c`, 59 features, AUC 0.745).
**Status:** snapshot histórico — o modelo ativo em produção hoje é o jan30 (`d51757f5`), não o `2a98e51c`. Complementa `memory/project_active_model.md`.

---

## Camada 5 — Histórico (decisões passadas, concluídas)

### `DIVERGENCIAS_TREINO_PRODUCAO.md`
**Papel:** documentou as divergências entre treino e produção em março/2026 — motivação central do refactor.
**Status:** ✅ resolvido pelo refactor (deploy 24/03/2026). Pode ser arquivado.

### `MIGRACAO_MLFLOW_GCS.md`
**Papel:** plano de migração do MLflow de SQLite para Cloud SQL.
**Status:** ✅ concluído (migrado em 17/03/2026, 50 runs no Cloud SQL). O documento interno diz "Planejado — pendente execução" mas a migração está feita.
**Ação sugerida:** atualizar o cabeçalho do documento para "Concluído" ou arquivar.

### `unificacao-mlflow.md`
**Papel:** plano de unificação do feature registry no MLflow.
**Status:** provavelmente histórico — verificar se ainda tem ações pendentes.

### `migracao_sheets_postgresql.md`
**Papel:** migração de Sheets para PostgreSQL (Railway).
**Status:** histórico — arquitetura já estabilizada.

### `purchase_events_status.md`
**Papel:** status de implementação dos eventos de compra CAPI.
**Status:** provavelmente histórico.

---

## Arquivo fora de lugar

### `pagina2_codigo_modificado.js`
**Papel:** snippet de código JavaScript — provavelmente instrução para dev front-end.
**Status:** não pertence a `docs/`. Mover para `docs/frontend/` ou entregar e deletar.

---

## Como os documentos se relacionam

```
bring_data_02_execução.md            (visão de negócio — o porquê)
swot_bringdata.md                    (análise competitiva e riscos)
bring_data_produto.md                (script comercial)
        ↓
ARQUITETURA_SISTEMA_COMPLETA.md      (como o sistema funciona — o quê) ← atualizar para estado atual
        ↓
PLANO_REFACTOR_MLOPS.md              (o que foi mudado e por quê — histórico + hardcodes)
        ├── CHECKLIST_DEPLOY_REFACTOR.md   (deploy refactor — CONCLUÍDO 24/03)
        └── ROADMAP_MLOPS_MATURIDADE.md    (para onde vamos — longo prazo)
        ↓
PLANO_EXECUCAO.md                    (o que fazer agora — Abr/Mai/Jun 2026) ← LEITURA DIÁRIA
        ├── AB_TEST.md                     (A/B champion/challenger — operacional)
        │       └── INVESTIGACAO_BAIXO_DESEMPENHO.md  (contexto do rollback e P1→P3)
        └── PLANO_SAFEGUARD.md             (19 itens de integridade — Tier 1/2/3)
                └── Erros_cometidos.md     (motivação de cada safeguard)

Onboarding:
  CHECKLIST_ONBOARDING_NEW_CLIENT.md   (quando Cliente B chegar)

Análises e validações:
  analise_valor_ml_devclub.md          (ROAS LF40→LF48 — snapshot)
  analise_perfil_leads_devclub.md      (perfil P1→P3 — snapshot)
  SISTEMA_VALIDACAO_ML.md              (como validate_ml_performance.py funciona)
  revenue_forecast.md                  (previsão de faturamento — MAE 2,6%)

Runbooks (como fazer tarefas específicas):
  acesso_sql.md / acesso_sheets.md / MLFLOW.md / monitoring-api.md

Histórico (contexto de decisões passadas — podem ser arquivados):
  DIVERGENCIAS_TREINO_PRODUCAO.md / MIGRACAO_MLFLOW_GCS.md / unificacao-mlflow.md
  migracao_sheets_postgresql.md / purchase_events_status.md
```

---

## Resumo das ações pendentes na documentação

| Documento | Ação | Quando |
|---|---|---|
| `CHECKLIST_DEPLOY_REFACTOR.md` | ✅ Concluído em 24/03/2026 — pode ser arquivado | Qualquer momento |
| `ROADMAP_MLOPS_MATURIDADE.md` | ✅ Existe — itens 1–5 concluídos, 6–18 pendentes | — |
| `ARQUITETURA_SISTEMA_COMPLETA.md` | Atualizar: refletir rollback edf23e9 em produção + A/B test ativo | Antes da próxima sessão de dev |
| `PLANO_REFACTOR_MLOPS.md` | Marcar item 19 como concluído; nota sobre prazo 15/04 de importance weighting | Qualquer momento |
| `MIGRACAO_MLFLOW_GCS.md` | Marcar como concluído ou arquivar | Qualquer momento |
| `DIVERGENCIAS_TREINO_PRODUCAO.md` | Arquivar (resolvido pelo refactor) | Qualquer momento |
| `pagina2_codigo_modificado.js` | Mover para `docs/frontend/` ou deletar | Qualquer momento |
| `modelo_producao_devclub_15mar2026_interno.txt` | Adicionar nota: modelo ativo hoje é jan30 (`d51757f5`), não `2a98e51c` | Qualquer momento |

---

## Skills disponíveis

Skills invocáveis via `/skill` para tarefas recorrentes:

| Skill | Quando usar | Documenta-ção |
|---|---|---|
| `/investigate` | Investigar por que um lançamento foi ruim — números históricos, causas do baixo ROAS, D10% anormal | `INVESTIGACAO_BAIXO_DESEMPENHO.md` |
| `/investigate-ab` | Verificar se o teste A/B está tecnicamente válido — roteamento correto, eventos chegando, janela limpa | `AB_TEST.md` |
| `/safeguard` | Auditoria completa de integridade — encoding, CAPI, deploy, timezone, monitoramento | `PLANO_SAFEGUARD.md` |
| `/plan-integrator` | Leitura completa de todos os docs + reconciliação de status + relatório integrado | Este índice |
