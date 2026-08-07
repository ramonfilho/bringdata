# Catálogo de dados

**Gerado automaticamente em 2026-08-06** por [scripts/catalogo_dados.py](../scripts/catalogo_dados.py). Não editar à mão: rode o script de novo.

A única parte escrita por gente é a coluna *Para que serve*, que mora no dicionário `PARA_QUE_SERVE` dentro do script. Tabela nova aparece aqui sozinha, marcada como SEM DESCRIÇÃO até alguém escrever a linha dela.

**Como ler a coluna Estado:** 🟢 escrita nos últimos 2 dias · 🟡 parada há até 15 dias · 🔴 parada há mais de 15 dias · ⬜ vazia. Parada não quer dizer quebrada: uma tabela de captação fica parada de propósito entre lançamentos. Quer dizer *confira antes de confiar*.

**25 tabelas** · 7 escritas nos últimos 2 dias · 5 paradas há mais de 15 dias.

## Schema `analytics` (20 tabelas)

| Tabela | Linhas | Estado | Última escrita | Janela dos dados | Para que serve |
|---|---:|---|---|---|---|
| `captacoes` | 503,438 | 🟡 3d sem escrita | 2026-08-03 | 2024-12-30 a 2026-08-03 | Histórico de captação no grão lead x LANÇAMENTO, com o anúncio que trouxe cada um e se comprou. Montada das planilhas do Drive. É a base da nota do criativo. |
| `cadastros` | 454,620 | 🟢 viva | 2026-08-06 | 2024-12-30 a 2026-08-06 | Espinha de TODOS os cadastros, respondentes ou não, uma linha por PESSOA. Serve para contar volume real de captação e casar compra. |
| `leads` | 366,412 | 🟢 viva | 2026-08-06 | 2024-12-30 a 2026-08-06 | Universo de treino: os leads que responderam a pesquisa, unificados de todas as fontes. É daqui que o pipeline de treino lê. |
| `leads_provenance` | 366,412 | 🟢 viva | 2026-08-06 | 2026-06-30 a 2026-08-06 | De qual fonte veio cada lead do universo de treino. Trilha de lineage. |
| `hotleads_seal` | 323,134 | ❔ sem coluna de data | - | - | Selo do HotLeads da Hotmart por lead: se a pessoa já comprou algo na plataforma. |
| `leads_arquivo_pre_elim` | 303,475 | 🔴 38d sem escrita | 2026-06-29 | 2024-12-30 a 2026-06-29 | **SEM DESCRIÇÃO** (escrever no script) |
| `ad_spend` | 74,147 | 🟢 viva | 2026-08-06 | - | Gasto por anúncio e por dia, vindo da API da Meta. Denominador do ROAS. |
| `sales` | 19,459 | 🟢 viva | 2026-08-06 | 2022-11-18 a 2026-08-05 | Vendas de todos os gateways (Guru, TMB, Boletex, Asaas, Hotmart), já unificadas. |
| `leads_train_unified_backup_20260730` | 18,931 | 🟡 7d sem escrita | 2026-07-30 | 2026-07-15 a 2026-07-30 | **SEM DESCRIÇÃO** (escrever no script) |
| `sales_audit_snapshot_20260721` | 18,626 | 🔴 16d sem escrita | 2026-07-21 | 2022-11-18 a 2026-07-21 | **SEM DESCRIÇÃO** (escrever no script) |
| `sales_tmb_xlsx_backup` | 7,334 | 🔴 22d sem escrita | 2026-07-15 | 2022-11-18 a 2026-07-14 | **SEM DESCRIÇÃO** (escrever no script) |
| `sales_tmb_risk` | 6,650 | 🔴 36d sem escrita | 2026-07-01 | - | Grau de risco de inadimplência das vendas por boleto da TMB. |
| `validation_metrics` | 2,436 | 🟡 3d sem escrita | 2026-08-03 | 2026-06-30 a 2026-08-03 | Métricas de cada rodada de validação. |
| `transcricoes` | 101 | 🟢 viva | 2026-08-05 | - | Transcrição da fala dos vídeos dos criativos, com duração e contagem de palavras. Alimenta o palpite para criativo estreante. |
| `validation_runs` | 60 | 🟡 3d sem escrita | 2026-08-03 | 2026-06-30 a 2026-08-03 | Cabeçalho de cada rodada de validação do modelo. |
| `campaign_labels` | 50 | ❔ sem coluna de data | - | - | Rótulo de cada campanha por qual MODELO a tocou, para o relatório saber a quem creditar cada lead. |
| `launch_calendar` | 27 | ❔ sem coluna de data | - | 2025-11-25 a 2026-07-21 | Calendário canônico dos lançamentos: quando cada um capta e quando vende. Espelha a planilha PC FORMULÁRIOS. |
| `leads_unified_audit` | 19 | ❔ sem coluna de data | - | - | Auditoria da unificação de leads: o que entrou, o que foi deduplicado. |
| `reference_rolling` | 4 | ❔ sem coluna de data | - | 2026-05-30 a 2026-07-13 | Referência rolante dos relatórios: a régua de comparação que substituiu o recorte congelado Top 5 ROAS. |
| `meta_insights` | 0 | ⬜ vazia | - | - | Métricas brutas de campanha da API da Meta (impressões, cliques, custo). |

## Schema `public` (5 tabelas)

| Tabela | Linhas | Estado | Última escrita | Janela dos dados | Para que serve |
|---|---:|---|---|---|---|
| `scores_historicos` | 221,415 | ❔ sem coluna de data | - | - | Score e decil recalculados retroativamente para leads antigos, quando um modelo novo precisa pontuar quem já tinha passado. |
| `leads_historico` | 202,803 | ❔ sem coluna de data | - | - | Backup da outra tabela de leads do Railway (nov/2025 a jun/2026), com a pesquisa em snake_case. Só histórico. |
| `lead_legado` | 142,943 | 🔴 53d sem escrita | 2026-06-14 | 2026-02-18 a 2026-06-14 | Backup da tabela de leads do front antigo do Railway (fev a jun/2026), com a pesquisa em camelCase. Só histórico. |
| `registros_ml` | 85,524 | 🟢 viva | 2026-08-06 | 2026-05-23 a 2026-08-06 | O ledger do ML. O consumer do Pub/Sub escreve uma linha por lead no momento em que o scoreia. É a fonte VIVA de decil, score, variante do A/B, respostas da pesquisa e status do envio ao Meta. |
| `lead_surveys_stg` | 1,624 | ❔ sem coluna de data | - | - | Área de passagem da migração de schema de maio/2026. Morta. |

## Colunas de cada tabela

### `analytics.ad_spend`

`id`, `client_id`, `platform`, `account_id`, `campaign_id`, `campaign_name`, `spend_date`, `spend`, `leads`, `impressions`, `clicks`, `extra`, `ingested_at`

### `analytics.cadastros`

`email`, `phone`, `first_name`, `last_name`, `is_buyer`, `first_seen_at`, `last_activity_at`, `campaign_key`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `has_computer`, `fbp`, `fbc`, `ip`, `user_agent`, `page_source`, `referrer`, `event_id`, `lead_score`, `decil`, `is_respondent`, `source`, `updated_at_src`, `ingested_at`, `refreshed_at`

### `analytics.campaign_labels`

`id`, `client_id`, `tag_signature`, `categoria`, `curated_at`, `source`

### `analytics.captacoes`

`lf`, `chave`, `email`, `phone`, `phone8`, `nome`, `captured_at`, `utm_source`, `utm_campaign`, `utm_content`, `ad_base`, `has_computer`, `planilha`, `bought_45d`, `bought_ever`, `ingested_at`, `ad_name`

### `analytics.hotleads_seal`

`email`, `hot`, `sealed_at`, `execution_id`

### `analytics.launch_calendar`

`client_id`, `lf_name`, `cap_start`, `cap_end`, `vendas_start`, `vendas_end`, `entry`, `source`, `synced_at`

### `analytics.leads`

`id`, `client_id`, `source`, `event_id`, `email`, `phone`, `first_name`, `last_name`, `capturado_em`, `status_envio`, `decil`, `score`, `variant`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `utm_url`, `capi_enviado_em`, `erro`, `survey_responses`, `fbp`, `fbc`, `user_agent`, `ip`, `has_computer`, `ingested_at`

### `analytics.leads_arquivo_pre_elim`

`id`, `client_id`, `source`, `event_id`, `email`, `phone`, `first_name`, `last_name`, `capturado_em`, `status_envio`, `decil`, `score`, `variant`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `utm_url`, `capi_enviado_em`, `erro`, `survey_responses`, `fbp`, `fbc`, `user_agent`, `ip`, `has_computer`, `ingested_at`

### `analytics.leads_provenance`

`source`, `event_id`, `provenance`, `prio`, `ingested_at`, `first_seen_at`

### `analytics.leads_train_unified_backup_20260730`

`id`, `client_id`, `source`, `event_id`, `email`, `phone`, `first_name`, `last_name`, `capturado_em`, `status_envio`, `decil`, `score`, `variant`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `utm_url`, `capi_enviado_em`, `erro`, `survey_responses`, `fbp`, `fbc`, `user_agent`, `ip`, `has_computer`, `ingested_at`

### `analytics.leads_unified_audit`

`run_at`, `prio`, `fonte`, `na_fonte`, `excl_data`, `excl_email`, `deduplicadas`, `incluidas`, `conserva`, `source`

### `analytics.meta_insights`

`id`, `client_id`, `account_id`, `campaign_id`, `campaign_name`, `insight_date`, `spend`, `leads`, `cpl`, `impressions`, `clicks`, `extra`, `ingested_at`

### `analytics.reference_rolling`

`client_id`, `window_end`, `window_start`, `as_of`, `ruler_run_id`, `source`, `n_leads`, `conversion`, `calibration`, `generated_at`, `audience_profile`

### `analytics.sales`

`id`, `client_id`, `gateway`, `external_id`, `source_file`, `email`, `phone`, `nome`, `sale_value`, `sale_value_realizado`, `sale_date`, `produto`, `status`, `ingested_at`

### `analytics.sales_audit_snapshot_20260721`

`id`, `client_id`, `gateway`, `external_id`, `source_file`, `email`, `phone`, `nome`, `sale_value`, `sale_value_realizado`, `sale_date`, `produto`, `status`, `ingested_at`

### `analytics.sales_tmb_risk`

`client_id`, `email`, `risk_grade`, `ingested_at`

### `analytics.sales_tmb_xlsx_backup`

`id`, `client_id`, `gateway`, `external_id`, `source_file`, `email`, `phone`, `nome`, `sale_value`, `sale_value_realizado`, `sale_date`, `produto`, `status`, `ingested_at`

### `analytics.transcricoes`

`criativo`, `fonte`, `ref`, `dur_s`, `palavras`, `texto`, `ingested_at`

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

