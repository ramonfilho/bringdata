# Índice de Documentação — Bring Data V2

**Atualizado:** 2026-03-22
**Propósito:** mapa de todos os documentos da pasta `docs/`, seus papéis, status e como se relacionam.

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

### `adsmarter_02_execução.md`
**Papel:** visão de negócio, roadmap de escala (Fases 1/2/3 do produto), moat competitivo, backlog de features.
**Status:** ativo, mas desatualizado — escrito antes do segundo cliente ser confirmado.
**Relação:** é o "porquê" de tudo. O plano de refactor e o roadmap MLOps são consequências das decisões aqui.
**Ação sugerida:** revisar após Cliente B onboarding.

---

## Camada 2 — Planejamento

### `PLANO_REFACTOR_MLOPS.md`
**Papel:** plano de execução do refactor MLOps (Fases 1–5). Decisões arquiteturais, o que foi mudado, por quê, e o que falta.
**Status:** ⚠️ parcialmente completo.
- Fases 1, 2, 3a, 3c → ✅ concluídas
- Fase 3b (Cliente B) → bloqueada por dados do cliente
- Fase 4 (EDA Generator) → após Cliente B estável
- Item 19 (deploy do refactor) → pendente execução do `CHECKLIST_DEPLOY_REFACTOR.md`
- Seção 12 ("Caminho para Nível 3") → rasa, será substituída pela referência ao `ROADMAP_MLOPS_MATURIDADE.md`
**Relação:** é o "como chegamos aqui". Referencia o checklist de deploy e o roadmap de maturidade.
**Ação sugerida:** atualizar seção 12 para referenciar o novo roadmap; fechar item 19 após deploy.

### `CHECKLIST_DEPLOY_REFACTOR.md`
**Papel:** runbook operacional de uso único para o merge e deploy da branch `refactor/mlops-core`.
**Status:** ⏳ pendente execução (próximo passo imediato).
**Relação:** filho direto do `PLANO_REFACTOR_MLOPS.md` (item 19). Após execução, pode ser arquivado.
**Ação sugerida:** executar, preencher a tabela de status, arquivar após deploy bem-sucedido.

### `ROADMAP_MLOPS_MATURIDADE.md` *(a criar)*
**Papel:** guia de longo prazo mapeando os níveis de maturidade MLOps (Google Levels 0→2) para o contexto do Bring Data. Define o que cada nível significa em termos concretos de stack, com condições de negócio para avançar — não um compromisso de execução imediata.
**Status:** ⏳ a criar.
**Relação:** é o "para onde vamos". Referenciado pela seção 12 do plano de refactor e pelo `adsmarter_02_execução.md` (FASE 3: MLOps completo). Inclui a visão de stack GCP (Pub/Sub, Dataflow, Vertex AI, BigQuery Feature Store) com condições explícitas de quando cada peça entra.

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

## Camada 4 — Referência técnica (como o sistema funciona hoje)

### `ARQUITETURA_SISTEMA_COMPLETA.md`
**Papel:** visão geral de toda a arquitetura — pipelines, componentes, fluxo de dados, decisões de design.
**Status:** ⚠️ **desatualizado**. Última atualização: 2026-02-20, antes do refactor. Não reflete `src/core/`, `ClientConfig`, `configs/clients/`, multi-cliente.
**Relação:** era o documento de referência central (lido no início de toda sessão). Após o refactor, o `PLANO_REFACTOR_MLOPS.md` descreve melhor o estado atual.
**Ação sugerida:** duas opções:
  - **A (recomendada):** atualizar para refletir a arquitetura pós-refactor, mantendo o papel de referência central.
  - **B:** arquivar e deixar o refactor plan + código como fonte de verdade. Mais simples, mas perde a visão holística.

### `SISTEMA_VALIDACAO_ML.md`
**Papel:** documenta o sistema de validação — como `validate_ml_performance.py` funciona, métricas calculadas.
**Status:** ativo, atualizado em 2026-03-17.

### `analise_valor_ml_devclub.md`
**Papel:** análise de valor real do ML para DevClub (LF40→LF46), responde se o sistema gera ROAS genuíno.
**Status:** snapshot — válido para o período analisado, não atualizado automaticamente.

### `modelo_producao_devclub_15mar2026_interno.txt`
**Papel:** documentação interna do modelo em produção (run `2a98e51c`, 59 features, AUC 0.745).
**Status:** ativo enquanto o modelo não for retreinado. Complementa `memory/project_active_model.md`.

---

## Camada 5 — Histórico (decisões passadas, concluídas)

### `DIVERGENCIAS_TREINO_PRODUCAO.md`
**Papel:** documentou as divergências entre treino e produção em março/2026 — motivação central do refactor.
**Status:** ✅ resolvido pelo refactor. Pode ser arquivado.

### `MIGRACAO_MLFLOW_GCS.md`
**Papel:** plano de migração do MLflow de SQLite para Cloud SQL.
**Status:** ✅ concluído (migrado em 17/03/2026, 50 runs no Cloud SQL). Documento diz "pendente" mas está feito.
**Ação sugerida:** atualizar status ou arquivar.

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
adsmarter_02_execução.md          (visão de negócio — o porquê)
        ↓
ARQUITETURA_SISTEMA_COMPLETA.md   (como o sistema funciona — o quê) ← DESATUALIZADO
        ↓
PLANO_REFACTOR_MLOPS.md           (o que foi mudado e por quê — o como)
        ├── CHECKLIST_DEPLOY_REFACTOR.md   (deploy deste refactor — uso único)
        └── ROADMAP_MLOPS_MATURIDADE.md    (para onde vamos — longo prazo) ← A CRIAR

Runbooks (como fazer tarefas específicas):
  acesso_sql.md / acesso_sheets.md / MLFLOW.md / monitoring-api.md

Histórico (contexto de decisões passadas):
  DIVERGENCIAS_TREINO_PRODUCAO.md / MIGRACAO_MLFLOW_GCS.md / unificacao-mlflow.md
  migracao_sheets_postgresql.md / purchase_events_status.md
```

---

## Resumo das ações pendentes na documentação

| Documento | Ação | Quando |
|---|---|---|
| `CHECKLIST_DEPLOY_REFACTOR.md` | Executar, preencher status, arquivar | Antes do merge do PR |
| `ROADMAP_MLOPS_MATURIDADE.md` | Criar | Esta sessão |
| `ARQUITETURA_SISTEMA_COMPLETA.md` | Decisão: atualizar (opção A) ou arquivar (opção B) | Após deploy do refactor |
| `PLANO_REFACTOR_MLOPS.md` | Atualizar seção 12 para referenciar o roadmap; fechar item 19 após deploy | Esta sessão + pós-deploy |
| `MIGRACAO_MLFLOW_GCS.md` | Marcar como concluído ou arquivar | Qualquer momento |
| `DIVERGENCIAS_TREINO_PRODUCAO.md` | Arquivar (resolvido pelo refactor) | Qualquer momento |
| `pagina2_codigo_modificado.js` | Mover para `docs/frontend/` ou deletar | Qualquer momento |
