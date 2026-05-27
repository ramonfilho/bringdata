# Qualidade de Audiência — Diagnóstico e Sinal Diário

**Sistema Bring Data · Cliente DevClub · 11/05/2026**

> **Nota:** este relatório usou o pool anterior `LF40, LF41, LF45, LF50, LF53` como Top 5 ROAS realized. Definição canônica do Top 5 atualizada em 2026-05-14 (LF45, LF44, LF46, LF41, LF43) — ver [docs/METODOLOGIA_TOP5_ROAS.md](METODOLOGIA_TOP5_ROAS.md).

---

## Sumário executivo

Investigação para responder operacionalmente: **a audiência que está chegando ao lançamento atual sinaliza bom faturamento, considerando apenas o público?** Três abordagens metodológicas foram testadas; a vencedora foi integrada ao endpoint `/monitoring/daily-check` em produção.

**Achados-chave:**
- **Sinal univariado de features (P(target|valor)) descartado** — MAPE 43% em receita, Pearson 0.30 com ROAS. Detecta drift de mix mas não prediz absolutos.
- **Backtest do RF** (LF52 + LF53 first peak, OOS): Challenger `abr28` com lift D10 de **1.8–2.2×** vs Champion `jan30` de **1.4×**. Calibração de ambos ~60× off (score é rank, não probabilidade absoluta).
- **Sinal escolhido:** %D9-D10 e score médio do Challenger no LF atual comparados ao baseline pré-computado dos Top5 ROAS realized (LF40, LF41, LF45, LF50, LF53).
- **LF54 e DEV20:** ambos **DENTRO do padrão histórico** de bons lançamentos. DEV20 inclusive sinaliza ligeiramente acima (+3pp em D9-D10).

> **Resultado em produção (11/05/2026):** Revisão `smart-ads-api-00439-fir` em 100% do tráfego. Daily-check emite o bloco `audience_quality_signal` todo dia comparando o LF ativo vs baseline. Hoje: LF54 (n=5.576 leads) DENTRO do padrão, Δ%D9-D10 = +1.8pp, Δscore = +0.3%.

---

## 1. Pergunta-objeto

O sistema Bring Data já fornece o score do modelo (Random Forest) por lead. O score é usado para enviar eventos qualificados ao Meta (CAPI) e para o forecast de faturamento que existe no endpoint de monitoramento.

A pergunta operacional desta investigação é diferente: **tirando o score do modelo, a composição da audiência atual (gênero, idade, ocupação, faixa salarial, etc.) está sinalizando faturamento bom ou ruim?** A motivação é construir um sinal secundário que possa servir de orientação durante o lançamento, e que complemente o forecast já existente.

---

## 2. Audiência usada

### 2.1 Pool de referência — Top5 ROAS realized

Cinco lançamentos cujo ROAS realizado (cobrado pelo cliente, descontados cancelamentos e ajustando TMB para 1/12 do ticket) foi mais alto entre todos os 16 ciclos cobertos pelo histórico (dez/2025 a abr/2026).

| Lançamento | Período de captação | Período de vendas | ROAS realized | Leads |
|---|---|---|---|---|
| LF40 | 25/11/2025 — 02/12/2025 | 08/12 — 14/12/2025 | **3.40** | 3.999 |
| LF41 | 02/12/2025 — 08/12/2025 | 15/12 — 21/12/2025 | **3.97** | 2.464 |
| LF45 | 03/02/2026 — 23/02/2026 | 02/03 — 08/03/2026 | **3.25** | 15.325 |
| LF50 | 24/03/2026 — 29/03/2026 | 01/04 — 06/04/2026 | **3.11** | 9.122 |
| LF53* | 13/04/2026 — 20/04/2026 | 27/04 — 03/05/2026 | **4.54** | 10.058 |

*\* LF53 — usou subset "first peak" (primeiros 3 dias de venda) para isolar o produto principal do upsell. ROAS de 4.54 considera só o primeiro pico.*

**Total do pool: 40.968 leads.** Pool definido após investigação comparativa entre 10 candidatos de referência (Top5 ROAS atual, ROAS realized com/sem outliers BF, interseção, mediana, etc.) — Top5 ROAS realized foi o de maior poder discriminante na correlação Spearman expected_conv × roas_realized das demais LFs (corr +0.66).

### 2.2 Pool de avaliação — LF atual + sanity

| LF | Estado | Captação | Vendas | Leads (em 11/05) |
|---|---|---|---|---|
| **LF54** | Em curso | 05/05 — 11/05/2026 | 18/05 — 24/05/2026 | 5.576 |
| **DEV20** | Cap encerrado | 21/04 — 04/05/2026 | 11/05 — 17/05/2026 | 29.298 |
| LF52* | Sanity check | 07/04 — 12/04/2026 | 17/04 — 24/04/2026 | 9.391 |

*\* LF52 — usado apenas como sanity check da metodologia. ROAS realized 2.46 (decente, não excepcional). Esperamos que fique "dentro do padrão" levemente abaixo.*

---

## 3. Features categóricas analisadas

Nove perguntas categóricas da pesquisa de captação são usadas em todas as análises:

| Feature | Valores |
|---|---|
| O seu gênero | Masculino / Feminino |
| Qual a sua idade | <18, 18-24, 25-34, 35-44, 45-54, 55+ |
| O que você faz atualmente | CLT, Autônomo, Estudante, Sem trabalho/estudo |
| Atualmente, qual a sua faixa salarial | 6 faixas, "sem renda" → ">R$15k" |
| Você possui cartão de crédito | Sim / Não |
| O que mais quer ver no evento | Programação / Mentoria / Outros |
| Tem computador/notebook | Sim / Não |
| Já estudou programação | Sim / Não |
| Pretende fazer faculdade | Sim / Não |

---

## 4. Metodologia — três abordagens testadas

### 4.1 Abordagem A — Sinal univariado P(target=1|valor) — descartada

Para cada feature × valor, calcular P(target=1|valor) no pool de referência via Empirical Bayes (prior_n=5). Combinar por feature via Naive Bayes log-odds e prever conversão esperada do LF alvo. Multiplicar por ticket médio realizado para obter receita prevista.

**Backtest (10 LFs fora da referência):** MAPE 43% em receita, MAPE 43% em ROAS, Pearson 0.30 com ROAS, acurácia direcional 60% (apenas 10pp acima do chute).

Conclusão: a metodologia univariada não prediz faturamento absoluto. **Detecta drift de mix mas não substitui o modelo**. Razão: independência assumida entre 9 features subestima interações multivariadas que o RF captura.

### 4.2 Abordagem B — Re-scorear com o Random Forest existente — adotada

Em vez de inventar uma nova métrica, usar o próprio modelo Random Forest do sistema. Para o pool de referência e o LF atual, scorear todos os leads com o mesmo modelo, calcular percentual de leads em D9-D10 e score médio. Comparar.

Esta abordagem captura as **interações multivariadas** que a univariada perde. O Random Forest, treinado com 60 features pós-encoding, modela combinações como "homem, 18-24, CLT, com cartão" que individualmente são fracas mas juntas são preditivas.

### 4.3 Abordagem C — Usar Lead.decil já gravado em produção — descartada

Consultar o decil que produção atribuiu via Cloud Run a cada lead, sem re-scorear. Vantagem: simplicidade total. **Descartada** porque os leads dos lançamentos históricos foram escorados por **versões diferentes do código e modelo**: o Champion `jan30` esteve ativo, mas o patch DT-12 (que corrigia idade/salário cegos via encoding overrides) só entrou em 02/05/2026. Comparar `Lead.leadScore` antigo com `Lead.leadScore` atual mistura cobertura de bug.

> **Decisão metodológica chave:** Re-scorear TUDO agora (baseline histórico + LF atual) com o mesmo código e o mesmo modelo. Self-consistent por construção. Não depender de fotografias antigas do score salvas em produção.

---

## 5. Backtest do Random Forest — Champion vs Challenger

Antes de adotar o score do RF como sinal, validamos sua capacidade preditiva em lançamentos out-of-sample para ambos os modelos ativos. Dois modelos vivem no A/B test atual:

| Modelo | Run ID | Treino até | Roteamento |
|---|---|---|---|
| **Champion jan30** | `d51757f5...` | 04/11/2025 | Default (sem UTM HQLB) |
| **Challenger abr28** | `5d158f0a...` | 08/04/2026 | utm_campaign "utm_pixel" ou URL `ml-parabens-psq-devf` |

**LFs out-of-sample escolhidos:** LF52 (cap 07-12/04, n=9.391 leads) e LF53 first peak (cap 13-20/04, n=10.054). LF52 é OOS para o Champion (treino até 04/11) e parcial OOS para o Challenger (3 dias dentro do treino). LF53fp é 100% OOS para ambos.

### 5.1 Discriminação (lift por decil)

| Métrica | LF52 | LF53fp |
|---|---|---|
| Lift D10 — Champion jan30 | 1.39× | 1.37× |
| **Lift D10 — Challenger abr28** | **1.81×** | **2.19×** |
| Concentração top30 — Champion (D8-D10 = 60% leads) | 81% | 68% |
| **Concentração top30 — Challenger (D8-D10 = 34% leads)** | **61%** | **53%** |
| ROAS top30 offline — Champion | 3.26 | 1.80 |
| **ROAS top30 offline — Challenger** | **4.31** | **2.35** |

**Leitura:** em ambos os LFs OOS, o Challenger discrimina 30-60% melhor que o Champion (lift D10 mais alto). Em LF53fp — 100% out-of-sample do Challenger — o lift D10 atinge 2.19×, o que significa que a taxa de conversão real do D10 é **2.19× a baseline**. Esse é o sinal preditivo que importa para o Meta otimizar audiência.

### 5.2 Calibração (score absoluto)

| Métrica | Champion jan30 (LF52) | Challenger abr28 (LF52) |
|---|---|---|
| Score médio do modelo | 0.387 | 0.417 |
| Taxa real de conversão | 0.69% | 0.69% |
| **calib_ratio (score / taxa real)** | **56×** | **60×** |

> **Diferença crítica — discriminação ≠ calibração**
>
> O score do RF está **56-60× a taxa real** de conversão. Isso não é bug — é estrutural: o modelo foi treinado com class balancing, e `predict_proba` devolve um score de **ranking**, não uma probabilidade calibrada. Por isso o "Champion prevê faturamento maior do que o real" é literal, mas não é erro do modelo — é decisão de design. **Σ(score) × ticket NÃO é receita prevista útil.** Para predizer faturamento absoluto, seria preciso recalibrar via Platt scaling ou isotonic regression (item de backlog). Para o sinal de drift, basta usar rank (% leads em decis altos), que é o que esta investigação faz.

---

## 6. Sinal final — qualidade de audiência LF54 e DEV20

Aplicamos a abordagem B (re-scorear com Challenger) sobre os 5 LFs do pool de referência e sobre LF54 + DEV20. Calculamos para cada LF o score médio, %D10, %D9-D10 e %D8-D10. O baseline ponderado pelo volume de leads do pool é a régua de comparação.

### 6.1 Métricas por LF

| LF | n leads | score médio | %D10 | %D9-D10 | %D8-D10 |
|---|---|---|---|---|---|
| ★ LF40 | 3.986 | 0.4302 | 11.5% | 23.5% | 36.4% |
| ★ LF41 | 3.984 | 0.4379 | 11.8% | 26.5% | 34.5% |
| ★ LF45 | 8.531 | 0.4559 | 17.1% | 30.5% | 43.1% |
| ★ LF50 | 9.122 | 0.4209 | 12.2% | 23.7% | 35.0% |
| ★ LF53fp | 10.054 | 0.4159 | 11.6% | 23.3% | 34.0% |
| **Baseline (pond.)** | **35.677** | **0.4308** | **13.1%** | **25.5%** | **36.7%** |
| **◆ LF54 (atual)** | **5.532** | **0.4319** | **13.9%** | **27.3%** | **38.9%** |
| **◆ DEV20 (cap fim.)** | **29.298** | **0.4401** | **15.7%** | **28.7%** | **40.6%** |
| · LF52 (sanity) | 9.391 | 0.4169 | 12.1% | 23.5% | 34.4% |

*★ = LFs do pool de referência (Top5 ROAS realized). ◆ = LFs avaliados (LF54 em curso, DEV20 com captação encerrada). · = sanity check.*

### 6.2 Δ vs baseline (régua única — Challenger abr28)

| LF | Δscore | Δ%D10 (pp) | Δ%D9-D10 (pp) | Sinal |
|---|---|---|---|---|
| **LF54** | +0.3% | +0.8 | **+1.8** | DENTRO do padrão |
| **DEV20** | +2.2% | +2.7 | **+3.2** | DENTRO (ligeiramente acima) |
| LF52 | -3.2% | -1.0 | -2.0 | DENTRO (ligeiramente abaixo) |

> **Conclusão prática**
>
> **LF54 (5.576 leads parcial) e DEV20 (29.298 leads, captação encerrada) têm audiência DENTRO do padrão histórico de bons lançamentos.** DEV20 inclusive sinaliza ligeiramente acima (+3.2pp em D9-D10, +2.2% em score médio). Não há indício de degradação de público. Se houver problema, está em outro lugar (criativo, taxa de conversão da página, mix de produto, sazonalidade).

**Sanity check passou:** LF52, cujo ROAS realized foi 2.46 (decente mas não top), ficou levemente abaixo do baseline (-2.0pp em D9-D10) — alinhado com sua performance histórica intermediária. Isso valida que a métrica é estável e discriminante.

---

## 7. Integração no endpoint de monitoring

O sinal foi integrado ao `/monitoring/daily-check/railway` do Cloud Run. Toda execução diária do monitoramento (via Cloud Scheduler) passa a emitir um bloco `audience_quality_signal` que aparece junto com os demais alertas no digest.

### 7.1 Arquitetura

**Chain idêntica à produção:** a função `_check_audience_quality_signal` chama `LeadScoringPipeline.run` com tempfile CSV e `predictor_override=Challenger` — exatamente o que o webhook de produção faz em `api/app.py:345` (batch) e `:959` (síncrono). Reusa o `LeadScoringPipeline` já carregado no startup via injeção de dependência (orchestrator → DataQualityMonitor).

**Baseline pré-computado** em `configs/reference_audience_profiles/devclub_quality_signal.json` com as métricas do Top5 ROAS realized. Re-gerar quando trocar de modelo Challenger.

### 7.2 Severidade do alerta emitido

| Condição | Severity | Sinal |
|---|---|---|
| Δ%D9-D10 ≤ -5pp OU Δscore ≤ -10% | **HIGH** | Audiência ABAIXO do padrão (alerta) |
| Δ%D9-D10 ≤ -3pp OU Δscore ≤ -5% | **MEDIUM** | Levemente abaixo (atenção) |
| Δ%D9-D10 ≥ +3pp E Δscore ≥ +5% | **LOW** | ACIMA do padrão (informativo) |
| Faixa neutra entre os limites | **LOW** | DENTRO do padrão (informativo) |

### 7.3 Deploy

Revisão Cloud Run `smart-ads-api-00439-fir` deployed em 11/05/2026 10:44 BRT, promovida para 100% do tráfego após smoke test e validação do bloco em chamada direta na revisão canary.

### 7.4 Resultado real em produção (chamada em 11/05/2026 08:36 BRT)

Saída do digest do `/monitoring/daily-check/railway?hours=1` capturada do endpoint em produção logo após a promoção:

```
══════════════════════════════════════════════════════════════════════════════
  DAILY CHECK — DevClub
  timestamp: 2026-05-11T08:36:19.099593
  rev: smart-ads-api-00439-fir · scoring há 1.0 min
  STATUS: 3 HIGH · 0 MEDIUM · 4 LOW · total 7
══════════════════════════════════════════════════════════════════════════════

🔴  DISTRIBUTION_DRIFT  (HIGH) · Medium · champion_jan30
    aberto                                                    14.5% →   90.6%  (+76.1pp)
    linguagem de programacao                                  33.0% →    0.0%  (-33.0pp)
    lookalike 2 cadastrados dev 20 interesses                 21.1% →    0.0%  (-21.1pp)

🔴  DISTRIBUTION_DRIFT  (HIGH) · Medium · challenger_abr28
    aberto                                                    49.9% →   90.6%  (+40.7pp)
    linguagem de programacao                                  16.1% →    0.0%  (-16.1pp)

🔴  AUDIENCE_PROFILE_DRIFT  (HIGH)
    Janela lanç.: LF54 2026-05-05 BRT 00:00→2026-05-11 08:35 (parcial) (n=5271)
    Janela ontem: 2026-05-10 BRT (último dia completo) (n=713)
    Janela hoje:  2026-05-11 BRT 00:00→08:35 (parcial) (n=187)
    Referência:   Top 5 ROAS realized (n=40,968)
    Threshold:    ≥5pp

    Característica                          Top5       Lanç. (Δ)       Ontem (Δ)        Hoje (Δ)
    ────────────────────────────────────────────────────────────────────────────────────────────
    Ocupação: Estudante                    17.9%   21.6% ( +3.6)   23.7% ( +5.8)   18.2% ( +0.3)
    Idade: <18                              7.8%    9.6% ( +1.8)   13.0% ( +5.2)    6.4% ( -1.4)
    Já Estudou Programação: Sim            34.4%   35.2% ( +0.8)   39.4% ( +5.0)   36.9% ( +2.5)
    Idade: 18-24                           22.3%   27.2% ( +4.8)   24.1% ( +1.8)   31.0% ( +8.7)
    Faixa Salarial: Sem renda              27.6%   32.0% ( +4.4)   28.9% ( +1.3)   22.5% ( -5.2)
    [...]

⚪  CATEGORY_DRIFT  (LOW) · telefone_comprimento · champion_jan30
    novas: outros  ·  1 leads  (1.9%)

⚪  DISTRIBUTION_DRIFT  (LOW) · Atualmente, qual a sua faixa salarial? · champion_jan30
    entre r1000 a r2000 reais ao mes                          32.4% →   17.0%  (-15.4pp)

⚪  SCORE_DISTRIBUTION_CHANGE  (LOW)
    Distribuição de decis mudou: D5: 5% → 19% (+13.7pp)

🔵  AUDIENCE_QUALITY_SIGNAL  (LOW) · LF54 — DENTRO do padrão
    Modelo:       challenger_abr28 (run_id=5d158f0a…)
    Lançamento:   LF54 cap 2026-05-05→2026-05-11 (n=5,576)
    Baseline:     Top 5 ROAS realized (n=35,677)

    Métrica            Atual  Baseline         Δ
    ────────────────────────────────────────────
    score médio       0.4322    0.4308     +0.3%
    %D10               14.0%     13.1%    +0.9pp
    %D9-D10            27.3%     25.5%    +1.8pp
    %D8-D10            38.9%     36.8%    +2.1pp
```

**Bloco `audience_quality_signal` (em azul, severity LOW)** entrou no digest com payload completo: modelo identificado, n de leads atual, baseline, e tabela Atual / Baseline / Δ. O sinal **DENTRO do padrão** confirma os achados das seções 6.1–6.2.

Observe também que outros alertas pré-existentes ainda aparecem (drift de Medium = HIGH porque tráfego está mudando de "linguagem de programacao" para "aberto", drift de perfil de audiência sob threshold 5pp, etc.). O novo bloco é complementar — não substitui o drift de mix categórico do `_check_audience_profile_drift`.

---

## 8. Limitações conhecidas

**1. Score absoluto não-calibrado.** calib_ratio ~60× — para predição de R$ absoluto, seria necessária recalibração via Platt scaling ou isotonic regression. Item de backlog. Para o sinal de drift adotado, basta o rank, então não é bloqueador.

**2. Sinal é premissa, não previsão.** Audiência com composição similar aos bons LFs (medida pelo modelo) *sugere* faturamento similar. Pode falhar se o Meta entregar leads bem-ranqueados pelo modelo mas com criativo/fluxo/landing page ruim. O sinal não substitui o forecast de receita do endpoint, apenas o complementa.

**3. Paridade backtest vs Lead.leadScore: 23%.** Comparando re-score atual com o valor salvo pelo Cloud Run em produção, a coincidência exata é de apenas 23% (decil bate em 52%). Causa raiz não identificada (testamos round-trip xlsx vs csv, race condition em `createdAt` vs `updatedAt`, mudanças de schema). Possíveis explicações: estado dinâmico do `pesquisa` jsonb (parcial no momento do score em prod, completo agora), versões de código diferentes entre score em prod e re-score agora. Mitigação adotada: **não usar Lead.leadScore — re-scorear tudo agora com mesma chain**, garantindo self-consistency.

**4. Challenger parcialmente in-sample para LF45/LF50 do baseline.** O Challenger abr28 teve cutoff em 08/04/2026 — LF45 e LF50 estão dentro do training+test do Challenger. Apenas LF53fp é 100% OOS. Para o baseline (régua de comparação) isso não é problema; para validar capacidade preditiva do modelo, usei LF53fp como OOS puro.

**5. Spread baixo entre os deltas observados.** LF52 (-2pp), LF54 (+1.8pp), DEV20 (+3.2pp). O sinal de drift dentro do esperado tem amplitude pequena — não classifica em "ótimo / médio / ruim". Está dizendo apenas: "audiência similar aos bons" ou "diferente". Para classificações finas, seria preciso baseline maior + threshold calibrado em mais lançamentos.

---

## 9. Próximos passos / backlog

**1. Recalibração do score do RF.** Treinar uma camada de calibração isotônica num holdout pós-train (~30min de trabalho). Salvar a curva no MLflow junto com o modelo. Output: score do RF passa a ser uma probabilidade calibrada (Σ(score) ≈ buyers reais). Não muda nada no rank (lift D10 idêntico), mas resolve o viés sistemático do revenue forecast (que hoje tem patches heurísticos).

**2. Acompanhar LF54 até o fim do ciclo.** Δ%D9-D10 = +1.8pp parcial; o sinal pode se mover quando a captação fechar (11/05). O daily-check vai mostrar o valor atualizado diariamente.

**3. Re-validar quando próximo Champion entrar.** O backtest precisa ser refeito com modelo novo. Baseline JSON pré-computado também precisa ser regerado.

**4. Investigar causa raiz da divergência backtest vs Lead.leadScore.** 77% de divergência indica algo estrutural (estado dinâmico, race condition). Não bloqueia o sinal porque já adotamos self-consistency, mas vale entender pra futuras integrações que dependam de `Lead.leadScore`.

---

*Bring Data · maio/2026*
