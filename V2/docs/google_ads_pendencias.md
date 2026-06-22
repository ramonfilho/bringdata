# Google Ads — Envio de conversão de lead (status da implementação)

> Criado: 2026-04-14 · Atualizado: 2026-06-22
>
> Antes se chamava *"Pendências antes de implementar"*. Implementado e **validado ponta a ponta** (sender + despachante no consumer, Fase A+B); falta só o go-live operacional. Este doc rastreia o **status** da frente, mantendo o histórico das decisões.
>
> Posição no roadmap: **H6 — Diversificação de canais** do `PLANO_EXECUCAO.md` (tese estratégica em `swot_bringdata.md`: modelo único → N canais, sair da concentração 100% Meta). Escopo: **só DevClub**. Código na branch **`feat/google-ads`** (worktree `~/bring_data.worktrees/google-ads`).

## Status atual (2026-06-15)

**O caminho de envio está validado ponta a ponta** contra a API real, em modo `validateOnly` (HTTP 200): autenticação, acesso da service account e a forma do payload — tudo confirmado. **Nenhuma conversão real foi enviada ainda.**

Todo o código está **DESLIGADO** (`google_ads.enabled=false`, allowlist vazia → inerte). Não toca o envio Meta que já roda.

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
| Go-live operacional (migração → merge → deploy canary → ligar `enabled`) | ⏳ **FALTA** |

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

### gclid — NÃO é bloqueante (corrige o 🔴 anterior)
Versões anteriores marcavam a captura de `gclid` como **bloqueante 🔴**, pelo caminho da landing page → schema → tabela `leads_capi`. **Dois motivos derrubam isso:**
1. O Enhanced Conversions for Leads casa por **email/telefone hasheado** (que o ledger já tem) — `gclid` é opcional, melhora atribuição.
2. O caminho de captura daquela versão **morreu na migração de 17/05** (landing/`leads_capi` são legado). Hoje a captura é o **front do dono publicando no Pub/Sub → consumer → ledger `registros_ml`**. Quando o `gclid` for incluído, é: front popula no payload do Pub/Sub → coluna `gclid` no `registros_ml` → disponível no disparo. Aditivo e posterior.

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

*Análise de se vale um sinal/valor separado por canal: `analise_valor_decil_por_canal_google_vs_meta.md` (ranqueamento do Challenger transfere pro Google; ticket à-vista é o único eixo em aberto).*

*Identificador histórico: frente "Google Ads" (H6 do PLANO_EXECUCAO).*

*Fontes (virada de transporte 2026-05-18): Google Ads Developer Blog 2026-05-15 "Changes to Offline Click Conversion Import Support in the Google Ads API"; Google for Developers — Data Manager API (`/data-manager/api/devguides/events/send-events`, `/reference/rest/v1/events/ingest`). Forma do payload (2026-06-15): confirmada empiricamente via `validateOnly` + `/reference/rest/v1/Event` e `/reference/rest/v1/Destination`.*
