# Divergências Treino × Produção — Fix Urgente
**Branch:** `fix/prod-pipeline-sync`
**Data:** 2026-03-15
**Contexto:** Modelos b58e2b98 (TMB None + tuning) e 210470d9 (TMB All, sem tuning) foram treinados no `dev/retreino` com mudanças que o `production_pipeline.py` ainda não reflete.

---

## Como usar este documento

Cada item é um passo do checklist. Para cada um:
1. Aplicar a mudança em `production_pipeline.py` (e/ou nos módulos que ele chama)
2. Verificar com batch de leads reais
3. Marcar como ✅

**Critério de convergência:** rodar um batch de leads pelo train_pipeline (sem treinar — só até encoding) e pelo production_pipeline, comparar os `lead_score` coluna a coluna. Diferença tolerada: < 0.001 por lead.

---

## Mudanças que afetam o feature space (críticas)

### 1. ⚠️ Medium encoding — binary_top3 → get_dummies dinâmico

**A mudança mais crítica.** O modelo foi treinado com 7 features dinâmicas de Medium via `pd.get_dummies`. O production pipeline ainda gera 3 features binárias hardcoded.

**Treino (novo):**
```python
# encoding_training.py — Medium entra como categórica normal
# pd.get_dummies gera colunas dinâmicas baseadas nas categorias presentes
# A Célula 11 já reduziu Medium às categorias válidas do modelo ativo
# → resultado: 7 features Medium_* definidas pelo distribuicoes_esperadas.json
```

**Produção (atual — ERRADO para o novo modelo):**
```python
# encoding.py — ainda gera as 3 features hardcoded:
df['Medium_Linguagem_programacao'] = (df['Medium'] == 'Linguagem de programação').astype(int)
df['Medium_Aberto'] = (df['Medium'] == 'Aberto').astype(int)
df['Medium_Lookalike_2pct_Cadastrados'] = (df['Medium'] == 'Lookalike 2% Cadastrados - DEV 2.0 + Interesses').astype(int)
df = df.drop(columns=['Medium'])
```

**Fix:** substituir o bloco binary_top3 em `encoding.py` por `pd.get_dummies(df['Medium'], prefix='Medium')` seguido de alinhamento com o `feature_registry.json` do modelo ativo (que já tem as 7 colunas esperadas).

---

### 2. ⚠️ Remoção de nome_valido, email_valido, telefone_valido

**Treino (novo):** essas 3 features foram removidas de `feature_engineering_training.py`. Não existem no feature space dos modelos treinados.

**Produção (atual):** `engineering.py` provavelmente ainda cria essas features. Se forem passadas ao modelo, causam mismatch com o `feature_registry.json`.

**Fix:** verificar se `engineering.py` cria `nome_valido`, `email_valido`, `telefone_valido` — se sim, remover ou garantir que sejam dropadas antes do predict.

---

### 3. UTM Source — youtube-bio → youtube

**Treino (novo — `utm_training.py`):**
```python
# youtube-bio mapeado para 'youtube' (mesmo canal, variante orgânica)
df.loc[df['Source'] == 'youtube-bio', 'Source'] = 'youtube'

# Lista de 'outros': ['fb', 'teste', '[field id="utm_source"]',
#   'facebook-ads-SiteLink', 'utm_source', 'manychat', 'organico',
#   'BIO', 'livesemanal']
# 'youtube-bio' SAIU da lista — agora mapeado para 'youtube'
```

**Produção (atual — `utm_unification.py`):** verificar se `youtube-bio` é mapeado para `youtube` ou vai para `outros`. Se for para `outros`, leads do YouTube terão Source errado.

**Fix:** adicionar `'youtube-bio' → 'youtube'` em `utm_unification.py` antes do agrupamento em `outros`.

---

### 4. Telefone comprimento — agrupamento de raros

**Treino (novo):**
```python
# Comprimentos raros (4=inválido, 10=obsoleto) agrupados em 'outros'
df['telefone_comprimento'] = df['telefone_comprimento'].apply(
    lambda x: x if x in [9, 11] else 'outros'
)
# Resultado: apenas telefone_comprimento_9, telefone_comprimento_11, telefone_comprimento_outros
```

**Produção (atual):** verificar se `engineering.py` faz o mesmo agrupamento ou gera `telefone_comprimento_4`, `telefone_comprimento_10` separados.

**Fix:** replicar o agrupamento `[9, 11] → keep, resto → 'outros'` em `engineering.py`.

---

## Mudanças que NÃO afetam o feature space (não precisam ser replicadas)

| Mudança | Motivo para ignorar |
|---|---|
| Sample weights por tipo de comprador | Usado apenas no treino (fit). Predict não usa pesos. |
| Filtro TMB movido de Célula 15.1 para 5.3 | Lógica de treino — define labels, não features. |
| Janela de conversão simétrica | Define dataset de treino — não afeta scoring em produção. |
| Cutoff automático por missing rate | Define dataset de treino — não afeta scoring. |
| `hyperparameter_tuning.py` — baseline params | Usado apenas no tuning. |
| `compare_models.py` + `--save-encoded` | Ferramenta de comparação offline. |
| Logging e relatórios | Sem impacto em dados. |

---

## Verificação de convergência

```bash
# 1. Gerar scores pelo production_pipeline com um batch de leads reais
# 2. Comparar com scores do train_pipeline (modo scoring, sem treinar)
# Diferença esperada após fix: < 0.001 por lead
```

Os arquivos de referência do modelo ativo estão em `configs/active_model.yaml` → `files/{timestamp}/`:
- `feature_registry.json` — lista exata de features esperadas (com ordem)
- `distribuicoes_esperadas.json` — distribuições incluindo as 7 categorias Medium

---

## Ordem de execução sugerida

1. ✅ Fix Medium encoding (`encoding.py`) — item mais crítico
2. ✅ Verificar e remover nome_valido/email_valido/telefone_valido (`engineering.py`)
3. ✅ Fix youtube-bio → youtube (`utm_unification.py`)
4. ✅ Fix telefone_comprimento agrupamento (`engineering.py`)
5. ✅ Teste de convergência com batch real
6. ✅ Deploy do novo modelo
