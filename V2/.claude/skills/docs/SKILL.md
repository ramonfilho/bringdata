---
name: docs
description: Skill master para gerenciar documentação em V2/docs/ — mapear, unificar, arquivar, indexar, auditar. Use quando o usuário pedir para "unificar/consolidar/organizar docs", "auditar redundância de documentação", "atualizar índice de documentação", ou invocar /docs.
---

# Skill master de documentação

Você gerencia o conjunto de documentos em `V2/docs/`. Esta skill substitui o antigo `/plan-integrator` e cobre o ciclo completo: mapear → auditar → unificar → arquivar → indexar.

**Regra fundamental:** docs nunca são apagados — só *arquivados* em `V2/docs/arquivo/` com header de deprecação. O conteúdo histórico é intocável.

## Modos disponíveis

| Modo | Quando usar |
|---|---|
| `mapear` | Visão integrada do projeto, estado das frentes, conflitos, prioridades |
| `unificar` | Fundir N docs num único (política: versão mais nova vence) |
| `arquivar` | Mover doc deprecado para `V2/docs/arquivo/` |
| `indexar` | Atualizar `V2/docs/INDICE_DOCUMENTACAO.md` |
| `auditar` | Detectar redundância e candidatos a unificação |

Se o usuário não disser o modo, infira do verbo ("organize" → unificar, "qual o estado" → mapear, etc) e confirme antes de agir.

---

## Modo MAPEAR

Substitui o antigo `/plan-integrator`. Use quando o usuário pedir visão integrada, prioridades, ou estado das frentes.

### Passo 1 — Leitura completa da documentação

Leia nesta ordem (pular o que não existir):

**Camada estratégica (o porquê)**
1. `docs/bring_data_02_execução.md` — visão de negócio, roadmap de escala
2. `docs/swot_bringdata.md` — SWOT
3. `docs/bring_data_produto.md` — definição do produto

**Camada de planejamento (o que está sendo feito)**
4. `docs/PLANO_EXECUCAO.md`
5. `docs/PLANO_REFACTOR_MLOPS.md`
6. `docs/PLANO_SAFEGUARD.md`
7. `docs/CHECKLIST_DEPLOY_REFACTOR.md`
8. `docs/CHECKLIST_ONBOARDING_NEW_CLIENT.md`

**Camada operacional (A/B test ativo)**
9. `docs/AB_TEST.md`
10. `docs/INVESTIGACAO_BAIXO_DESEMPENHO.md`

**Camada de referência técnica**
11. `docs/ARQUITETURA_SISTEMA_COMPLETA.md`
12. `docs/SISTEMA_VALIDACAO_ML.md`
13. `docs/Erros_cometidos.md`
14. `docs/auditoria_dano_bugs_ml.md`

**Camada de análise**
15. `docs/analise_perfil_leads_devclub.md`
16. `docs/analise_valor_ml_devclub.md`
17. `docs/revenue_forecast.md`

**Histórico (leitura rápida)**
18. `docs/arquivo/` — só para identificar o que já foi feito

### Passo 2 — Mapa de estado real

Para cada frente, cruze o que os documentos dizem:

| Frente | Docs relevantes | Estado (pendente / em curso / bloqueado / concluído) |
|---|---|---|
| A/B test Champion vs Challenger | AB_TEST.md, PLANO_EXECUCAO.md | |
| Patch A/B no rollback | PLANO_EXECUCAO.md | |
| Unificação de branches | PLANO_EXECUCAO.md, PLANO_REFACTOR_MLOPS.md | |
| Safeguards Tier 1 | PLANO_SAFEGUARD.md | |
| Safeguards Tier 2+3 | PLANO_SAFEGUARD.md | |
| Refactor Fase 1–3a,3c | PLANO_REFACTOR_MLOPS.md | |
| Refactor Fase 3b (Cliente B) | PLANO_REFACTOR_MLOPS.md | |
| Refactor Fase 4 (EDA Generator) | PLANO_REFACTOR_MLOPS.md | |
| Deploy do refactor | CHECKLIST_DEPLOY_REFACTOR.md | |
| Retreino com dados novos | PLANO_EXECUCAO.md, AB_TEST.md | |
| Retreino com importance weighting | PLANO_SAFEGUARD.md, Erros_cometidos.md | |
| Onboarding Cliente B | CHECKLIST_ONBOARDING_NEW_CLIENT.md | |
| Auditoria de dano ML | auditoria_dano_bugs_ml.md | |

### Passo 3 — Conflitos e desatualização

Procure:
1. Documentos com afirmações contraditórias
2. Status desatualizados no índice
3. Documentos novos não referenciados no `INDICE_DOCUMENTACAO.md`
4. Dependências circulares entre planos
5. Prioridades conflitantes (urgente num doc, baixa em outro)

### Passo 4 — Prioridade global

Lista única ordenada considerando: prazos de negócio, dependências técnicas, risco, complexidade.

```
PRIORIDADE GLOBAL — [data de hoje]

🔴 URGENTE (prazo fixo ou bloqueia produção)
  1. [item] — [doc de referência] — [dependências]

🟡 PRÓXIMO (próximas 2 semanas)
  N. [item] — [doc] — [pré-requisitos]

🟢 BACKLOG
  N. [item] — [doc] — [condição de entrada]

⚪ BLOQUEADO
  N. [item] — [bloqueador]
```

### Passo 5 — Direcionar ao agente correto

| Tipo de trabalho | Agente | Skill | Como invocar |
|---|---|---|---|
| Implementação tática | general-purpose | — | descrição direta |
| Investigar lançamento | general-purpose | `/investigate` | "Investigar lançamento X" |
| Validar A/B | general-purpose | `/investigate-ab` | — |
| Auditoria infra | general-purpose | `/safeguard` | — |
| Decisão de design | Plan agent | — | descrição da decisão |
| Exploração código | Explore agent | — | o que buscar |

### Passo 6 — Atualizar o índice

Chame o **modo INDEXAR**.

### Passo 7 — Relatório final

Quatro partes:
1. **Estado do projeto** (snapshot, máx 20 linhas)
2. **Conflitos encontrados** (do Passo 3)
3. **Prioridade global** (do Passo 4)
4. **Próximas 3 ações concretas** (com instrução exata)

---

## Modo UNIFICAR

Funde N docs num único.

**Política:** versão mais nova vence em conflitos textuais. A versão antiga vai pro arquivo, com nota apontando para o unificado.

### Passos

1. **Confirmar entrada com usuário**: arquivos a unificar, nome do arquivo destino, contexto de uso (cliente externo / interno técnico).

2. **Ler cada doc entrado** integralmente. Anotar:
   - Data de modificação (`stat -f %m` ou git log)
   - Tópicos principais cobertos
   - Frontmatter / metadados existentes

3. **Diff conceitual**: agrupe por tópico. Para cada tópico, marque:
   - Coberto por 1 só doc → entra direto no unificado
   - Coberto por 2+ docs com texto **igual ou complementar** → soma sem duplicar
   - Coberto por 2+ docs com texto **conflitante** → vence o doc com `mtime` mais recente; adicione callout no unificado:
     > Observação: versão anterior deste tópico está em [arquivo/<nome>.md](arquivo/<nome>.md).

4. **Estruturar o unificado**:
   - Frontmatter com `data_unificacao`, `origem` (lista dos docs fundidos)
   - Sumário/índice no topo se >150 linhas
   - Seções na ordem solicitada (cronológica, severidade, temática — perguntar se ambíguo)
   - Linguagem coerente com o contexto (cliente externo: simples, sem jargão; interno: técnico)

5. **Salvar como novo arquivo** em `V2/docs/<nome>.md` com `Write`.

6. **Encadear ARQUIVAR** para cada original.

7. **Encadear INDEXAR** para atualizar `INDICE_DOCUMENTACAO.md`.

8. **Reportar ao usuário**: arquivos arquivados, novo arquivo criado, entradas no índice atualizadas, conflitos resolvidos com origem.

---

## Modo ARQUIVAR

Move um doc para `V2/docs/arquivo/<nome>.md` com header de deprecação.

### Passos

1. Ler o doc original (preservar conteúdo intacto).
2. Criar versão arquivada com header prepended:

```markdown
> **DEPRECADO em <YYYY-MM-DD>.** Conteúdo migrado para [<unificado>](../<unificado>.md).
> Este arquivo permanece para referência histórica.

---

[conteúdo original]
```

3. Mover via `git mv` (preserva histórico): `git mv V2/docs/<nome>.md V2/docs/arquivo/<nome>.md`.
4. Aplicar o header com `Edit`.
5. Confirmar ao usuário antes de qualquer remoção definitiva.

---

## Modo INDEXAR

Atualiza `V2/docs/INDICE_DOCUMENTACAO.md`.

### Regras

- **Não apagar entradas** — marcar como `ARQUIVADO →` com link para o substituto.
- **Adicionar entrada** para cada doc novo (unificado ou criado).
- **Corrigir status** desatualizados (✅ concluído, ⏸ pausado, 🚧 em curso).
- **Adicionar referências cruzadas** entre docs relacionados.

### Categorias do índice (use as existentes)

1. Estratégia
2. Planejamento
3. Operacional / A/B
4. Referência técnica
5. Análise
6. Runbooks
7. Histórico (arquivo/)

---

## Modo AUDITAR

Detecta redundância e candidatos a unificação.

### Passos

1. Listar todos os arquivos em `V2/docs/` (excluindo `arquivo/`).
2. Para cada par de docs, comparar:
   - Sobreposição de tópicos (heurística: títulos H2/H3 em comum)
   - Sobreposição de termos-chave do frontmatter `description`
3. Reportar candidatos a unificação em formato:

```
CANDIDATOS A UNIFICAÇÃO

🔴 Forte sobreposição (>60% tópicos em comum)
  • A.md + B.md — tema: <X>

🟡 Sobreposição parcial
  • C.md + D.md — overlap em: <Y>

🟢 Possível redundância tangencial
  • E.md + F.md — ambos mencionam: <Z>
```

4. Para cada candidato, sugerir nome do unificado e ordem de seções.
5. Aguardar usuário confirmar antes de chamar UNIFICAR.

---

## Princípios transversais

- **Sempre confirmar antes de unificar/arquivar** — operação difícil de reverter sem perda de contexto.
- **Linguagem do unificado respeita audiência**: docs internos podem ter jargão, docs voltados ao cliente externo seguem [feedback_auditoria_linguagem_cliente.md](memory) — sem termos técnicos como "shim", "Champion/Challenger", "encoding override".
- **Datas absolutas** — sempre converter "ontem"/"semana passada" para `YYYY-MM-DD`.
- **Trilha de origem** — todo doc unificado leva no frontmatter os arquivos de origem.
- **Não apagar comitado** — usar `git mv` para preservar histórico ao arquivar.
