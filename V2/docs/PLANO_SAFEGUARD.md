# Catálogo de salvaguardas — Smart Ads V2

**Criado:** 2026-04-16. **Reescrito em linguagem natural:** 2026-05-10.

**Papel deste documento:** catálogo das verificações que protegem o sistema de scoring contra regressões silenciosas, dados ruins e deploys quebrados. Cada item descreve **o que faz**, **por que existe** (motivação ancorada em incidente real), **como funciona** e **onde no código**.

**Status canônico e prioridade vivem em `PLANO_EXECUCAO.md`.** Este documento é o "como"; o "quando" é definido lá. Quando houver conflito, o `PLANO_EXECUCAO` vence.

**Identificadores históricos** (`T1-X`, `T2-X`, `T3-X`) ficam no rodapé de cada item — preservam rastreabilidade com commits e issues antigas, mas não ocupam o título.

Referências:
- Roadmap (sequência de execução): [`PLANO_EXECUCAO.md`](PLANO_EXECUCAO.md)
- Cenários a estressar (ataques deliberados): [`AUDITORIA_QUEBRA_PRODUCAO.md`](AUDITORIA_QUEBRA_PRODUCAO.md)
- Erros históricos (motivação): [`registro_erros_ml.md`](registro_erros_ml.md)
- Skills de investigação: `/investigate`, `/investigate-ab`, `/safeguard`

---

## Como cada item é tratado

Cada salvaguarda é implementada, testada, commitada e deployada **individualmente** — sem agrupar.

```
1. IMPLEMENTAR   — fazer a mudança no código
2. TESTAR        — rodar o(s) teste(s) específicos do item
                   O item só avança se os testes passarem
3. COMMITAR      — commit isolado descrevendo o item
4. DEPLOYAR      — deploy com --no-traffic → smoke test → canary → 100%
5. MARCAR        — atualizar status na tabela final deste arquivo
```

**Por que deploy por item:** cada salvaguarda é uma mudança independente de comportamento em produção. Agrupar várias num único deploy torna impossível identificar qual mudança causou um problema. Deploy granular = rollback preciso.

**Glossário rápido (termos do nosso projeto que aparecem ao longo do doc):**

- **canary** — uma revisão recém-deployada que recebe % crescente de tráfego (0% → 10% → 50% → 100%) antes de ir a 100%, pra detectar problema com exposição limitada.
- **shim de variante (Champion shim)** — uma entrada no YAML de variantes A/B que existe **só pra hospedar a configuração** (encoding, conversion rates) de um modelo legado — sem fazer roteamento de tráfego próprio. Funciona como "configuração-fantasma": o modelo legado continua sendo usado pra leads que não caem em variante específica, mas a config dele fica acessível pelo mesmo mecanismo do A/B.
- **D10%** — porcentagem de leads que receberam decil 10 (D10), o decil top do scoring. Métrica de saúde do output (deve flutuar pouco em torno do baseline histórico).
- **drift** — mudança no formato ou na distribuição dos dados que o modelo recebe em produção, comparado ao que ele viu no treino. Se o drift é grande, o modelo continua scoreando mas o sinal degrada.
- **`mlflow_run_id`** — identificador único de cada treino no MLflow. É como cada modelo é referenciado em todo o sistema (YAML, banco, logs).
- **`feature_registry`** — JSON que o `train_pipeline` salva junto com o modelo no MLflow, listando quais colunas o modelo espera receber e em que ordem.
- **`--set-active`** — flag do `train_pipeline.py` que marca um modelo recém-treinado como o ativo no `configs/active_models/{cliente}.yaml`. Sem ela, o modelo é treinado e registrado mas não vai pra produção.
- **`configs/clients/{cliente}.yaml`** — parâmetros do cliente em si: fórmulas, valores de conversão esperados, regras de negócio.
- **`configs/active_models/{cliente}.yaml`** — aponta qual versão de modelo está ativa pra esse cliente, com config de A/B (variantes, regras de roteamento, ajustes específicos de cada uma).
- **`conversion_rates`** — tabela `decil → taxa de conversão esperada` que o pipeline usa pra calcular o `value` enviado ao Meta em cada evento CAPI.
- **`utm_pattern` / `url_pattern`** — regras no YAML que dizem quais leads (por UTM ou URL) caem em qual variante A/B.
- **override (de variante)** — ajuste específico de uma variante A/B em cima da regra base do cliente. Pode ser de encoding (variante usa transformação diferente pra alguma feature), de predictor (variante usa modelo diferente do default), ou de conversion_rates (variante usa tabela de valores diferente pro Meta). Quem decide qual override aplicar é o roteador A/B no momento do scoring de cada lead.
- **Gate A/B/C/D** — etapas automatizadas que rodam dentro do `deploy_capi.sh` antes da nova revisão receber tráfego de verdade. Cada gate cobre uma classe diferente de regressão (paridade de transformação, smoke pós-deploy, equivalência de score, configuração interna da imagem). Cada uma é descrita na seção "Verificações de antes do deploy" mais abaixo.
- **`funnel_metrics.capi_sent.send_rate`** — % de leads scoreados que tiveram evento CAPI enviado ao Meta.
- **`meta_response.acceptance_rate`** — % desses eventos enviados que o Meta aceitou (sem rejeição por dedupe ou validação).

---

## Antes de subir `main` em produção

Antes de executar `FORCE_DEPLOY=true ./deploy_capi.sh --force-deploy` pra subir a branch `main`, confirmar manualmente cada item abaixo. Não é gate automatizado — é responsabilidade de processo.

**Verificações que sempre precisam estar OK:**

- Encoding tem fallback bloqueado quando falha — ✅ ativo
- CAPI alerta quando algum decil para de enviar eventos — ✅ ativo
- CAPI deduplica eventos antes de enviar — ✅ ativo
- Datas usam UTC consistente em todos os componentes — ✅ ativo
- Auditoria de paridade treino × produção passa — ✅ ativo
- Auditoria automatizada no fluxo do deploy — ✅ ativo
- Tráfego cresce gradual com critério objetivo — ✅ ativo
- Cobertura de features em runtime — ✅ ativo
- Validador pré-encoding de features — ✅ ativo
- Drift de perfil de audiência detectado — ✅ ativo (08/mai)
- Smoke test cobre todas as variantes A/B — ✅ ativo (08/mai)
- Auditoria de paridade por variante A/B — ✅ ativo (08/mai)
- Auditoria de YAML dentro da imagem deployada — ✅ ativo (08/mai)
- Equivalência de score+decil entre revisões — ✅ ativo (08/mai)

**Verificações em backlog (não bloqueiam deploy normal mas devem entrar):**

- Smoke de paridade pipeline-modelo no fim do treino — 🟡 backlog (próximo retreino). Inline-blocker plantado em [`src/train_pipeline.py`](../src/train_pipeline.py) próximo ao `--set-active` pra não esquecer no próximo retreino.
- Validação de schema contra MLflow no parity audit — ✅ ativo. Função `audit_schema_against_mlflow` registrada em [`tests/parity_audit.py:493`](../tests/parity_audit.py#L493) e disparada pelo Gate A do `deploy_capi.sh` com `--function schema_mlflow`.
- Validador pós-encoding ">X% leads zerados → bloqueia" — ✅ ativo desde 11/mai (commit `8b1c804`). Resolve V.1.3 do registro de erros.
- Validador pós-deploy automático (PROMOTE/HOLD/ROLLBACK) — ✅ script entregue ([`scripts/progression_gate.py`](../scripts/progression_gate.py)). Ainda **não cabeado** no `deploy_capi.sh` — progressão 10→50→100 segue manual. Cabeamento depende de aprovação operacional.

**Gates automáticos que o `deploy_capi.sh` roda:**
1. Branch verificada — bloqueia se branch não-rollback sem `FORCE_DEPLOY=true`
2. Auditoria de paridade — bloqueia se houver divergência treino × produção

**Gates manuais (responsabilidade humana):**
- Checklist acima revisado com status atual no arquivo
- `--no-traffic` usado no primeiro deploy (nova revisão recebe 0%)
- Smoke test pós-deploy: 5 leads → score + decil + log CAPI OK
- Progressão de tráfego conforme protocolo (0% → 10% → 50%)

**Em caso de dúvida:** se qualquer item acima não puder ser confirmado, a resposta certa é **não deployar** e resolver primeiro.

---

## Verificações de antes do deploy ("gates")

Etapas que rodam **antes** de uma revisão receber tráfego, dentro do `deploy_capi.sh`. A ideia é: se algo errado vai acontecer em produção, esses gates pegam antes.

### Auditoria de paridade treino × produção (Gate A)

**O que faz:** compara, coluna por coluna, o resultado das transformações de dados (encoding, UTM, medium, feature engineering) entre o que o pipeline de treino produz e o que o pipeline de produção produz, sobre o mesmo input. Bloqueia o deploy se diverge.

**Por que existe:** há histórico longo de bugs onde a transformação de dados rodava diferente em produção e em treino — ex.: `.lower()` aplicado num lado mas não no outro. O modelo era treinado vendo X e produção alimentava com X', score saía degradado sem que ninguém soubesse.

**Como funciona:** roda os snapshots em `tests/fixtures/snapshot_*.pkl` por uma versão isolada da pipeline em código (sem subir Cloud Run) e compara o output esperado contra o atual.

**Onde no código:** [`V2/tests/parity_audit.py`](../tests/parity_audit.py). Funções: `audit_utm`, `audit_medium`, `audit_fe`, `audit_encoding`, `audit_encoding_ab_variants`. Chamado por `deploy_capi.sh` no Gate A.

**Status:** ✅ ativo. Snapshot regenerado em 21/abr (67k linhas × 51 colunas, 0 divergências). Cobertura por variante A/B implementada em 08/mai.

*Identificador histórico: T1-7.*

### Auditoria de paridade por variante A/B

**O que faz:** quando o teste A/B está ativo, roda o gate de paridade **uma vez por variante** (Champion shim, Challenger), aplicando a configuração específica de encoding de cada uma. Pega divergências que afetam só uma variante e seriam invisíveis num teste do caminho default.

**Por que existe:** em 29/abr o Champion `jan30` rodou no A/B sem `encoding_overrides` correto. Idade e salário chegaram zerados em ~25% dos leads por 7 dias. A auditoria que existia antes só testava a configuração base — nunca a variante. O bug passou silencioso pelos gates.

**Como funciona:** lê `configs/active_models/{cliente}.yaml`, identifica cada variante ativa (Champion e Challenger), e pra cada uma monta a configuração completa de encoding. Essa configuração tem duas camadas: a regra base do cliente e ajustes específicos da variante quando ela precisa de tratamento diferente — esses ajustes são o que o config chama de "override". Exemplo concreto: o Champion `jan30` precisa que idade e salário sejam tratados em ordem (`< 18 anos < 18-24 < 25-34 ...`) em vez de cada faixa virar uma categoria solta. O audit aplica regra base + ajuste específico em conjunto e compara coluna por coluna contra um snapshot de leads conhecido. Se qualquer variante diverge, bloqueia o deploy. Quando o snapshot por-variante não existe ainda, faz bootstrap automático (salva o output atual como baseline pra próxima execução).

**Onde no código:** [`V2/tests/parity_audit.py`](../tests/parity_audit.py) função `audit_encoding_ab_variants`. [`V2/tests/capture_encoding_snapshots_ab.py`](../tests/capture_encoding_snapshots_ab.py) faz captura inicial dos snapshots por variante. Chamado pelo Gate A do `deploy_capi.sh` com `--function encoding_ab`.

**Status:** ✅ ativo desde 08/mai. Validado: Champion `jan30` 52 colunas, Challenger `abr28` 61 colunas, outputs idênticos.

*Identificador histórico: T1-15.*

### Validação de schema contra MLflow

**O que faz:** complementa a auditoria por variante validando que o conjunto de colunas que sai do encoding **bate exatamente** com o que o modelo da variante registrou no MLflow como entrada esperada (`feature_names_in_`).

**Por que existe:** a auditoria por variante (acima) garante que o encoding produz output válido (sem NaN, dtype certo, nomes válidos). Mas não garante que o número de colunas e os nomes batem com o que o modelo espera consumir. Se a variante tem registro com 87 colunas e o encoding produz 86 ou 88, o gate atual passa silencioso e o erro só aparece no momento de scorear.

**Como funciona (proposto):** pra cada variante, baixar o `feature_registry.json` do `mlflow_run_id` correspondente, passar como `artifacts={'feature_registry': variant_registry}` para `apply_encoding`, e comparar `set(df_actual.columns) == set(variant_registry['feature_names'])`. Falha por divergência de schema bloqueia.

**Pré-condição:** rotina de download de artefato do MLflow no parity audit. Duas opções: (a) Cloud SQL `smart-ads-db` rodando durante deploy (atrita: hoje está em `activation-policy=NEVER`); (b) cachear `feature_registry.json` localmente sob `configs/active_models/registry_cache/{run_id}.json` no momento do `--set-active` — preferida.

**Onde no código:** [`tests/parity_audit.py:493`](../tests/parity_audit.py#L493) função `audit_schema_against_mlflow`. Disparada pelo Gate A do `deploy_capi.sh` com `--function schema_mlflow`. Usa input de produção (`_build_production_encoding_input` puxa leads reais do Railway via `railway_lead_to_sheets_row` e aplica core pipeline completo) em vez de snapshot de treino — classifica missings em CRÍTICO (coluna pré-OHE ausente) vs AMOSTRAL (categoria não presente no sample) pra zero falso positivo.

**Status:** ✅ ativo. Cobertura: variantes Champion shim + Challenger, comparando `set(df_actual.columns)` com `feature_registry.json` de cada `mlflow_run_id`.

*Identificador histórico: T1-19.*

### Smoke test pós-canary (Gate B)

**O que faz:** depois que a nova revisão sobe com 0% de tráfego, dispara uma execução do pipeline contra leads reais do Railway pela URL direta da revisão (com `--tag`). Verifica que o scoring volta com decil válido, sem CAPI 5xx, e que as features críticas não chegam zeradas. Bloqueia a progressão de tráfego se algo falhar.

**Por que existe:** o deploy podia subir uma revisão tecnicamente saudável (container vivo) mas com bug funcional (decil errado, feature zerada). Sem essa verificação, só íamos descobrir depois de promover.

**Como funciona:** chama `/monitoring/daily-check/railway` na URL tagged da revisão canary; depois consulta `/monitoring/feature-report` pra ver se houve `severity=ERROR` em features importantes; depois chama `/smoke/run-variants` pra cobrir cada variante A/B. Se qualquer um desses passos retorna problema, aborta o deploy.

**Onde no código:** [`V2/scripts/smoke_test_revision.py`](../scripts/smoke_test_revision.py). Integrado no `deploy_capi.sh:542`. Endpoint `/smoke/run-variants` em [`V2/api/app.py`](../api/app.py).

**Status:** ✅ ativo desde 21/abr. Cobertura por variante A/B implementada em 08/mai.

**Cleanup automático de tags antigas (14/mai/2026):** o `deploy_capi.sh` remove automaticamente, antes de cada deploy `--no-traffic`, todas as tags `canary-*` em revisões com 0% de tráfego. Implementado após incidente de custo (33 tags acumuladas geraram +R$ 70/dia em min-instances always-on no Cloud Run — cada tag mantém URL dedicada e respeita `min-instances=1` perpetuamente). Tags em revisões com tráfego > 0 são preservadas. Detalhes do incidente em [`operacoes_gcp_custos.md`](operacoes_gcp_custos.md) seção "Investigação de spike de custo — 2026-05-14".

*Identificadores históricos: T1-10 (verificação de cobertura), T1-11 (validação pré-encoding e endpoint `/feature-report`), T1-14 (smoke por variante A/B).*

### Auditoria de YAML dentro da imagem deployada (Gate D)

**O que faz:** baixa a imagem Docker da revisão canary, abre os arquivos YAML que foram empacotados (`clients/{cliente}.yaml` e `active_models/{cliente}.yaml`), e verifica que valores críticos não foram acidentalmente apagados ou zerados.

**Por que existe:** mudanças silenciosas em YAML produzem runtime sem erro mas com sinal degradado. Dois incidentes recentes:
- **30/abr → 06/mai/2026:** `business.conversion_rates` removido em commit sem alerta. Runtime caía em `valor_projetado = 0.0` silencioso. 7 dias de eventos `LeadQualified` enviados ao Meta com `value=0`.
- **08/mai/2026:** `champion_jan30` e `challenger_abr28` em `active_models/devclub.yaml` tinham `conversion_rates: {D01: 0.0, ..., D10: 0.0}` por copy-paste. Comentário do YAML afirmava "NUNCA são lidos" mas eram. Bug parcial só apareceu durante canary.

O Gate B cobre encoding e features. O Gate D cobre **configuração de negócio** dentro da imagem deployada — outro vetor que B não enxerga.

**Como funciona:** recebe nome da revisão Cloud Run, resolve o digest da imagem via `gcloud run revisions describe`, faz `docker pull` + `cat` dos YAMLs internos. Verifica:
- **Bloco 1 (cliente):** `business.conversion_rates` existe, cobre `D01..D10`, todos os valores `> 0`.
- **Bloco 2 (modelo ativo):** pra cada variante "ativa" em `ab_test.variants` (matcheia roteamento OU `run_id == active_model.mlflow_run_id`), `conversion_rates` cobre `D01..D10` e `MAX(values) > 0`.

Bloqueia o deploy via `exit 1` se qualquer invariante falhar.

**Onde no código:** [`V2/scripts/gate_d_config_audit.py`](../scripts/gate_d_config_audit.py). Roda no `deploy_capi.sh` entre Gate B e progressão de canary. Pré-requisito: docker daemon local disponível.

**Status:** ✅ ativo desde 08/mai. Substituirá DT-17 quando a duplicação `business_config.py × YAML` for fechada arquiteturalmente.

*Identificador histórico: T1-17.*

### Equivalência de score+decil entre revisões (Gate C)

**O que faz:** depois do canary subir com 0% de tráfego, pega N leads reais do Railway, manda os mesmos leads pra duas revisões (a atual em produção e a nova canary), compara o decil que cada uma atribui. Bloqueia se houver divergência.

**Por que existe:** mudanças não-intencionais no scoring (regressão de modelo, regressão de encoding, regressão de pipeline) só apareciam depois de promovidos. Custosa de detectar e reverter. Esse gate descobre na hora se duas revisões pontuam os mesmos leads diferente.

**Como funciona:** dois modos:
- **`capi-dry-run` (default):** usa `/capi/process_daily_batch?dry_run=true`. Executa todo o caminho de roteamento A/B + cálculo de `valor_projetado`, mas pula chamada Meta + escrita no banco. Cobre o path A/B real.
- **`predict` (legado):** usa `/predict/batch`. Não exercita roteamento A/B. Útil pra validar pipeline de scoring isoladamente.

**Cobertura forçada do A/B:** pegando leads aleatórios do Railway, raramente algum bate `utm_campaign='PIXEL NOVO API'` (que rotearia pro Challenger). O fetcher reescreve `utm_campaign` da metade dos leads pra forçar Challenger path, e prefixa `email` com `chlng+` pra evitar colisão de cache. Garante cobertura ≥50% Challenger.

**Critério de bloqueio:** somente divergência de decil. Value/event_name divergentes são **informativos** — revisões frequentemente mudam value/event_name intencionalmente. Esse lado já é coberto pelo Gate D.

**Override de mudança intencional:** quando o objetivo da revisão **é** mudar scoring (novo modelo Champion, novo encoder), passar `--expect-score-change` pra aceitar divergência como esperada.

**Onde no código:** [`V2/scripts/test_revision_equivalence.py`](../scripts/test_revision_equivalence.py). Roda no `deploy_capi.sh` entre Gate D e progressão de canary. Pré-requisito: env vars `RAILWAY_DB_*` no `V2/.env`.

**Status:** ✅ ativo desde 08/mai. Payload completo (com nome, telefone, e-mail e todas as chaves de pesquisa) corrigido em 09/mai (commit `4c6c472`) — o gate antigo enviava payload pobre que poluia o validador pré-encoding.

*Identificador histórico: T1-18.*

---

## Verificações em runtime

Etapas que rodam **dentro do pipeline de produção a cada lead** (ou a cada batch). Função: pegar o problema cedo, antes que vire degradação invisível.

### Encoding com fallback bloqueado quando falha

**O que faz:** quando o encoding ordinal não encontra o nome de coluna esperado, em vez de cair silenciosamente em OHE (one-hot encoding), levanta erro alto. Se isso acontecer, o operador sabe imediatamente que tem desalinhamento.

**Por que existe:** o encoding ordinal vivia hardcoded em `src/features/encoding.py` com nomes literais (`'Qual a sua idade?'`). Se o nome da coluna no DataFrame não batia exatamente, o código antigo caía em OHE como fallback — produzindo features completamente diferentes do que o modelo esperava, sem alerta.

**Onde no código:** [`V2/src/core/encoding.py`](../src/core/encoding.py).

**Status:** ✅ ativo desde 20/abr.

*Identificador histórico: T1-1.*

### CAPI: alerta quando algum decil para de enviar eventos

**O que faz:** verifica diariamente se todos os decis (D1-D10) estão produzindo eventos enviados ao Meta. Alerta se algum decil ficou com 0 eventos nas últimas 24h.

**Por que existe:** o D9 ficou 2 meses sem nenhum evento CAPI sendo enviado, e ninguém percebeu. Sintoma silencioso que afeta a otimização de campanhas no Meta.

**Onde no código:** [`V2/src/monitoring/capi_monitor.py`](../src/monitoring/capi_monitor.py).

**Status:** ✅ ativo desde 20/abr.

*Identificador histórico: T1-2.*

### CAPI: deduplica eventos antes de enviar

**O que faz:** antes de empurrar evento pro Meta, verifica se o mesmo `email` já tem `capi_sent_at` preenchido no banco. Se está, descarta o duplicado (retorna `capi_skipped: "already_sent"`). Em batch, o endpoint `/capi/check_sent` filtra a lista antes do envio. Como segunda camada, o `event_id` enviado pro Meta também serve de dedup do lado deles.

**Por que existe:** envios duplicados poluem a atribuição do Meta e podem inflar `value` agregado.

**Onde no código:**
- Dedup individual em [`V2/api/app.py:865-875`](../api/app.py#L865-L875) (`existing_lead.capi_sent_at` check).
- Dedup batch via endpoint [`V2/api/app.py:1599-1638`](../api/app.py#L1599-L1638) (`/capi/check_sent`) que consulta `get_leads_already_sent_to_capi` em [`V2/api/database.py`](../api/database.py).
- `event_id` propagado pro Meta em [`V2/api/capi_integration.py`](../api/capi_integration.py) como segunda camada (dedup do lado Meta).

**Status:** ✅ ativo desde 20/abr. Verificado em meta-auditoria de 11/mai (Cenário 3.1 do `AUDITORIA_QUEBRA_PRODUCAO.md`).

*Identificador histórico: T1-3.*

### Datas usam UTC consistente em todos os componentes

**O que faz:** centraliza o uso de `datetime.now(timezone.utc)` em vez de `datetime.now()` (que pega o timezone local da máquina).

**Por que existe:** o Cloud Run roda em UTC. São Paulo está 3h atrás. Sem padronização, leads na borda do dia (23h59 BRT vs 02h59 UTC) iam pro dia errado em diferentes componentes (treino, produção, monitoramento, validação) — quebrando o casamento entre score e venda.

**Onde no código:** constante centralizada em [`V2/src/core/utils.py`](../src/core/utils.py). Substituições em `train_pipeline.py`, `production_pipeline.py`, `monitoring/orchestrator.py`, `validation/analyze_tmb_inadimplencia.py`.

**Status:** ✅ ativo desde 20/abr.

*Identificador histórico: T1-4.*

### Detecção de feature crítica zerada após encoding

**O que faz:** durante o encoding em produção, antes do passo de fill com 0, verifica se as features mais importantes do modelo (importância ≥ 1%) estão zeradas em mais de X% dos leads do batch. Se sim, emite alerta `severity=ERROR` (≥5%) ou `WARNING` (≥1%).

**Por que existe:** o `Medium_Linguagem_programacao` ficou zerada por semanas sem alerta. Bug clássico de degradação silenciosa — feature de alta importância sumiu do mix de tráfego, encoding zerou a coluna, modelo continuou pontuando mas sem o sinal real.

**Onde no código:** [`V2/src/core/encoding.py`](../src/core/encoding.py). Resultado consumido pelo Gate B (smoke test pós-canary).

**Status:** ✅ ativo desde 21/abr.

*Identificador histórico: T1-10.*

### Validador pré-encoding de features

**O que faz:** logo depois do feature engineering e antes do encoding, verifica que cada feature pré-OHE esperada pelo modelo ativo:
- Existe no DataFrame
- Tem o tipo certo (bool, string categórica, numérico — conforme schema)
- Não está com taxa alta de nulo
- Tem valores dentro do domínio conhecido do treino

Emite log estruturado JSON por batch (`event=feature_validator`) com `severity` proporcional às issues.

**Por que existe:** o detector de feature zerada (acima) cobre o sintoma (coluna OHE faltando). Esse validador cobre a **causa-raiz**: feature pré-OHE ausente, com tipo errado, ou com categoria nova que o modelo nunca viu. Cada uma dessas condições produziria silenciosamente score degradado.

**Como o resultado é consumido:** o `deploy_capi.sh` consulta o endpoint `/monitoring/feature-report?hours=24` durante o smoke test. Se houver `batches_with_issues > 0` ou `overall_status=ERROR`, bloqueia a progressão de tráfego.

**Onde no código:** [`V2/src/core/feature_validator.py`](../src/core/feature_validator.py) (validação). [`V2/api/app.py`](../api/app.py) endpoint `GET /monitoring/feature-report` (agregação). Schema de referência em `configs/pre_encoding_schemas/{cliente}.json`.

**Status:** ✅ ativo desde 23/abr.

*Identificador histórico: T1-11.*

### Validador pós-encoding ">X% leads zerados → bloqueia"

**O que faz (proposto):** após o passo de encoding, pra cada feature com importância ≥ 3% no registro do modelo ativo, calcula a fração de leads do batch onde aquela feature ficou zerada. Se a fração observada exceder a esperada do treino (capturada como `proporcao_esperada_zero`), levanta `ValueError` antes que o batch seja enviado pra scorear.

**Por que existe:** essa salvaguarda foi declarada como entregue em 21/abr no checklist mas, na investigação V.1.3 do registro de erros (08/mai), confirmou-se que **nunca foi implementada**. O que existe hoje é log de feature **ausente do DataFrame** — não cobre o caso típico em que `pd.get_dummies()` cria a coluna mas ela chega zerada (o cenário dos Clusters 3, 4 e 5 do Erro 2). O log atual também nunca bloqueia o pipeline.

**Pré-condição (revisada em 2026-05-11):** o `proporcao_esperada_zero` por coluna OHE **não precisa de retreino** — pode ser calculado offline a partir dos `distribuicoes_esperadas.json` já registrados no MLflow para Champion e Challenger. Fórmula: para cada coluna `feature_categoria` resultante do OHE, `proporcao_esperada_zero = 1 - distribuicoes_esperadas['categorical'][feature][categoria]` (a fração de leads que NÃO têm essa categoria no treino). Para colunas que vêm de features numéricas ou ordinais, a regra é diferente (proporcao_esperada_zero ≈ 0 para ordinais; calculável via `bins` para numéricas). Script ad-hoc gera um JSON por modelo e salva em `configs/feature_zero_baselines/{run_id}.json`.

**Threshold precisa ser feature-aware:** features ordinais (idade, salário) podem ter "0" como categoria válida (`< 18 anos` é encodada como 0); features OHE (`Medium_*`, `genero_*`) não. Comparar contra a proporção esperada por feature, não threshold absoluto.

**Onde no código (proposto):**
- Geração offline dos baselines: novo script `V2/scripts/generate_feature_zero_baselines.py` lê `distribuicoes_esperadas.json` do `mlflow_run_id` de cada variante ativa, escreve `configs/feature_zero_baselines/{run_id}.json`.
- Validação em runtime: novo bloco em [`V2/src/core/encoding.py`](../src/core/encoding.py) após `pd.get_dummies`, novo método em [`V2/src/core/feature_validator.py`](../src/core/feature_validator.py) que carrega o baseline da variante ativa e compara batch atual contra esperado.

**Status:** ✅ ativo desde 11/mai/2026. Componentes:
- Script offline gerador dos baselines em [`V2/scripts/generate_feature_zero_baselines.py`](../scripts/generate_feature_zero_baselines.py) — lê `distribuicoes_esperadas.json` de cada modelo ativo e gera `V2/configs/feature_zero_baselines/{run_id}.json` (Champion 64 colunas, Challenger 58 colunas no estado atual).
- Validador em runtime: `validate_post_encoding_zero_rates()` em [`V2/src/core/feature_validator.py`](../src/core/feature_validator.py). Thresholds default (batch ≥50, expected ≥15%, drop ≥70%) calibrados pra zero falso positivo em batches do polling Railway.
- Chamada no encoding: passo 9 de [`V2/src/core/encoding.py`](../src/core/encoding.py) — só roda se `artifacts['mlflow_run_id']` está setado (caminho de produção; treino e parity audit pulam).
- Pré-requisito operacional: após cada `--set-active` de um modelo novo, rodar `python -m V2.scripts.generate_feature_zero_baselines` pra gerar o baseline do novo `run_id`. Sem baseline o validador degrada pra noop com log informativo.

**Revisão proposta (18/05/2026) — três defeitos e desenho de correção**

A investigação 17–18/05/2026 (achado completo no `registro_erros_ml.md` § V.5) mostrou que o validador, como está, tem três defeitos que se reforçam: ele mede a coisa errada, roda no lugar errado, e causa dano silencioso quando dispara. Resumo dos defeitos:

1. **Mede a coisa errada.** O critério atual compara a taxa de ativação da coluna pós-encoding contra a distribuição capturada **no treino** (`observed_nonzero_rate < expected_do_treino × 0,3`). Esse sinal é idêntico para duas causas opostas: feature quebrada por bug (parsing/casing) **e** mix de tráfego que mudou legitimamente (campanha trocou de Facebook para Google). O validador não distingue as duas — trata mudança de negócio como bug.
2. **Roda no lugar errado.** O validador é proteção de runtime de produção, mas está embutido no caminho de scoring que o teste de equivalência de deploy (Gate C) usa. Resultado: ele aborta o Gate C antes de ele comparar decis entre as revisões — uma salvaguarda de runtime contaminando um teste de equivalência. Composição atípica afeta as duas revisões igualmente; não é regressão entre versões.
3. **Dano silencioso quando dispara em produção.** Em `/railway/process-pending` não há `except` em volta do `pipeline.run()`: o `ValueError` aborta o batch inteiro, os leads ficam com `leadScore IS NULL`, o polling re-seleciona os mesmos a cada 5 min (loop infinito, nunca vão pro Meta), e o hook de alertas críticos daquele ciclo nem roda porque a exceção propaga antes dele. Vira HTTP 500 que o Cloud Scheduler engole.

Desenho de correção (tratado como sistema, não três remendos isolados):

- **D1 — o que medir:** trocar "pós-OHE vs distribuição do treino" por "pré-OHE vs pós-OHE no mesmo batch" (testar **conservação**, não conformidade com o treino). Bug real = campo bruto presente e mapeável, mas o lead não ativa **nenhuma** coluna do grupo OHE correspondente. Shift legítimo = o bruto mudou de proporção, mas todo lead com valor válido continua ativando exatamente uma coluna do grupo → não dispara. Independe de qual categoria e da distribuição de treino.
- **D2 — onde rodar:** desacoplar do Gate C. No Gate C, o scoring roda com o validador em modo observa-mas-não-bloqueia (o Gate C compara decil entre revisões mesmo com composição atípica). Em produção (polling), o validador continua ativo, com o comportamento de D3.
- **D3 — o que fazer ao disparar em produção:** (1) fail-loud explícito — alerta crítico dedicado ("feature X quebrada no encoding; N leads não scoreados / não enviados ao Meta"); (2) garantir que o alerta roda mesmo com falha de scoring (mover o hook de alertas críticos para um `finally` ou rodá-lo antes do scoring sempre); (3) não prender leads em loop — marcar os leads do batch com status terminal para não serem re-selecionados a cada 5 min. A escolha "scorear degradado vs segurar o lead" é decisão de produto, mas o loop silencioso tem de acabar.

Sequência de implementação proposta: **D3 primeiro** (estanca o dano operacional, maior risco), **D1 depois** (corrige o critério na raiz e elimina o falso positivo), **D2 por último** (separação de responsabilidades — D1 já torna o Gate C raramente disparável, mas o desacoplamento ainda vale).

**Status desta revisão:** desenho/proposta. **Não implementado.** Decisão de execução e priorização pendente com o operador (registrado em 18/05/2026). Não recebe identificador novo — é evolução do próprio T1-16. Referências de código: validador em [`V2/src/core/feature_validator.py`](../src/core/feature_validator.py) (`validate_post_encoding_zero_rates`), chamada no passo 9 de [`V2/src/core/encoding.py`](../src/core/encoding.py), handler de produção em [`V2/api/app.py`](../api/app.py) (`/railway/process-pending`), amostragem do Gate C em [`V2/scripts/test_revision_equivalence.py`](../scripts/test_revision_equivalence.py) (`fetch_leads_predict_mode`).

*Identificador histórico: T1-16.*

### Drift de perfil de audiência

**O que faz:** todo dia compara o perfil agregado dos leads que entraram no dia anterior contra um snapshot de "audiência winner" — proporções do pool dos Top 5 lançamentos por ROAS atribuível 60d, definido em `docs/METODOLOGIA_TOP5_ROAS.md` (atualizado 2026-05-14: LF45, LF44, LF46, LF41, LF43, n=42.038 leads). Emite alerta agregado com até dois subgrupos de features:
- **`top_list`** — features com `|Δpp| ≥ 3` → severity HIGH
- **`down_list`** — features com `2 ≤ |Δpp| < 3` → severity MEDIUM

**Por que existe:** o drift de público no LF54 (08/mai) ficou invisível pros sensores até alguém abrir uma análise ad-hoc. O monitoring antigo só comparava distribuições contra `distribuicoes_esperadas.json` capturado **no treino** — e treino é estimação de "como o público costumava ser", não "como o público winner se parecia". Drift contra winner é o que importa pro próximo lançamento.

**Como funciona:**
1. Snapshot estático em `configs/reference_audience_profiles/{cliente}.json` (não rolling — atualização manual ao "fechamento de lançamento")
2. Categorias canônicas em `_AUDIENCE_UNIFICATION` no `data_quality.py`, espelhando o `UNIFICATION` em `scripts/perfil_audiencia.py`
3. Janela comparada: último dia completo BRT (00:00 → 23:59 anterior a hoje)
4. Min responses no dia: 50 (skip silencioso info-level se menor)
5. Snapshot ausente: emite `audience_profile_drift_config_missing` severity MEDIUM com instrução de comando — **fail-loud, não silencioso**

**Onde no código:** [`V2/src/monitoring/data_quality.py`](../src/monitoring/data_quality.py) (método `_check_audience_profile_drift`). Snapshot em [`V2/configs/reference_audience_profiles/devclub.json`](../configs/reference_audience_profiles/devclub.json). Gerador em [`V2/scripts/build_reference_audience_profile.py`](../scripts/build_reference_audience_profile.py). Hook em `DataQualityMonitor.check()`, executado pelo `orchestrator.run_daily_check`.

**Status:** ✅ ativo desde 08/mai.

*Identificador histórico: T1-13.*

---

## Como tráfego cresce após o deploy

Etapas obrigatórias entre revisão criada e revisão em 100%. Cada etapa exige **tempo mínimo de observação E critérios objetivos cumpridos** — não avançar sem ambos.

### Etapas padrão

| De | Para | Tempo mínimo | Critérios objetivos |
|---|---|---|---|
| Build | 0% (`--no-traffic`) | — | Smoke test 5 leads: score retorna, decil atribuído, log CAPI sem 5xx |
| 0% | 10% | 1 hora | Taxa de 5xx na nova rev < 1%; top-5 features do modelo não zeradas no smoke |
| 10% | 50% | 24 horas | `funnel_metrics.capi_sent.send_rate` ≥ 90%; `meta_response.acceptance_rate` ≥ 85%; nenhum decil com 0 eventos CAPI; D10% últimas 24h não diverge de últimos 30 dias em mais de 10pp; `/monitoring/feature-report?hours=24` retorna `batches_with_issues=0` e `overall_status ∈ {OK, INFO}` |
| 50% | 100% | Caso a caso — ver abaixo | Caso a caso |

### 50% → 100% — dois cenários

**(a) Unificação main → produção (caso especial):** aguardar o ciclo do lançamento fechar. O critério aqui **é** ROAS, apesar da latência de ~21 dias, porque a janela de validação é única e a decisão é irreversível.

**(b) Deploys normais (retreinos mensais, patches, fixes):** 1 semana em 50% sem regressão operacional:
- `funnel_metrics.capi_sent.send_rate` estável (±5pp do baseline da revisão anterior)
- Taxa de 5xx não aumentou vs revisão anterior
- Cobertura de features não degradou (top-5 features não zeradas em > 5% dos leads)

ROAS **não é critério** pra deploys normais — ciclo de 15-21 dias paralisaria deploys se fosse exigido.

### O que NÃO é critério de bloqueio

| Sinal | Por que não bloqueia |
|---|---|
| D10% absoluto alto (> 20-30%) | Constante histórica do projeto por feedback loop — não específico ao deploy |
| Features novas/não reconhecidas | Esperado em retreinos quando dados reais mudam; gera alerta mas não regressão |
| Alertas HIGH genéricos do orchestrator | Muitos HIGH são drift externo (Meta API, Sheets) alheios ao deploy |
| Divergência absoluta em métricas de negócio | Se a nova revisão for melhor (ex: ROAS maior), não bloqueia |

### Rollback nomeado

**Antes de cada etapa de progressão**, documentar por escrito:
- **Qual revisão é o rollback?** nome exato (ex.: `smart-ads-api-00269-jjn`)
- **Comando pronto para colar:**
  ```bash
  gcloud run services update-traffic smart-ads-api --region us-central1 \
      --to-revisions <ROLLBACK_REVISION>=100
  ```
- **Tempo de reversão esperado:** < 2 minutos (Cloud Run propagação)

**Onde no código:** documentação inline em [`V2/api/deploy_capi.sh`](../api/deploy_capi.sh) após o Gate B do smoke test.

*Identificadores históricos: T1-9 (protocolo), T3-1 (documentação inline), T2-7 (validador automatizado pós-deploy via `progression_gate.py`).*

---

## Qualidade do treino

Salvaguardas que garantem que o dataset de treino é representativo, deduplicado e bem instrumentado.

### Smoke de paridade pipeline-modelo no fim do treino

**O que faz (proposto):** ao final do treino, antes de marcar o modelo como ativo, pega ~100 leads reais e roda eles pelo pipeline de produção usando o modelo recém-treinado. Verifica:
- Conjunto de features esperadas pelo modelo está contido no que `apply_encoding` produz
- Score sai sem NaN no intervalo `[0, 1]`
- Decis atribuídos cobrem `D01–D10`

Se qualquer falhar, aborta o `--set-active`.

**Por que existe:** as proteções de runtime (validador pré-encoding, cobertura de features) protegem leads em produção. Mas o modelo é registrado no MLflow **sem nenhum check** de "esse modelo, com o pipeline atual, scoreia sem perder feature". Bug silencioso possível: registrar modelo cujo `feature_names_in_` não casa exatamente com o que `apply_encoding` produz no main code → primeiro deploy descobre o problema.

**Onde no código (proposto):** [`V2/src/train_pipeline.py`](../src/train_pipeline.py) ao final, antes de `--set-active`. Reusa lógica de [`V2/scripts/smoke_test_revision.py`](../scripts/smoke_test_revision.py).

**Custo:** ~30s adicionais por treino.

**Status:** 🟡 backlog. Implementar quando próximo retreino for feito.

*Identificador histórico: T1-12.*

### Deduplicação no treino

**O que faz:** antes de consolidar o dataset de treino, remove duplicados por planilha.

**Onde no código:** [`V2/src/core/ingestion.py`](../src/core/ingestion.py) (3 funções: `filter_sheets`, `remove_duplicates_per_sheet`, `consolidate_datasets`). Assinatura config-driven.

**Status:** ✅ ativo desde 23/abr.

*Identificador histórico: T2-1.*

### Log de count em cada etapa

**O que faz:** em cada filtro do pipeline (treino e produção), loga count antes e depois com delta.

**Onde no código:** função helper `_log_step_count` em [`V2/src/train_pipeline.py:223`](../src/train_pipeline.py#L223) (invocada em 8 pontos do pipeline de treino) e [`V2/src/production_pipeline.py:35`](../src/production_pipeline.py#L35) (invocada em 3 pontos do pipeline de produção). Formato `[step] N=X | Δ=±Y (±%)`.

**Status:** ✅ ativo desde 28/abr (commit `8b46645`). Contagem real confirmada em meta-auditoria de 11/mai.

*Identificador histórico: T2-2.*

### Importance weighting pra grupo controle

**O que faz:** treina com peso maior pros leads do grupo controle (campanhas sem ML), pra balancear o viés do feedback loop.

**Onde no código:** `_compute_control_weights` em [`V2/src/train_pipeline.py`](../src/train_pipeline.py). Flags: `--control-group-weights`, `--control-alpha`, `--train-ratio`.

**Status:** ✅ ativo desde 28/abr.

*Identificador histórico: T2-3.*

### Limite de queries de validação

**O que faz:** queries de validação que retornariam exatamente o limite (10k antes, 100k/200k agora) emitem ERROR — sinal de que estavam sendo truncadas silenciosamente.

**Por que existe:** lançamentos > 10k leads estavam sendo truncados sem alerta no relatório de validação.

**Onde no código:** [`V2/src/validation/generate_taxa_resposta_csv.py`](../src/validation/generate_taxa_resposta_csv.py) (limite 100k) e [`V2/src/validation/capi_events_counter.py`](../src/validation/capi_events_counter.py) (limite 200k).

**Status:** ✅ ativo desde 28/abr.

*Identificador histórico: T2-4.*

### Filtro de vendas não aprovadas

**O que faz:** confirmação de que `include_canceled=False` é default em todos os loaders de venda. Só relatório de fechamento permite override pra incluir canceladas.

**Onde no código:** loaders [`load_guru_sales`](../src/validation/data_loader.py#L651), [`load_tmb_sales`](../src/validation/data_loader.py#L836), [`load_hotpay_sales`](../src/validation/data_loader.py#L966) em `V2/src/validation/data_loader.py`. Override só em `validate_ml_performance.py:1388-1389` quando `report_type='fechamento'`.

**Status:** ✅ confirmado em 28/abr (não exigiu mudança de código). Localização revalidada em 11/mai.

*Identificador histórico: T2-5.*

### Eliminar exceções silenciosas críticas

**O que faz:** converte `except: pass` e `except Exception: return {}` em pontos críticos pra `logger.error` com `exc_info`. Operações que falham passam a ser visíveis.

**Pontos onde estava silencioso:**
- `monitoring/orchestrator.py:245-250` (rollback de transação) — agora `logger.error` com `exc_info=True`
- `monitoring/orchestrator.py:315` (parse de linha gspread) — agora contador de skips com warning agregado no fim do loop
- `app.py:1636-1638` (Railway CAPI lookup, `/capi/check_sent`) — `logger.error` + `raise HTTPException`; `exc_info=True` adicionado em 11/mai (estava ausente após refactor anterior)
- `app.py:2263-2264` e `2596-2597` — já tinham `logger.warning`, classificados baixa severidade

**Status:** ✅ ativo desde 28/abr. Migração de `exc_info=True` em `app.py:1637` completada em 11/mai (achado da meta-auditoria do Cenário 3.1 — ver `AUDITORIA_QUEBRA_PRODUCAO.md`).

*Identificador histórico: T2-6.*

### Validador automatizado pós-deploy

**O que faz:** consome `/monitoring/feature-report` e `/monitoring/daily-check/railway`, consolida em PROMOTE / HOLD / ROLLBACK, e (com `--execute`) chama `gcloud run services update-traffic` pra avançar.

**Por que existe:** elimina dependência de disciplina humana na progressão de tráfego.

**Onde no código:** [`V2/scripts/progression_gate.py`](../scripts/progression_gate.py).

**Status:** ✅ ativo desde 23/abr (commit `42990b8`).

*Identificador histórico: T2-7.*

### Alerta pra feature de alta importância com variância baixa em produção

**O que faz:** dispara alerta quando uma feature com `importance ≥ 1%` no modelo ativo cai pra estado quase-constante em produção (>95% dos leads no mesmo valor, ou 100% zerada).

**Por que existe:** complementaria a cobertura existente do `Medium_Linguagem_programacao` cobrindo o caso "categoria sumiu do mix de tráfego, não do encoding".

**Status:** ✅ verificado em 29/abr — `check_distribution_drift` (existente) já cobre o caso operacional. Cobertura sobreposta. Único ganho marginal seria ordenar a saída por `feature_importance` pra destacar high-impact primeiro — fica como melhoria opcional de UX, não item separado.

*Identificador histórico: T2-8.*

### Bootstrap dos snapshots de paridade em máquina fresca / CI

**O que faz (proposto):** na primeira execução do parity audit em máquina fresca (sem snapshots locais), captura automaticamente os pickles necessários a partir do dataset atual. Sem isso, o audit levanta `FileNotFoundError`.

**Por que existe:** snapshots em `tests/fixtures/snapshot_*.pkl` são gitignored (37–95 MB cada). Em máquina fresca, o `parity_audit` não encontra `snapshot_encoding_input.pkl` e aborta antes de chegar nos audits. T1-15 já bootstrappa snapshots por-variante automaticamente quando faltam (commit 09/mai), mas pressupõe que o input já existe localmente.

**Implementação possível:**
- (a) download do `snapshot_encoding_input.pkl` de GCS no início do Gate A
- (b) executar `train_pipeline --capture-parity-snapshots` automaticamente quando input está ausente
- (c) checkar pickles em `gs://bring-data-fixtures/parity/` versionados por hash do dataset

**Status:** 🟡 backlog. Sem urgência enquanto não houver CI ou segundo dev.

*Identificador histórico: T2-9.*

---

## Observabilidade

Salvaguardas que melhoram visibilidade de operação, sem alterar fluxo de scoring.

### Canary documentado inline no script de deploy

**O que faz:** após o smoke test no `deploy_capi.sh`, imprime os 3 comandos `gcloud run services update-traffic` pra 10% → 50% → 100% e referência aos critérios objetivos.

**Onde no código:** [`V2/api/deploy_capi.sh`](../api/deploy_capi.sh) (após Gate B).

**Status:** ✅ ativo desde 29/abr.

*Identificador histórico: T3-1.*

### Smoke test pós-deploy

**Status:** ✅ implementado em 21/abr como Gate B (acima). Cobre o requisito original.

*Identificador histórico: T3-2.*

### Proteção da branch main

**O que faz:** require PR + aprovação antes de merge em `main`.

**Status:** 🟡 adiável. Branch protection do GitHub não disponível em repo privado de conta Free (HTTP 403 "Upgrade to GitHub Pro"). Como há um único colaborador (admin), o risco real (`push --force` ou delete acidental) é baixo. Reativar quando: plano subir pra Pro/Team, repo virar público, ou um segundo colaborador entrar.

*Identificador histórico: T3-3.*

### Verificação periódica do token Meta

**Status:** ❌ cancelado em 23/abr. Token é System User vitalício, não expira. Premissa original errada.

*Identificador histórico: T3-4.*

### Relatório operacional consolidado no daily-check

**O que faz:** bloco "Rotinas operacionais" no log do `run_daily_check` mostra: `run_id` ativo, status do A/B, revision/service do Cloud Run, último scoring + lag, contadores 24h (recebidos / scoreados / CAPI enviados).

**Onde no código:** `_generate_operational_routines_summary()` em [`V2/src/monitoring/orchestrator.py`](../src/monitoring/orchestrator.py).

**Status:** ✅ ativo desde 29/abr.

*Identificador histórico: T3-5.*

### Validação de modelo carregado no startup

**O que faz:** no startup do servidor, verifica que `predictor.model is not None` e `predictor.feature_names` está populado após `load_model()`. Falha → `RuntimeError` no startup, API não aceita tráfego.

**Por que existe:** detecta cenário "imagem Docker baked com `run_id A` mas YAML aponta pra `B`". Pega divergência entre `mlflow_run_id` no `configs/active_models/{cliente}.yaml` e `predictor.mlflow_run_id` em runtime. Mesma verificação pra variantes A/B.

**Onde no código:** `validate_model_loaded` em [`V2/src/core/startup_checks.py`](../src/core/startup_checks.py) (commit `a1213f9`). Integrado em `production_pipeline.LeadScoringPipeline.__init__`.

**Status:** ✅ ativo desde 29/abr.

*Identificadores históricos: T3-6 (validação MODEL_PATH) e T3-7 (reconciliação run_id).*

---

## Auditoria de infraestrutura — gaps e ações

Catálogo dos componentes do sistema, com status atual de cada peça e o que precisaria ser feito.

### Encoding: treino vs produção

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| Encoding categórico (função `apply_categorical_encoding`) | ✅ existe | `src/features/encoding.py:64-365` | — |
| Carregamento do registro de features | ✅ existe | `src/core/encoding.py:37-100` | — |
| Teste de encoding por variante A/B | ✅ existe | `scripts/test_encoding_overrides.py:160-223` | Adaptar pra cobrir paridade geral, não só A/B |
| Auditoria de paridade (Medium) | ✅ parcial | `tests/parity_audit.py:138-150` | Estender pra encoding ordinal e UTM |
| Nomes de colunas ordinal | ✅ corrigido | `src/features/encoding.py:45,56` | (era bug ativo — `'Qual a sua idade?'` desalinhado entre yaml e DataFrame com fallback silencioso para OHE) |
| Snapshot encoding treino vs prod | ✅ existe | `tests/fixtures/` | — |
| Verificação de feature 100% zerada | ✅ ativo | `src/core/encoding.py` | — |

### CAPI: integridade do sinal enviado ao Meta

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| Envio de evento ao Meta | ✅ existe | `api/capi_integration.py:263-375` | — |
| Verificação de taxa de eventos perdidos | ✅ existe | `src/monitoring/capi_monitor.py:45-129` | — |
| Verificação de taxa de eventos rejeitados | ⚠️ stub | `src/monitoring/capi_monitor.py:136-149` | Implementar query de rejeitados vs aceitos |
| Alerta de decil sem eventos | ✅ ativo | `src/monitoring/capi_monitor.py` | — |
| Deduplicação antes do envio | ✅ ativo | `api/capi_integration.py` | — |
| Alerta `capiStatus blocked/null` | ❌ não existe | — | Criar: alerta se blocked+null > 10% do volume diário |
| Formato chaves D01 vs D1 | ⚠️ risco | `api/capi_integration.py:356-357` | Confirmar que lookup de `conversion_rates` usa o mesmo formato que o YAML |

### Pipeline de dados: qualidade do dataset

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| Janela de conversão simétrica | ✅ existe | `src/data_processing/conversion_window.py:13-93` | — |
| Ordem TMB → merge vendas | ✅ correto em treino | `src/train_pipeline.py:400-430` | Confirmar que `production_pipeline.py` respeita |
| Deduplicação no treino | ✅ ativo | `src/core/ingestion.py` | — |
| Cross-check dataset pós-filtro | ❌ não existe | — | Criar: log de N leads por etapa |
| Log de estatísticas por etapa | ✅ ativo | — | — |

### Infraestrutura e configuração

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| `ARG MODEL_PATH` no Dockerfile | ✅ existe | `api/Dockerfile:45-52` | — |
| Stage de artefatos do modelo | ✅ existe | `api/deploy_capi.sh:284-341` | — |
| `load_dotenv()` no treino | ✅ existe | `src/train_pipeline.py:14-17` | — |
| `load_dotenv()` no app.py | ⚠️ ausente | `api/app.py` | Cloud Run injeta env vars, mas guards explícitos em `capi_integration.py` cobrem; falha ruidosa, não silenciosa. Item pulado. |
| Verificação de freshness do token Meta | ❌ não aplicável | — | Token é System User vitalício, não expira. Cancelado. |
| Validação MODEL_PATH vs YAML | ✅ ativo | `src/core/startup_checks.py` | — |
| MLflow experiment ID hardcoded | ⚠️ risco não auditado | `src/` | Verificar: `grep -rn "experiment_id.*=.*[0-9]" V2/src/` |

### Deploy: segurança e reversibilidade

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| Flag `--no-traffic` | ✅ existe | `api/deploy_capi.sh:51` | — |
| Whitelist de branches | ✅ existe | `api/deploy_capi.sh:68-128` | — |
| Referência à revisão anterior | ✅ existe | `api/deploy_capi.sh:252-264` | — |
| Progressão de tráfego (canary) | ✅ documentada | `api/deploy_capi.sh` | — |
| Rollback automático | ❌ não existe | — | Criar: health check pós-deploy + rollback automático |
| Script de validação pós-deploy | ✅ ativo | `scripts/smoke_test_revision.py` | — |
| Proteção de branch main | 🟡 adiável | GitHub | Bloqueada por plano Free do repo |

### Autorização de processo: o deploy deveria acontecer?

Adicionado em 20/abr após incidente: `main` deployada com 100% do tráfego por horas sem verificação de pré-requisitos. Audita se o deploy está autorizado pelo processo (não só tecnicamente OK).

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| Branch autorizada pra produção | ✅ ativo | `api/deploy_capi.sh:68` | — |
| Pré-requisitos checklist concluídos | ✅ verificado manualmente | este doc | — |
| Parity check antes de deploy de main | ✅ ativo | `tests/parity_audit.py` | — |
| Gate de progressão de tráfego | ✅ documentado | — | — |
| Trail de autorização de deploy | ❌ não existe | — | Criar: cada mudança de split de tráfego registrada com motivo e autorização |

### Exceções silenciosas (foco do T2-6)

Pontos onde `except: pass`, `except Exception: pass` ou `except Exception: return {}` engoliam erros sem log.

| Arquivo | Linha | Padrão antigo | Severidade | Status |
|---|---|---|---|---|
| `src/monitoring/orchestrator.py` | 219-220 | `except Exception: pass` (db.rollback) | MÉDIA | ✅ corrigido |
| `src/monitoring/orchestrator.py` | 315 | `except: continue` (gspread row parse) | MÉDIA | ✅ corrigido |
| `api/app.py` | 1638-1640 | `except Exception: return {}` (Railway CAPI lookup) | ALTA | ✅ corrigido |
| `api/app.py` | 2263-2264 | `except Exception: logger.warning` | BAIXA | ✅ já adequado |
| `api/app.py` | 2596-2597 | `except Exception: logger.warning` (revenue_forecast) | BAIXA | ✅ já adequado |

### Fuso horário

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| `datetime.now(timezone.utc)` no capi_monitor | ✅ correto | `src/monitoring/capi_monitor.py:59` | — |
| Constante central de timezone | ✅ existe | `src/core/utils.py` | — |
| Treino, pipeline, orchestrator, validação usam UTC | ✅ ativo | múltiplos | — |

### Monitoramento: alertas automáticos

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| `MonitoringOrchestrator` | ✅ existe | `src/monitoring/orchestrator.py:88-350` | — |
| `DataQualityMonitor` (drift) | ✅ existe | `src/monitoring/data_quality.py` | — |
| `OperationalMonitor` | ✅ existe | `src/monitoring/operational_monitor.py` | — |
| `CAPIQualityMonitor` | ⚠️ parcial | `src/monitoring/capi_monitor.py` | Implementar rejection_rate |
| Envio de alerta no Slack | ✅ existe | `src/validation/slack_notifier.py` | — |
| Thresholds no `config.py` | ✅ existe | `src/monitoring/config.py` | — |
| Alerta D10% out-of-range | ⚠️ pulado | `src/monitoring/orchestrator.py` | Alertas só aparecem no endpoint — usuário consulta manualmente. Sem notificação proativa, item não agrega valor além do que já existe. Reavaliar junto com relatório consolidado (`T3-5`). |
| Thresholds hardcoded | ⚠️ pendente | `src/monitoring/operational_monitor.py` | Mover pra `ClientConfig` |
| Alerta decil com 0 eventos | ✅ ativo | `src/monitoring/capi_monitor.py` | — |
| Relatório diário consolidado | ✅ ativo | `src/monitoring/orchestrator.py` | — |

### Grupo controle e feedback loop

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| `fair_campaign_comparison.py` | ✅ existe | `src/validation/fair_campaign_comparison.py` | — |
| `campaign_classifier.py` | ✅ existe | `src/validation/campaign_classifier.py` | — |
| Importance weighting no treino | ✅ ativo | `src/train_pipeline.py` | — |
| Identificação de leads controle | ⚠️ pendente | — | Filtro por campanha sem ML no dataset de treino |
| Log de proporção controle/tratamento | ⚠️ pendente | — | Logar % de leads controle no dataset antes do treino |

### Relatório de validação

| Componente | Status | Onde | O que fazer |
|---|---|---|---|
| `validate_ml_performance.py` | ✅ existe | `src/validation/validate_ml_performance.py:15-100` | — |
| `CampaignMetricsCalculator` | ✅ existe | `src/validation/metrics_calculator.py` | — |
| `validate_tmb_sales_freshness()` | ✅ existe | `src/validation/validate_ml_performance.py:105-150` | — |
| Limite de queries de validação | ✅ ativo (100k/200k com alerta) | `src/validation/` | — |
| Filtro de vendas não aprovadas | ✅ confirmado (default `include_canceled=False`) | `src/validation/` | — |
| Cross-check total vs fonte primária | ❌ não existe | — | Criar: assert total_leads_relatório ≈ total_Meta_Ads ± 5% |
| Reconciliação de run_id | ✅ ativo | `src/core/startup_checks.py` | — |

---

## Status final por item (tabela enxuta)

Mapeamento entre os identificadores históricos e o status atual. Use isso quando precisar localizar um commit antigo que cita `T1-X`.

| ID histórico | Título verbal | Status | Data |
|---|---|---|---|
| T1-1 | Encoding com fallback bloqueado quando falha | ✅ Concluído | 2026-04-20 |
| T1-2 | CAPI alerta quando algum decil para de enviar | ✅ Concluído | 2026-04-20 |
| T1-3 | CAPI deduplica eventos antes de enviar | ✅ Concluído | 2026-04-20 |
| T1-4 | Datas usam UTC consistente | ✅ Concluído | 2026-04-20 |
| T1-5 | D10% alerta out-of-range | ⚠️ Pulado | (ver "Monitoramento: alertas automáticos") |
| T1-6 | `app.py` com `load_dotenv` | ⚠️ Pulado | (Cloud Run injeta env vars; guards explícitos cobrem) |
| T1-7 | Auditoria de paridade treino × produção | ✅ Concluído | 2026-04-21 |
| T1-8 | Branch autorizada + gate de processo | ✅ Concluído | 2026-04-21 |
| T1-9 | Protocolo de progressão de tráfego | ✅ Concluído | 2026-04-21 |
| T1-10 | Detecção de feature crítica zerada após encoding | ✅ Concluído | 2026-04-21 |
| T1-11 | Validador pré-encoding de features | ✅ Concluído | 2026-04-23 |
| T1-12 | Smoke de paridade pipeline-modelo no fim do treino | 🟡 Backlog | 2026-04-29 |
| T1-13 | Drift de perfil de audiência | ✅ Concluído | 2026-05-08 |
| T1-14 | Smoke test cobre todas as variantes A/B | ✅ Concluído | 2026-05-08 |
| T1-15 | Auditoria de paridade por variante A/B | ✅ Concluído | 2026-05-08 |
| T1-16 | Validador pós-encoding ">X% leads zerados" | ✅ Concluído | 2026-05-11 (commit `8b1c804`). Resolve V.1.3 do registro de erros. |
| T1-17 | Auditoria de YAML dentro da imagem (Gate D) | ✅ Concluído | 2026-05-08 |
| T1-18 | Equivalência de score+decil entre revisões (Gate C) | ✅ Concluído | 2026-05-08 |
| T1-19 | Validação de schema contra MLflow | ✅ Concluído | 2026-05-11 (`audit_schema_against_mlflow` em `parity_audit.py` + Gate A) |
| T2-1 | Deduplicação no treino | ✅ Concluído | 2026-04-23 |
| T2-2 | Log de count em cada etapa | ✅ Concluído | 2026-04-28 |
| T2-3 | Importance weighting pra grupo controle | ✅ Concluído | 2026-04-28 |
| T2-4 | Limite de queries de validação | ✅ Concluído | 2026-04-28 |
| T2-5 | Filtro de vendas não aprovadas | ✅ Confirmado | 2026-04-28 |
| T2-6 | Eliminar exceções silenciosas críticas | ✅ Concluído | 2026-04-28 |
| T2-7 | Validador automatizado pós-deploy | ✅ Concluído | 2026-04-23 |
| T2-8 | Alerta variância baixa em feature de alta importância | ✅ Coberto por `check_distribution_drift` | 2026-04-29 |
| T2-9 | Bootstrap de snapshots em máquina fresca / CI | 🟡 Backlog | 2026-05-09 |
| T3-1 | Canary documentado inline no script | ✅ Concluído | 2026-04-29 |
| T3-2 | Smoke test pós-deploy | ✅ Concluído (= Gate B) | 2026-04-21 |
| T3-3 | Proteção de branch main | 🟡 Adiável | (Plano Free do GitHub) |
| T3-4 | Verificação periódica do token Meta | ❌ Cancelado | 2026-04-23 |
| T3-5 | Relatório operacional consolidado | ✅ Concluído | 2026-04-29 |
| T3-6 | Validação MODEL_PATH vs YAML no startup | ✅ Concluído | 2026-04-29 |
| T3-7 | Reconciliação de run_id no startup | ✅ Concluído | 2026-04-29 |

---

## Como testar cada item

Após implementar qualquer item, o teste mínimo é:

**Encoding / CAPI / timezone:**
```bash
cd V2/
python scripts/test_encoding_overrides.py --limit 200
python -m pytest tests/parity_audit.py -v
python -c "from src.core.utils import UTC; print(UTC)"
```

**Monitoramento:**
```bash
python -c "
from src.monitoring.orchestrator import MonitoringOrchestrator
m = MonitoringOrchestrator()
result = m.run_daily_check()
print(result)
"
```

**Deduplicação:**
```bash
python -c "
from src.core.ingestion import remove_duplicates_per_sheet
print('OK')
"
```

**Smoke test pós-deploy (manual):**
```bash
curl -X POST https://smart-ads-api-12955519745.us-central1.run.app/predict/single \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","campaign":"TEST",...}'
# Verificar: leadScore != null, decil entre 1-10, capiStatus registrado
```
