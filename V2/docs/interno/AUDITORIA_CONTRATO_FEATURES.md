# Auditoria do contrato de features entre treino e produção

**Data:** 2026-08-06
**Motivo:** o champion e o challenger em produção têm listas de features diferentes (60 e 53), e as 7 de diferença não são um subconjunto. Isso levantou a suspeita de que produção pudesse estar entregando a um modelo features que ele nunca viu, ou deixando de entregar features que ele espera.
**Conclusão:** **não há divergência de contrato.** Produção entrega os dois contratos por inteiro. O que a auditoria encontrou foi outra coisa: o **formulário de pesquisa mudou três vezes** desde o fim de 2024, e cada troca deixou resíduo nos modelos treinados em cima dela.

---

## Resumo dos achados

| # | Achado | Gravidade |
|---|---|---|
| 1 | Cada modelo recebe o próprio contrato de features, nos 5 caminhos de scoring. Zero features órfãs em 400 leads reais. | ✅ sistema correto |
| 2 | O formulário teve **3 gerações** de opções de resposta desde 30/12/2024. | 📋 fato a conhecer |
| 3 | O champion (modelo `abr28`) carrega **2 features permanentemente zeradas**, herdadas do formulário aposentado em fev/2025. | 🟡 peso morto, não cegueira |
| 4 | Um **terceiro formulário rodou de 16/02 a 14/06/2026** com textos que não casam com nenhuma categoria conhecida. Cerca de **2.800 leads** ficaram com dois grupos de features inteiramente zerados. | 🟠 ponto cego real, hoje inativo |
| 5 | Contagem de features **não prova** que a seleção de features rodou. Corrigido. | ✅ corrigido ([PR #145](https://github.com/ramonfilho/bringdata/pull/145)) |

---

## 1. O contrato de features é honrado por modelo

### Como funciona

Quando o teste A/B está ligado, cada variante carrega o **próprio** modelo e a **própria** lista de features esperadas (o arquivo `feature_registry.json` gravado no MLflow junto do modelo):

```python
# src/production_pipeline.py:161
vpredictor = LeadScoringPredictor(mlflow_run_id=variant.run_id)
```

E o passo que transforma respostas de texto em colunas numéricas (o encoding) alinha o resultado usando a lista **daquela** variante, não a do modelo padrão:

```python
# src/production_pipeline.py:309
_effective_predictor = predictor_override or self.predictor
_artifacts['mlflow_run_id'] = _effective_predictor.mlflow_run_id
```

Isto é a dívida técnica **DT-12** (o encoding precisa usar o registro de features da variante certa, não o do modelo padrão), já resolvida. Verificado nos cinco caminhos vivos de scoring:

| Caminho | Onde | Passa o modelo da variante? |
|---|---|---|
| Lead único, via API | `api/app.py:1057` | ✅ |
| **Lote via fila Pub/Sub** (caminho quente desde 31/07/2026) | `src/scoring/service.py:131` | ✅ |
| Re-scoring de leads já gravados | `api/scores_refresh.py:121` | ✅ |
| Ramo de pesquisa | `api/survey_branch.py:233` | ✅ |
| Endpoint de conferência de paridade | `api/app.py:4879` | ✅ |

### A prova empírica

400 leads reais e recentes do ledger (`registros_ml`), passados pelo pré-processamento e encoding de produção, uma vez por variante:

| Modelo | Features que ele espera | **Ausentes do DataFrame (viram zero)** | Zeradas no lote | Score mediano |
|---|---|---|---|---|
| `abr28` (champion) | 60 | **0** | 10 de 60 | 0,4943 |
| `jul_24` (challenger) | 53 | **0** | 5 de 53 | 0,4916 |

Nenhuma feature órfã nos dois. As zeradas são categorias que simplesmente não ocorreram no lote (não houve tráfego de TikTok nem de YouTube, as campanhas de público semelhante não estavam rodando, ninguém tinha nome ou e-mail inválido).

**As 6 features que só o `jul_24` tem chegam normalmente.** As duas perguntas de origem estão mapeadas em `api/railway_mapping.py:377`:

```
atracaoProfissao  → interesse_programacao      (4 features no jul_24)
investiuCurso     → investiu_curso_online      (2 features no jul_24)
```

Preenchidas em 400 de 400 leads.

### As guardas funcionam, comprovado por acidente

Na primeira tentativa a auditoria montou o teste com o mapeamento errado. A trava que checa se um grupo inteiro de colunas saiu zerado (dívida técnica **DT-19**, a verificação entre colunas do mesmo grupo) **bloqueou o pipeline** com erro explícito, nomeando cada grupo:

```
ValueError: [DT-19] 9 grupo(s) OHE com leads todo-zerados acima do limiar
(batch=400, mlflow_run_id=5d158f0a). Exemplos: O_seu_g_nero=1.000 (400 leads)...
```

Com o mapeamento correto, os validadores pós-encoding voltam a `severity: OK, issues: []`.

---

## 2. Três gerações de formulário

A pergunta "O que você faz atualmente?" mudou de opções duas vezes. Levantamento sobre `analytics.leads` (366.412 leads, de 30/12/2024 a 06/08/2026):

### Geração 1: até 23/02/2025

| Resposta | Leads | Primeira | Última |
|---|---|---|---|
| Trabalho em outra área e quero fazer transição para tecnologia. | 12.563 | 30/12/2024 | **23/02/2025** |
| Sou autônomo (Uber, freela, vendedor, etc). | 5.234 | 30/12/2024 | **23/02/2025** |
| Atualmente não trabalho e nem estudo. | 2.752 | 30/12/2024 | **23/02/2025** |
| Estou no ensino médio ou acabei de sair e quero entrar na programação. | 1.130 | 30/12/2024 | **22/02/2025** |
| Estudo T.I. na faculdade mas quero aprender mais por fora. | 969 | 30/12/2024 | **23/02/2025** |
| Faço outro curso na faculdade e quero mudar para T.I. | 316 | 30/12/2024 | **23/02/2025** |

### Geração 2: de 01/03/2025 até hoje (a viva)

| Resposta | Leads | Primeira | Última |
|---|---|---|---|
| Sou CLT/Funcionário Público | 145.972 | 04/03/2025 | 06/08/2026 |
| Sou autonomo | 93.006 | 03/03/2025 | 06/08/2026 |
| Sou apenas estudante | 58.579 | 01/03/2025 | 06/08/2026 |
| Não trabalho e nem estudo | 36.628 | 03/03/2025 | 05/08/2026 |
| Sou aposentado | 4.715 | 04/03/2025 | 04/08/2026 |

O corte é limpo: a geração 1 zera em março de 2025 e a geração 2 estreia entre 01 e 04/03/2025. **Um formulário inteiro foi aposentado numa troca só**, 17 meses antes de qualquer mudança na forma como consumimos os leads (a fila Pub/Sub). Não há relação entre as duas coisas.

### Geração 3: o formulário fantasma, 16/02 a 14/06/2026

Ver seção 4.

---

## 3. Duas features mortas dentro do champion

O modelo `abr28` (champion desde 25/07/2026) foi treinado com dados a partir de **08/02/2025**, ou seja, pegou as duas últimas semanas do formulário da geração 1. Aprendeu duas colunas de um formulário que já estava morto:

- `O_que_voc_faz_atualmente_estou_no_ensino_medio_ou_acabei_de_sair_e_quero_entrar_na_programacao`
- `O_que_voc_faz_atualmente_trabalho_em_outra_area_e_quero_fazer_transicao_para_tecnologia`

**Não é cegueira, é peso morto.** O modelo não perde informação que existe: a informação deixou de existir. O efeito é que 2 das 60 entradas dele são constantes em zero, para sempre. Numa Random Forest isso custa capacidade de árvore, não sinal.

A seleção de features do `jul_24` cortou exatamente essas duas, o que é evidência independente de que a seleção fez o trabalho certo.

**Ação:** nenhuma. As duas saem sozinhas quando o `abr28` for aposentado. Não vale retreinar por causa disso.

---

## 4. O formulário fantasma (16/02 a 14/06/2026)

Este é o achado que merece registro permanente.

Entre **16/02/2026 e 14/06/2026** rodou uma terceira versão do formulário, com textos de resposta que **não normalizam** para nenhuma das categorias conhecidas pelos modelos. Não é acento nem pontuação (a limpeza de texto resolveria isso): são redações diferentes.

### Pergunta de ocupação

| Texto (geração 3) | Leads | Primeira | Última |
|---|---|---|---|
| CLT / Funcionário Público | 1.521 | 16/02/2026 | 01/06/2026 |
| Autônomo / Empreendedor | 874 | 16/02/2026 | 14/06/2026 |
| Desempregado | 708 | 16/02/2026 | 08/05/2026 |
| Estudante | 530 | 16/02/2026 | 08/05/2026 |
| Aposentado | 64 | 16/02/2026 | 07/05/2026 |

Compare com a geração 2: `CLT / Funcionário Público` contra `Sou CLT/Funcionário Público`, `Estudante` contra `Sou apenas estudante`, `Desempregado` contra `Não trabalho e nem estudo`. Semanticamente iguais, textualmente diferentes.

### Pergunta de interesse em programação

| Texto (geração 3) | Leads | Primeira | Última |
|---|---|---|---|
| Trabalhar de qualquer lugar | 637 | 16/02/2026 | 11/05/2026 |
| Estabilidade / nunca faltar emprego | 542 | 16/02/2026 | 16/05/2026 |
| Ganhar mais dinheiro / bons salários | 499 | 16/02/2026 | 04/05/2026 |
| Trabalhar para fora / dólar | 337 | 16/02/2026 | 14/05/2026 |

### O impacto

Cerca de **2.800 leads** (3.697 respostas somando as duas perguntas, com sobreposição de pessoas) receberam **os dois grupos de features inteiramente zerados**. Para o modelo, esses leads responderam "nenhuma das alternativas" a duas perguntas que ele considera relevantes.

Como o alvo do modelo é ordenar leads por propensão, o efeito é empurrar esses leads para o meio da distribuição: sem sinal de ocupação e sem sinal de motivação, sobra o resto das features. Não é erro de scoring, é **informação perdida na entrada**.

### Por que ninguém viu na época

A trava que pega grupo inteiro zerado (**DT-19**) mede a **fração do lote** que está zerada e compara com um limiar de 2%. Esses leads eram uma fração pequena do volume diário (2.800 em ~4 meses, contra ~1.500 leads/dia no pico), então nunca cruzaram o limiar. A trava está correta: ela existe para pegar quebra sistêmica, não gotejamento.

### Status hoje

**Inativo.** Última ocorrência em 14/06/2026. Não é problema corrente.

### Ação recomendada

1. **Descobrir de onde veio.** A hipótese mais provável é uma landing page ou formulário paralelo (teste do cliente, página de outro lançamento) que não passou pelo mesmo template. Vale identificar para saber se pode voltar.
2. **Alerta de resposta desconhecida.** Hoje o sistema alerta quando um grupo de features zera em massa. Falta o alerta complementar: "chegou um **texto de resposta que nunca vi antes** nesta pergunta". Esse dispararia no dia 16/02/2026, com 1 lead, e não em junho com 2.800. Candidato a item da lista de salvaguardas.
3. **Não recuperar retroativamente.** Mapear os textos da geração 3 para as categorias da geração 2 no histórico mudaria o passado do dataset de treino sem ganho claro. Os 2.800 leads são 0,8% do universo.

---

## 5. Contagem de features não prova seleção de features

Ao comparar `abr28` (60 features) com `jul_24` (53), a única pista de que a seleção de features havia rodado era **contar features**. E a contagem mente, porque dois efeitos se somam:

```
60 → 53 = (a seleção cortou 13) + (6 features novas entraram no universo)
```

As 6 novas (`interesse_programacao` com 4 opções e `investiu_curso_online` com 2) não existiam no contrato do `abr28`. Logo, as 53 do `jul_24` **não são um subconjunto** das 60 do `abr28`, e a diferença de 7 não descreve nem a seleção nem a mudança de formulário isoladamente.

**Corrigido em [PR #145](https://github.com/ramonfilho/bringdata/pull/145).** A função `feature_selection.params_mlflow()` grava no run: método, limiar, quantas features entraram, quantas saíram, quantas foram cortadas, e a área sob a curva ROC do holdout antes e depois. Roda sempre, inclusive gravando `use_feature_selection=false` quando a seleção não foi pedida, porque parâmetro ausente é indistinguível de run antigo que nem conhecia a opção.

Separa também o caso mais traiçoeiro: uma seleção que **rodou e não cortou nada** (trava de não-regressão) tem a mesma contagem de features de quem **não rodou**.

---

## 6. O que NÃO é problema

Duas coisas que pareciam achado e não são:

**"A ideia de nunca faltar emprego na área" não sumiu.** 20.258 leads, de 15/04/2025 a 04/08/2026, chegando normalmente. Ela não está no contrato do `jul_24` porque a **seleção de features cortou** (é a menos frequente das 5 opções, ~6% do volume). Com as outras 4 zeradas, ela vira a categoria de referência implícita. O modelo não perde a informação, ela só muda de representação.

**"Não trabalho e nem estudo" e "Sou aposentado" também estão vivas.** 36.628 e 4.715 leads, chegando até 04-05/08/2026. São raras num lote de 400 (28 e 3 ocorrências), não sumidas.

---

## 7. Armadilha de investigação registrada

**A resposta sobre computador mora numa coluna, não no JSON da pesquisa.** No ledger `registros_ml`, a coluna é `has_computer`; ela **não** está dentro de `survey_responses`. A feature derivada dela é a **número 1 em importância** do `abr28` e a número 4 do `jul_24`.

Qualquer análise que leia só o JSON vai concluir, falsamente, que a feature mais importante do modelo desapareceu. Esta auditoria caiu nisso na primeira rodada, mesmo com o fato já registrado na memória do projeto.

Ao montar qualquer teste que reconstrua o input do modelo a partir do ledger, incluir explicitamente:

```python
survey = dict(row["survey_responses"])
survey.setdefault("computador", row["has_computer"])   # mora em coluna, não no jsonb
```

---

## Referências

- Dívida técnica **DT-12** (encoding usa o registro de features da variante certa) e **DT-19** (trava de grupo de colunas zerado): `PLANO_REFACTOR_MLOPS.md`
- Salvaguarda **T1-10** (feature crítica ausente do DataFrame) e **T1-16** (coluna zerada em massa após encoding): `PLANO_SAFEGUARD.md`
- Histórico de bugs de encoding e divergência treino/produção: `registro_erros_ml.md` § I.2
- Configuração das variantes em produção: `configs/active_models/devclub.yaml`
- Roteiro da auditoria: leads reais do ledger → `api/railway_mapping.railway_lead_to_sheets_row` → `LeadScoringPipeline.preprocess(predictor_override=...)` → comparação contra `predictor.feature_names`
