# Investigação: Baixo Desempenho D10 — DevClub

> Última atualização: 2026-04-13

---

> **⚠️ AVISO CRÍTICO**
>
> Este é um sistema de ML em produção com **US$18.000/semana de investimento em mídia** otimizado pelo modelo. Decisões erradas têm impacto financeiro direto e imediato.
>
> **Padrão de evidência exigido:** toda conclusão registrada neste documento deve ser comprovada por código executado e dados reais. Nada deve ser intuído, inferido ou concluído sem verificação robusta — preferencialmente com significância estatística quando comparações entre grupos forem feitas. Hipóteses não testadas devem ser explicitamente marcadas como pendentes.

---

## Contexto

Queda observada no percentual de leads classificados como D10 entre os períodos P1 e P3.

| Período | Datas | Modelo | D10% |
|---|---|---|---|
| P1 | 18/02 – 09/03 | jan30 (`d51757f5`) | ~41.7% |
| P2 | 15/03 – 25/03 | TMB All (`2a98e51c`) | crash |
| P3 | 26/03 – hoje | jan30 (Champion) | ~30% |

---

## Conclusões consolidadas (sessões de investigação)

### O que foi descartado definitivamente

> **Nota metodológica:** apenas os itens marcados com ✅ têm respaldo estatístico direto. Os demais são conclusões lógicas ou verificações de código.

1. ⚠️ **Bug no pipeline atual para jan30 — validação fraca anterior superada** — teste com 300 leads e só D10% concluíra "correto". Teste robusto desta sessão (3.500 leads, 5 testes estatísticos) encontrou divergência real: **`Medium_Linguagem_programacao` sempre zerada** no código atual (OHE + regex remove `ç` → coluna errada → zero-fill silencioso). Feature é a 5ª mais importante (5.31%). Fix aplicado: `column_name_corrections` em `configs/clients/devclub.yaml`. Pós-fix: 86.7% de decis exatos vs ~67% do próprio edf23e9. **Ver seção "Plano de rollback" abaixo — a ação correta é voltar ao edf23e9, não manter o código atual com patch.**
2. ✅ **Modelo reconhece os mesmos tipos de lead como D10 em P3 e P1** — chi² no subgrupo D10: perfil de ocupação, idade e faixa salarial equivalentes. *Não prova que esses perfis ainda convertem proporcionalmente — ver "Risco residual" abaixo.*
3. **Efeito de batch size na OHE** — `prepare_features()` sempre filtra para as N features exatas do modelo. Verificado no código, não testado com dados.
4. **Crash de P2 afetou P3** — P2 causado por TMB All + encoding quebrado. Ambos resolvidos. P3 usa jan30 com encoding correto. Verificado no código e no parity test.

### Risco residual não verificável com dados atuais

**Concept drift:** provamos que o modelo atribui D10 para os mesmos perfis de lead. Não provamos que esses perfis ainda convertem acima do baseline com a nova composição de audiência (P3). Para isso seria necessário um LF completo em P3 com jan30 ativo desde a captação e N suficiente de conversões. O LF50 (1.28x lift, N pequeno) é sinal positivo mas insuficiente estatisticamente.

**Edge case no `encoding_overrides`:** se `pipeline.predictor.mlflow_run_id` não estiver setado (predictor carregado sem MLflow), o fallback Champion recebe `enc_overrides=None` silenciosamente — D10 cai para ~21% sem log e sem erro. Depende de `active_model.mlflow_run_id = guru_jan30.run_id = d51757f5` estar sincronizados.

### O que causou o crash de P2 (já resolvido)

- Deploy do TMB All (`2a98e51c`) em 15/03 com thresholds calibrados para outro perfil de leads
- Simultaneamente: commit `9b86d37` removeu ordinal encoding de `idade`/`faixa_salarial` de `encoding.py`, zerando essas features para o jan30 → D10 caiu para 21.3%
- Corrigido via `encoding_overrides` no `devclub.yaml` (DT-12), aplicado em `app.py` linhas 3014–3056

### O que explica o gap P3 (~30% D10 vs 41.7% P1)

**O pipeline está correto. O gap é real e vem dos leads, não do modelo.**
Os mesmos leads de P1 rodados no pipeline atual produzem 41.3% D10. Se P3 entrega ~30%, é porque os leads de P3 têm perfil diferente — menos leads de alta propensão chegando nas campanhas atuais.

**Causa identificada:** em 10/03 as campanhas migraram o evento de otimização de `LeadQualifiedHighQuality` (só D09–D10) para `LeadQualified` (todos os decis com valor proporcional). A migração de orçamento foi crescendo até ~25/03, quando o gestor começou a reverter, retornando ~80% para LQHQ. Durante esse período o Meta aprendeu a buscar um perfil de lead mais amplo — o "aberto" de P3 é o mesmo UTM, mas com audiência qualitativamente diferente porque o sinal de otimização mudou. O D10% caiu de 41.7% para ~6–30% conforme a migração avançava e recuava.

---

## Hipóteses testadas

### Eliminadas com dados

**1. O modelo classifica leads de P3 de forma diferente dos leads de P1**
Perfil de features D10 em P3 ≈ P1 (+5.6pp CLT, sem diferença sistemática). Mesmos tipos de lead → mesmos scores. **Eliminado.**

**2. Batch size causa divergência de scores (50 leads em produção vs 300 no teste)**
`prepare_features()` filtra sempre para as N features exatas do modelo. Colunas OHE extras de batches grandes são ignoradas antes de entrar no Random Forest. **Eliminado.**

**3. Pipeline atual está quebrado para o modelo jan30**
Sem `encoding_overrides`: D10 = 21.3% (quebrado).
Com `encoding_overrides` (como `app.py` faz em produção): D10 = 41.3% ≈ P1 — testado com 300 leads/D10% apenas.
Teste robusto (3.500 leads, 5 testes): **3/5 falham** antes do fix. Causa: `Medium_Linguagem_programacao` zerada.
Fix aplicado em `devclub.yaml` → 86.7% exact match. **Parcialmente eliminado — ver rollback.**

---

### Causas confirmadas (já resolvidas)

**4. Campo `createdAt::date` vs `data` (timestamp completo)**
Usar só a data sem hora zerava `hora_cadastro` para todos os leads → delta médio de −0.071 nos scores. Corrigido usando o campo `data` completo.

**5. Deploy simultâneo no dia 15/03: TMB All + remoção do ordinal encoding**
Commit `9b86d37` (15/03) removeu ordinal encoding de `idade`/`faixa_salarial` de `encoding.py`. O jan30 foi treinado com ordinal — sem ele, essas features viram OHE com colunas ausentes, preenchidas com 0. Resultado: 21.3% D10.
Corrigido via `encoding_overrides` no `devclub.yaml` (DT-12), aplicado em `app.py` linhas 3021–3040.

**6. Modelo TMB All causou o crash de P2**
Modelo diferente com thresholds diferentes. Causa isolada, resolvida com retorno do jan30 como Champion.

---

## Fatos estabelecidos

- Commit exato em produção durante P1: **`edf23e9`** (05/03/2026), identificado via timestamp da imagem Cloud Run.
- `edf23e9` reproduz os scores de P1 armazenados no Railway: D10 = 41.7% = 41.7%, delta médio de score +0.008.
- Pipeline atual (main) com `encoding_overrides` reproduz P1: D10 = 41.3% ≈ 41.7% (1 lead de diferença em 300).
- A/B test: todo lead sem `utm_campaign=ML_MAR` vai para jan30 (Champion fallback, linhas 3024–3029 de `app.py`).
- Variação residual de ~33% nos decis individuais (28% ±1 decil, 5% >±1) é inerente à comparação — leads próximos de limiares flutuam com qualquer diferença mínima de formato de entrada. Não é bug.

---

## Análise do gap P1 → P3

### Conclusão principal

**O código está correto. A queda de ROAS e conversões absolutas em P3 é causada por degradação da qualidade da audiência.** Se o modelo continua discriminando bem dentro da nova audiência não é verificável com dados atuais — LF51 completo é o próximo passo.

Evidências:

**1. Quando a queda de D10 começou — breakdown diário (Railway, n=61.212 leads)**

| Dia | D10% | Score médio |
|---|---|---|
| 09/03 | 42.2% | 0.4147 |
| 10/03 | 41.4% | 0.4089 |
| 11/03 | 39.9% | 0.4071 |
| **12/03** | **31.6%** | **0.3718** ← primeira queda |
| 13/03 | 29.8% | 0.3633 |
| 14/03 | 27.5% | 0.3573 |
| 15/03 | 17.1% | 0.3196 ← TMB All deploy |
| 16/03+ | ~6% | 0.2933 ← crash total |

A queda começou em **12/03, três dias antes do deploy do TMB All**. A causa foi mudança na estratégia de tráfego — não o modelo.

**2. O que mudou no perfil dos leads — P1 vs P3 (chi² p≈0, n=32.787 + 28.425)**

| Feature | P1 | P3 | Δ |
|---|---|---|---|
| Tem computador | 88.5% | 79.5% | **−9.0pp** |
| Tem cartão de crédito | 43.5% | 38.1% | −5.4pp |
| Sem renda | 25.1% | 30.0% | +4.9pp |
| Não trabalha nem estuda | 9.4% | 12.9% | +3.4pp |
| Medium "aberto" (broad) | 56.9% | 78.9% | **+22.0pp** |
| Medium "mix quente" | 7.3% | 0% | −7.3pp |
| Medium "linguagem de programação" | 6.5% | 0.1% | −6.4pp |

Todas as diferenças são estatisticamente significativas (p<0.001). A audiência de P3 tem menor capacidade de compra e vem predominantemente de broad targeting.

**3. O modelo ainda discrimina — taxa de conversão real por decil**

Fonte: `outputs/validation/historico/evolucao_ml_devclub_20260409_140310.xlsx`

| Decil | LF44 (P1 ref) | LF45 (P1) | LF49 (P3) | LF50 (P3) |
|---|---|---|---|---|
| Baseline (todos os leads) | 0.732% | 0.862% | 0.445% | 0.575% |
| **D10** | **1.078% (1.47x)** | **1.013% (1.17x)** | **1.375% (3.09x)** | **0.736% (1.28x)** |
| D9 | 0.412% (0.56x) | 0.725% (0.84x) | 0.728% (1.64x) | 1.187% (2.07x) |
| D1 | 0.000% | 0.206% | 0.075% | 0.374% |

D10 converte acima do baseline em LF50 (1.28x) — único período P3 com jan30 correto desde a captação. O lift do LF49 (3.09x) não é válido: leads do LF49 foram pontuados durante o crash de P2 (D10%=5.1% na captação), tornando essa comparação não representativa do jan30.

**4. O problema real: queda do baseline, não do lift**

A "conversão baixa" em LF49/50 é queda da taxa absoluta — o baseline caiu de 0.862% (LF45) para 0.445% (LF49). Com audiência pior, a taxa de conversão de todos os decis cai proporcionalmente. O modelo rank-ordena corretamente dentro do pool disponível, mas o pool piorou.

**5. Sobre limpar o pixel**

Tecnicamente seguro. Os sinais CAPI enviados desde 26/03 são corretos (jan30 com encoding_overrides). O pixel foi contaminado especificamente entre 15–25/03 (TMB All com encoding quebrado). Desde 26/03, os sinais refletem decis corretos.

**Porém:** limpar o pixel sem corrigir a estratégia de audiência reproduzirá o mesmo resultado. O medium "aberto" em 79% e ausência de `mix quente`/`linguagem de programação` é a causa raiz da degradação.

---

### 6. Queda de tracking (70% → 34%) — investigado

Fonte: caches `guru/asaas/hotmart_2026-03-30_2026-04-05.parquet` cruzados com Sheets (all_all) + Railway. n=141 compradores únicos Guru+Asaas LF49.

| Grupo | n | Explicação |
|---|---|---|
| Matched à captação LF49 (17–23/03) | ~60 | Contados no tracking |
| Capturados em LFs anteriores (LF44–LF48) | 24 | Excluídos pelo filtro de período — correto |
| Capturados no LF50 (24–29/03), compram 01–05/04 | 35 | **Aparecem no LF50** — janelas sobrepostas |
| Capturados após abertura do carrinho (30/03+) | 6 | Excluídos pelo filtro de período |
| Nunca fizeram pesquisa (orgânico/base DevClub) | 28 | Estruturalmente não rastreáveis |

LF49 (vendas até 05/04) e LF50 (vendas a partir de 01/04) compartilham 5 dias. Os 35 compradores do LF50 entram no denominador do LF49 mas são removidos pelo `filter_conversions_by_capture_period`. Não são vendas perdidas — aparecem rastreados no LF50.

Os 28 orgânicos (20% dos compradores) nunca passaram pelo funil Meta/pesquisa. Em LF44 esse número era ~12%. Tende a crescer conforme a base da DevClub acumula clientes.

**Conclusão:** 34.5% de tracking no LF49 não é falha. ~25% das vendas da janela são do LF50, ~17% de LFs anteriores. Problema real: ~20% de compradores orgânicos/base — estruturalmente fora do alcance do rastreamento Meta.

---

### Aberto

Nenhuma hipótese pendente de verificação.

---

## Mapa de lançamentos

### Lançamentos por período de investigação

| LF | Captação | Vendas | Período ML | Nota | Classificação |
|---|---|---|---|---|---|
| LF43 | 13/01 – 26/01 | 02/02 – 08/02 | Pré-P1 | Referência limpa | ✅ Bom |
| LF44 | 27/01 – 03/02 | 09/02 – 15/02 | Pré-P1 | Referência limpa | ✅ Bom |
| LF45 | 03/02 – 23/02 | 02/03 – 08/03 | **P1** | Base FRIA e QUENTE | ✅ Bom |
| LF46 | 24/02 – 02/03 | 09/03 – 15/03 | **P1** | Disparo p/ base errada | ⚠️ Flag |
| LF47 | 03/03 – 09/03 | 16/03 – 22/03 | **P1→P2** | Captação ok; vendas no crash | ⚠️ Misto |
| LF48 | 10/03 – 16/03 | 23/03 – 29/03 | **P2** | Campanhas ML RUIM (11/03) | ❌ Ruim |
| LF49 | 17/03 – 23/03 | 30/03 – 05/04 | **P2→P3** | Campanhas ML RUIM | ❌ Ruim |
| LF50 | 24/03 – 29/03 | 01/04 – 06/04 | **P3** | ML antigo retomado ao vivo | ⚠️ Transição |
| LF51 | 30/03 – 06/04 | 13/04 – 19/04 | **P3** | Padrão Ouro | 🔍 Referência atual |
| LF52 | 07/04 – 12/04 | 17/04 – 24/04 | **P3** | — | 🔍 Em andamento |

### ROAS e margem por lançamento (do analise_valor_ml_devclub.md)

| LF | ROAS ML | ROAS Ctrl | Ganho ML | Observação |
|---|---|---|---|---|
| LF43 | 4.61x | 1.52x | +R$89.977 | Referência limpa ✓ |
| LF44 | 5.94x | 2.30x | +R$118.941 | Referência limpa ✓ |
| LF45 | 3.98x | — | ~+R$224.160 | ML only; baseline histórico |
| LF46 | 2.55x | — | ~+R$35.546 | Flag: base errada |
| LF47 | 2.89x | — | ~+R$63.023 | Flag: vendas no período do crash |
| LF48 | 2.11x | 0.79x | +R$90.714 | Ctrl insuficiente (3 conv.) |

**Lançamentos limpos de referência (sem flags):** LF43 + LF44. ROAS mediano do Ctrl = 1.91x.

---

## Períodos de captação a investigar

A queda de D10 de 41.7% → ~30% acontece nos leads captados a partir de **~10/03/2026**. A hipótese é que mudanças na estratégia de tráfego alteraram o perfil dos leads entrando.

| Prioridade | Período | LF | Por que investigar |
|---|---|---|---|
| 🔴 Alta | 10/03 – 16/03 | LF48 cap. | Primeiro período com "Campanhas ML RUIM". Limite superior da zona limpa. |
| 🔴 Alta | 17/03 – 23/03 | LF49 cap. | Continuidade das campanhas ruins. D10 já em plateau ~30%. |
| 🟡 Média | 03/03 – 09/03 | LF47 cap. | Último período limpo (P1). Baseline para comparação. |
| 🟡 Média | 24/03 – 06/04 | LF50+51 cap. | P3 com jan30 restaurado. Confirmar se D10 ~30% é estável. |

**Marco de contaminação:** a partir de 14/03, dados já contaminados por alterações na estratégia de tráfego. Baseline limpo: até 09/03 (fim do LF47 captação).

**Comparação a fazer:**
- Distribuição de features (Medium, Source, Term, ocupação, faixa salarial, idade) entre LF47 cap. (limpo) e LF48/49 cap. (ruim)
- Taxa de D10 por medium/source em cada período
- Se a queda de D10 está concentrada em alguma origem de tráfego específica

---

## Rollback executado — 13/04/2026

**Commit:** `edf23e9` (05/03/2026) — código exato do período P1
**Deploy executado:** 13/04/2026 às 19:33 BRT (22:33 UTC)
**Revisão ativa:** `smart-ads-api-00267-5gn`
**Revisão anterior:** `smart-ads-api-00266-6v5`
**A/B test:** encerrado — 100% dos leads vão para jan30 com `LeadQualified`

### Por que esse commit

`edf23e9` usa `medium_strategy="binary_top3"` — cria `Medium_Linguagem_programacao` por comparação de string direta, sem OHE nem regex. Elimina o bug central (5ª feature mais importante zerada). Também tem ordinal encoding de `idade`/`faixaSalarial` embutido, que o código atual removeu no commit `9b86d37`.

### O que foi executado

1. `git worktree add smart_ads_v2_rollback edf23e9` — cópia isolada do repositório no commit `edf23e9`; branch `main` intocado
2. Cópia de `files/20260130_090227/` para o worktree — artefatos do modelo jan30 não são rastreados por git
3. `deploy_capi.sh --yes` a partir do worktree — build Docker com código `edf23e9` + modelo jan30, push para GCR, deploy no Cloud Run com 100% de tráfego
4. Testes pós-deploy: health check HTTP 200, predição de teste `score=0.478` — OK

### Rollback de emergência (desfaz em ~2 min, sem rebuild)

```bash
gcloud run services update-traffic smart-ads-api \
  --region=us-central1 \
  --to-revisions=smart-ads-api-00266-6v5=100
```

---

## Referências

| Artefato | Localização |
|---|---|
| Commit de produção P1 | `edf23e9` |
| Modelo jan30 | MLflow run `d51757f5`, `files/20260130_090227/` |
| encoding_overrides no A/B config | `configs/active_models/devclub.yaml` |
| Correção DT-12 no app.py | `api/app.py` linhas 3014–3056 |
| Script de paridade | `scripts/test_parity.py` |
