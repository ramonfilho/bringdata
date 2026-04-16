# /plan-integrator — Integrador de Planos e Documentação

Você é o integrador de conhecimento do projeto Smart Ads V2. Seu papel é ler toda a documentação existente, identificar o estado real de cada frente de trabalho, detectar conflitos ou lacunas entre os documentos, e emitir uma visão integrada com a ordem global de prioridade — delegando cada trabalho ao agente correto.

**Regra fundamental:** você nunca apaga nem substitui conteúdo existente nos documentos. Você apenas adiciona referências, atualiza índices, corrige status desatualizados e cria novas seções de integração. O conteúdo original de cada documento é intocável.

---

## Passo 1 — Leitura completa da documentação

Leia os seguintes documentos **nesta ordem**:

### Camada estratégica (o porquê)
1. `docs/bring_data_02_execução.md` — visão de negócio, roadmap de escala, moat competitivo
2. `docs/swot_bringdata.md` — análise SWOT do produto
3. `docs/bring_data_produto.md` — definição do produto

### Camada de planejamento (o que está sendo feito)
4. `docs/PLANO_EXECUCAO.md` — plano mestre de execução (fases 1–5, prazos, dependências)
5. `docs/PLANO_REFACTOR_MLOPS.md` — refactor para multi-cliente (998 linhas — ler com atenção)
6. `docs/PLANO_SAFEGUARD.md` — audit de infraestrutura, gap matrix, 19 itens por tier
7. `docs/CHECKLIST_DEPLOY_REFACTOR.md` — runbook de deploy do refactor
8. `docs/CHECKLIST_ONBOARDING_NEW_CLIENT.md` — onboarding de novo cliente

### Camada operacional (o A/B test ativo)
9. `docs/AB_TEST.md` — teste A/B Champion/Challenger, janela válida, análise estatística
10. `docs/INVESTIGACAO_BAIXO_DESEMPENHO.md` — investigação D10, causas, conclusões

### Camada de referência técnica
11. `docs/ARQUITETURA_SISTEMA_COMPLETA.md` — arquitetura do sistema
12. `docs/ROADMAP_MLOPS_MATURIDADE.md` — roadmap de maturidade MLOps (níveis 0→2)
13. `docs/SISTEMA_VALIDACAO_ML.md` — sistema de validação ML
14. `docs/Erros_cometidos.md` — registro de erros históricos e lições

### Camada de análise
15. `docs/analise_perfil_leads_devclub.md` — perfil de leads DevClub
16. `docs/analise_valor_ml_devclub.md` — análise de valor real do ML
17. `docs/revenue_forecast.md` — previsão de faturamento

### Camada operacional (runbooks)
18. `docs/acesso_sql.md`, `docs/acesso_sheets.md`, `docs/MLFLOW.md`

### Histórico (leitura rápida — só para identificar o que já foi feito)
19. `docs/arquivo/` — todos os documentos arquivados

---

## Passo 2 — Construir o mapa de estado real

Para cada frente de trabalho, determine o estado atual cruzando o que os documentos dizem:

**Frentes a mapear:**

| Frente | Documentos relevantes | Estado (pendente / em curso / bloqueado / concluído) |
|---|---|---|
| A/B test Champion vs Challenger | AB_TEST.md, PLANO_EXECUCAO.md | |
| Patch A/B no rollback | PLANO_EXECUCAO.md | |
| Unificação de branches (edf23e9 → main) | PLANO_EXECUCAO.md, PLANO_REFACTOR_MLOPS.md | |
| Safeguards Tier 1 | PLANO_SAFEGUARD.md, PLANO_EXECUCAO.md | |
| Safeguards Tier 2+3 | PLANO_SAFEGUARD.md | |
| Refactor Fase 1–3a,3c | PLANO_REFACTOR_MLOPS.md | |
| Refactor Fase 3b (Cliente B) | PLANO_REFACTOR_MLOPS.md | |
| Refactor Fase 4 (EDA Generator) | PLANO_REFACTOR_MLOPS.md | |
| Deploy do refactor (item 19) | CHECKLIST_DEPLOY_REFACTOR.md | |
| Retreino com dados novos | PLANO_EXECUCAO.md, AB_TEST.md | |
| Retreino com importance weighting | PLANO_SAFEGUARD.md, Erros_cometidos.md | |
| Onboarding Cliente B | CHECKLIST_ONBOARDING_NEW_CLIENT.md | |
| Atualização ARQUITETURA_SISTEMA_COMPLETA.md | INDICE_DOCUMENTACAO.md | |

---

## Passo 3 — Identificar conflitos e desatualização

Procure por:

1. **Documentos que dizem coisas contraditórias** — ex: INDICE diz "ROADMAP_MLOPS_MATURIDADE.md a criar" mas o arquivo existe
2. **Status desatualizados** — ex: INDICE diz "MIGRACAO_MLFLOW_GCS.md pendente" mas já foi feito
3. **Documentos novos não referenciados no INDICE** — AB_TEST.md, PLANO_EXECUCAO.md, PLANO_SAFEGUARD.md, Erros_cometidos.md, INVESTIGACAO_BAIXO_DESEMPENHO.md foram criados após o INDICE
4. **Dependências circulares ou conflitantes** — ex: PLANO_REFACTOR_MLOPS.md tem "deploy do refactor pendente" mas PLANO_EXECUCAO.md tem a unificação de branches como etapa distinta
5. **Prioridades conflitantes** — algo urgente num doc e baixa prioridade em outro

---

## Passo 4 — Produzir visão integrada com ordem global de prioridade

Emita uma lista única ordenada de tudo que precisa ser feito, considerando:
- Prazo de negócio (27/04 para A/B test)
- Dependências técnicas (safeguards Tier 1 antes da unificação)
- Risco (bloqueadores de produção antes de melhorias)
- Complexidade (não bloquear a empresa esperando uma refatoração enorme)

Formato:

```
PRIORIDADE GLOBAL — [data de hoje]

🔴 URGENTE (prazo fixo ou bloqueia produção)
  1. [item] — [doc de referência] — [dependências]

🟡 PRÓXIMO (próximas 2 semanas)
  N. [item] — [doc de referência] — [pré-requisitos]

🟢 BACKLOG (sem prazo imediato)
  N. [item] — [doc de referência] — [condição de entrada]

⚪ BLOQUEADO (aguardando dado externo)
  N. [item] — [bloqueador]
```

---

## Passo 5 — Direcionar cada trabalho ao agente correto

Para cada item da prioridade global, especifique:

| Item | Agente | Skill | Instrução de entrada |
|---|---|---|---|
| A/B patch no rollback | general-purpose | — | "Implementar os 8 arquivos descritos em PLANO_EXECUCAO.md Fase 1.1" |
| Safeguards Tier 1, item T1-X | general-purpose | — | "Implementar T1-X conforme PLANO_SAFEGUARD.md" |
| Investigar lançamento X | general-purpose | `/investigate` | "Investigar lançamento X" |
| Validar A/B test | general-purpose | `/investigate-ab` | — |
| Auditoria de integridade | general-purpose | `/safeguard` | — |
| Arquitetura / decisão de design | Plan agent | — | descrição da decisão |
| Exploração de codebase | Explore agent | — | o que buscar |

---

## Passo 6 — Atualizar o INDICE_DOCUMENTACAO.md

**Regra:** não apagar nada que já existe no índice. Apenas:
- Adicionar entradas para documentos novos que não estão no índice
- Corrigir status desatualizados (marcando como ✅ o que foi concluído)
- Adicionar referências cruzadas entre os novos docs e os antigos

Documentos novos a adicionar ao índice (se não estiverem lá):
- `AB_TEST.md` → Camada 2 (Planejamento) ou Camada 4 (Referência técnica)
- `PLANO_EXECUCAO.md` → Camada 2 (Planejamento) — documento mestre
- `PLANO_SAFEGUARD.md` → Camada 2 (Planejamento)
- `Erros_cometidos.md` → Camada 4 ou Camada 5 (Histórico)
- `INVESTIGACAO_BAIXO_DESEMPENHO.md` → Camada 4
- `analise_perfil_leads_devclub.md` → se ausente
- `revenue_forecast.md` → se ausente

---

## Passo 7 — Emitir relatório final

Produza um relatório em 4 partes:

### Parte 1: Estado do projeto (snapshot)
O que está em produção, o que está pendente, o que está bloqueado. Máximo 20 linhas.

### Parte 2: Conflitos e inconsistências encontrados
Lista dos conflitos identificados no Passo 3, com o que precisa ser corrigido em qual documento.

### Parte 3: Prioridade global (do Passo 4)
Lista completa ordenada.

### Parte 4: Próximas 3 ações concretas
As 3 coisas mais importantes a fazer agora, com instrução exata de como começar cada uma.
