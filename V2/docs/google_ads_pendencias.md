# Google Ads — Pendências antes de implementar

> Criado: 2026-04-14 · Atualizado: 2026-05-01
>
> Posição no roadmap: **H6 — Escala 2-4 clientes** do `PLANO_EXECUCAO.md`. Tese estratégica em `swot_bringdata.md` (F8 multi-plataforma, W4 concentração 100% Meta, O4 expansão natural). Pré-condição: Cliente B estabilizado (H5).

## Decisões já fixadas (2026-05-01)

1. **Estratégia: Enhanced Conversions for Leads.** Envio em tempo real no momento da captura, análogo ao CAPI atual. Requer `gclid` + SHA-256 de email/telefone. Offline Conversion Import descartado (mais preciso mas tardio; não combina com o ciclo de 5 min do `LeadQualified`).
2. **Credenciais.** Conta Google Ads acessível via gerenciador do usuário; configuração de Developer Token + Customer ID + Conversion Action será feita pelo usuário antes do desenvolvimento começar.

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
- (frontend) Estender `getUTMParameters()` para ler `gclid`, `gbraid`, `wbraid` do querystring e adicionar como hidden fields no formulário.
- (backend) Adicionar `gclid: Optional[str]` em `LeadCaptureRequest` e propagar até `lead_dict`.
- (banco) Migração adicionando `gclid` (e idealmente `gbraid`/`wbraid`) em `leads_capi` (Railway) e na tabela `Lead` do Prisma.

### 2. Configuração da conta Google Ads  🟡 USUÁRIO

Antes do desenvolvimento começar, no gerenciador de anúncios:
- Criar **Conversion Action** do tipo "Lead" com Enhanced Conversions for Leads habilitado.
- Definir nome do evento (sugestão: `LeadQualified` para paridade com Meta) e ação de alta qualidade separada (sugestão: `LeadQualifiedHighQuality`, decis D9-D10).
- Anotar `Customer ID`, `Conversion Action ID` e gerar Developer Token + OAuth2 client.

## Infraestrutura já preparada para receber a integração

A correção de DT-CAPI-01 (commit `41cc2bf`, 29/04/2026) deixou o roteamento por plataforma centralizado e já com hook explícito para Google Ads:

- **Função de roteamento:** `should_send_to_destination(lead, capi_config, destination='meta')` em `V2/api/capi_integration.py:886-939`. Hoje qualquer `destination ≠ 'meta'` retorna `False, 'unknown_destination'`. Para ativar Google basta adicionar branch `elif destination == 'google'` lendo `capi_config.google_source_allowlist` (mais checagem `if not lead.get('gclid')`).
- **Dataclass de config:** `CAPIConfig` em `V2/src/core/client_config.py:209-221` precisa ganhar campos `google_developer_token`, `google_customer_id`, `google_conversion_action_id`, `google_source_allowlist`, `google_event_name_with_value`, `google_event_name_high_quality`.
- **YAML por cliente:** `configs/clients/devclub.yaml` precisa de bloco `google_ads:` paralelo ao `capi:`.
- **Dispatcher:** os 4 paths que hoje chamam `should_send_to_destination(..., destination='meta')` precisam de chamada espelhada para `destination='google'`, disparando o cliente Google Ads quando passar.
- **Persistência:** coluna `googleAdsStatus` em `leads_capi` análoga a `capiStatus`.
- **Cliente da API:** módulo novo `V2/api/google_ads_integration.py` (não juntar com `capi_integration.py` — outro SDK e outro fluxo OAuth2). Espelhar interface de `send_event` / `send_batch_events` do CAPI.

## Ordem de execução

1. Cliente B estabilizado (H5 do `PLANO_EXECUCAO.md`).
2. Pré-requisito 1 (gclid frontend → backend → banco) **e** pré-requisito 2 (conta Google Ads configurada) — em paralelo.
3. Implementação na ordem: estender `CAPIConfig` → branch em `should_send_to_destination` → módulo `google_ads_integration.py` → integrar nos 4 paths → coluna `googleAdsStatus` → bloco YAML do DevClub → smoke test em ambiente canary.
4. Por simetria com Meta: aplicar o mesmo princípio em `googleAdsStatus` (`'allowed' / 'skipped' / 'blocked' / 'sent'`).

## Observações arquiteturais

- **Modelo único, dispatch múltiplo (F8).** Pipeline de treino e scoring NÃO mudam — score é o mesmo. O que muda é o destino do evento. Adicionar Google Ads não cria fork de modelo nem retreino.
- **Sem vazamento de sinal cross-platform.** Como Meta usa allowlist `["facebook-ads", "instagram"]` e Google usará `["google-ads"]`, leads não sangram para o canal errado. Isso fecha definitivamente o vazamento histórico DT-CAPI-01.
- **TikTok Events API** segue o mesmo padrão, próximo da fila depois de Google Ads (também em H6).
