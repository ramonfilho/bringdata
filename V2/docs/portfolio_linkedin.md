# Portfólio LinkedIn — Bring Data V2

Knowledge base para o agente `/linkedin` compor posts. Não é material de venda — é o inventário técnico pessoal de Ramon Filho sobre o projeto Bring Data como portfólio.

**Regras duras de uso:**
- Todo número sai deste arquivo ou de `/comercial`. Se precisar de um número que não está aqui, parar e perguntar.
- **DevClub** é o único cliente citável por nome (já público nas propostas).
- **Cliente B** e prospects: nunca nomear em post.
- Nunca prometer resultado futuro ("vamos gerar X", "garantimos Y"). Sempre "verificado em operação real".
- Direcional > específico quando o número pode envelhecer.
- Quando em dúvida, preferir a versão mais honesta (ex.: "5 de 7 A/B com p<0,05" > "12/12 superou o controle").

---

## 1. O PROJETO EM UMA FRASE

Sistema de lead scoring por ML que, em menos de 5 minutos após o lead chegar, envia um sinal calibrado ao Meta via Conversions API com valor proporcional à propensão de compra (decil D01–D10). Rodando em produção desde dez/2025 com o cliente DevClub.

**Por que isso importa:** o Meta otimiza anúncios a partir de eventos de conversão. O evento padrão `Purchase` só acontece 7–21 dias depois da compra real. `LeadQualified` com score calibrado chega em 5 min — o algoritmo aprende 56× mais rápido. Campanhas novas saem do "modo exploração" em 7 dias em vez de 35–70.

---

## 2. ESCALA E VOLUME (números do próprio projeto)

| Métrica | Valor |
|---|---|
| Período ativo | abr/2025 → presente (**12+ meses**) |
| Commits | **688** |
| Dias com commits | **154** |
| LOC adicionadas / removidas | **537.903 / 285.384** (net +252k) |
| LOC total | **48.737** em **121 arquivos Python** |
| YAMLs de config | **144** |
| Endpoints FastAPI `/v1/*` | **31** |
| `api/app.py` | 3.527 LOC |
| `src/core/` (SSoT de transformações) | 15 módulos, 3.942 LOC |
| `src/validation/` | 25 módulos, 20.308 LOC |
| Scripts de análise | 26 (11.386 LOC) |
| Leads processados em produção | ~100k (Railway) |

---

## 3. STACK TÉCNICA (vocabulário para tagging de posts)

**Backend / API**
- FastAPI 0.104, Uvicorn, Pydantic 2.4
- SQLAlchemy 2.0, psycopg2, pg8000

**ML / Dados**
- scikit-learn 1.6 (RandomForest, 59 features, AUC 0.745)
- pandas 2.0, joblib
- MLflow (tracking em Cloud SQL Postgres, artifacts em GCS)

**Cloud — GCP**
- Cloud Run (API + Jobs)
- Cloud Scheduler (monitoramento diário + retreino mensal)
- Cloud SQL Postgres (MLflow backend)
- Cloud Storage (artifacts, caches)
- Cloud Logging
- BigQuery (análises ad-hoc)

**Bancos**
- Railway PostgreSQL (~100k leads em produção)
- Cloud SQL Postgres (MLflow)

**Integrações externas**
- Meta Conversions API (`facebook-business` 19.0.3)
- Guru API (plataforma de vendas)
- Hotmart API (plataforma de vendas)
- Google Sheets API + Apps Script

**Patterns MLOps já em produção**
- Feature registry sincronizado treino↔produção via MLflow
- Parity audit por snapshot de (input, output) coluna-a-coluna
- Champion/challenger A/B por UTM com event names distintos
- Canary deploy gradual (`--no-traffic` → 5% → 10% → 100%)
- Schema validation pré-treino
- Fail-loud asserts obrigatórios em `src/core/`
- Dispatch CAPI por plataforma (`utm_source_allowlist`)

---

## 4. NÚCLEO TÉCNICO — DECISÕES DE DESIGN POSTÁVEIS

### 4.1 SSoT em `src/core/` (nasceu de um bug)
15 módulos consolidam transformações de 3 pipelines (treino, produção, monitoramento) em uma única implementação. Contrato de assinatura: `transform(df, config, **artifacts) -> df`.

**Motivação real:** em mar/2026 descobri que treino e produção aplicavam regras diferentes para encoding, Medium e UTM — divergências que estavam no código há meses, mascaradas porque o modelo anterior tinha sido treinado e servido com as mesmas regras erradas. Ao trocar o modelo, a divergência veio à tona: o score em produção não correspondia ao esperado pelo treino. O refactor inteiro nasceu desse incidente.

**Módulos principais:**
- `preprocessing.py` — orquestra a sequência canônica
- `encoding.py` — ordinal + one-hot com feature registry do MLflow
- `matching.py` — consolidou 6 arquivos antigos (`src/matching/`) em 1
- `utm.py`, `medium.py` — unificação de canais (consolidou 3 arquivos de Medium em 1)
- `feature_engineering.py` — features derivadas
- `client_config.py` — dataclass com 15 sub-configs

### 4.2 ClientConfig multi-cliente (153 hardcodes → 1 YAML)
Dataclass tipado em Python com 15 sub-configs e ~130 campos parametrizando **153 hardcodes** extraídos do código. Onboarding de novo cliente não requer alteração de código — é 1 YAML.

Sub-configs: `InfraConfig`, `IngestionConfig`, `UTMConfig`, `MediumConfig`, `MatchingConfig`, `EncodingConfig`, `MonitoringConfig`, `ModelConfig`, `BusinessConfig`, `CAPIConfig`, `ABTestConfig`.

### 4.3 Padrão A2 — pipelines dict por client_id
```python
pipelines: Dict[str, LeadScoringPipeline]
```
Header `X-Client-ID: devclub`. Suporta N clientes em um único serviço Cloud Run.

### 4.4 A/B testing via UTM + event names CAPI distintos
Gestor de tráfego cria dois grupos de campanhas com UTMs diferentes (ex.: `ML_V1` vs `ML_V2`). Pipeline detecta pelo UTM do lead qual modelo rodar. Cada modelo envia evento CAPI com nome diferente (`LeadQualified` vs `LeadQualifiedCha`).

**Consequência:** Meta atribui compras a cada evento separadamente — ROAS por variante é lido direto no Ads Manager, sem análise contrafactual. Crítica de promoção: ROAS do challenger ≥ champion após 1 lançamento com janela de conversão fechada (≥27 dias).

### 4.5 Parity audit (o teste que pega o que humano não pega)
`train_pipeline.py --capture-parity-snapshots` captura (input, output) de 4 transformações críticas (UTM, Medium, feature_engineering, encoding). Depois `tests/parity_audit.py` compara coluna-a-coluna treino vs produção, falha alto em divergência, lista as top 3 colunas divergentes.

Foi o teste que pegou o bug histórico de `Medium_Linguagem_programacao` zerada.

### 4.6 Retraining orchestrator com hook injection
Retreino mensal reutiliza 100% do `train_pipeline.py` via hook injection — zero duplicação de lógica. Compara champion (em produção) vs challenger (novo): AUC, monotonia entre decis, concentração de positivos. Deploy condicional por quality gate.

### 4.7 Dispatch CAPI por plataforma (DT-CAPI-01)
`utm_source_allowlist` em `CAPIConfig`: só envia evento Meta se `utm_source` estiver na lista permitida (`["facebook-ads", "instagram"]`). Leads de Google Ads e orgânicos recebem `capiStatus = 'skipped'`.

**Por que:** incluir leads que o Meta nunca gerou faz o algoritmo aprender padrões que ele não consegue usar para targeting — dilui o sinal sem benefício. Descoberta de abr/2026.

### 4.8 Validador pré-encoding (Safeguard T1-11)
Contrato offline via snapshot de features esperadas + validação runtime com tolerância configurável de missing por feature. Log JSON estruturado. Endpoint `/monitoring/feature-report`.

### 4.9 Fail-loud em todo transform novo
Regra dura em `CLAUDE.md`: todo transform novo em `src/core/` inclui pelo menos um `assert` que falha alto se output for inesperadamente zero/nulo. Se remover o assert não causaria confusão em produção, não precisa. Se causaria — obrigatório.

Motivado por dois bugs reais: `Medium_Linguagem_programacao` zerada por semanas e D9 sem eventos por 2 meses. Falhas silenciosas degradam sinal sem avisar.

### 4.10 Progression gate (Safeguard T2-7)
Script que bloqueia progressão de tráfego canary → 100% se métricas pré-definidas não estiverem dentro de bandas esperadas (AUC, distribuição de decis, taxa de envio CAPI). Complementa o protocolo manual de deploy.

---

## 5. WAR STORIES (ouro para posts "lição aprendida")

### 5.1 D9 sem eventos CAPI por 2 meses
Bug de comparação de strings: código comparava `'D9'` mas sistema formatava decis como `'D09'`. Resultado: nenhum lead classificado como D9 gerava evento CAPI por ~2 meses. Nenhum alerta automático. Só descoberto em auditoria de distribuição de decis no banco.

**Correção estrutural:** alerta automático CAPI por decil com 0 eventos (Safeguard T1-2).

**Ângulo postável:** "Tive um bug que sumiu 10% dos meus eventos de conversão por 2 meses. Não era crash. Era um `'D9' vs 'D09'` de caractere."

### 5.2 `Medium_Linguagem_programacao` zerada — a 5ª feature mais importante
5ª feature mais importante do modelo (5,31% de peso) estava sendo preenchida com zero para 100% dos leads desde que o modelo foi implantado. Bug silencioso — nenhum erro explícito, apenas eliminação do sinal. Descoberto ao investigar queda de D10% após rollback: mesmo com modelo correto, D10 estabilizou em ~30% em vez de voltar aos ~42% de antes.

**Correção estrutural:** validador pré-encoding (T1-11) + fail-loud obrigatório em core.

**Ângulo postável:** "Tinha uma feature de 5% de peso zerada em produção. Não era bug. Era encoding divergente entre treino e produção."

### 5.3 Deploy de modelo novo com 100% de tráfego (15/03/2026)
Ativei um modelo novo sem estratégia de canário. O modelo tinha sido treinado com parâmetros diferentes e a divergência de paridade treino/produção descrita em 5.4 veio à tona exatamente nesse momento: **D10 colapsou de 20% para 5% em 48 horas**. Rollback manual alguns dias depois. Tempo de exposição com sinal degradado: ~10 dias.

**Correção estrutural:** protocolo obrigatório `--no-traffic` + canary 5%→10%→100% com progression gate (T1-9, T2-7).

**Ângulo postável:** "Deployei um modelo novo com 100% de tráfego. D10 caiu 75% em 48h. Aprendi caro."

### 5.4 Divergência sistêmica treino/produção
Encoding, Medium e UTM aplicavam regras diferentes entre treino e produção há meses, mascarados porque o modelo tinha sido treinado e servido com as mesmas regras erradas. Descoberto ao trocar de modelo. Motivou o refactor `src/core/` inteiro.

**Ângulo postável:** "A consistência entre treino e produção é um teorema, não um acordo de cavalheiros."

### 5.5 Feedback loop de 3 meses sem grupo controle
Modelo foi treinado em dados produzidos por ele mesmo: classificou leads em D10, direcionou orçamento, Meta passou a entregar mais leads com esse perfil, que eram super-representados no próximo treino. **D10 chegou a 41% dos leads (esperado ~10%).** Feedback loop ativo desde dez/2025, diagnosticado só em 11/03/2026. Grupo controle (10–20% do budget fora do ML) ativado em 15/03/2026.

**Ângulo postável:** "Meu modelo treinou em dados que ele mesmo produziu por 3 meses. O D10 chegou a 41% — quase 5× o esperado. Grupo controle não é luxo, é infraestrutura."

### 5.6 Mudança de evento de otimização sem grupo controle
10/03/2026: migrei todas as campanhas de `LQHQ` (só D9-D10, sinal de topo) para `LQ` (todos decis com valor proporcional) de uma vez, sem A/B. Meta recalibrou para audiência mais ampla. **D10 caiu de ~42% para ~30% em 2 dias.**

**Correção estrutural:** A/B via UTM com event names distintos (§4.4).

### 5.7 Valor CAPI errado em 3 gerações
- **v1:** tabela fixa hardcoded descolada do produto real
- **v2 (15/03):** correção do formato `D1 → D01` quebrou, gerando valores nulos em 9/10 decis por dias
- **v3 (22/03):** cálculo runtime `ticket_médio × taxa_conversão_decil` — mas `ticket_médio` era média simples (não ponderada Guru-à-vista vs TMB-parcelado)
- **v4 (03/04):** ticket Guru real × fator de realização TMB

**Ângulo postável:** "O número que você envia ao Meta é a função-objetivo do algoritmo dele. Errei esse número 3 vezes. Cada erro virou um trimestre de ajuste."

### 5.8 Timezone bug recorrente em 3 componentes
UTC vs Brasília (UTC−3). Apareceu em 17/01 (monitoramento × Sheets), 18/02 (filtro com sinal invertido — somou em vez de subtrair), 19/02 (Railway × hora do servidor). Leads perdidos em janelas de corte.

**Correção estrutural:** regra dura `datetime.now(timezone.utc)` em todo o código (T1-4).

### 5.9 UTM fantasma (origens não mapeadas)
`ig`, `manychat`, `org`, campo vazio viraram features zeradas no modelo ao aparecer em produção. Três correções ao longo de 2 meses, todas reativas. Reincidiu em UTM Term (`'0405'` com 669 leads/dia, 16% do volume) — a lógica de unificação tinha uma exceção para preservar códigos numéricos que virou brecha.

**Lição:** regras de unificação de UTM precisam ser whitelist estrita, sem ramos condicionais que "preservam" casos.

### 5.10 FBP/FBC — 4 tentativas no mesmo dia
Percentual de cobertura de cookies calculado errado em 4 formas distintas, todas no mesmo dia (03/04/2026): (1) sem filtro de período, (2) filtro só no numerador, (3) duplicatas não deduplicadas, (4) JOIN finalmente correto por email + período + dedup.

**Lição:** cálculo incremental sem número de referência externo acumula erros — cada correção resolvia um problema mas criava outro porque não havia como validar.

### 5.11 Janela de conversão assimétrica + TMB filter fora de ordem
**Janela assimétrica:** removia do dataset só os compradores que chegaram tarde. Não-compradores do mesmo período ficavam — criando ilusão de que "leads do fim raramente compram". Modelo aprendia padrão falso.

**TMB filter:** filtro de inadimplentes aplicado **depois** do matching com vendas. Compradores inadimplentes já tinham sido marcados como "comprou=sim" antes de serem filtrados, e ao sair do dataset desapareciam silenciosamente.

Ambos corrigidos em 06/03/2026, na auditoria do refactor.

---

## 6. RESULTADOS MENSURÁVEIS

### 6.1 Tabela oficial (usada em decks, sempre consistente entre canais)

| Métrica | Valor |
|---|---|
| Margem incremental verificada | **R$ 470.000** em 4 meses |
| Investimento do período | R$ 508.000 |
| Retorno extra por R$1 investido | **+92 centavos** |
| Receita mediana por real investido vs controle | **+131%** |
| CPL ML vs controle | **28–44% menor** em todos os períodos conclusivos |
| Superioridade ML vs controle | **12/12 lançamentos**, 7 A/B com grupo simultâneo |
| Testes A/B com p<0,05 | **5 de 7** (2 inconclusivos por N pequeno, direção positiva) |

### 6.2 Quebra fina (use em post técnico, quando rigor importa mais que impacto)

| Escopo | Valor | Método |
|---|---|---|
| **LF43 + LF44** (clean A/B, sem flags) | **+R$ 209k** | Contrafactual direto, auditável |
| **A/B total** (7 períodos com controle) | **+R$ 470k** | Contrafactual direto, inclui flagados |
| **LF45–LF47** (100% ML) | **~R$ 323k** | Estimativa sobre baseline 1,91× |
| **Total LF40–LF48** | **~R$ 793k** | Combinação |

### 6.3 Sinal de honestidade metodológica
- Valores são **conservadores** — tracking rate varia de 14,8% a 65% (subestimativa proporcional)
- **Sem canibalização:** correlação Pearson −0,23 entre % budget ML e ROAS controle
- LF48 controle com 3 conversões → excluído do baseline (CI 95%: [−0,10; 1,69])
- LF40 e LF41 inconclusivos por N pequeno (4 e 17 conversões ML), não por ausência de efeito

### 6.4 Mecanismo (para posts técnicos)
ML envia ao Meta sinais de leads de alta propensão (`LeadQualified` com score calibrado). Algoritmo do Meta aprende a encontrar esse perfil mais eficientemente no leilão → CPL **27–44% menor**. Com custo menor e taxa de conversão equivalente ou superior, ROAS sobe estruturalmente.

### 6.5 Modelo de referência em produção
- Run ID: `2a98e51c`
- AUC: **0.745**
- **59 features** (após feature engineering + encoding)
- Dataset: ~49.214 leads, 777 positivos
- Hiperparâmetros: RandomForest `n_estimators=200`, `max_depth=8`, `max_features="log2"`, `min_samples_leaf=3`, `class_weight="balanced"`

---

## 7. JORNADA DE MATURIDADE MLOps (posts de arco)

| Fase | Janela | Narrativa técnica |
|---|---|---|
| **Bootstrap reativo** | nov/25 – fev/26 | Cada componente novo (banco, CAPI, MLflow, deploy) estreou com bug de integração. Correções pontuais. Ausência de testes de integração era a causa raiz. |
| **Consolidação** | fev – mar/26 | Refactor `src/core/`. 6 arquivos de matching → 1. 3 arquivos de Medium → 1. 153 hardcodes → ClientConfig. Parity audit. Schema validation. |
| **Safeguards Tier 1** | abr/26 | 11 itens implementados um a um: encoding fail-loud, alerta CAPI por decil, dedup CAPI webhook, timezone UTC, parity audit no deploy, progression gate, coverage check, smoke test pós-deploy, validador pré-encoding, endpoint feature-report. |
| **Horizonte** | pós-Cliente B | GitHub Actions CI, BigQuery Feature Store, Vertex AI Model Registry, Pub/Sub + Dataflow — ativados por gargalos reais (3+ clientes, 10k+ leads/dia), não por prescrição. |

**Princípio de escalada:** cada nova peça de infraestrutura entra quando a atual vira gargalo real, não por "seguir as práticas". Cloud Run + MLflow + Postgres fica ~3 clientes; Vertex AI Model Registry entra quando aponta dor de gerenciar 3+ modelos manualmente.

---

## 8. NARRATIVA PESSOAL (posts de transição)

- **Transição atípica:** vendeu escola de budismo, foi estudar ML do zero
- **Formação técnica:** Stanford (ML), University of Michigan (Python), DeepLearning.AI (ML in Production), Google ML Engineer Certificate, MLOps Community, IBM (SQL/DB)
- **Bagagem de domínio:** 7 anos de mercado em captação, +120 ciclos de lançamento
- **Diferencial intelectual:** crítica a lead scoring linear via Kahneman ("ilusão da validade" em modelos lineares); RandomForest captura não-linearidade que pontuação por regras não consegue — o peso de uma variável muda dependendo do valor das outras
- **Referências comerciais que usa para explicar:** Netflix (predição de churn), Nubank (classificação de risco), iFood (recomendação)
- **Citação-assinatura:** "In God we trust, all others must bring data." — W. Edwards Deming

---

## 9. INVENTÁRIO DE TEMAS PARA POSTS

1. **Technical deep dive** — SSoT `src/core/`, A/B via UTM, feature registry, parity audit, dispatch por plataforma
2. **War stories / lição aprendida** — §5 inteiro: D9 silencioso, feature zerada, feedback loop, deploy 100%, timezone recorrente, valor CAPI errado
3. **Business value** — ROAS com contrafactual, CPL −44%, significância p<0,001, honestidade metodológica
4. **Design decisions** — multi-cliente via config, event names distintos no A/B, fail-loud vs silent warning, allowlist por plataforma
5. **Journey arc** — de bootstrap reativo a safeguards Tier 1, 153 hardcodes → ClientConfig, refactor nasceu de incidente
6. **Meta insights** — `LeadQualified` em 5 min vs `Purchase` em 21 dias, ilusão de validade em lead scoring linear, 56× mais aprendizado
7. **Carreira** — transição budismo → ML, formação, diferencial de domínio em captação
8. **Milestone / release** — primeiro mês 100% ML, refactor mergeado, Safeguard T1-X concluído, Cliente B onboardado (quando for público)

---

## 10. CLAIMS — PERMITIDOS E PROIBIDOS

### Permitidos (com fonte)

**Resultados de negócio:**
- "R$ 470.000 de margem incremental em 4 meses" ← /comercial
- "+92 centavos de margem extra por R$1 investido" ← /comercial
- "+131% de receita mediana por real investido vs controle" ← /comercial
- "CPL 28–44% menor que o controle" ← /comercial
- "12/12 lançamentos com ROAS > controle" ← /comercial
- "5 de 7 testes A/B com significância estatística (p<0,05)" ← versão mais honesta, analise_valor_ml
- "ROAS ML 1,95× a 3,03× o ROAS controle" ← §6.2
- "R$ 209k auditável em 2 lançamentos clean" ← §6.2 versão técnica

**Arquitetura e sistema:**
- "Em 5 minutos após o lead chegar" ← latência arquitetural
- "56× mais aprendizado" ← 30–40 LeadQualified/dia vs 10 Purchase/21 dias
- "Decis D01–D10" ← formato canônico
- "153 hardcodes extraídos para ClientConfig" ← refactor
- "15 módulos em src/core/" ← §2
- "31 endpoints FastAPI" ← §2
- "~100k leads em produção" ← direcional
- "RandomForest, 59 features, AUC 0.745" ← §6.5
- "688 commits em 12 meses" ← git log

**Formação:**
- Stanford ML, Michigan Python, DeepLearning.AI, Google ML Engineer, MLOps Community

### Proibidos

- Qualquer número que não está neste doc ou em `/comercial`
- Nome de clientes além de DevClub
- Nome de fornecedores, gestores, colegas sem autorização
- Valor de contratos, preços, MRR
- "Revolucionar", "transformar", "exponencial", "game-changer", "disruptivo"
- "Garantimos X", "vamos gerar Y", "com certeza resultará em Z"
- Crítica nominal a empresas concorrentes ou fornecedores
- Screenshots com emails, tokens, URLs de produção, dados de leads

---

## 11. TONS DE VOZ DISPONÍVEIS

| Tom | Quando usar | Marcadores |
|---|---|---|
| **Confidente técnico** | Deep dive, design decision | Primeira pessoa, código/config no miolo, admite trade-off |
| **Honesto com o bug** | War story | Começa pelo erro, impacto quantitativo, correção estrutural |
| **Mostra o resultado** | Business value | Número direto na primeira linha, método depois |
| **Contrarian** | Meta insight, crítica a prática padrão | Afirmação que desafia consenso, lógica por trás |
| **Celebrando marco** | Milestone | Fato concreto, crédito a quem ajudou se aplicável, próximo marco |

---

## 12. REGRAS DE FORMATAÇÃO PARA LINKEDIN

- Primeira linha é o **hook** — o que aparece antes de "ver mais". Nunca gastar com "Hoje eu quero falar sobre".
- Parágrafos curtos — máximo 3 frases. Usuário lê no celular.
- Linha em branco entre parágrafos — LinkedIn respeita quebras.
- **Nada de markdown** — asteriscos, underline, bold viram caracteres literais.
- Listas com `—` (travessão), não `•` nem `1.`.
- **Hashtags:** 3–5 no final, separadas por espaço. Nunca no meio.
- **Link externo:** no primeiro comentário, não no post (LinkedIn penaliza links no post).
- **Emoji:** só se o usuário pedir explicitamente.
- **Primeira pessoa** — "eu construí", "errei", "descobri" é mais forte que "foi construído".

---

## 13. O QUE ATUALIZAR NESTE DOC E QUANDO

Atualizar este arquivo quando:
- Um número novo verificado aparece (lançamento finalizado, métrica validada)
- Um bug grande é corrigido (virou war story §5)
- Uma decisão de design nova é consolidada (§4)
- Um marco é atingido (§7)
- Um claim antigo vira indefensável (remover, não "atualizar")

Não atualizar para:
- Flutuações diárias de métrica
- Estado efêmero do projeto (use `/ctx` em vez disso)
- Opiniões não-verificadas
