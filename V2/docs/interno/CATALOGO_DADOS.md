# Catálogo de dados

**Gerado automaticamente em 2026-08-11** por [scripts/catalogo_dados.py](../../scripts/catalogo_dados.py). Não editar à mão: rode o script de novo.

As partes escritas por gente são duas, as duas dentro do script: a coluna *Para que serve* (dicionário `PARA_QUE_SERVE`) e a seção *Relações entre tabelas* (constante `RELACOES`). Tabela nova aparece aqui sozinha, marcada como SEM DESCRIÇÃO até alguém escrever a linha dela.

**Como ler a coluna Estado:** 🟢 escrita nos últimos 2 dias · 🟡 parada há até 15 dias · 🔴 parada há mais de 15 dias · ⬜ vazia. Parada não quer dizer quebrada: uma tabela de captação fica parada de propósito entre lançamentos. Quer dizer *confira antes de confiar*.

**23 tabelas** · 9 escritas nos últimos 2 dias · 3 paradas há mais de 15 dias.

## Schema `analytics` (18 tabelas)

| Tabela | Linhas | Estado | Última escrita | Janela dos dados | Para que serve |
|---|---:|---|---|---|---|
| `captacoes` | 505,371 | 🟢 viva | 2026-08-11 | 2024-12-30 a 2026-08-11 | Histórico de captação, uma linha por INSCRIÇÃO (chave `lf, chave, origem_id`). É a FONTE ÚNICA da entrega de leads para a agência de tráfego e a base da nota do criativo. Alimentada por `ingest_captacoes_railway.py` a partir do Railway (`Client` LEFT JOIN `UTMTracking`) a cada 5 min; as ~503 mil linhas antigas vieram das planilhas do Drive (coluna `planilha` guarda a procedência). Até 11/08/2026 não tinha escritor nenhum no repositório — por isso parou sozinha em 03/08 e o LF64 ficou com ZERO linhas com o lançamento rodando. |
| `cadastros` | 455,679 | 🟢 viva | 2026-08-11 | 2024-12-30 a 2026-08-11 | Espinha de TODOS os cadastros, respondentes ou não, uma linha por PESSOA. Serve para contar volume real de captação e casar compra. **Não é base de treino**: a marca `is_respondent` dela é calculada perguntando se a pessoa está em `analytics.leads`. |
| `leads` | 367,289 | 🟢 viva | 2026-08-11 | 2024-12-30 a 2026-08-11 | Universo de treino: os leads que responderam a pesquisa, unificados de CINCO fontes por `leads_unify.py` (a prioridade 1 é `registros_ml`). É daqui que o pipeline de treino lê. Uma linha por (e-mail, dia). **Não é a tabela de todos os leads** — quem não respondeu não está aqui, está em `analytics.cadastros`. |
| `leads_provenance` | 367,289 | 🟢 viva | 2026-08-11 | 2026-06-30 a 2026-08-11 | De qual fonte veio cada lead do universo de treino. Trilha de lineage. |
| `hotleads_seal` | 323,134 | ❔ sem coluna de data | - | - | Selo do HotLeads da Hotmart por lead: se a pessoa já comprou algo na plataforma. |
| `url_captura_legado` | 101,389 | ❔ sem coluna de data | - | - | Repescagem da URL de captura de JANEIRO e fevereiro/2026, montada em 09/08/2026 por `scripts/recupera_url_legado.py` a partir do dump do Cloud SQL de 25/02. Estática de propósito: é histórico recuperado, não fonte viva. Existe porque a URL daquele período morava em `leads_capi.event_source_url`, que hoje está vazia — o dado não se perdeu, deixou de ser copiado adiante numa migração de schema. Levou janeiro de 0,9% para 98,6% de cobertura na entrega da agência. |
| `ad_spend` | 78,308 | 🟢 viva | 2026-08-11 | - | Gasto por anúncio e por dia, vindo da API da Meta. Denominador do ROAS. |
| `sales` | 19,714 | 🟢 viva | 2026-08-11 | 2022-11-18 a 2026-08-11 | Vendas de todos os gateways (Guru, TMB, Boletex, Asaas, Hotmart), já unificadas. |
| `sales_tmb_risk` | 6,650 | 🔴 41d sem escrita | 2026-07-01 | - | Grau de risco de inadimplência das vendas por boleto da TMB. |
| `validation_metrics` | 2,746 | 🟢 viva | 2026-08-10 | 2026-06-30 a 2026-08-10 | Métricas de cada rodada de validação. |
| `decis_backfill_jul24` | 418 | 🔴 21d sem escrita | 2026-07-21 | 2026-07-21 a 2026-07-21 | Foto pontual (21/07/2026) do decil do MESMO lead pelos dois modelos, jul24 e abr28, lado a lado — 418 linhas. Serviu para comparar os dois na mesma régua; não é alimentada por nada, é registro de uma análise. |
| `transcricoes` | 101 | 🟡 6d sem escrita | 2026-08-05 | - | Transcrição da fala dos vídeos dos criativos, com duração e contagem de palavras. Alimenta o palpite para criativo estreante. |
| `validation_runs` | 67 | 🟢 viva | 2026-08-10 | 2026-06-30 a 2026-08-10 | Cabeçalho de cada rodada de validação do modelo. |
| `campaign_labels` | 50 | ❔ sem coluna de data | - | - | Rótulo de cada campanha por qual MODELO a tocou, para o relatório saber a quem creditar cada lead. |
| `launch_calendar` | 28 | ❔ sem coluna de data | - | 2025-11-25 a 2026-08-07 | Calendário canônico dos lançamentos: quando cada um capta e quando vende. Espelha a planilha PC FORMULÁRIOS. |
| `leads_unified_audit` | 19 | ❔ sem coluna de data | - | - | Auditoria da unificação de leads: o que entrou, o que foi deduplicado. |
| `reference_rolling` | 5 | ❔ sem coluna de data | - | 2026-05-30 a 2026-07-13 | Referência rolante dos relatórios: a régua de comparação que substituiu o recorte congelado Top 5 ROAS. |
| `meta_insights` | 0 | ⬜ vazia | - | - | Métricas brutas de campanha da API da Meta (impressões, cliques, custo). |

## Schema `public` (5 tabelas)

| Tabela | Linhas | Estado | Última escrita | Janela dos dados | Para que serve |
|---|---:|---|---|---|---|
| `scores_historicos` | 221,415 | ❔ sem coluna de data | - | - | Score e decil recalculados retroativamente para leads antigos, quando um modelo novo precisa pontuar quem já tinha passado. |
| `leads_historico` | 202,803 | ❔ sem coluna de data | - | - | Backup da outra tabela de leads do Railway (nov/2025 a jun/2026), com a pesquisa em snake_case. Só histórico. |
| `lead_legado` | 142,943 | 🔴 58d sem escrita | 2026-06-14 | 2026-02-18 a 2026-06-14 | Backup da tabela de leads do front antigo do Railway (fev a jun/2026), com a pesquisa em camelCase. Só histórico. |
| `registros_ml` | 86,708 | 🟢 viva | 2026-08-11 | 2026-05-23 a 2026-08-11 | O ledger do ML. O consumer do Pub/Sub escreve uma linha por lead no momento em que o scoreia. É a fonte VIVA de decil, score, variante do A/B, respostas da pesquisa e status do envio ao Meta. **É a prioridade 1 de `analytics.leads`** — as duas cobrem a mesma gente de 23/05/2026 pra cá; ver Relações entre tabelas. |
| `lead_surveys_stg` | 1,624 | ❔ sem coluna de data | - | - | Área de passagem da migração de schema de maio/2026. Morta. |

## Relações entre tabelas

A tabela acima descreve cada tabela isolada. Esta seção diz como elas se cruzam, que é a
parte que a listagem não consegue mostrar.

### Os três lugares onde um lead pode estar (e por que não é redundância)

```
      o lead responde a pesquisa
                 │
                 ▼
   public.registros_ml ......... LEDGER VIVO. Uma linha por RESPOSTA.
   (23/05/2026 em diante)        Chega em minutos, pela fila do Pub/Sub.
                 │
                 │  prio 1 de cinco fontes (leads_unify.py)
                 ▼
   analytics.leads ............. UNIVERSO DE TREINO. Só respondente.
   (histórico completo)          Uma linha por (e-mail, dia). Refeita 09:00.
                 │
                 │  define a marca is_respondent
                 ▼
   analytics.cadastros ......... ESPINHA. Respondente E não-respondente.
   (histórico completo)          Uma linha por PESSOA. Refeita 10:00.
```

**`registros_ml` e `analytics.leads` cobrem a mesma gente de 23/05/2026 para cá.** Não é
duplicação por descuido: o ledger é a fonte CRUA e VIVA, e `analytics.leads` é a
consolidação tratada que o INGERE como prioridade 1. Antes de 23/05 o ledger não existia,
e naquele período `analytics.leads` é a única que tem o dado — ele vem das outras quatro
fontes (`lead_legado`, `lead_surveys`, planilhas do Sheets e arquivos `.xlsx`).

Consequência prática, e é a que morde: **quem quer o lead de HOJE não pode ler as duas
derivadas**, porque as duas são reconstruídas de madrugada. Tem que ler o ledger.

### Os dois erros de leitura mais fáceis de cometer

1. **"`analytics.leads` tem todos os leads."** Não. Ela tem os que RESPONDERAM a pesquisa.
   Quem se cadastrou e não respondeu (23% da base em 2026) só existe em
   `analytics.cadastros`.
2. **"`analytics.cadastros` é a base de treino."** Não. O treino lê `analytics.leads`. A
   marca `is_respondent` de `cadastros` é derivada de estar em `analytics.leads`, então
   inverter os dois papéis inverte a direção da dependência.

### Onde cada uma é consumida

| Consumidor | Lê | Por quê |
|---|---|---|
| Pipeline de treino | `analytics.leads` | é o universo de treino |
| Entrega para a agência de tráfego | **`analytics.captacoes`, só ela** | fonte única desde 11/08/2026; antes somava as três |
| Nota do criativo | `analytics.captacoes` | histórico de captação com desfecho |
| Contagem de volume real de captação | `analytics.cadastros` | é a única com quem não respondeu |
| Relatórios de decil e score | `public.registros_ml` | é onde score e decil moram |

### A QUARTA tabela de lead: `analytics.captacoes`

Ela não entra no desenho acima porque não vem daquela cadeia. As três de cima nascem da
PESQUISA; a `captacoes` nasce do CADASTRO, direto do Railway (`Client` LEFT JOIN
`UTMTracking`), por `scripts/ingest_captacoes_railway.py`.

```
   Railway: Client (todo mundo)  +  UTMTracking (a campanha)
                 │
                 ▼
   analytics.captacoes ......... uma linha por INSCRIÇÃO.
   (chave lf+email+origem_id)    Chega em minutos. É a fonte da entrega
                                 para a agência e da nota do criativo.
```

O grão dela é o único que permite a MESMA pessoa aparecer duas vezes no mesmo lançamento —
as outras três colapsam por pessoa ou por (pessoa, dia). Foi essa a razão da mudança de
chave em 11/08/2026: a agência precisa ver o recadastro.

Cuidado ao contar gente nela: 505 mil linhas NÃO são 505 mil pessoas. Quem for contar
público tem que deduplicar por e-mail — `read_captacoes_audience` já faz, e `nota_criativo`
deduplica por (pessoa, criativo, dia) porque a nota é uma taxa.

## Colunas de cada tabela

### `analytics.ad_spend`

`id`, `client_id`, `platform`, `account_id`, `campaign_id`, `campaign_name`, `spend_date`, `spend`, `leads`, `impressions`, `clicks`, `extra`, `ingested_at`

### `analytics.cadastros`

`email`, `phone`, `first_name`, `last_name`, `is_buyer`, `first_seen_at`, `last_activity_at`, `campaign_key`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `has_computer`, `fbp`, `fbc`, `ip`, `user_agent`, `page_source`, `referrer`, `event_id`, `lead_score`, `decil`, `is_respondent`, `source`, `updated_at_src`, `ingested_at`, `refreshed_at`

### `analytics.campaign_labels`

`id`, `client_id`, `tag_signature`, `categoria`, `curated_at`, `source`

### `analytics.captacoes`

`lf`, `chave`, `email`, `phone`, `phone8`, `nome`, `captured_at`, `utm_source`, `utm_campaign`, `utm_content`, `ad_base`, `has_computer`, `planilha`, `bought_45d`, `bought_ever`, `ingested_at`, `ad_name`, `utm_medium`, `utm_term`, `utm_url`, `origem_id`

### `analytics.decis_backfill_jul24`

`email`, `event_id`, `utm_campaign`, `utm_source`, `decil_jul24`, `decil_abr28`, `created_at`, `gerado_em`, `run_id`

### `analytics.hotleads_seal`

`email`, `hot`, `sealed_at`, `execution_id`

### `analytics.launch_calendar`

`client_id`, `lf_name`, `cap_start`, `cap_end`, `vendas_start`, `vendas_end`, `entry`, `source`, `synced_at`

### `analytics.leads`

`id`, `client_id`, `source`, `event_id`, `email`, `phone`, `first_name`, `last_name`, `capturado_em`, `status_envio`, `decil`, `score`, `variant`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `utm_url`, `capi_enviado_em`, `erro`, `survey_responses`, `fbp`, `fbc`, `user_agent`, `ip`, `has_computer`, `ingested_at`

### `analytics.leads_provenance`

`source`, `event_id`, `provenance`, `prio`, `ingested_at`, `first_seen_at`

### `analytics.leads_unified_audit`

`run_at`, `prio`, `fonte`, `na_fonte`, `excl_data`, `excl_email`, `deduplicadas`, `incluidas`, `conserva`, `source`

### `analytics.meta_insights`

`id`, `client_id`, `account_id`, `campaign_id`, `campaign_name`, `insight_date`, `spend`, `leads`, `cpl`, `impressions`, `clicks`, `extra`, `ingested_at`

### `analytics.reference_rolling`

`client_id`, `window_end`, `window_start`, `as_of`, `ruler_run_id`, `source`, `n_leads`, `conversion`, `calibration`, `generated_at`, `audience_profile`

### `analytics.sales`

`id`, `client_id`, `gateway`, `external_id`, `source_file`, `email`, `phone`, `nome`, `sale_value`, `sale_value_realizado`, `sale_date`, `produto`, `status`, `ingested_at`

### `analytics.sales_tmb_risk`

`client_id`, `email`, `risk_grade`, `ingested_at`

### `analytics.transcricoes`

`criativo`, `fonte`, `ref`, `dur_s`, `palavras`, `texto`, `ingested_at`

### `analytics.url_captura_legado`

`email`, `utm_url`, `fonte`, `recuperado_em`

### `analytics.validation_metrics`

`id`, `run_id`, `grain`, `decile`, `campaign`, `comparison_group`, `leads`, `conversions`, `conversion_rate`, `expected_conversion_rate`, `performance_ratio`, `revenue`, `spend`, `cpl`, `roas`, `roas_adjusted`, `extra`, `created_at`

### `analytics.validation_runs`

`run_id`, `client_id`, `lf`, `cap_start`, `cap_end`, `sales_start`, `sales_end`, `model_run_id`, `report_type`, `matching_method`, `tracking_rate`, `params`, `git_sha`, `created_at`

### `public.lead_legado`

`id`, `data`, `hora`, `nome_completo`, `email`, `telefone`, `pesquisa`, `source`, `campaign`, `medium`, `content`, `term`, `remote_ip`, `user_agent`, `fbc`, `fbp`, `page_url`, `lead_score`, `decil`, `created_at`, `updated_at`, `capi_sent_at`, `capi_status`

### `public.lead_surveys_stg`

`clientEmail`, `submittedAt`, `genero`, `idade`, `ocupacao`, `faixaSalarial`, `cartaoCredito`, `estudouProgramacao`, `faculdade`, `investiuCurso`, `atracaoProfissao`, `interesseEvento`, `has_computer`

### `public.leads_historico`

`id`, `email`, `lf`, `nome`, `telefone`, `data_captura`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `survey_responses`, `tem_computador`, `fonte`, `score_producao`, `decil_producao`, `generated_at`

### `public.registros_ml`

`event_id`, `email`, `variant`, `lead_score`, `decil`, `base_meta_event_id`, `base_status`, `hq_meta_event_id`, `hq_status`, `capi_sent_at`, `error_message`, `created_at`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `utm_url`, `survey_responses`, `first_name`, `last_name`, `phone`, `fbp`, `fbc`, `user_agent`, `ip`, `has_computer`, `decile_propensity`, `decile_roas_v1`, `cpl_source`, `events_fired`, `extra_hq_destinations_fired`, `google_ads_status`, `score_champion`, `score_challenger`, `decil_champion`, `decil_challenger`, `champion_run_id`, `challenger_run_id`, `scored_at`, `core_commit`, `hotleads_status`, `hotleads_hot`, `hotleads_execution_id`, `hotleads_submitted_at`, `hotleads_scored_at`, `hotleads_capi_sent_at`, `hotleads_error`

### `public.scores_historicos`

`id`, `email`, `lf`, `mes_lancamento`, `vendas_inicio`, `vendas_estimada`, `data_captura`, `semana_captacao`, `score_champion`, `decil_champion`, `score_challenger`, `decil_challenger`, `champion_run_id`, `challenger_run_id`, `core_commit`, `generated_at`

