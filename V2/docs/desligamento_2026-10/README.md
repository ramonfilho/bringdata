# Desligamento do projeto (outubro de 2026) e como reativar

Leia este arquivo inteiro antes de tocar em qualquer recurso do projeto `smart-ads-451319`.
Ele existe para que uma sessão futura saiba em que estado o projeto ficou, por quê, o que
ainda falta fazer e como acordar tudo de novo.

## 0. Em uma tela

- O contrato com o cliente (DevClub) terminou em 03/10/2026. O termo de encerramento foi
  assinado e pago. Os valores e prazos do termo são confidenciais e ficam na
  memória de sessão do Claude, não neste repositório.
- Obrigações que sobraram para a Bring Data: desligar sistemas e integrações, eliminar todo
  dado pessoal do cliente dentro do prazo contratual, e manter apenas o que o termo permite:
  modelos treinados e uma base anonimizada (sem nome, e-mail, telefone, IP ou identificador).
- O projeto GCP fica vivo, dormindo, por uns R$ 3 por mês. Tudo que custa parado foi apagado
  ou será apagado dentro do prazo. Tudo que é preciso para reativar está guardado (seção 5).
- O que nunca volta: o dado pessoal do cliente antigo e as credenciais dele. Reativação é com
  cliente novo, dados novos e segredos novos.
- Registro de execução, com data e resultado de cada passo: seção 8, no fim.

## 1. O que existia em 14/10/2026 e quanto custava

Custo medido no export de faturamento (BigQuery `billing_export`), 30 dias até 14/10/2026:
R$ 236 brutos, R$ 205 líquidos.

| Recurso | Quantidade | Custo em 30 dias | Decisão |
|---|---|---|---|
| Cloud Run, serviços (`smart-ads-api`, `smart-ads-monitoring`, `smart-ads-webhook`) | 3 | R$ 142 (R$ 31 de crédito) | Ficam, sem tráfego |
| Cloud Run, jobs | 18 | dentro do valor acima | Ficam, nunca executam sozinhos |
| Cloud Scheduler | 27 | R$ 13 | Apagados, definição guardada em `estado_2026-10-14/schedulers.json` |
| Cloud SQL `smart-ads-db` (db-f1-micro, 15 GB SSD, bancos `ledger` 4 GB, `mlflow`, `dash`) | 1 | R$ 64 | Apagada depois dos dumps |
| Artifact Registry (`gcr.io`: 482 imagens de `smart-ads-api`, 9 de `smart-ads-treino`, 7 pacotes de teste) | 15,9 GiB | R$ 13 | Fica só a imagem em uso por serviço e por job |
| Secret Manager | 14 segredos | R$ 4 | Apagados, nomes e papel na seção 5.3 |
| Buckets `smart-ads-mlflow` (1,5 GiB), `smart-ads-validation-reports` (550 MiB), `_cloudbuild` (68 MiB), `run-sources` (vazio) | 4 | menos de R$ 1 | Modelos ficam, backups com dado pessoal saem |
| Pub/Sub (`lead-capture-ingest` + DLQ, 1 assinatura) | 2 tópicos | R$ 0 | Assinaturas apagadas, tópicos ficam |
| BigQuery `billing_export` | 2 tabelas | R$ 0,5 | Fica |

A pasta `estado_2026-10-14/` guarda a definição completa de cada recurso como estava antes do
desligamento (serviços, jobs, agendadores, instância SQL, IAM, Pub/Sub, contas de serviço,
APIs ativas). Valores de variáveis de ambiente que eram segredo estão redigidos. Os JSON
foram gerados com `gcloud ... --format=json` e servem de referência para recriar.

## 2. Por que cada coisa foi feita

1. **Desligar primeiro, apagar depois.** Pausar agendador e fechar entrada dos serviços é
   reversível em um comando. Apagar não é. O desligamento aconteceu antes de qualquer dump.
2. **Dump completo em cofre temporário antes de apagar o banco.** O bucket
   `smart-ads-cofre-temporario` recebeu o export SQL dos três bancos e tem regra de ciclo de
   vida que apaga os objetos sozinha em 24 dias. Ele existe só para corrigir um erro no dump
   anonimizado enquanto o prazo contratual corre. Depois do prazo ele não pode existir.
3. **Base anonimizada separada do dado bruto.** A chave de pessoa é um UUID calculado com md5 de
   um sal aleatório mais o e-mail (seção 6). O sal existiu só durante a exportação e foi apagado
   depois da verificação. Sem ele não dá para recalcular o UUID de um e-mail conhecido, e não
   existe tabela de correspondência em lugar nenhum.
4. **Modelos ficam.** São propriedade da Bring Data e não contêm dado pessoal.
5. **Serviços e jobs ficam deployados.** Cloud Run não cobra instância parada. Apagar e recriar
   custaria mais tempo na reativação do que os centavos de mantê-los.
6. **Workflow de deploy desativado no GitHub.** Um push na `main` recriaria `smart-ads-api` com
   tráfego aberto. Ele volta com `gh workflow enable Deploy`.

## 3. Passos do desligamento (checklist)

Marcação: `[x]` feito, `[ ]` pendente. Data e resultado de cada um na seção 8.

### Passo 1: desligar (obrigação de desligamento do termo)

- [x] 1.1 Pausar os 27 agendadores do Cloud Scheduler.
- [x] 1.2 Fechar a entrada dos 3 serviços: `--ingress internal`.
- [x] 1.3 Tirar `allUsers` do invoker de `smart-ads-webhook` (estava aberto para webhooks dos gateways e do HotLeads).
- [x] 1.4 Apagar a assinatura `lead-capture-ingest-sub` (a DLQ era só tópico, sem assinatura). Os tópicos ficam: o front do cliente ainda tem permissão de publicar, e publicar num tópico sem assinatura descarta a mensagem sem erro do lado dele.
- [x] 1.5 Desativar o workflow `Deploy` no GitHub (`gh workflow disable Deploy`).
- [x] 1.6 Verificar: nenhum agendador `ENABLED`, ingress `internal` nos 3 serviços, zero assinaturas, workflow `disabled_manually`.

### Passo 2: preservar

- [x] 2.1 Criar `gs://smart-ads-cofre-temporario` (us-central1) com ciclo de vida de 24 dias e dar `objectAdmin` à conta de serviço da instância SQL.
- [x] 2.2 Export SQL completo de `ledger`, `mlflow` e `dash` para o cofre.
- [x] 2.3 Gerar a base anonimizada (desenho na seção 6) em parquet, local em `~/Desktop/bring_data_arquivo/anon_2026-10/` e cópia em `gs://smart-ads-mlflow/arquivo_anon_2026-10/`.
- [x] 2.4 Copiar `gs://smart-ads-mlflow/artifacts`, `mlruns` e `deploy-gate` para `~/Desktop/bring_data_arquivo/mlflow_2026-10/` (modelos e histórico de treinos).
- [x] 2.5 Conferir contagens da base anonimizada contra o banco, tabela a tabela.

### Passo 3: eliminar (dentro do prazo contratual)

- [x] 3.1 Apagar a instância Cloud SQL `smart-ads-db` (leva junto os backups automáticos).
- [x] 3.2 Apagar os objetos com dado pessoal nos buckets: `smart-ads-validation-reports/backups/`, `ledger_etapa5_backup/`, `vendas/` (xlsx da TMB), `validation/` (20 relatórios xlsx com a aba de vendas nominais) e `smart-ads-mlflow/backups/`. No `validation-reports` sobrou só `monitoring/critical_alerts/state.json`.
- [x] 3.3 Apagar os 27 agendadores (definição já guardada).
- [x] 3.4 Apagar os 14 segredos (nomes e papel na seção 5.3).
- [x] 3.5 Apagar as imagens que nenhum serviço ou job usa, e os 7 pacotes de teste (`bring-data-api`, `smart-ads-api-final`, `-fix`, `-strict`, `-apiatest`, `smartads`, `smartads-api`, `hotleads-*`).
- [x] 3.6 Apagar `gs://smart-ads-451319_cloudbuild` e `gs://run-sources-...` (cache de build, recriados pelo deploy).
- [x] 3.7 Apagar as cópias locais com dado pessoal no Mac (lista na seção 7).
- [ ] 3.8 Apagar a pasta compartilhada do Drive com a entrega, depois de o cliente confirmar que baixou.
- [x] 3.9 Apagar os diretórios de trabalho das sessões do Claude que guardam CSV bruto (`csv_brutos`, `pacote_devclub`).
- [ ] 3.10 Confirmar que o cofre temporário foi apagado pela regra de ciclo de vida, ou apagar à mão.
- [x] 3.11 Achado na execução: um run do MLflow tinha o conjunto de treino logado como artefato (`conjunto_de_treino.parquet`, com e-mail, telefone e nome). Apagado do bucket e da cópia local. Os `model.pkl` ficam.

### Passo 4: registrar

- [ ] 4.1 E-mail curto ao cliente registrando a data da eliminação.
- [ ] 4.2 Atualizar a seção 8 deste arquivo e a memória de sessão.

## 4. O que fica dormindo

| Recurso | Estado | Custo mensal estimado |
|---|---|---|
| Projeto, APIs ativas, IAM, contas de serviço | intactos | R$ 0 |
| 3 serviços Cloud Run | deployados, ingress `internal`, sem agendador, sem invoker público | R$ 0 |
| 18 jobs Cloud Run | deployados, sem agendador | R$ 0 |
| 1 imagem por serviço e por job no `gcr.io` | mantidas | cerca de R$ 2 |
| `gs://smart-ads-mlflow` (modelos, mlruns, cópia anonimizada) | mantido | cerca de R$ 0,5 |
| `gs://smart-ads-validation-reports` sem as pastas de backup | mantido | centavos |
| BigQuery `billing_export` | mantido | cerca de R$ 0,5 |
| Tópicos Pub/Sub | mantidos, sem assinatura | R$ 0 |

Os serviços referenciam dois segredos por `valueFrom`. Com os segredos apagados, uma instância
nova do serviço não sobe até os segredos existirem de novo. Isso é esperado no estado dormente.

## 5. Como reativar, passo a passo

Pré-requisitos: `gcloud auth login` com dono do projeto, `gcloud config set project smart-ads-451319`,
`gh auth login` na conta do repositório. As APIs continuam ativas (`estado_2026-10-14/apis_enabled.txt`).

### 5.1 Banco

1. Criar a instância: `gcloud sql instances create smart-ads-db --database-version=POSTGRES_15 --tier=db-f1-micro --region=us-central1 --storage-size=15 --storage-type=SSD`. A versão exata que existia está em `estado_2026-10-14/sql_instance.json` (`databaseVersion`).
2. Criar os bancos `ledger` e `mlflow` e os usuários que os serviços esperam (`LEDGER_DB_USER` em `services.json`, usuário do mlflow em `jobs.json` do `retreino-mensal`).
3. Carregar dados: o cliente novo traz os dele pelo ETL normal (`src/data/etl_leads.py`, `src/validation/etl_sales.py`, `src/validation/etl_ad_spend.py`). A base anonimizada (seção 6) serve para análise e retreino local, não para subir em produção.
4. O `mlflow` pode começar vazio. O histórico de runs antigo está em `~/Desktop/bring_data_arquivo/mlflow_2026-10/` e no dump do cofre enquanto ele existiu.

### 5.2 Segredos

Recriar com `gcloud secrets create <nome> --data-file=-`. Os serviços leem a maioria por variável
de ambiente literal (ver `services.json`, valores redigidos), e `scripts/puxar_segredos_env.sh`
mostra como o `.env` local era montado.

### 5.3 Nomes dos segredos que existiam e para que serviam

| Segredo | Papel |
|---|---|
| `api-internal-token` | chamadas internas entre serviços |
| `ledger-db-password`, `mlflow-db-password`, `railway-db-password` | senhas dos bancos (ledger, mlflow, Railway do front do cliente) |
| `meta-audiences-token` | token Meta com `ads_management` para públicos personalizados |
| `tmb-api-token`, `hotmart-basic` | gateways de venda do cliente |
| `hotleads-cron-token`, `hotleads-webhook-token` | integração HotLeads |
| `slack-bot-token`, `slack-webhook-url` | Slack do cliente (relatórios e alertas) |
| `dash-zanelato-password`, `dash-zanelato-supabase-url`, `dash-lead-id-salt` | entrega de dados à agência do cliente |

### 5.4 Serviços

1. Religar o workflow: `gh workflow enable Deploy`. O próximo push na `main` (fora de `docs/` e `.md`) reconstrói a imagem e sobe `smart-ads-api` pelo canário descrito em `docs/DEPLOY_GATEKEEPER.md`.
2. Ou, sem push, reabrir o que já está deployado: `gcloud run services update <serviço> --region us-central1 --ingress all`.
3. Devolver o invoker público ao webhook: `gcloud run services add-iam-policy-binding smart-ads-webhook --region us-central1 --member=allUsers --role=roles/run.invoker`. Os outros dois serviços são chamados só pela conta `scheduler-invoker@...` (ver `iam_*.json`).
4. Variáveis de ambiente: `gcloud run services update ... --update-env-vars` mescla com as existentes. As que estão redigidas em `services.json` precisam de valor novo.
5. Os relatórios de validação do monitoramento (`api/routers/monitoring.py`) gravam no bucket da variável `VALIDATION_REPORTS_BUCKET`, que vale `bring-data-validation-reports`. Esse bucket não existe neste projeto (404 em 15/10/2026). O que existe é `smart-ads-validation-reports`, o mesmo dos alertas críticos (`src/monitoring/critical_alerts.py`). Na reativação, apontar a variável para o bucket que existir.

### 5.5 Agendadores

Os scripts `api/setup_ingestion_schedulers.sh`, `api/setup_hotleads_scheduler.sh`,
`scripts/setup_scheduler_oidc.sh` e `api/deploy_*_job.sh` criam os agendadores. A grade completa
(27 jobs, horário, URI, conta OIDC) está em `estado_2026-10-14/schedulers.json`. Os cabeçalhos
com token aparecem como `<redigido>` e vêm dos segredos.

### 5.6 Pub/Sub

Recriar a assinatura pull `lead-capture-ingest-sub` no tópico `lead-capture-ingest`, com DLQ
`lead-capture-ingest-dlq`, como em `estado_2026-10-14/pubsub_subscriptions.json`. O publicador do
front usa a conta `lead-capture-publisher@...` (ver `pubsub_topic_iam.json`).

### 5.7 Conferência

`docs/DEPLOY_GATEKEEPER.md` e a skill `/deploy` descrevem o smoke test e o gate de promoção.
`scripts/relatorio_lf.sh` e o DM das 06:00 são a prova de vida do dia seguinte.

## 6. Base anonimizada

Gerada em 14/10/2026 a partir do schema `analytics` e das tabelas vivas de `public`, em parquet.

**Chave.** `pessoa_id` é `md5(sal + chave)` no formato UUID. A chave é o e-mail em minúsculas e
sem espaço, ou `tel:` mais os dígitos do telefone quando não havia e-mail. Em `scores_historicos`
e nas três tabelas satélites a chave é só o e-mail. O sal (32 bytes aleatórios) ficou num arquivo
temporário durante a exportação e foi apagado depois da verificação. A mesma pessoa tem o mesmo
`pessoa_id` em todas as tabelas, então os cruzamentos entre lead, cadastro, captação, venda e
score continuam funcionando.

**Removido das tabelas com pessoa:** toda coluna cujo nome contém e-mail, telefone, fone, nome,
name, IP, `fbp`, `fbc`, `user_agent`, `utm_url`, `referrer`, `external_id`, `event_id` (derivado
do e-mail), `source_file`, `chave`, CPF ou erro, mais `id`, `client_id` e `origem_id` (que
embutia o e-mail nas captações). No JSON da pesquisa saiu toda chave cujo nome lembra identidade:
e-mail, telefone, fone, nome, IP, `fbp`, `fbc`, user agent, `id`, CPF, WhatsApp e celular. O
filtro por nome levou junto uma coluna sem dado pessoal, `captacoes.ad_name`. O `ad_base` (código
do criativo, como `AD0150`) está preenchido em 74,5% das captações.

| Arquivo | Origem | O que tem |
|---|---|---|
| `leads_anon.parquet` | `analytics.leads` + `analytics.sales` | uma linha por resposta de pesquisa: `pessoa_id`, fonte, data, decil, score, variante, UTMs, respostas (JSON limpo), tem computador, e as colunas de rótulo `comprou_45d`, `comprou_ever`, `dias_ate_compra`, `valor_primeira_compra` |
| `cadastros_anon.parquet` | `analytics.cadastros` | uma linha por pessoa, com flags de comprador e respondente, datas, UTMs, nota e decil |
| `captacoes_anon.parquet` | `analytics.captacoes` | uma linha por captação por lançamento, com `lf`, UTMs, anúncio, planilha de origem e flags de compra |
| `vendas_anon.parquet` | `analytics.sales` | uma linha por venda: `pessoa_id`, gateway, valor, valor realizado, data, produto, status |
| `registros_ml_anon.parquet` | `public.registros_ml` | o ledger de produção: notas, decis, eventos enviados, run_ids, sem identidade |
| `scores_historicos_anon.parquet` | `public.scores_historicos` | histórico de score e decil por lançamento |
| `hotleads_seal_anon.parquet`, `sales_tmb_risk_anon.parquet`, `decis_backfill_jul24_anon.parquet` | tabelas satélites | selo HotLeads, grau de risco TMB, decis de backfill |
| `sem_dado_pessoal/*.parquet` | `ad_insights`, `ad_spend`, `campaign_labels`, `criativo_historico`, `criativo_id_map`, `launch_calendar`, `reference_rolling`, `transcricoes`, `validation_metrics`, `validation_runs` | cópias integrais, com os nomes de campanha, conjunto, anúncio e lançamento (`campaign_name`, `adset_name`, `ad_name`, `lf_name`) |
| `sem_dado_pessoal/leads_provenance.parquet` | `analytics.leads_provenance` | fonte e prioridade de cada lead, sem a chave `event_id`: serve para contagem agregada e não cruza com as outras tabelas |

**Como carregar:** `pandas.read_parquet("leads_anon.parquet")`. O JSON da pesquisa está na
coluna `survey_responses` como texto, `json.loads` por linha. O pipeline de treino lê o banco
(`src/data/leads_reader.py`), então para treinar com a base anonimizada é preciso um leitor de
parquet que entregue o mesmo shape de `read_pesquisa` e `read_sales`, usando `pessoa_id` no
lugar do e-mail.

**Limitações:** não cruza com nenhuma fonte nova (não há e-mail). Qualquer coluna derivada de
identidade (telefone com 8 dígitos, hash de e-mail) foi removida.

## 7. Cópias locais com dado pessoal (apagar no passo 3.7)

Fora do git, no Mac, em 14/10/2026:

- `V2/outputs/cache/raw_data_latest.pkl`, `raw_data_2026-06-10.pkl`, `raw_data_2026-04-08.pkl` (188 MB cada)
- `V2/tests/fixtures/snapshot_*.pkl` (10 arquivos, 36 a 90 MB, trechos reais do pipeline)
- `V2/data/devclub/contas_a_receber_08062026_1538.xlsx` (TMB, com CPF) e `V2/data/devclub/publicos_meta/lista_leads_devclub_320.csv`
- `V2/outputs/validation/**` (`leads_enriched_*.csv`, `scores_2026_por_lead.csv`, `matched_fora_do_ab.parquet` por mês), `V2/outputs/_matched_recover.parquet`
- `V2/files/*/test_set_predictions.csv`
- `V2/db_capi.pkl`
- `~/Downloads/fe05016a-*.pdf` é o contrato, fica. Os zips de dados em `~/Downloads`, se houver, saem.

Os testes que dependem dos snapshots de `tests/fixtures/` já pulam quando o arquivo não existe
(o CI roda sem eles).

## 8. Registro de execução

| Data | Passo | Resultado |
|---|---|---|
| 14/10/2026 | 0 | Inventário feito, pasta `estado_2026-10-14/` gravada, plano escrito |
| 14/10/2026 | 1.1 a 1.5 | 23 agendadores pausados (4 já estavam), ingress `internal` nos 3 serviços, `allUsers` removido do webhook, assinatura Pub/Sub apagada, workflow Deploy `disabled_manually` |
| 14/10/2026 | 1.6 | Verificado: 27 `PAUSED`, 3 serviços `internal`, 0 assinaturas, invoker do webhook vazio |
| 14/10/2026 | 2.1 | `gs://smart-ads-cofre-temporario` criado em us-central1, regra Delete aos 24 dias, `objectAdmin` para a conta de serviço da instância SQL |
| 14/10/2026 | 2.2 | Export SQL com offload para o cofre: `ledger_2026-10-14.sql.gz` (328 MiB), `mlflow_2026-10-14.sql.gz` (114 KiB, 219 runs), `dash_2026-10-14.sql.gz` (54 MiB) |
| 14/10/2026 | 2.3 | Base anonimizada gerada: 9 tabelas com `pessoa_id` + 11 sem dado pessoal, 101 MB em parquet, local e em `gs://smart-ads-mlflow/arquivo_anon_2026-10/`. Chave (sal) destruída depois da verificação |
| 14/10/2026 | 2.5 | Contagem igual ao banco nas 20 tabelas. Dois vazamentos pegos e corrigidos antes de fechar: chave `E-mail` do JSON (filtro só casava `email`) e coluna `origem_id` das captações (embutia o e-mail). Varredura final: 0 e-mails e 0 telefones em todos os arquivos |
| 14/10/2026 | 3.1 | Instância `smart-ads-db` apagada (com os backups automáticos). Zero instâncias no projeto |
| 14/10/2026 | 3.2 | Apagados `validation-reports/backups`, `ledger_etapa5_backup`, `vendas` e `mlflow/backups` |
| 14/10/2026 | 3.3 | 27 agendadores apagados |
| 14/10/2026 | 3.4 | 14 segredos apagados |
| 14/10/2026 | 3.6 | Buckets `_cloudbuild` e `run-sources` apagados, e o repositório `cloud-run-source-deploy` (587 MiB) apagado |
| 14/10/2026 | 3.2 | `validation/` apagado depois de abrir um relatório: a aba "Detalhes das Conversões" listava as vendas com e-mail |
| 14/10/2026 | 3.5 | 575 imagens apagadas em duas passadas pelo Artifact Registry (a primeira derruba os índices multi-arquitetura, a segunda os filhos liberados). Restam 27 manifests: 14 em uso e 13 filhos (camadas por arquitetura) dessas 14, que a API protege enquanto o pai existir. Sete exclusões deram `PERMISSION_DENIED` numa corrida entre pai e filho e sumiram na recontagem |
| 14/10/2026 | 3.7 | Apagados `data/devclub`, `outputs/cache`, `outputs/validation`, `outputs/production`, `files/`, os parquet `_matched_*` e `_feat_*`, 6 arquivos de `outputs/analysis` e `outputs/comercial`, `db_capi.pkl` e os 10 snapshots de `tests/fixtures`. Primeira tentativa rodou na pasta errada e não apagou nada: a segunda usou caminho absoluto e conferiu item a item |
| 14/10/2026 | 3.9 | `csv_brutos`, `pacote_devclub`, `export_estado` e o estado bruto (com segredos) apagados do scratchpad da sessão |
| 14/10/2026 | 3.11 | `conjunto_de_treino.parquet` do run `47b0cae6` apagado do bucket e da cópia local |
| 14/10/2026 | 2.4 | Cópia local do MLflow concluída em `~/Desktop/bring_data_arquivo/mlflow_2026-10/`: 1.720 arquivos de `artifacts` (225 `model.pkl`), 617 de `mlruns`, `deploy-gate`. O `rsync` travou duas vezes e deixou 799 duplicatas com sufixo " 2", removidas. Varredura final da cópia: nenhum e-mail ou coluna de identidade |
| 14/10/2026 | fim do dia | Pendentes: 3.8 (pasta do Drive, espera o cliente confirmar o download), 3.10 (cofre some sozinho por ciclo de vida até ~07/11, conferir), 4.1 (e-mail ao cliente depois de 3.8 e 3.10) e 4.2 (memória atualizada em 14/10, fechar no fim) |
| 15/10/2026 | 2.3 | O filtro de colunas da exportação tinha derrubado colunas sem dado pessoal nas tabelas de `sem_dado_pessoal/` (`ad_name`, `adset_name`, `campaign_name`, `lf_name`). As 10 tabelas foram refeitas do dump do cofre, lido em streaming sem gravar nada em disco: contagem igual ao banco nas 10, zero e-mail e zero telefone. Cópia do bucket atualizada, tamanhos iguais aos locais |
| 15/10/2026 | 2.4 | Um processo de cópia do MLflow que tinha ficado pendurado desde 14/10 foi encerrado. Conferido: 2.628 arquivos (225 `model.pkl`), nenhuma duplicata, nenhum arquivo escrito depois de 14/10. O `conjunto_de_treino.json` que ficou no run `47b0cae6` é só o resumo do parquet apagado (contagem, nomes de coluna, hash) |
| 15/10/2026 | 3.2 | Conferência pedida pela revisão da PR #352: `bring-data-validation-reports`, o valor de `VALIDATION_REPORTS_BUCKET`, não existe (404), e os outros projetos da conta não têm bucket nem dataset do BigQuery. O dado pessoal em bucket estava só em `smart-ads-validation-reports`, limpo no passo 3.2. Scheduler conferido com zero agendadores |
