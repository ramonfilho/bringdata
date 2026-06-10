# CLAUDE.md — Bring Data V2

Leia este arquivo no início de toda sessão antes de qualquer tarefa.

**Regra inegociável:** o `PLANO_EXECUCAO.md` define a ordem de execução. Seguir passo a passo, na sequência documentada. Nunca reordenar, pular ou antecipar itens sem instrução explícita do usuário.

**Protocolo por item de safeguard:** cada T1-x / T2-x / T3-x é implementado, testado, commitado e deployado individualmente antes de avançar para o próximo. Ver protocolo completo em `docs/PLANO_SAFEGUARD.md` — seção "Protocolo obrigatório por item".

---

## Documentos autoritativos

| Documento | Papel |
|---|---|
| `docs/PLANO_EXECUCAO.md` | ⭐ **Roadmap único** — única fonte de "o que fazer e quando" (horizontes H1–H7, gate único, A/B em Standby, backlog) |
| `docs/ARQUITETURA_SISTEMA_COMPLETA.md` | Arquitetura, fluxos, endpoints, comandos |
| `docs/PLANO_SAFEGUARD.md` | 📚 Catálogo técnico dos itens T1-X / T2-X / T3-X (especificação, não prioridade) |
| `docs/PLANO_REFACTOR_MLOPS.md` | 📚 Catálogo técnico dos DT-X / R-X + histórico do refactor (especificação, não prioridade) |
| `docs/PLANO_REMEDIACAO_LEAD_SCORE.md` | 📚 Catálogo técnico dos consumidores L1–L9 que leem `Lead.leadScore` / `Lead.decil` como verdade atemporal — fotografia do código que rodou na hora, não medição estável (especificação, não prioridade) |
| `docs/AB_TEST.md` | 📚 Design do teste A/B (executar quando o gate for retomado) |
| `docs/INDICE_DOCUMENTACAO.md` | Mapa de papéis e relações entre todos os docs |

**Hierarquia:** `PLANO_EXECUCAO.md` é o roadmap único. Os catálogos (📚) descrevem o **como** técnico de cada item; o **quando** vive no PLANO_EXECUCAO. Quando houver conflito de status ou prioridade, o PLANO_EXECUCAO vence.

Quando houver dúvida sobre o que fazer agora: `PLANO_EXECUCAO.md`.
Quando houver dúvida sobre como um componente deve funcionar: `ARQUITETURA_SISTEMA_COMPLETA.md`.
Quando houver dúvida sobre como implementar um item específico: ir ao catálogo correspondente.

## Skills disponíveis

| Skill | Quando usar |
|---|---|
| `/ctx` | Contexto operacional do projeto — onboarding e desenvolvimento |
| `/mlops-architect` | Contexto arquitetural profundo + checklists de segurança (sinal ML) |
| `/sw-architect` | Arquitetura de software — invocar antes de qualquer mudança em camada cruzada, acesso a dados, ou criação de componente novo |
| `/investigate` | Investigar por que um lançamento foi ruim |
| `/investigate-ab` | Verificar se o teste A/B está tecnicamente válido |
| `/safeguard` | Auditoria completa de integridade do projeto |
| `/docs` | Skill master de documentação — `mapear` (= antigo plan-integrator), `unificar`, `arquivar`, `indexar`, `auditar` |

---

## Comunicação no projeto — linguagem natural sempre primeiro

**Regra obrigatória — aplica a conversas em sessão E a documentação nova.**

Toda menção a um item técnico identificado por código — cenários da auditoria de quebra de produção (1.1, 1.2, 2.1, 3.1, etc.), salvaguardas (T1-X, T2-X, T3-X), dívidas técnicas (DT-X), pré-requisitos do segundo cliente (R-X), itens M1/M2/etc do roadmap, gates A/B/C/D, "Cluster N do Erro 2", etc. — precisa vir acompanhada de uma **descrição em linguagem natural** que permita entender o item sem abrir o catálogo correspondente.

**Por que esta regra existe:** a documentação atual assume que o leitor lembra o nome de todas as funções do código e de cada item dos catálogos. Para um repositório com ~180k linhas e uma única pessoa atuando, isso é humanamente impossível — e o resultado é que cada conversa vira "pergunta pelo significado de cada sigla" e o tempo do operador se perde em decodificar em vez de decidir.

**Formato esperado:**

| Errado | Certo |
|---|---|
| "Vamos atacar o 1.2 e o 2.1 sequencial." | "Vamos atacar dois cenários: categorias UTM novas que não estavam na whitelist do modelo (cenário 1.2 da auditoria) e troca de modelo sem ajustar a tabela de valor por decil enviado ao Meta (cenário 2.1)." |
| "M1 e DT-18 dependem de retreino." | "Duas dívidas dependem do próximo retreino: reativar o público 'MIX QUENTE' como categoria canônica do Medium (item M1 do PLANO_EXECUCAO), e normalizar as 4 features binárias da pesquisa — gênero, estudou programação, fez faculdade, investiu em curso (DT-18 do PLANO_REFACTOR_MLOPS)." |
| "Gate D bloqueia se VAL=0." | "O Gate D (auditoria do YAML dentro da imagem Docker antes do canary) bloqueia o deploy se algum decil estiver com taxa de conversão zerada — protege contra o bug que mandou eventos com `value=0` pro Meta entre 30/abr e 06/mai." |

**Aplicação prática:**

1. Em mensagens da sessão: a primeira vez que um ID aparece **em cada resposta**, descreva. Repetições da mesma mensagem podem ser abreviadas.
2. Em tabelas/listas: a coluna "Item" leva o nome verbal; o ID codificado vai entre parênteses ou em coluna lateral.
3. Em documentação nova: título e introdução em linguagem natural; identificador codificado no rodapé (`*Identificador histórico: DT-X.*`).
4. Quando recuperar contexto de outras sessões via memória ou docs: aplicar a mesma tradução antes de devolver pro usuário.

**Catálogos onde os IDs vivem (para o leitor consultar quando quiser detalhe técnico):**
- Cenários de auditoria → `docs/AUDITORIA_QUEBRA_PRODUCAO.md`
- Salvaguardas (T-X) → `docs/PLANO_SAFEGUARD.md`
- Dívidas técnicas (DT-X) e pré-requisitos do segundo cliente (R-X) → `docs/PLANO_REFACTOR_MLOPS.md`
- Itens M-X de prioridade operacional → `docs/PLANO_EXECUCAO.md`
- Erros históricos e Clusters → `docs/registro_erros_ml.md`

---

## Antes de mudança arquitetural — consultar `/sw-architect`

**Regra obrigatória — aplica antes de planejar, não depois.**

Toda mudança que adicione leitura/escrita de dados, toque camada que múltiplos lugares consomem (monitoramento, scoring, captura, envio de evento, retreino), ou crie componente novo: invocar `/sw-architect` **antes** de codar. A skill cobra "a abstração existe? deveria existir? estou espalhando acoplamento direto na fonte?".

**Por que esta regra existe:** trocar a fonte de dados do monitoramento virou um refator de várias etapas porque cada monitor consultava o banco direto, sem camada intermediária. O custo de não ter pensado arquitetura no momento certo (quando o ledger novo foi criado em 23/05/2026) virou semanas de trabalho depois. A skill obriga a parar e perguntar antes de espalhar mais N pontos de acoplamento.

**Quando NÃO invocar:** fix de bug pontual, refator de nomes contido, atualização de doc, mudança num único arquivo que não muda interface pública.

A regra é gêmea da `/mlops-architect`: aquela cobra a integridade do sinal ML; esta cobra a manutenibilidade do código que sustenta tudo.

---

## Contexto de negócio

- **Cliente atual:** DevClub (curso de programação)
- **Segundo cliente:** chegando em breve — toda decisão arquitetural deve considerar multi-cliente
- **Fluxo de lançamento:** Semana 1 captação (7d) → Semana 2 CPL/nutrição (6d) → Semana 3 vendas/carrinho (7d)
- **Sinal central:** lead preenche pesquisa → modelo atribui decil D1–D10 → evento `LeadQualified` enviado ao Meta em ~5 minutos com valor proporcional ao decil

---

## Regras de código — práticas permanentes

### Fail-loud: nenhuma falha silenciosa em `src/core/`

Todo transform novo em `src/core/` deve incluir pelo menos uma verificação que **falha alto** se o output for inesperadamente zero, nulo ou vazio. Exemplos:

```python
# Ao final de um transform crítico
assert df[coluna_encoding].sum() > 0, f"[FALHA SILENCIOSA] {coluna_encoding} zerada — verificar encoding"
assert df.shape[0] == n_original, "Linhas perdidas inesperadamente no transform"
assert not df[feature_critica].isnull().all(), f"{feature_critica} toda nula após transform"
```

**Por quê:** `Medium_Linguagem_programacao` ficou zerada por semanas sem erro. D9 ficou sem eventos CAPI por 2 meses sem alerta. Falhas silenciosas degradam sinal sem avisar.

**Regra:** se remover o assert não causaria confusão em produção, não precisa. Se causaria — obrigatório.

---

## Regras críticas de sincronização

**Toda transformação de dados deve ser idêntica em treino, produção e monitoramento.**

Já houve quebra em produção por divergência de normalização (UTM com `.lower()` aplicado no treino mas não na produção). Esta é a principal motivação do refactor para `src/core/`.

- Treino (`train_pipeline.py`) importa 100% de `core/` para transformações
- Produção (`production_pipeline.py`) importa 100% de `core/` — comportamento idêntico ao treino por construção
- Monitoramento (`monitoring/orchestrator.py`) chama `core.preprocessing.preprocess()` com wrapper de preservação de `decil`/`lead_score`
- **Nunca reimplementar uma transformação fora de `core/`**

---

## O que é canônico quando há conflito

| Componente | Versão canônica |
|---|---|
| Encoding | `encoding.py` de produção (tem feature registry, reordenação, `mapeamentos_especificos`) |
| UTM unification | `core/utm.py` com `.lower()` — corrige divergência histórica |
| Medium unification | `core/medium.py` — elimina os 3 arquivos atuais |
| Matching | `core/matching.py` — consolida os 6 arquivos de `src/matching/` |
| Janela de conversão | Simétrica — remove TODOS os leads após `date_limite`, não só `target=1` |

> **⚠️ Schema do banco mudou (11–17/05/2026).** As tabelas `Lead`/`leads_capi` **morreram em ~17/05** (somente histórico). Para dados a partir de 17/05/2026 a fonte é o ledger **`registros_ml`** + as tabelas novas `Client`/`UTMTracking`/`Activity`. As linhas abaixo mostram a fonte **atual** e, entre parênteses, a fonte **histórica** (<17/05). Detalhe completo em `docs/ARQUITETURA_SISTEMA_COMPLETA.md` § BANCO DE DADOS e `docs/PROCESSO_CAPI_LEAD_SURVEYS.md`.

| `fbp`/`fbc` | **Atual: `registros_ml.fbp`/`fbc`** (ou `Client.fbp`/`fbc`). Histórico (<17/05): `leads_capi`. NUNCA `Lead.fbp`/`Lead.fbc` (sempre vazios). |
| `pesquisa` (respostas) | **Atual: `registros_ml.survey_responses` (jsonb)**. Histórico: `Lead.pesquisa` (jsonb). As colunas tabulares de `leads_capi` são 100% NULL — vestígio. |
| `pageUrl` | Atual: `UTMTracking.url`. Histórico: existe **só em `Lead`** (`leads_capi.event_source_url` quase sempre null). |
| `leadScore`/`decil` | **Atual: `registros_ml.decil`/`lead_score`** (ledger do consumer Pub/Sub). Histórico 30/04–17/05: `Lead.leadScore`/`Lead.decil`. Antes de 30/04: `leads_capi`. |
| `utm_campaign` | Atual: `registros_ml.utm_campaign` (campanha CAP real) e `UTMTracking.campaign`. Histórico: `leads_capi.utm_*` / `Lead.campaign`. |

---

## Convenção de assinatura em `src/core/`

Todas as funções em `src/core/` seguem o padrão:

```python
def transform(df: pd.DataFrame, config: SubConfig, **artifacts) -> pd.DataFrame:
```

Funções utilitárias sem DataFrame seguem:

```python
def utility_name(input, config: SubConfig) -> output:
```

Nunca adicionar hardcodes dentro de funções `core/`. Todo valor específico de cliente vem do `ClientConfig`.

---

## ClientConfig

- Carregado de `configs/clients/{cliente}.yaml`
- Dataclass tipado em `src/core/client_config.py`
- Todo campo novo deve ter valor default para não quebrar clientes existentes
- Após refactor: modelo ativo em `configs/active_models/{cliente}.yaml` (hoje: `configs/active_model.yaml`)

---

## O que não tocar sem aprovação explícita

- `configs/active_model.yaml` — aponta para o modelo em produção
- `src/production_pipeline.py` em produção — qualquer mudança requer teste completo de paridade com treino
- `META_ACCESS_TOKEN` — System User vitalício, não expira. Não alterar sem motivo claro (revogação quebraria CAPI imediato)
- Pipelines em execução no Cloud Run

---

## Como rodar localmente

> Banco operacional (`leads_capi`, `Lead`) está no **Railway** desde 25/02/2026 — não usa Cloud SQL Proxy. Ver `docs/acesso_sql.md` "Banco 2 — Railway" para credenciais.
>
> **MLflow tracking** (necessário para treinar/retreinar) usa Cloud SQL `smart-ads-db`, **parado desde 26/04/2026**. Subir antes — ver `docs/operacoes_gcp_custos.md`.

```bash
# Subir Cloud SQL para MLflow (só antes de treinar/retreinar)
gcloud sql instances patch smart-ads-db --activation-policy=ALWAYS --project=smart-ads-451319
# Aguardar state=RUNNABLE (~2-3 min)

# Treinar modelo (MLflow tracking via 104.197.138.129:5432/mlflow)
python -m src.train_pipeline --initial-matching email_telefone --set-active

# Monitoramento local (lê do Railway via env vars RAILWAY_DB_*)
bash src/monitoring/run_monitoring_local.sh

# Retreino mensal
python src/retrain/retraining_orchestrator.py --config configs/retreino_mensal.yaml

# Parar Cloud SQL após terminar (economia)
gcloud sql instances patch smart-ads-db --activation-policy=NEVER --project=smart-ads-451319
```

---

## Estado atual do refactor (branch `refactor/mlops-core`)

**Implementado em `src/core/`:**
- `client_config.py` — dataclass ClientConfig com sub-configs
- `utils.py`, `ingestion.py`, `column_unification.py`, `category_unification.py`
- `utm.py`, `medium.py`, `matching.py`, `dataset_versioning.py`
- `feature_engineering.py`, `encoding.py`, `preprocessing.py`

**Pendente:**
- Migração de `train_pipeline.py` para importar de `core/`
- Migração de `production_pipeline.py` para importar de `core/`
- Migração de `monitoring/orchestrator.py`
- `configs/clients/devclub.yaml` com todos os hardcodes mapeados
- Retreino automático Sprint 2–3 (comparação champion/challenger, deploy condicional)

---

## Divergências conhecidas ainda não resolvidas

| Divergência | Localização | Status |
|---|---|---|
| UTM `.lower()` | `utm_unification.py:36` vs `utm_training.py` | Resolvido em `core/utm.py` — pendente migração |
| Medium mapping_dict | `medium_unification.py` vs `medium_training.py` | Resolvido em `core/medium.py` — pendente migração |
| Encoding ordinal nomes de colunas | treino usa `'idade'`; produção usa `'Qual a sua idade?'` | Pendente em `core/encoding.py` |
| `binary_top3` Medium | Removido do treino; produção ainda usa | Verificar `encoding.py` antes de migrar |
| `nome_valido`/`email_valido`/`telefone_valido` | Removidos do treino; verificar se produção ainda cria | Pendente |

---

## Infraestrutura de produção

- **API:** FastAPI + Uvicorn em Cloud Run (`https://smart-ads-api-12955519745.us-central1.run.app`)
  - Serviço ativo: `smart-ads-api` (`bring-data-api` foi deletado em 26/04/2026 — sem tráfego)
- **Banco operacional:** Railway PostgreSQL (env vars `RAILWAY_DB_*`) — Cloud SQL `bring-data-db` foi descomissionado em 25/02/2026
- **Cloud SQL (MLflow tracking):** `smart-ads-451319:us-central1:smart-ads-db` — **parado desde 26/04/2026** (`activation-policy=NEVER`); subir manualmente antes de retreinar (ver `docs/operacoes_gcp_custos.md`)
- **Banco operacional Railway — schema mudou em 11–17/05/2026.** As tabelas vivas hoje são do sistema novo do dono + nosso ledger:
  - **`registros_ml`** ⭐ — nosso ledger ML (consumer Pub/Sub, live desde 23/05). Fonte de `decil`, `lead_score`, `variant` (A/B), `utm_campaign`, `survey_responses`, `fbp`/`fbc`. **Fonte de leitura do monitoramento novo.**
  - **`Client`** — cadastro do lead (front novo). Tem `campaignKey`, `isBuyer`, `firstSeenAt`, `fbp`/`fbc`, `hasComputer`.
  - **`UTMTracking`** — UTM por lead (`campaign`/`source`/`medium`/`url`), 1:N por `clientEmail`.
  - **`Activity`** — log de eventos do lead (entrou no grupo, lista VIP).
  - **Mortas (somente histórico, pararam ~17/05):** `Lead`, `leads_capi`, `LeadsClient` e a transitória `lead_surveys` (morreu 21/05). NÃO consultar para dados recentes — retornam vazio e induzem falso "ingestão parada".
  - Detalhes e regras de consulta em `docs/ARQUITETURA_SISTEMA_COMPLETA.md` § "BANCO DE DADOS — armadilhas de schema" e `docs/PROCESSO_CAPI_LEAD_SURVEYS.md`.
- **Scheduler:** Cloud Scheduler → Cloud Run (monitoramento diário e polling Railway a cada 5min). Retreino é manual.
- **Notificações:** Slack

```bash
# Ver logs do Cloud Run
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=bring-data-api" --limit=50
```
