# Análise — avaliação da feature User Agent (e o que prediz grau de risco TMB)

**Data:** 2026-06-29
**Método:** avaliação de feature com a skill `/data-scientist` (modelos de adaptação para triagem; veredito sobre o modelo real).
**Pergunta:** o User Agent (aparelho do lead) vale como feature do modelo? E, de passagem, quais features de pesquisa predizem o grau de risco da TMB?

---

## Resumo executivo

- **User Agent: arquivada.** O aparelho é um proxy de poder de compra **redundante** com a pesquisa (faixa salarial, cartão de crédito, ocupação, idade). Somado ao modelo, dá **+0,005 de AUC e zero de ganho na concentração de decis** (a métrica de negócio). Não vale o custo de engenharia no modelo real.
- **Grau de risco TMB: uma feature domina** — **"Você possui cartão de crédito?"**. Sem cartão ~dobra a chance de ser "Alto" risco (62–69% vs 33–40%). O resto da pesquisa quase não prediz risco.
- **Device → risco TMB:** sinal fraco e **underpowered** (só 484 compradores TMB têm UA, pois o UA é recente e os compradores são antigos) — não dá pra cravar, mas não aparece.

---

## Contexto: por que o User Agent virou candidato

O User Agent (string `navigator.userAgent`) existe ~100% desde fev/2026 e foi recuperado para a `analytics.leads.user_agent` (ver `CONSOLIDACAO_CLOUDSQL.md`). A string crua traz o **modelo do aparelho** (ex.: `SM-A146M`, `moto g05`), um proxy plausível de poder de compra. A hipótese: o aparelho prediz conversão e/ou capacidade de pagamento (risco TMB).

Derivações testadas do UA cru: `os`, `device` (mobile/desktop/tablet), `browser`, `brand`, `model`, `android_version`, e um `price_tier` heurístico (budget/mid/premium/apple/desktop).

---

## Q1 — Features que predizem o grau de risco da TMB

**Dataset:** 1.722 compradores TMB com pesquisa casada e rótulo de risco (`Baixo`/`Médio`/`Alto`), do `contas_a_receber_*.xlsx`. Distribuição: Alto 54%, Médio 39%, Baixo 7% (desbalanceado pro Alto — coerente: TMB é o gateway de parcelamento).

**Resultado:** uma única feature domina.

| Feature | Cramér's V | p | |
|---|---|---|---|
| **Você possui cartão de crédito?** | **0,214** | 1e-28 | 🟢 forte |
| Qual a sua idade? | 0,170 | 2e-08 | 🟡 fraco-significativo (<25 anos = menos "Alto") |
| Faixa salarial | 0,128 | 0,03 | 🟡 muito fraco |
| `Medium` (UTM) | 0,315 | 0,36 | ❌ artefato de cardinalidade (167 categorias, não significativo) |
| demais (gênero, faculdade, nível…) | <0,08 | n.s. | ❌ sem sinal |

**Taxa de "Alto" por resposta de cartão:** sem cartão 62–69% Alto; com cartão 33–40% (baseline 54%). Na importância por permutação o cartão domina sozinho (+0,083; demais ≈0). **Leitura:** coerente — sem cartão empurra o comprador pro parcelamento por boleto, que a TMB classifica como maior risco. No agregado a pesquisa **não** monta um bom modelo de risco (classificador empata com baseline "sempre Alto", 0,54); o sinal está concentrado nessa pergunta.

---

## Q2 — User Agent num modelo de conversão

**Dataset:** 144.244 leads (fev–mai/2026, dedup por email), 1.908 conversões (1,32%), 94% com UA. RandomForest, split temporal, 3 seeds. *(Modelo de adaptação para triagem — não o `train_pipeline` real.)*

| Modelo | AUC | concentração top-3 decis |
|---|---|---|
| BASE (só pesquisa) | 0,5948 | 41,6% |
| BASE + UA simples (mobile/iOS/Android) | 0,5938 | 38,5% |
| **BASE + UA rico (marca+modelo+versão)** | **0,6036** (+0,007) | 41,7% |
| BASE + tier de preço (5 categorias) | 0,5996 (+0,005) | — |
| **SÓ UA rico (zero pesquisa)** | **0,5688** | 40,1% |

**Achados:**
1. O **modelo do aparelho tem sinal real** — só com o device (AUC 0,569) quase empata com a pesquisa inteira (0,595). (Device/OS simples mobile/desktop **não** tem: meu primeiro parser jogou o sinal fora.)
2. Mas é **largamente redundante** com a pesquisa (ambos medem poder de compra) → ganho marginal **+0,005 AUC e zero de concentração de decis**.
3. **Direção contraintuitiva:** aparelhos **mais baratos** convertem **mais** (público DevClub é aspiracional). Por tier: budget 1,01% (lift 0,77) < apple/premium ~1,25% < mid 1,41% < desktop 1,64% (lift 1,24).
4. **Encoding importa:** o `tier de preço` (5 colunas) captura quase todo o ganho do modelo cru (41 colunas). Limitações: iOS não expõe modelo (todos iPhones colapsam) e o corte de cardinalidade joga o premium em `other`.

---

## Q3 — Device/tier → grau de risco da TMB

Apenas **484 compradores TMB têm risco E User Agent** (o UA é de fev/2026; os compradores TMB são majoritariamente anteriores → pouco overlap). `tier` V=0,089 (p=0,47), `brand` V=0,100 (p=0,46), `device` V=0,047 (p=0,58) — todos **não significativos**, longe do benchmark do cartão (0,214). Gradiente na direção esperada (budget 66% Alto vs premium 52%), mas fraco e **underpowered**. Não dá pra cravar "sem sinal"; com os dados disponíveis ele não aparece.

---

## Veredito (skill `/data-scientist`)

**Arquivar o User Agent** como feature: *avaliada, valor marginal ~zero por redundância com a pesquisa, não vale o custo no modelo real.*

**Por que o modelo de adaptação basta para o NÃO:** o proxy usou um subconjunto das features; o modelo real tem as ~60 completas → **ainda mais** coisa para o UA ser redundante. Logo o valor marginal no modelo real é **≤** os +0,005 medidos. O viés do proxy **superestima** o UA — então um "~zero" no proxy é um teto seguro. Precisa-se do modelo real para **justificar INCLUIR** uma feature (provar ganho na régua real), **não** para **excluí-la** quando o proxy já mostra redundância.

**Desenho do teste mínimo no modelo real (só se reabrir, para confirmação definitiva):**
1. `leads_reader` passa a surgir `user_agent` (+ união de sources p/ ver os `registros_ml`).
2. `core/user_agent.py` (parser → `tier`, assinatura `parse(df,config)->df`, paridade).
3. Registrar no feature_engineering/encoding/`feature_registry`.
4. `train_pipeline --min-date 2026-02-01` **duas vezes** (com/sem `tier`), mesma janela/split; comparar na validação real **concentração de decis + monotonia**, não só AUC.

Custo ~1–2 dias de core+reader+encoding + 2 treinos + risco de paridade. Mesmo positivo, só valeria num modelo de **janela encurtada** (perde 2025, base pior). **Reabrir só se:** (a) o mix do público mudar (mais desktop, hoje 5%); (b) um retreino futuro já estiver na base fev/2026+ e adicionar o `tier` sair barato; (c) houver vontade de confirmação definitiva.

Se um dia entrar, a forma é o **`tier` de preço (5 categorias) em `core/user_agent.py`**, derivado on-read — nunca o modelo cru one-hot. Um `tier` preciso pediria tabela de referência externa device→preço (ver `/data-architect`); fica no backlog até haver payoff.

---

## Limitações conhecidas

- Q2/Q3 usaram **modelos de adaptação** (RF simplificado, `get_dummies`, subconjunto de features, alvo = email-casa-venda) — válidos para triagem/NÃO, não para um GO de produção.
- AUC absoluto (~0,60) **não é comparável** ao Challenger (0,754): janela mais curta/menos madura + pipeline de features simplificado. O que vale é o **delta com/sem UA na mesma base**.
- Q3 underpowered (484 casos).

---

## Referências

- Dados e cobertura do UA: `CONSOLIDACAO_CLOUDSQL.md` (recuperação de leads + user_agent, 29/06).
- Backlog de features (UA listado): `EXPERIMENTO_MOAT_MODELO.md`, `PLANO_EXECUCAO.md`.
- Skill de avaliação: `/data-scientist` (`.claude/commands/data-scientist.md`).
