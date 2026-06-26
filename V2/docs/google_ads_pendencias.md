# Google Ads — Envio de conversão de lead (status da implementação)

> Criado: 2026-04-14 · Atualizado: 2026-06-26
>
> Antes se chamava *"Pendências antes de implementar"*. Hoje o **envio está NO AR em produção** (desde 22/06) e a **leitura de campanhas/dados via API está validada** (26/06). Este doc rastreia o **status** da frente, mantendo o histórico das decisões.
>
> Posição no roadmap: **H6 — Diversificação de canais** do `PLANO_EXECUCAO.md` (tese estratégica em `swot_bringdata.md`: modelo único → N canais, sair da concentração 100% Meta). Escopo: **só DevClub**. Mergeado na `main` (PR #16); worktree `~/bring_data.worktrees/google-ads` pode ser removida.

## Status atual (2026-06-26)

**Envio NO AR.** O consumer Pub/Sub envia conversão pro Google a cada lead `google-ads` (`google_ads.enabled=true`, allowlist `["google-ads"]`), na revisão Cloud Run `smart-ads-api-00766-gut` (100% do tráfego). Até 26/06: **786 enviados, 2 erros** (~200/dia), todos aceitos pela Data Manager API (HTTP 200, `registros_ml.google_ads_status='sent'`).

> ⚠️ **Mas o Google atribuiu ZERO conversões em 30 dias** (786 enviados × 0 casados). Não é lag — é **casamento**: ver "gclid virou requisito" abaixo. Confirmado por query de reporting em 26/06.

| Item | Estado |
|---|---|
| Data Manager API habilitada (projeto `smart-ads-451319`) | ✅ feito |
| Service account de runtime + acesso à conta Google Ads | ✅ App Engine SA, acesso via MCC |
| Conversion actions criadas | ✅ `LeadQualified`=7649573174 · `HQ`=7649572493 |
| Config (`GoogleAdsConfig`) + bloco `google_ads:` no yaml | ✅ inerte na branch |
| Módulo enviador `api/google_ads_integration.py` | ✅ inerte na branch |
| Forma do payload `events:ingest` confirmada (`validateOnly` 200) | ✅ |
| Despachante no consumer Pub/Sub (Fase A — canal paralelo, Meta intacto) | ✅ feito |
| Rastro `google_ads_status` no ledger (Fase B) + migração idempotente | ✅ feito |
| Go-live operacional (migração → merge → deploy canary → ligar `enabled`) | ✅ feito (22/06, rev `00766-gut`, 100% tráfego) |
| Leitura de campanhas/dados via Google Ads API (reporting) | ✅ validada (26/06) — ver seção própria abaixo |
| Atribuição real (Google casar e reportar a conversão) | 🔴 **0/786** — bloqueada por `gclid` (ver abaixo) |

## Como funciona — decisões fixadas (histórico)

### Mecanismo: Enhanced Conversions for Leads (2026-05-01)
Envio no momento da captura (~5 min), análogo ao CAPI do Meta. Casa a conversão por **email/telefone hasheados (SHA-256)** — que o ledger `registros_ml` já guarda.

> **Correção (2026-06-15):** a decisão original dizia *"requer `gclid`"*. **Não requer.** A doc oficial e o smoke test confirmam que o Enhanced Conversions for Leads casa **só por email/telefone hasheado**; o `gclid` é **opcional** (eleva match rate/atribuição). Ver seção "gclid".

### Transporte: Data Manager API, NÃO a Google Ads API legada (2026-05-18)
A pesquisa em 2026-05-18 confirmou que o endpoint `UploadClickConversions` da Google Ads API (o caminho legado de offline/enhanced conversions) **fecha para novos integradores em 2026-06-15**. O substituto é a **Data Manager API** (`datamanager.googleapis.com`), sem data de sunset.
- Endpoint: `POST https://datamanager.googleapis.com/v1/events:ingest`.
- **Não exige developer token** — autentica só com OAuth2, escopo `https://www.googleapis.com/auth/datamanager`, via service account.
- A *conversion action* de destino é criada no Google Ads (tipo `UPLOAD_CLICKS`) e a Data Manager API só ingere nela por outro transporte. As decisões de produto (dois eventos, value por decil) ficam intactas.

## O que foi feito (2026-06-14/15)

### Conversion actions ✅
Criadas via `scripts/create_google_ads_conversion_actions.py` (a UI da conta migrada não deixa criar `UPLOAD_CLICKS` "pelada" — loopa no conector de Google Sheets). IDs gravados no `configs/clients/devclub.yaml`:
- `LeadQualified` = **7649573174** (value-weighted, todos os decis)
- `LeadQualifiedHighQuality` = **7649572493** (só decis altos)

Fix aplicado no script: campo `currency_code` → `default_currency_code` (renomeado no `google-ads` v31). O developer token/OAuth do `.env` serve **só** pra esta criação one-time.

### Setup GCP de runtime ✅
- **Data Manager API habilitada** em `smart-ads-451319`.
- Runtime autentica como a **App Engine SA** `smart-ads-451319@appspot.gserviceaccount.com` (via ADC; sem chave baixada, sem developer token). Localmente a mesma SA está no `GOOGLE_APPLICATION_CREDENTIALS`, então o smoke test local valida a identidade real.
- **Acesso concedido no MCC BringData (`6351164315`) como `Standard`**, e cascateia pra conta DevClub (`6266441811`). Por que via MCC: a UI "Invite users" da própria conta DevClub é a migrada/quebrada (só oferece "Email only", que não vale pra service account, e o seletor não responde — Standard requer Admin, que o login operacional não tinha lá). O MCC é nossa conta → Admin + UI normal. `Standard` (não `Read only`) porque upload de conversão é escrita.
- **Não há papel de IAM "Data Manager" no GCP** — o controle de acesso é todo do lado do Google Ads (o grant acima).

### Forma do payload `events:ingest` ✅ — descoberta no smoke test
A doc não publica o JSON completo; o `validateOnly` (autenticado como a App Engine SA) revelou os nomes certos:
- **Valor/moeda:** top-level `conversionValue` (number) + `currency` (string) — **não** um objeto `conversion` aninhado.
- **Destino:** `loginAccount` (a conta que autentica = MCC) é **campo irmão** de `operatingAccount` (onde a conversão cai = DevClub) no `destination`, cada um um `ProductAccount {product:"GOOGLE_ADS", accountId}` — **não** `loginAccountId` dentro de `operatingAccount`. `productDestinationId` = a conversion action.
- **`eventSource` obrigatório** → `"WEB"` (lead de formulário web).
- **`encoding` obrigatório** no request → `"HEX"` (identifiers em SHA-256 hex).
- `validateOnly: true` valida sem gravar conversão.

Resultado: **HTTP 200**, com o roteamento por decil correto (D10 → evento value + evento HQ; D3 → só value). Esses nomes estão centralizados em `build_event` / `build_ingest_request` no módulo.

### Por que a aplicação ao tier "Basic" da API legada NÃO era necessária
A aplicação pesada ao **developer token Basic** (com revisão de site/modelo de negócio pela Google) foi esforço gasto num caminho **abandonado**:
- O plano **original** (pré-18/05) era enviar em runtime pela **Google Ads API legada**, que em produção exige Basic → daí o site e as devolutivas.
- A **virada pra Data Manager API (18/05)** matou essa necessidade: o runtime autentica **só com service account**, sem developer token e sem revisão (comprovado: o `validateOnly` 200 saiu sem nenhum token nem aprovação).
- Criar as conversion actions (único uso restante da API legada) precisou só do **Explorer Access**, liberado por padrão, **sem revisão**.

**Conclusão:** o tier Basic **não é necessário** pra esta frente. Só voltaria a importar se um dia formos usar a Google Ads API legada pra outra coisa em escala (ex.: gerenciar campanhas por API).

### gclid — VIROU REQUISITO (corrige o "opcional" de 15/06)

> **Correção empírica (2026-06-26).** A teoria dizia que o Enhanced Conversions for Leads casaria **só por email/telefone hasheado**, deixando o `gclid` opcional. **Os dados desmentiram:** 786 conversões enviadas só com hash = **0 casadas** pelo Google em 30 dias. Na prática, pro nosso fluxo, **o `gclid` é o que falta pra atribuir qualquer coisa.**

**Por que o casamento por email não funcionou:** ele só fecha se o **site do DevClub gravar o par email↔clique no momento do formulário** (a tag de Enhanced Conversions for Leads do próprio Google no site). Como deu 0/786, isso **não está acontecendo** — então o único caminho de atribuição que sobra é **mandarmos o `gclid` direto no evento** (`adIdentifiers.gclid`, que o sender `build_event` já sabe preencher; só falta o valor).

**O que fazer (desbloqueio):** front captura o `gclid` da URL de entrada (`?gclid=...` ou cookie `_gcl_*`) e popula no payload do Pub/Sub → vira coluna `gclid` no `registros_ml` → o consumer passa no `build_event`. Depois disso, re-rodar `scripts/probe_google_ads_reporting.py`: se as conversões começarem a aparecer, a atribuição fechou. Se mesmo com `gclid` continuar 0, investigar roteamento da Data Manager API (destino/linkagem da conversion action).

**Consequência operacional:** enquanto o `gclid` não entrar, qualquer campanha que o gestor configure pra otimizar pelo nosso evento (LeadQualified/LeadQualifiedHighQuality) **vê 0 conversão** — o Smart Bidding não tem sinal pra aprender. O evento **está sendo enviado e aceito**, mas a atribuição só liga com o `gclid`.

## Ponto de integração — o consumer Pub/Sub (corrige "os 4 paths")

> **Correção importante (2026-06-15):** versões anteriores mandavam espelhar `should_send_to_destination(..., destination='google')` **"nos 4 paths do `app.py`"**. **Isso ficou desatualizado pela migração Pub/Sub.** Os 4 (`webhook_lead_capture`, `webhook_update_survey`, `process_daily_batch_capi`, `railway_process_pending`) são **legado** e leem tabelas mortas (`Lead`/`leads_capi`).

O caminho de envio **vivo** hoje (`PUBSUB_CAPI_ENABLED=true`) é o **consumer Pub/Sub** `api/pubsub_branch.py`: o front do dono publica o lead na fila → o consumer scoreia, decide elegibilidade Meta por `is_meta_eligible`, dispara o CAPI via `send_batch_events` e grava o ledger `registros_ml`. **É aí que o envio Google deve plugar.**

## Implementação no consumer (feita — Fase A + B)

O envio Google entra como **canal paralelo** no único ponto de dispatch do consumer Pub/Sub (`api/pubsub_branch.py`), não como fachada pesada — o consumer já centraliza o dispatch (a fachada que colapsaria "N caminhos" era dos webhooks legado, que estão mortos).

- **Fase A** — no ramo `not meta_elig` (onde leads não-Meta viravam `skipped_allowlist`): se `google_ads.is_eligible` (enabled + source na allowlist Google), o lead é coletado e enviado por um `send_batch_events` Google paralelo ao Meta. **Paridade por construção:** a mudança vive só no ramo dos leads que NÃO vão pro Meta; com `enabled=false`, nada é coletado → comportamento byte-a-byte igual.
- **Fase B** — coluna `google_ads_status TEXT` no `registros_ml` (desfecho do envio Google por lead, análogo a `base_status`/`capi_sent_at` do Meta; `base_status` segue `skipped_allowlist`). O lead Google é deferido pro pós-send (como o Meta) pra gravar o desfecho real. Migração idempotente dual-target em `scripts/add_google_ads_status_column.py`.
- **Testes:** `tests/test_pubsub_branch.py` 25/25, incl. caminho Google ligado (coletado → enviado → ledger `sent`, Meta intacto).

## O que falta — go-live operacional

1. **Migração nos DOIS ledgers** (antes do deploy): `add_google_ads_status_column.py --target railway` **e** `--target cloudsql`. A coluna tem que existir antes do código que a escreve (o INSERT do consumer passa a referenciá-la).
2. **Merge** `feat/google-ads` → `main` (PR) → **deploy canary** sem tráfego, validar.
3. **Ligar:** `google_ads.enabled=true` + `source_allowlist: ["google-ads"]` no `devclub.yaml`; **envio real** (não-dry-run) de teste; monitorar; soltar.
4. **`gclid`** no payload do Pub/Sub (pedido pro front) + coluna no ledger — melhora atribuição, posterior.

## Observações arquiteturais

- **Modelo único, dispatch múltiplo.** Treino e scoring NÃO mudam — o score é o mesmo. Muda só o destino do evento. Adicionar Google Ads não cria fork de modelo nem retreino.
- **Config separada por design.** `GoogleAdsConfig` é dataclass **própria** (não estende `CAPIConfig`) — outra API e outro auth. Bloco `google_ads:` paralelo ao `capi:` no yaml.
- **Módulo separado por design.** `api/google_ads_integration.py` não se junta com `capi_integration.py` (soldado ao SDK do Facebook). Fala a Data Manager API por REST (`POST /v1/events:ingest`), espelha a interface `send_batch_events` do CAPI. Limites: 2.000 events/request, 300 req/min, 100k req/dia por projeto GCP.
- **Sem vazamento cross-canal.** Meta usa allowlist `["facebook-ads","instagram"]` e Google usará `["google-ads"]` — leads não sangram pro canal errado.
- **TikTok Events API** segue o mesmo padrão, depois do Google Ads (também H6).

---

# Leitura de campanhas e dados (reporting) — acesso e integração no monitoramento

> Esta parte é o **espelho de leitura** do que já fazemos com o Meta: hoje puxamos da **Meta Insights API** o spend e os leads por adset pra calcular CPL e popular o monitoramento (camada `src/data/cost_attribution/`, via `src/validation/meta_api_client.py`). Aqui fica **tudo que é preciso pra puxar o equivalente do Google** (custo, cliques, conversões por campanha e por ação) e plugar no mesmo monitoramento. **Validado em 2026-06-26** com o token que já temos — sem precisar do Basic access.

## Duas APIs diferentes — não confundir

| Função | API | Como autentica |
|---|---|---|
| **Enviar** evento (já no ar) | **Data Manager API** (`datamanager.googleapis.com/v1/events:ingest`) | service account (App Engine SA via ADC), escopo `datamanager`. **Sem developer token.** |
| **Ler** relatório (custo, conversão por campanha) | **Google Ads API** (`googleads.googleapis.com`, lib `google-ads` v31) | developer token + OAuth do usuário + `login_customer_id` do MCC |

A leitura usa a **mesma credencial** que criou as conversion actions (`scripts/create_google_ads_conversion_actions.py`) — só que agora pra `SELECT` (GAQL via `GoogleAdsService.search_stream`), não pra mutação.

## Credenciais necessárias (todas já no `V2/.env`)

| Env var | Papel | Valor |
|---|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | token de API (tier Explorer) | (no `.env`) |
| `GOOGLE_ADS_CLIENT_ID` / `_CLIENT_SECRET` | OAuth client "Desktop app" | (no `.env`) |
| `GOOGLE_ADS_REFRESH_TOKEN` | refresh token do usuário `ramonfceo@gmail.com` | (no `.env`) |
| `GOOGLE_ADS_CUSTOMER_ID` | conta DevClub (destino da query) | `6266441811` |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | MCC BringData (quem autentica) | `6351164315` |

**Nível de acesso — confirmado suficiente.** O `developer token` está no tier **Explorer** (liberado por padrão, sem revisão). Em 26/06 ele **leu relatório da conta de produção sem erro de quota** — ou seja, **não precisa do Basic access** (aquela aplicação com revisão de site que foi recusada) pra um pull diário de baixa frequência. O Basic só voltaria a importar se um dia formos fazer reporting em alto volume.

**Cuidado com o refresh token:** ele **expira/é revogado** (já aconteceu — `invalid_grant`). Pra renovar: `python scripts/google_ads_oauth_refresh_token.py` logado como `ramonfceo@gmail.com` e colar o novo valor em `GOOGLE_ADS_REFRESH_TOKEN` no `.env`.

## Autenticação (padrão reusável)

```python
from google.ads.googleads.client import GoogleAdsClient
client = GoogleAdsClient.load_from_dict({
    "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
    "client_id":       os.environ["GOOGLE_ADS_CLIENT_ID"],
    "client_secret":   os.environ["GOOGLE_ADS_CLIENT_SECRET"],
    "refresh_token":   os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
    "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],  # MCC, só dígitos
    "use_proto_plus":  True,
})
ga = client.get_service("GoogleAdsService")
for batch in ga.search_stream(customer_id="6266441811", query=GAQL):
    for row in batch.results:
        ...
```

O builder está pronto em `scripts/probe_google_ads_reporting.py::build_client` (importável). Customer da query = DevClub (`6266441811`); login = MCC (`6351164315`).

## Queries GAQL que funcionam (validadas 26/06)

**1) Custo + conversões por campanha** (o "funil Google"):
```sql
SELECT campaign.id, campaign.name, campaign.status,
       metrics.cost_micros, metrics.clicks, metrics.conversions, metrics.all_conversions
FROM campaign
WHERE segments.date DURING LAST_7_DAYS AND metrics.cost_micros > 0
ORDER BY metrics.cost_micros DESC
```
`cost_micros / 1_000_000` = valor em BRL.

**2) Conversões quebradas POR ação** (acha LeadQualified / LeadQualifiedHighQuality por campanha):
```sql
SELECT segments.conversion_action_name, metrics.all_conversions, metrics.conversions
FROM customer
WHERE segments.date DURING LAST_30_DAYS
```

**3) Status/existência das conversion actions:**
```sql
SELECT conversion_action.id, conversion_action.name, conversion_action.status, conversion_action.type
FROM conversion_action
WHERE conversion_action.id IN (7649573174, 7649572493)
```

**4) Quais campanhas otimizam por qual objetivo** (custom goals, account-default, biddable por categoria) — ver `scripts/probe_google_ads_goal_usage.py`.

### Gotchas descobertos
- O recurso `conversion_action` **rejeita** `metrics.conversions` (`PROHIBITED_METRIC_IN_SELECT_OR_WHERE_CLAUSE`). Pra contar conversão por ação, consultar `FROM customer`/`FROM campaign` segmentado por `segments.conversion_action_name`.
- `login_customer_id` (MCC) é obrigatório — sem ele a auth falha.
- Janela canônica exclui o dia corrente (spend intraday flutua) — igual ao refresh do Meta.

## Scripts-semente (probes descartáveis, read-only)
- `scripts/probe_google_ads_reporting.py` — custo + conversões por campanha e por ação. **Re-rodar este depois que o `gclid` entrar** pra confirmar atribuição.
- `scripts/probe_google_ads_goal_usage.py` — quais campanhas estão configuradas pra otimizar pelas nossas ações (independe de ter conversão). Em 26/06: custom goal `LQHQ` (id `6458091660`) existe mas **nenhuma campanha linkada**; categoria `QUALIFIED_LEAD` é biddable no account-default mas só **3 campanhas ENABLED** (de venda, `DEV16 | Vendas`) herdam; as de captação que gastam otimizam por outra categoria → **o gestor ainda não plugou o evento em nenhuma campanha de captação**.

## Integração no monitoramento — plano (espelho do funil Meta)

**Onde o Meta vive (modelo a copiar):**
- `src/validation/meta_api_client.py` — cliente da Meta Insights API (batch, v24.0, filtro `campaign_name contém 'CAP'`).
- `src/data/cost_attribution/refresh.py` — job que puxa spend+leads da janela móvel e faz UPSERT nas tabelas `cpl_adset` / `ad_to_adset_map` (Railway).
- `src/data/cost_attribution/` (`cpl_repository.py`, `cpl_lookup.py`, adapters) — camada de acesso; o digest das 06:00 (`src/monitoring/digest.py`) consome dela pra mostrar Spend/CPL por variante.

**O análogo Google (a fazer):**
1. **Cliente de leitura** `GoogleAdsReportingClient` (semente: as duas probes) — encapsula `build_client` + as queries GAQL acima.
2. **Job de refresh** que puxa, por campanha, custo + cliques + conversões (inclusive `LeadQualified`/`LeadQualifiedHighQuality`) da janela móvel e grava numa tabela de custo Google (espelho de `cpl_adset`), reusando a **camada `cost_attribution`** (repository/adapters) em vez de um pull bespoke.
3. **Superfície no monitoramento** — o endpoint que já roda o digest (`api/app.py`, rotas `slack-digest`/`daily-check`) passa a mostrar o bloco "funil Google" (Spend/CPL/conversão por campanha), ao lado do Meta.

**Antes de codar:** isto adiciona **acesso a dados externo + componente novo** → **invocar `/sw-architect`** (regra do `CLAUDE.md`), reusando a abstração de `cost_attribution` (não espalhar query direta de API pelos monitores).

---

*Análise de se vale um sinal/valor separado por canal: `analise_valor_decil_por_canal_google_vs_meta.md` (ranqueamento do Challenger transfere pro Google; ticket à-vista é o único eixo em aberto).*

*Identificador histórico: frente "Google Ads" (H6 do PLANO_EXECUCAO).*

*Fontes (virada de transporte 2026-05-18): Google Ads Developer Blog 2026-05-15 "Changes to Offline Click Conversion Import Support in the Google Ads API"; Google for Developers — Data Manager API (`/data-manager/api/devguides/events/send-events`, `/reference/rest/v1/events/ingest`). Forma do payload (2026-06-15): confirmada empiricamente via `validateOnly` + `/reference/rest/v1/Event` e `/reference/rest/v1/Destination`.*
