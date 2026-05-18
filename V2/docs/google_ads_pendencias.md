# Google Ads — Pendências antes de implementar

> Criado: 2026-04-14 · Atualizado: 2026-05-18
>
> Posição no roadmap: **H6 — Diversificação de canais** do `PLANO_EXECUCAO.md`. Tese estratégica em `swot_bringdata.md` (F8 multi-plataforma, W4 concentração 100% Meta, O4 expansão natural). Escopo desta frente: **só DevClub** — sem dependência de outros clientes (decisão do usuário em 2026-05-18).

## Decisões já fixadas

### 2026-05-01

1. **Estratégia: Enhanced Conversions for Leads.** Envio no momento da captura, análogo ao CAPI do Meta. Requer `gclid` + SHA-256 de email/telefone. Offline Conversion Import "puro" (sem identificadores hasheados) descartado: mais tardio, não combina com o ciclo de ~5 min do `LeadQualified`.

### 2026-05-18 — virada de transporte (importante)

2. **Transporte: Google Data Manager API, NÃO a legacy `UploadClickConversions` da Google Ads API.**
   Motivo: pesquisa em 2026-05-18 (Google Ads Developer Blog 2026-05-15 + Search Engine Land + PPC News Feed) confirmou que o endpoint `UploadClickConversions` da Google Ads API — o caminho que usaríamos para "Enhanced Conversions for Leads" — **fecha para novos integradores em 2026-06-15**. A DevClub nunca importou conversão offline (integrador novo), então construir nele seria construir numa porta que fecha em ~4 semanas. A própria doc oficial da Google já diz: *"We don't recommend implementing new offline conversion workflows using the Google Ads API. Upgrade to the Data Manager API."* O substituto é a **Data Manager API** (`datamanager.googleapis.com`), sem data de sunset, infra de ingestão permanente da Google.
   - Endpoint: `POST https://datamanager.googleapis.com/v1/events:ingest` (serviço `IngestionService`, método `events.ingest`).
   - **Não exige Google Ads Developer Token** (diferença-chave vs. legacy) — autentica só com OAuth2 escopo `https://www.googleapis.com/auth/datamanager`.
   - A *conversion action* de destino ainda é criada no UI do Google Ads e continua sendo do tipo `UPLOAD_CLICKS` — exatamente o mesmo objeto que a legacy usava. A Data Manager API só ingere nele por um caminho de transporte diferente. Logo: nenhuma das decisões de produto muda; muda só o cliente HTTP que o backend fala.
3. **Credenciais.** Conta Google Ads acessível via gerenciador do usuário. Configuração da conversion action + conexão Data Manager + service account no GCP será feita pelo usuário (com guia passo a passo) antes do desenvolvimento do backend começar.

## Pré-requisitos técnicos abertos

### 1. Captura de `gclid` na landing page  🔴 BLOQUEANTE

Verificação em 2026-04-29 confirmou que **o `gclid` não é capturado em nenhuma camada**:

| Camada | Estado | Evidência |
|---|---|---|
| Frontend (landing) | ❌ não captura | `V2/api/landing_page/index.html:287-310` — `getUTMParameters()` lê só `utm_*` |
| Request schema | ❌ sem campo | `V2/api/app.py:513-565` (`LeadCaptureRequest`) |
| Banco | ❌ sem coluna | `V2/api/database.py:22-88` (`LeadCAPI` tem fbp/fbc/utm_*, não tem gclid) |
| Payloads reais | ❌ não chega | `V2/docs/monitoring_golden_snapshot.json` (7,8 MB sem ocorrência) |

Sem o `gclid`, eventos enviados ao Google não atribuem a campanha — feature inútil.

**Itens de implementação:**
- (frontend) Estender `getUTMParameters()` para ler `gclid`, `gbraid`, `wbraid` do querystring e persistir (localStorage ~90d) + adicionar como hidden fields no formulário.
- (backend) Adicionar `gclid: Optional[str]` (e `gbraid`/`wbraid`) em `LeadCaptureRequest` e propagar até `lead_dict`.
- (banco) Migração adicionando `gclid` (e `gbraid`/`wbraid`) em `leads_capi` (Railway) e na tabela `Lead` do Prisma.

### 2. Criação das Conversion Actions  🟡 USUÁRIO + SCRIPT

**Achado 2026-05-18 (UI morto nesta conta):** a conta DevClub foi migrada pro setup de conversão unificado. Todo `+ Create conversion action` cai num wizard que **força um conector de fonte de dados** (Google Sheets) e não oferece criar uma `UPLOAD_CLICKS` "pelada". Mesmo a opção "Skip this step and set up a data source later" reentra no loop do Sheets nesta conta. A própria Google **não documenta** o caminho de UI pra conta migrada. Decisão: **criar as conversion actions via Google Ads API** (`ConversionActionService` — parte de MUTAÇÃO, NÃO a `UploadClickConversions` deprecada).

- **Script:** `V2/scripts/create_google_ads_conversion_actions.py` (idempotente; cria `LeadQualified` + `LeadQualifiedHighQuality`, `type=UPLOAD_CLICKS`, valor por-conversão). Helper de token: `V2/scripts/google_ads_oauth_refresh_token.py`. Deps: `V2/scripts/requirements_google_ads_setup.txt`.
- **Developer token descartável:** exigido só pra esta criação. Aplicar pro nível **Basic** está com backlog na Google (sem prazo, fev/2026), mas o tier novo **Explorer Access** dá mutação em conta de produção **sem aprovação formal** (costuma vir aprovado por padrão no signup) — suficiente pra criar conversion action. Em runtime nada disto é usado (Data Manager API usa service account, sem developer token).
- **Credenciais necessárias (V2/.env):** `GOOGLE_ADS_DEVELOPER_TOKEN` (ads.google.com/aw/apicenter, Explorer Access), `GOOGLE_ADS_CLIENT_ID`/`_SECRET` (OAuth client "Desktop app" no GCP), `GOOGLE_ADS_REFRESH_TOKEN` (gerado pelo helper), `GOOGLE_ADS_CUSTOMER_ID` (ID da conta, só dígitos), `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (opcional, se via MCC).
- **Saída:** os dois `Conversion Action ID` numéricos → viram `google_conversion_action_id_*` no `devclub.yaml` (= `productDestinationId` da Data Manager API).

### 2b. Setup do GCP para o runtime (Data Manager API)  🟡 USUÁRIO

Independente do item 2 (este é o transporte de produção):
- Habilitar a **Data Manager API** no projeto GCP.
- Criar **service account** (server-to-server; Google recomenda impersonation, não chave baixada — e service account dispensa a verificação OAuth do escopo sensível `datamanager`).
- Dar acesso da service account à conta Google Ads.

### 3. Risco de prazo a monitorar  🟡

A janela de 2026-06-15 é da legacy `UploadClickConversions`, **não** da Data Manager API — construir na Data Manager API já evita o corte. Mas confirmar, ao habilitar a API, que não há fila de allow-list pendente para a service account.

## Infraestrutura já preparada para receber a integração

A correção do vazamento de sinal cross-platform (item DT-CAPI-01 — leads de um canal sendo enviados como conversão de outro; commit `41cc2bf`, 29/04/2026) deixou o roteamento por plataforma centralizado e já com hook explícito para Google Ads:

- **Função de roteamento:** `should_send_to_destination(lead, capi_config, destination='meta')` em `V2/api/capi_integration.py:886-939`. Hoje qualquer `destination ≠ 'meta'` retorna `False, 'unknown_destination'`. Para ativar Google basta adicionar branch `elif destination == 'google'` lendo `capi_config.google_source_allowlist` (mais checagem `if not lead.get('gclid')`).
- **Dataclass de config:** `CAPIConfig` em `V2/src/core/client_config.py:209-221` precisa ganhar (revisado para Data Manager API — **sem `google_developer_token`**):
  - `google_customer_id` (operatingAccount/loginAccount)
  - `google_conversion_action_id_with_value` e `google_conversion_action_id_high_quality` (os dois `productDestinationId`)
  - credenciais da service account (referência a Secret, não valor): `google_sa_secret`
  - `google_source_allowlist`, `google_event_name_with_value`, `google_event_name_high_quality`
- **YAML por cliente:** `configs/clients/devclub.yaml` precisa de bloco `google_ads:` paralelo ao `capi:`.
- **Dispatcher:** os 4 paths que hoje chamam `should_send_to_destination(..., destination='meta')` precisam de chamada espelhada para `destination='google'`, disparando o cliente Google Ads quando passar.
- **Persistência:** coluna `googleAdsStatus` em `leads_capi` análoga a `capiStatus`.
- **Cliente da API:** módulo novo `V2/api/google_ads_integration.py` (não juntar com `capi_integration.py` — outra API e outro fluxo de auth). Fala a **Data Manager API** via lib oficial `google-ads-datamanager` (+ `google-ads-datamanager-util` para normalização/hash), ou REST puro em `POST /v1/events:ingest`. Espelhar interface `send_event` / `send_batch_events` do CAPI. Single-event em near-real-time é suportado (como o CAPI); limites: 2.000 events/request, 300 req/min, 100k req/dia por projeto GCP.

## Ordem de execução

1. Pré-requisito 1 (gclid frontend → backend → banco) **e** pré-requisito 2 (conta Google Ads + GCP configurados) — em paralelo.
2. Implementação na ordem: estender `CAPIConfig` → branch em `should_send_to_destination` → módulo `google_ads_integration.py` (Data Manager API) → integrar nos 4 paths → coluna `googleAdsStatus` → bloco YAML do DevClub → smoke test com `validateOnly:true` → canary.
3. Por simetria com Meta: `googleAdsStatus` usa o mesmo vocabulário (`'allowed' / 'skipped' / 'blocked' / 'sent'`).

## Observações arquiteturais

- **Modelo único, dispatch múltiplo (F8).** Pipeline de treino e scoring NÃO mudam — score é o mesmo. O que muda é o destino do evento. Adicionar Google Ads não cria fork de modelo nem retreino.
- **Sem vazamento de sinal cross-platform.** Como Meta usa allowlist `["facebook-ads", "instagram"]` e Google usará `["google-ads"]`, leads não sangram para o canal errado. Isso fecha definitivamente o vazamento histórico DT-CAPI-01.
- **Mudança de transporte é isolada.** A virada legacy → Data Manager API afeta só o módulo `google_ads_integration.py` e os campos de auth do `CAPIConfig`. Decisões de produto (Enhanced Conversions for Leads, dois eventos, value por decil) ficam intactas.
- **TikTok Events API** segue o mesmo padrão, próximo da fila depois de Google Ads (também em H6).

---

*Identificador histórico: pré-requisitos da frente "Google Ads" (H6 do PLANO_EXECUCAO).*

*Fontes da virada de transporte (2026-05-18): Google Ads Developer Blog 2026-05-15 "Changes to Offline Click Conversion Import Support in the Google Ads API"; Google for Developers — Data Manager API (`/data-manager/api/devguides/events/send-events`, `/reference/rest/v1/events/ingest`, `/devguides/quickstart/set-up-access`, `/devguides/limits`); Google Ads Help 15707550 (Data Manager com ECfL) e 16884284 (updates enhanced conversions); Search Engine Land "Google is moving offline conversion imports out of the Google Ads API"; PPC News Feed 2026-05.*
