# Auditoria de quebra de produção

Documento operacional, escrito em linguagem natural. Lista os cenários que **podem efetivamente quebrar produção** (degradar score em massa, zerar valor enviado ao Meta, bloquear retreino) e que **valem o tempo de atacar agora**.

**Critério de entrada:** o cenário só está aqui se já tem **precedente histórico de quebrar produção** OU se tem **pré-condição clara hoje pra afetar ≥2% dos leads**. O resto vai pro fundo (seção "Documentado mas não atacar agora") com motivação curta.

**Política de referência:** este doc é a camada operacional. Quando um cenário precisar de detalhe técnico de implementação, link direto pro arquivo correspondente em vez de duplicar conteúdo. Especificações técnicas continuam vivendo em [PLANO_SAFEGUARD.md](PLANO_SAFEGUARD.md), [PLANO_REFACTOR_MLOPS.md](PLANO_REFACTOR_MLOPS.md) e [registro_erros_ml.md](registro_erros_ml.md).

---

## 1. As features chegam certas no modelo?

**O que esta seção cobre:** tudo que pode fazer uma feature crítica chegar **zerada**, com **tipo errado**, ou com **valor inesperado** pro modelo — degradando o score sem aviso. É a categoria de bug mais frequente e mais danosa do histórico desse projeto: quase todos os Erros 1-17 do registro de erros caem aqui.

### Cenário 1.1 — Encoding desalinhado quando A/B reativar com Champion novo

**O que aconteceria:** o próximo Champion é promovido pra rotação A/B e a configuração de encoding por variante (`encoding_overrides` em `configs/active_models/{client}.yaml`) não acompanha. Modelo recebe features encodadas no formato errado, score sai degradado.

**Por que isso importa:** já aconteceu. De 29/abr a 05/mai, Champion `jan30` rodou no A/B sem `encoding_overrides` — `idade` e `faixa_salarial` chegaram zeradas em ~25% dos leads por 7 dias. Quando o próximo Champion sair (DT-16), o mesmo gap reabre se a checklist de promoção não cobrir explicitamente.

**Como verificar:**
- Ler [PROMOCAO_MODELO_CHECKLIST.md](PROMOCAO_MODELO_CHECKLIST.md) e confirmar que o checklist exige editar `encoding_overrides` da variante junto com `mlflow_run_id`.
- Rodar `python V2/tests/parity_audit.py --function encoding_ab` antes de qualquer promoção — auditoria por variante já cobre o caso (instrumentação fechada hoje em commit `4c6c472`).

**Critério de fechamento:** próximo deploy de Champion passar pelo Gate A do `deploy_capi.sh` com `--function encoding_ab` retornando OK.

### Cenário 1.2 — Categoria nova de feature de alta importância escapa da whitelist canônica — [📊 AUDITADO 2026-05-14]

**Resultado da auditoria (n=44.397 leads dos últimos 30 dias, SQL direto no Railway):**

| Coluna | Categorias com ≥2% do volume | Observação |
|---|---|---|
| `medium` | `aberto` 38.85%, `mix quente` 14.87%, `dgen` 9.67%, variantes `aberto \| ad0XXX...` 4-6%, criativo TikTok literal (`dev-ad0150-vid-captação-v0-...`) 3.69%, `org` 3.26%, vazio 2.17% | `mix quente` é a categoria distinta confirmada — vira "Outros" hoje. Decisão já tomada (item M1 do `PLANO_EXECUCAO`: virar categoria canônica no próximo retreino). Variantes de `aberto \| ad0XXX` são granulação fina e são absorvidas pelo threshold de frequência (`medium.frequency_threshold=0.025`) — não exigem ação. |
| `source` | `facebook-ads` 77.75%, `google-ads` 9.67%, `tiktok` 3.69%, `ig` 2.55% | `tiktok` confirma o bug ativo do path Champion descrito em DT-19 (refactor unify_utm variant-aware). `ig` é mapeado para `instagram` via `source_to_channel_mapping`. |
| `term` | `ig` 62.24%, `fb` 14.60%, vazio 5.86%, IDs longos `23504811738--...` 2.49% + `23731741326--...` 2.23% | IDs numéricos longos (>10 dígitos) não casam com `term_outros_patterns` atuais (que pegam dígitos curtos, ver DT-13). Volume agregado 4.72% — entra na decisão de DT-19 (extensão da whitelist do Term via variante). |

**Critério de fechamento:** auditoria realizada, todas as categorias ≥2% têm decisão registrada (M1 para mix quente; DT-19 para tiktok e IDs longos Term; absorção por threshold para granulação `aberto \| ad0XXX`). Sensor adicional (validador cross-coluna `Source_*` todas zeradas) plantado em [`src/core/feature_validator.py`](../src/core/feature_validator.py) `validate_post_encoding_all_zero_groups` em 14/mai — detecta automaticamente novas categorias que escapem da whitelist da variante.

### Cenário 1.2 — Categoria nova de feature de alta importância escapa da whitelist canônica (descrição original)

**O que aconteceria:** o gestor lança uma campanha com nova categoria de `Medium`/`Source`/`Term` (ex.: `Medium_Banco_de_Dados`). A whitelist canônica em `configs/distribuicoes_esperadas.json` não cobre, encoding zera essa coluna, e leads daquela categoria têm score degradado.

**Por que isso importa:** já aconteceu duas vezes. Cluster 3 do Erro 2 foi `Medium_Linguagem_programacao` zerado. Cluster 4 foi padrão similar com outra categoria. Em cada vez, a feature ficou silenciosamente zerada por semanas porque o sensor que existia (`check_category_drift`) só logava warning sem bloquear.

**Como verificar:**
- Sample 30 dias de leads do Railway, agrupar `utm_medium` / `utm_source` / `utm_term` por categoria, e cruzar com a whitelist em `configs/distribuicoes_esperadas.json`.
- Para cada categoria não-whitelisted que tem ≥2% do volume, decidir: aceitar como "outros" (atualizar whitelist) ou criar tratamento dedicado.

**Critério de fechamento:** lista de categorias fora da whitelist com ≥2% volume nos últimos 30 dias = vazia, OU cada categoria tem decisão registrada.

### Cenário 1.3 — Front muda formato das 4 features binárias raw — [✅ AUDITADO 2026-05-14]

**Resultado da auditoria (amostra n=10.000 leads dos últimos 30 dias com `Lead.pesquisa` preenchido):**

| Feature | Valores distintos vistos | Strings vazias |
|---|---|---|
| `genero` | `'Masculino'` 76.53%, `'Feminino'` 23.43% | 0.04% (4 leads) |
| `estudouProgramacao` | `'Não'` 64.96%, `'Sim'` 35.00% | 0.04% (4 leads) |
| `faculdade` | `'Sim'` 76.31%, `'Não'` 22.73% | 0.96% (96 leads) |
| `investiuCurso` | `'Não'` 57.70%, `'Sim'` 42.26% | 0.04% (4 leads) |

**Critério de fechamento:** ✅ atendido. Zero variação de casing ou whitespace nos últimos 30 dias. Strings vazias agregadas <1% por feature — viram NaN→0 no encoding, comportamento esperado. Front estável; DT-18 (normalização) continua sendo a defesa estrutural mas o risco atual é baixo. Reauditar em ciclo trimestral ou ao primeiro alerta `new_categories` em `_check_category_drift`.

### Cenário 1.3 — Front muda formato das 4 features binárias raw (descrição original)

**O que aconteceria:** o front começa a mandar `'sim'` (minúsculo) em vez de `'Sim'`, ou `'Masculino '` (com espaço extra). Essas 4 features **não passam por normalização** no pipeline — vão direto pro `pd.get_dummies()`. Resultado: cria coluna OHE inédita (`Sim_lower`), modelo zera a feature original. Conjunto representa ~8% do peso do modelo Champion atual.

**Por que isso importa:** sem precedente exato, mas a precondição é certa (sem normalização nessas 4 features) e foi documentada na seção V.2 do registro de erros. Mesma classe do Cluster 1 (07/jan: `'NÃO'` em "Tem computador?" quebrou OHE de outra feature). Risco operacional baixo enquanto front estiver estável, mas qualquer mudança de schema do form quebra silencioso.

**Como verificar:**
- Pull dos últimos 30 dias do `Lead.pesquisa` jsonb. Para cada uma das 4 chaves (`genero`, `estudouProgramacao`, `faculdade`, `investiuCurso`), listar todos os valores distintos e a contagem.
- Se aparecer qualquer valor fora do canônico (`Sim`/`Não`/`Masculino`/`Feminino`), levantar como bug do front antes de virar problema do modelo.

**Critério de fechamento:** zero valores fora do canônico nos últimos 30 dias, OU lista de exceções com volume <2% e plano de fix do front.

---

## 2. O modelo e a configuração estão consistentes?

**O que esta seção cobre:** tudo que pode fazer com que o **modelo ativo**, o **encoding por variante A/B** e os **valores enviados ao Meta** saiam dessincronizados durante uma promoção. O ponto cego clássico: alguém troca uma coisa achando que é trivial, mas era a ponta de um trio.

### Cenário 2.1 — Trocar `mlflow_run_id` sem ajustar `conversion_rates` por variante

**O que aconteceria:** novo modelo Champion entra com decis recalibrados (faixa de score diferente), mas os `conversion_rates` por decil em `active_models/{client}.yaml` (variants A/B) continuam dos valores antigos. Resultado: `value` enviado ao Meta sai descalibrado em 100% dos leads do path Champion, ou pior, zera (caso conversion_rates dos variants foi setado pra 0.0 em algum momento).

**Por que isso importa:** já aconteceu em 08/05 (bug VAL=0 v2 — variants A/B com `conversion_rates: {D01: 0.0, ..., D10: 0.0}` herdados de patch anterior, valor zerado pro Meta no path Champion durante canary).

**Como verificar:**
- Antes de qualquer promoção de modelo, rodar `python V2/scripts/audit_active_model_yaml.py` (Gate D em `deploy_capi.sh`) — confirma que `conversion_rates` de cada variant está dentro do esperado vs `business_config.conversion_rates`.
- Manualmente: para cada variant em `active_models/{client}.yaml`, calcular `value × product_value` pelo decil mediano e comparar com baseline conhecido.

**Status (atualizado em 11/mai/2026):** [✅ FECHADO]. Gate D já roda obrigatoriamente no `deploy_capi.sh` após o smoke test do canary (linhas 599-625). O único skip silencioso restante — "se o script Gate D não existir no caminho, pula com warning" — foi removido em 11/mai: agora script ausente = falha alta com `exit 1`. Sem caminho de fuga.

### Cenário 2.2 — Deploy aponta pra `run_id` cujo artefato sumiu — [✅ FECHADO 2026-05-11]

**Resultado da auditoria:** o cenário original foi descrito sob a premissa de que o Cloud Run baixaria artefatos do GCS no boot. **Não é a arquitetura real.** O sistema atual baka os artefatos do MLflow direto na imagem Docker (`mlruns_build/` é copiado pra dentro do container), então o Cloud Run nunca depende do GCS em runtime — ele depende da imagem.

Pre-flight equivalente JÁ EXISTE em [`V2/api/deploy_capi.sh`](../api/deploy_capi.sh):
- Linhas 272-290: confirma que `mlruns/1/{run_id}/artifacts/model/model.pkl`, `model_metadata.json` e `feature_registry.json` existem **localmente** antes de prosseguir com o build. Falha alto se faltar.
- Linhas 390-393: bloqueia o stage do Champion se a pasta de artefatos não existir.
- Linhas 419-423: bloqueia o stage de variantes A/B com mensagem pronta de `mlflow.artifacts.download_artifacts(run_id, dst_path)` pra puxar do GCS.

O cenário marginal restante seria "artefato existe localmente mas GCS foi limpo" — afeta apenas outro dev em máquina nova (não afeta produção). Não justifica check adicional.

**Precedente histórico (Erro 11):** modelo "salvo em path diferente" foi causa relatada na época. Esse caso específico está coberto pelo check local + a recuperação via `download_artifacts` documentada inline.

---

## 3. Promover nova versão não quebra produção?

**O que esta seção cobre:** tudo que pode fazer com que uma revisão nova suba pra 100% de tráfego carregando bug que os gates de pré-deploy não pegaram. Diferente da seção 2 (configuração inconsistente), aqui o foco é o **gate ele mesmo ter falhado em detectar**.

### Cenário 3.1 — Salvaguarda declarada como entregue mas nunca implementada — [✅ FECHADO 2026-05-11]

**O que aconteceria:** o `PLANO_SAFEGUARD.md` lista uma salvaguarda como ✅ concluída, mas o código correspondente nunca foi mergeado, ou foi mergeado mas o caminho de invocação está quebrado, ou foi removido depois sem atualizar o doc.

**Por que isso importa:** já aconteceu. A salvaguarda "feature zerada em >5% dos leads gera alerta + bloqueia" foi declarada como entregue em 21/abr no `PLANO_SAFEGUARD.md`, mas a investigação V.1.3 do registro de erros (08/mai) confirmou que **nunca foi implementada**. Existia apenas log de feature ausente do DataFrame, sem bloquear pipeline. Esse gap permitiu que o Cluster 5 (encoding zerado em 25% dos leads) passasse 7 dias sem detecção.

**Resultado da auditoria (11/mai/2026):** 23 itens declarados ✅ auditados com leitura direta do código (`production_pipeline.py`, `api/app.py`, `deploy_capi.sh`, `orchestrator.py`, `core/encoding.py`, etc.). **Zero fantasmas adicionais encontrados além de T1-16 (que já estava marcado como 🟡 backlog no doc).** Resultado por categoria:

- **19/23 ✅ FUNCIONA** — código existe na localização declarada E é invocado de caminho de produção real.
- **4/23 ⚠️ DRIFT** de documentação (não bug de produção):
  - **T1-3 (CAPI dedup)** — doc apontava `capi_integration.py`; na realidade dedup cliente-side vive em [`api/app.py:865-875`](../api/app.py#L865-L875) + endpoint `/capi/check_sent`. PLANO_SAFEGUARD.md atualizado.
  - **T2-2 (log_step_count)** — doc dizia "6+2 pontos"; real é "8+3". PLANO_SAFEGUARD.md atualizado.
  - **T2-5 (filtro vendas)** — loaders estão em [`src/validation/data_loader.py`](../src/validation/data_loader.py), não em `core/ingestion.py`. PLANO_SAFEGUARD.md atualizado.
  - **T2-6 (exceções silenciosas)** — `app.py:1637` tinha `logger.error` mas faltava `exc_info=True`. Adicionado em 11/mai.
- **0/23 ❌ FANTASMA** novo (T1-16 segue como o único fantasma conhecido, já catalogado como backlog).

**Critério de fechamento:** ✅ atendido. Lista de salvaguardas com status real registrada acima; correções aplicadas. T1-16 (validador pós-encoding bloqueador) continua sendo o único item declarado-mas-ausente, e a pré-condição dele foi destravada em 11/mai (baselines calculáveis offline — ver `PLANO_SAFEGUARD.md` § "Validador pós-encoding").

### Princípio de design — roteamento via UTM como ferramenta, não como solução para bugs arquiteturais

Discutido em sessão 11/mai. Roteamento (regras `utm_pattern` / `url_pattern` que mandam leads pra variantes A/B diferentes) é mecanismo válido para **comparar dois modelos** ou **isolar variante experimental**. Não é solução para contornar bug arquitetural — usar roteamento como "lead que tem normalização vai pro modelo novo, lead sem vai pro antigo" acumula complexidade exponencial: cada regra nova exige cobertura em smoke test, parity audit por variante, Gate C de equivalência de decil, e checklist de promoção.

**Regra de ouro:** routing pra isolar experimento ✅, routing pra contornar bug não-fixado ❌. Bug arquitetural se resolve com **retreino do Champion** com o fix, não com regra de UTM nova. Aplicação concreta: DT-18 (4 features binárias raw) e DT-19 (Source TikTok) ficam bloqueados por retreino — não viram regra de roteamento.

### Cenário 3.2 — Gates pré-deploy não exercitam todos os caminhos de produção — [📋 EM DOCUMENTAÇÃO]

**O que aconteceria:** o smoke test, o parity audit ou o Gate C cobrem só o caminho default. Caminhos específicos (variantes A/B, encoding overrides, predictor override) nunca são testados pré-deploy. Bug específico desse caminho passa.

**Por que isso importa:** já aconteceu (mesma origem do Cluster 5). Smoke test antigo chamava `/monitoring/daily-check/railway` sem contexto A/B — nunca exercitava o Champion com `encoding_overrides`. Parity audit antigo testava só `config.encoding` padrão. Os dois gaps foram fechados em 08/mai (smoke variantes + parity por variante), mas a classe persiste — qualquer caminho novo que entre precisa de cobertura explícita.

**Matriz de cobertura pré-deploy — estado em 11/mai/2026:**

Eixos:
- **Endpoint** (5): `/predict/single`, `/predict/batch`, `/railway/process-pending`, `/capi/process_daily_batch`, `/webhook/lead_capture`.
- **Variante A/B** (2): Champion `jan30` (path default, sem utm_campaign match), Challenger `abr28` (utm_campaign='PIXEL NOVO API').
- **Override** (3): encoding override (ordinal idade/salário pro Champion), conversion_rates override (per-variant no YAML), predictor override (variante A/B usa seu próprio modelo).

| Endpoint | Variante | Encoding override | Conversion override | Predictor override | Gate cobrindo |
|---|---|---|---|---|---|
| `/predict/batch` | Champion | ordinal (ativo) | rates Champion | predictor jan30 | Gate A (audit_encoding_ab Champion shim) + Gate B (smoke 5 leads default) + Gate C (capi-dry-run) |
| `/predict/batch` | Challenger | OHE (default) | rates Challenger | predictor abr28 | Gate A (audit_encoding_ab Challenger) + Gate B (smoke /run-variants Challenger) + Gate C (force chlng+ prefix) |
| `/predict/single` | Champion | ordinal | rates Champion | predictor jan30 | Coberto via /predict/batch que internamente delega |
| `/predict/single` | Challenger | OHE | rates Challenger | predictor abr28 | Coberto via /predict/batch |
| `/railway/process-pending` | Champion | ordinal | rates Champion | predictor jan30 | ✅ Smoke direto via `?dry_run=true` (11/mai) — `check_railway_polling_smoke()` em `scripts/smoke_test_revision.py` |
| `/railway/process-pending` | Challenger | OHE | rates Challenger | predictor abr28 | ✅ Mesmo gate — exercita o caminho A/B real do polling em dry_run |
| `/capi/process_daily_batch` | Champion | ordinal | rates Champion | predictor jan30 | Gate C (capi-dry-run mode) |
| `/capi/process_daily_batch` | Challenger | OHE | rates Challenger | predictor abr28 | Gate C (capi-dry-run + force chlng+ prefix) |
| `/webhook/lead_capture` | N/A (não scoreia) | — | — | — | Não scoreia, não precisa de gate de paridade |

**Gaps identificados:**
1. ~~`/railway/process-pending` não tem smoke test direto.~~ **Resolvido em 11/mai:** `check_railway_polling_smoke()` em `scripts/smoke_test_revision.py` chama o endpoint com `?dry_run=true` (lê + scoreia sem escrever no banco nem disparar CAPI). Pega bugs específicos do caminho — parse JSONB, dedup em batch, gravação.
2. Combinações 100%-Challenger / 100%-Champion (sem split) não são exercitadas — hoje sempre vai 50/50 no Gate C. Risco operacional baixo (não é cenário planejado).
3. Não há cobertura para o caminho "predictor_override do Challenger mas encoding default" — combinação atualmente inexistente em produção, mas seria armadilha se um Challenger novo entrar sem `encoding_overrides` definido.

**Critério de fechamento:** matriz acima mantida atualizada a cada mudança de variante A/B ou endpoint novo. Gap (1) ✅ fechado em 11/mai. Gaps (2) e (3) permanecem em backlog de baixa prioridade (cenários atualmente inexistentes em produção).

---

## 4. Conseguimos detectar quando algo quebrou?

**O que esta seção cobre:** quando a quebra escapa dos gates pré-deploy e chega em produção, em quanto tempo o sensor avisa? Quando o sensor não dispara, qual é o atalho de detecção manual? Aqui o foco é **observabilidade de falha em runtime**.

### Cenário 4.1 — Drift de público que afeta performance do lançamento passa silencioso — [✅ FECHADO TECNICAMENTE 2026-05-11]

**O que aconteceria:** o tráfego do lançamento traz perfil de audiência que diverge do perfil do treino (ex.: idade média 10 anos abaixo, mix de gênero invertido). O modelo continua scorreando dentro do range conhecido (sem `null_rate_high` nem `wrong_dtype`), então os sensores existentes não disparam. Performance do lançamento cai sem causa visível.

**Resultado da validação (11/mai):**
- Sensor `_check_audience_profile_drift` em [`V2/src/monitoring/data_quality.py:1968`](../src/monitoring/data_quality.py#L1968) está ativo via `THRESHOLDS['audience_profile_drift']['enabled']=True`.
- Snapshot de referência [`V2/configs/reference_audience_profiles/devclub.json`](../configs/reference_audience_profiles/devclub.json) foi regerado em 2026-05-14 — pós-LF54, captura corretamente o pool Top 5 ROAS atribuível 60d.
- Rodando o sensor com leads de ontem (n=707 do LF55), dispara 1 alerta HIGH com 11 categorias ≥2.0pp de drift (idade, ocupação, faixa salarial). Mensagem detalhada e acionável (ex.: "Idade: 35-44 — 23.4%→19.4% (-4.1pp)").
- O alerta entra automaticamente em `actionable_alerts` (HIGH+MEDIUM) do response `/monitoring/daily-check/railway` ([orchestrator.py:230-241](../src/monitoring/orchestrator.py#L230)), ordenado por severity no topo.

**Único item pendente:** **rotina humana** de leitura do alerta. Tecnicamente o sinal chega ao endpoint; cabe ao operador estabelecer cadência fixa de leitura (ex.: chave-de-dia antes do almoço). Sem isso, o alerta vai pro JSON sem ninguém olhar — risco real, mas não é mais "bug de salvaguarda" e sim "disciplina operacional".

**Por que isso importa:** aconteceu no LF54 em 08/mai. Detectado manualmente por comparação ad-hoc contra Top 5 ROAS histórico. Mitigação foi implementada e agora confirmada funcional.

### Cenário 4.2 — Feature crítica do modelo zera em massa e ninguém é notificado — [✅ FECHADO 2026-05-11]

**Resultado:** validador pós-encoding bloqueador implementado (item T1-16 do `PLANO_SAFEGUARD.md`). Quando o pipeline gera uma coluna OHE mas ela chega zerada em massa (sinal de feature pré-OHE quebrada — categoria sumiu, casing mudou, parsing JSONB falhou), o `apply_encoding` levanta `ValueError` antes do scoring. Bloqueia o caminho que causou os Clusters 3, 4 e 5 do Erro 2.

Componentes:
- Gerador offline dos baselines: [`V2/scripts/generate_feature_zero_baselines.py`](../scripts/generate_feature_zero_baselines.py) lê `distribuicoes_esperadas.json` do MLflow e calcula a fração esperada de cada coluna OHE. Saída em `V2/configs/feature_zero_baselines/{run_id}.json`.
- Validador em runtime: `validate_post_encoding_zero_rates()` em [`V2/src/core/feature_validator.py`](../src/core/feature_validator.py). Thresholds default — batch ≥50, expected ≥15%, drop ≥70% — distinguem bug claro de sample noise mesmo em batches do polling Railway.
- Integração no encoding: [`V2/src/core/encoding.py`](../src/core/encoding.py) passo 9, chama o validador quando `artifacts['mlflow_run_id']` está setado (caminho de produção; treino e parity audit passam `artifacts={}` e pulam).

Validado com input real de produção (200 leads do Railway via `railway_lead_to_sheets_row`): caso saudável passa sem disparar; caso patológico (`Source = None`) dispara corretamente com `Source_facebook_ads` esperado 89.9% / observado 0%.

**Próximo retreino:** rodar `python -m V2.scripts.generate_feature_zero_baselines` após `--set-active` pra gerar o baseline do novo Champion. Sem baseline pra um `run_id`, o validador degrada pra noop com log informativo.

**O que aconteceria (descrição original):** uma feature de alta importância (ex.: `idade`, `faixa_salarial`, ou uma das `Medium_*`) começa a chegar com valor 0 ou ausente em ≥10% dos batches. Modelo continua scoreando, mas o sinal degrada. Sem alerta automático, descoberto só dias depois quando alguém olha relatório.

**Por que isso importa:** mesma classe do Cluster 5 e da V.1.3. Aconteceu várias vezes no histórico. Mitigação prevista (validação ">X% zerados → bloqueia") **ainda não foi implementada** (declarada mas ausente — ver Cenário 3.1).

**Como verificar:**
- Implementar de fato a validação pós-encoding feature-aware. Para cada feature com `importance ≥ 0.03`, calcular `(df[feature] == 0).mean()`. Se >X% leads têm zero E a distribuição esperada do treino tinha <X%, raise.
- Pré-condição (revisada em 11/mai): **destravada.** O `proporcao_esperada_zero` por coluna OHE é derivável offline dos `distribuicoes_esperadas.json` já registrados no MLflow. Fórmula: para coluna `feature_categoria`, `proporcao_esperada_zero = 1 - distribuicoes_esperadas['categorical'][feature][categoria]`. Não precisa de retreino.

**Critério de fechamento:** baselines `configs/feature_zero_baselines/{run_id}.json` gerados pra Champion e Challenger via script offline, e validação pós-encoding implementada lendo desses baselines em runtime. Testar com batch sintético com feature zerada.

---

## 5. O retreino vai funcionar quando precisar?

**O que esta seção cobre:** o retreino mensal pode falhar por **pré-condição operacional** (banco parado, snapshot ausente, dataset corrompido) que ninguém percebe até o momento de rodar. Custo dessa falha é alto: atrasa o retreino e o time fica reagindo em cima da hora.

### Cenário 5.1 — Cloud SQL `smart-ads-db` em `activation-policy=NEVER` quando retreino disparar — [✅ FECHADO 2026-05-11]

**Resultado da auditoria:** o pre-flight check JÁ EXISTE como `assert_mlflow_backend_running()` em [`V2/src/model/training_model.py:46-96`](../src/model/training_model.py#L46-L96), invocado em `train_pipeline.main():246` e `retraining_orchestrator.main():631`. Verifica `state` da instância via `gcloud sql instances describe`, falha alto com `RuntimeError` se diferente de `RUNNABLE` e a mensagem inclui o comando exato pra subir a instância. Complementar: `register_mlflow_cleanup_reminder()` emite lembrete no fim do processo pra desligar a instância (economia ~R$40/mês). Verificado em 11/mai com instância em `STOPPED` — guard disparou corretamente com mensagem clara.

**O que aconteceria:** retreino é disparado (manual ou agendado), tenta conectar no MLflow tracking pra registrar o run, falha porque a instância está parada. Treino aborta no início, ninguém é notificado. Demora 2-3 minutos pra subir a instância depois que alguém percebe.

**Por que isso importa:** estado atual confirmado — instância está em `activation-policy=NEVER` desde 26/abr (registrado em memória `projeto_cloudsql_parado_retreino.md`). Pré-condição clara, alta probabilidade de morder no próximo retreino se ninguém lembrar.

**Como verificar:**
- Adicionar passo no início do `train_pipeline.py`: `gcloud sql instances describe smart-ads-db --format='value(state)'` e abortar com mensagem clara se diferente de `RUNNABLE`.
- Idealmente: rotina que sobe automaticamente no início do treino e para no fim (script já documentado em `operacoes_gcp_custos.md`).

**Critério de fechamento:** pre-flight check rodando no `train_pipeline.py` ou wrapper bash que sobe e para a instância automaticamente.

---

## Documentado mas não atacar agora

Cenários conhecidos que **não passam o critério de ≥2% de impacto OU não têm precedente direto**. Ficam aqui pra quando o tempo permitir, ou pra entrar quando contexto mudar.

| Cenário | Por que não atacar agora |
|---|---|
| Macros literais TikTok no `utm_medium` | ~1.3% volume, score levemente degradado, ação está com gestor (Isaque). Confirmado em 11/mai: sem ação nossa adicional. |
| `MIX QUENTE` como categoria canônica do Medium (LF54 frio = 0%; DEV quente = 30-46%) | **Decisão REABERTA em 18/mai.** A premissa de 11/mai ("coluna OHE zerada em LF é neutra, zero routing") está errada: se o RF aprende um split condicionado em `Medium_MIX_QUENTE` (público presente só em DEV), em LF todos os leads caem no mesmo galho → distorce a distribuição de decis em LF. Decisão pendente entre 3 opções (modelo separado DEV/LF, excluir, ou incluir-e-auditar). Hard-enforced: `retraining_decisions.mix_quente` no `devclub.yaml` bloqueia `--set-active` enquanto `PENDENTE`. Item M1 do PLANO_EXECUCAO. |
| Gate C de deploy com payload incompleto | Corrigido hoje (commit `4c6c472`) |
| In-app browser produzindo cliques sem `fbclid` | Não afeta score — é cosmético na atribuição |
| Lead com TZ na borda 23:59 BRT | Sem precedente recente, baixíssima frequência |
| `.str` accessor com batch=1 em `/railway/process-pending` | Auto-recupera no próximo poll |
| Token Guru renovado com `\|` na string | Sem precedente, robustez do dotenv não validada mas baixo risco |
| `utm_source` `null` vs `""` vs ausente | Esporádico, encoding já fallback pra `outros` |
| A/B 100% Challenger / 0% Champion | Cenário hipotético, não há plano operacional pra isso |
| `Lead.pesquisa` jsonb com chave nova | Front estável, sem mudança planejada |
| Encurtadores sem `utm_source/medium/term` | ~8 leads/48h, baixíssimo impacto |
| Pixel ID override em Challenger sem documentação | Funcional hoje, doc pendente mas não bloqueia |
| Lead Forms (formulário nativo Meta) com UTM diferente | Atualmente sem volume |
| Cobertura `feature_registry` real do MLflow no parity audit | Próximo passo natural depois da auditoria de paridade por variante; doc completo pendente |

---

## Como atualizar este doc

- Cenário fechado: marcar `[x]` no título (ex.: `### Cenário 1.1 — Encoding desalinhado [✅ FECHADO]`) e adicionar 1 linha com data + commit/PR.
- Cenário aprofundado: link pra issue/PR onde a investigação está detalhada.
- Cenário sobe da tabela "não atacar agora" pra seção principal: motivo do upgrade (mudança de contexto, novo precedente, etc.).
- Indexação: este doc vive em `INDICE_DOCUMENTACAO.md` na categoria "Operacional / Auditoria".
