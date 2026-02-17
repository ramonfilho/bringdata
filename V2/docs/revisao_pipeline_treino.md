# Revisão do Pipeline de Treino — 17/02/2026

Referência: `training_20260216_190140.log`

---

## Status dos Pontos

| # | Ponto | Status |
|---|-------|--------|
| 1 | Limpeza dos logs de carregamento da API Guru | ✅ Concluído |
| 2 | Linhas sem timestamp | ✅ Concluído |
| 3 | Remoção da tabela de datasets após filtro DevClub | ✅ Concluído |
| 4 | Categorias com <0,1% — mapeamento compatível com produção (Célula 7) | ✅ Concluído |
| 5 | Mapeamento de manychat/organico/youtube-bio em "outros" (Célula 10) | ✅ Concluído |
| 6 | Explicação da verificação de consistência (Célula 10) | ✅ Documentado |
| 7 | Threshold e estrutura da Célula 11 | ✅ Documentado |
| 8 | Formatação de linhas fora do padrão (Célula 11) | ✅ Concluído (via `_TrainingFormatter`) |
| 9 | Mix Quente sendo classificado como "não visto" (Célula 11) | ✅ Concluído |
| 10 | `Interesse Programação` faltando — descontinuação confirmada | ✅ Concluído |

---

## Pontos 7–10: Reestruturação da Célula 11

### Diagnóstico atual

A Célula 11 está implementada em dois arquivos (`medium_training.py` e `medium_production_training.py`) e tem **5 etapas** hoje:

| Etapa | Arquivo | Ação | Input → Output |
|-------|---------|------|----------------|
| 1 | `medium_training.py` | Extração do público: remove prefixo `ADV \|`, pega parte depois do `\|` | 374 únicos → 57 |
| 2 | `medium_training.py` | Deduplicação automática: normaliza e agrupa variantes idênticas (`ABERTO` → `Aberto`) | 57 → 54 |
| 3 | `medium_training.py` | Relatório intermediário (só log, zero transformação) | — |
| 4 | `medium_production_training.py` | Mapeamento para produção: lista **hardcoded** de 6 categorias preservadas + tudo mais → `Outros` | 54 → 7 |
| 5 | `medium_production_training.py` | Relatório final de produção (só log, zero transformação) | — |

### Distribuição após Etapa 2 (54 únicos → antes do mapeamento de produção)

| # | Público | Count | % |
|---|---------|-------|---|
| 1 | Linguagem de programação | 39.557 | 25,9% |
| 2 | Lookalike 2% Cadastrados - DEV 2.0 + Interesses | 32.294 | 21,2% |
| 3 | Aberto | 23.550 | 15,4% |
| 4 | Lookalike 1% Cadastrados - DEV 2.0 + Interesse Ciência da Computação | 20.179 | 13,2% |
| 5 | dgen | 11.518 | 7,6% |
| 6 | Lookalike 2% Alunos + Interesse Linguagem de Programação | 6.816 | 4,5% |
| 7 | Lookalike 2% Alunos + Interesse Ciência da Computação | 2.036 | 1,3% → Outros |
| 8 | Lookalike 1% Cadastrados - DEV 2.0 + Interesse Linguagem de Programação | 1.715 | 1,1% → Outros |
| 9 | Interesse Python (linguagem de programação) | 1.579 | 1,0% → Outros |
| 10 | Interesse Programação | 1.498 | 1,0% → Outros (descontinuada set/2025) |
| 11 | Lookalike Envolvimento 30D + ... | 1.460 | 1,0% → Outros |
| ... | + 43 outros | — | → Outros |

**Categorias finais produção (7):** Linguagem de programação · Lookalike 2% Cadastrados · Aberto · Lookalike 1% Cadastrados + Interesse Ciência · dgen · Lookalike 2% Alunos + Interesse Linguagem · Outros

### Problemas identificados

**Ponto 7 — Threshold**
- Não existe threshold dinâmico. A seleção das 6 categorias preservadas é uma **lista hardcoded**.
- O corte implícito hoje é ~4,5% (menor categoria explícita). Tudo abaixo vai para `Outros`.
- Recomendação: manter o corte atual (~4,5%) e não adicionar categorias abaixo de 1,5% pois têm poucas conversões (~60–75 vendas) para treino confiável.

**Ponto 8 — Formatação fora do padrão**
- Linhas sem timestamp na Célula 11, geradas por `logger.debug(f"\nUnificando em: ...")`  em `medium_training.py:150` e `logger.debug(f"\n{len}...")` em `medium_production_training.py:169,210`.
- Já corrigido globalmente pelo `_TrainingFormatter` (ponto 2). Verificar se ainda restam casos de `print()` direto.

**Ponto 9 — Mix Quente sendo descartado**
- `Mix Quente` é um público válido e ativo, mas está caindo no mapeamento de produção como "não visto" → `Outros` porque não está na lista hardcoded.
- Log atual: `5 novo(s) valor(es) não visto(s) → 'Outros': 'ADV', 'MIX QUENTE', 'email', 'grupo', 'utm_medium'`

**Ponto 10 — Interesse Programação**
- Está marcada como **descontinuada** (terminou set/2025) e mapeada explicitamente para `Outros` no `mapping_dict`.
- Log confirma: `"ATENÇÃO: 1 categorias esperadas estão faltando: Interesse Programação"`.
- Confirmar: foi descontinuada intencionalmente. O aviso no log é ruído — a categoria não deveria mais estar nas `categorias_validas_producao`.

### Plano de ação (Pontos 7–10)

**Ação 2 — Etapa 2: normalizar `MIX QUENTE`** (`medium_training.py`) ✅ Concluído
- Adicionado `'MIX QUENTE': 'Mix Quente'` ao dict `unificacoes_manuais`.
- Confirmado via planilha: `MIX QUENTE` = 294 leads nos últimos 60 dias (~25% do volume recente).

**Ação 2b — Etapa 4: adicionar Mix Quente como categoria válida** (`medium_production_training.py`) ✅ Concluído
- Adicionado `'Mix Quente'` a `categorias_validas_producao` e a `mapping_dict` (→ `'Mix Quente'`).
- Adicionado `'Mix Quente'` a `categorias_esperadas` no relatório de conformidade.

**Ação 3 — Etapa 4: remover Interesse Programação das categorias esperadas** ✅ Concluído
- Confirmado via planilha: 0 registros nos últimos 60 dias → descontinuada.
- Removida de `categorias_esperadas` em `relatorio_unificacao_producao()`. Aviso eliminado.

**Ação 4 — Revisão do relatório intermediário (Etapa 3)**
- O relatório mostra 54 categorias antes do mapeamento de produção — muita informação.
- Simplificar para mostrar apenas as categorias que **excedem o threshold** e as que **serão descartadas**.

---

## Anotações — Células 15 em diante

<!-- Espaço reservado para anotações das células 15+ -->

### Célula 15: Matching de Leads com Vendas
_a preencher_

### Célula 17: Janela de Conversão de 20 Dias
_a preencher_

### Célula 18: Feature Engineering
_a preencher_

### Célula 20: Encoding Estratégico
_a preencher_

### Célula 21: Treino e Registro do Modelo
_a preencher_
