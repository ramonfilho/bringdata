# Treino contínuo: desenho do projeto

**Estado em 17/09/2026:** o retreino é manual. Alguém roda `python -m src.train_pipeline`
no Mac, olha o model card, decide, e abre a PR do modelo com `scripts/abrir_pr_modelo.sh`.
O CI julga a PR (`scripts/ci_check_active_model.py`: run existe, métricas passam os
limiares de `configs/retreino_mensal.yaml`, git limpo, artefatos no bucket) e a pipeline
de deploy leva o modelo a produção pelos degraus. O que falta é a primeira metade
acontecer sozinha.

**O que "treino contínuo" quer dizer aqui:** um job agendado treina um challenger com os
dados novos, compara com o champion pela mesma régua do CI, e abre a PR do modelo quando
o resultado justifica. Ninguém decide sem ver; o que muda é que a candidatura chega
pronta, com número, em vez de depender de alguém lembrar.

## Etapa 1 entregue (18/09/2026)

Primeira rodada real do job `retreino-mensal` (imagem `smart-ads-treino:v20260918_011535`,
4 vCPU, 8 GiB, sem `.env`, sem gcloud, só do Cloud SQL): 396.366 linhas de pesquisa e
20.155 vendas lidas do `analytics`, 70 features, **9,5 minutos** de ponta a ponta. Run
`47b0cae614e24833b517e2508e392064` no MLflow: `FINISHED`, `git_commit=bb23587`,
`git_dirty=false` (o primeiro run do projeto com linhagem limpa; os anteriores eram
`dirty=true`), AUC 0,722 (IC95% 0,708 a 0,734), KS 0,316, monotonia 100%, artefatos em
`gs://smart-ads-mlflow/artifacts/`. O run não foi ativado: ativar continua sendo a PR do
modelo (etapas 3 e 4). Como rodar de novo: `bash scripts/setup_retreino_job.sh` e
`gcloud run jobs execute retreino-mensal --region us-central1 --wait`.

O que a primeira rodada ensinou, já corrigido: a imagem da API não tinha `mlflow` nem
`pyarrow` (etapa `treino` do Dockerfile, #297); a checagem do Cloud SQL chamava `gcloud`
(#297); a Célula 1 exigia planilha local (modo banco, #310); a tag da imagem de treino
saía como digest (#308); o `gcloud run jobs create` recusa valor repetido em `--args`
(#309); o Dependabot passou a propor mlflow 3 e pyarrow 23 por causa do
`requirements-treino.txt` (ignores em #312).

## Etapa 2 entregue (18/09/2026): o congelamento já existia, o gate passou a exigir

O desenho pedia uma tabela datada no Cloud SQL. Não precisou: desde a PR #175 (10/08/2026)
todo treino grava, no run do MLflow que ele gera, o retrato do conjunto de treino
(`src/core/train_snapshot.py`): um manifesto (linhas, colunas, intervalo de datas,
positivos, hash do conteúdo) e o parquet do conjunto inteiro antes da engenharia de
features, mais os params `dataset_hash` e `dataset_linhas`. O job headless roda o mesmo
código, então a primeira execução na nuvem já saiu congelada: o run 47b0cae6 tem
`dataset_hash` 77bc2ac9, 382.128 linhas, e `conjunto_de_treino.parquet` + `.json` em
`gs://smart-ads-mlflow/artifacts/47b0cae614e24833b517e2508e392064/artifacts/`.

O que esta etapa acrescentou: o gate do modelo no CI (`scripts/ci_check_active_model.py`)
reprova run que entra no YAML sem os dois params ou sem os dois arquivos no bucket. Um
modelo só chega em produção com o dado que o gerou preso ao run. Efeito colateral aceito:
uma PR que volte o YAML para um run anterior a 10/08 (sem retrato) é reprovada; volta de
modelo se faz pelo rollback do deploy, não pelo YAML.

A comparação champion contra desafiante "nas mesmas linhas" (o motivo da tabela datada)
fica para a etapa 3: o julgamento lê o `dataset_hash` dos dois runs e diz se o conjunto
mudou entre eles.

## Etapas 3, 4 e 5 entregues (18/09/2026)

**O que entra:** o run que o job acabou de gravar no MLflow (`--pos-treino` no fim de
`src.train_pipeline`), o champion do YAML de produção e os limiares de
`configs/retreino_mensal.yaml`.

**O que acontece:** `src/retreino/pos_treino.py` julga o run com a mesma função do gate
do CI (`julgar()`), monta o card (AUC, monotonia, lift, KS, delta contra o champion, hash e
linhas do conjunto congelado, motivos) e manda por DM no Slack em qualquer veredito. Se o
run passou, abre a PR do modelo pela API do GitHub: ramo `modelo/<run8>`, bloco
`active_model` reescrito pela mesma função de `--activate-run` (o `ab_test` fica intacto),
card no corpo. O CI julga a PR de novo; o merge continua sendo a aprovação humana.

**O que sai:** um DM por treino e, quando cabe, uma PR. Sem o segredo `github-pr-token`
(PAT fine-grained do repositório, Contents e Pull requests em escrita, guardado no Secret
Manager e ligado ao job por `scripts/setup_retreino_job.sh`), o DM traz o comando manual.

**Gatilhos:** o Cloud Scheduler `retreino-mensal-cron` roda o job no dia 1 às 06:00 de
São Paulo; a regra `score_drift` dos alertas críticos (score médio de 60 minutos fora do
baseline de 30 dias) chama `src/retreino/gatilho.py`, que executa o job pela API com
cooldown de 14 dias guardado em `gs://smart-ads-mlflow/retreino/ultimo_gatilho.json`. O
deploy troca a imagem do job junto com a da API, para o pós-treino ser o do código vigente.

## Entrada, processamento, saída

| Etapa | O que entra | O que acontece | O que sai |
|---|---|---|---|
| 1. Gatilho | dia 1 de cada mês às 06:00 (Cloud Scheduler), ou um alerta de drift do monitoring | dispara o Cloud Run Job `retreino-mensal` | uma execução do job |
| 2. Universo | `leads_treino_prod` no Cloud SQL, com corte temporal do dia | o treino grava o retrato do conjunto (manifesto + parquet, `src/core/train_snapshot.py`) no run, e o gate do CI exige isso | run com `dataset_hash` e o parquet do que foi usado |
| 3. Treino | o universo congelado e os hiperparâmetros de `configs/clients/devclub.yaml` | `src.train_pipeline` na imagem da API (mesmo Python, mesmos pins do scikit-learn) | run no MLflow com `git_commit` = SHA da imagem e `git_dirty=false` por construção; artefatos no bucket; model card |
| 4. Julgamento | run novo e run do champion | a função `julgar()` de `ci_check_active_model.py`, com os limiares de `retreino_mensal.yaml` (`min_auc` 0,65, `min_monotonia` 0,80, `auto_approve_threshold` +0,02 de AUC, `manual_approval_threshold` +0,005) | um de três: descarta, pede olhar humano, ou candidata |
| 5. Saída | o veredito | descarta: DM no Slack com o card e o motivo; candidata ou "olhar humano": `abrir_pr_modelo.sh <run>` abre a PR com o card no corpo | PR do modelo, que segue o caminho de hoje (CI, aprovação, deploy em degraus) |

A aprovação humana continua sendo o merge da PR. O que o projeto automatiza é chegar até
ela com a comparação feita.

## O que já existe e o que precisa nascer

| Peça | Estado | Trabalho |
|---|---|---|
| pipeline de treino (`src/train_pipeline.py`) | headless desde 17/09/2026: a etapa `treino` do `api/Dockerfile` (base da API + mlflow e pyarrow) vira `gcr.io/<projeto>/smart-ads-treino:<tag>` em todo deploy; o job `retreino-mensal` (`scripts/setup_retreino_job.sh`) recebe `LEDGER_DB_*` e `MLFLOW_DB_*` do Secret Manager e roda `--leads-source db --sales-source db --no-api-data` | nada |
| model card e `git_commit` no run | existe (PR #92) | nada |
| régua de comparação | existe (`ci_check_active_model.py`, PR #262); o job chama `julgar()` em `src/retreino/pos_treino.py` desde 18/09/2026 | nada |
| abrir a PR do modelo | existe: na mão (`abrir_pr_modelo.sh`) e pelo job, via API do GitHub (`src/retreino/pos_treino.py`, desde 18/09/2026) | criar o segredo `github-pr-token` (PAT fine-grained do repositório: Contents e Pull requests em escrita); sem ele o DM traz o comando manual |
| Cloud Run Job `retreino-mensal` | existe desde 17/09/2026 (`scripts/setup_retreino_job.sh`); o deploy troca a imagem em lockstep desde 18/09 | nada |
| congelar o universo | existe desde a PR #175 (retrato no run); o gate exige desde 18/09/2026 | nada |
| gatilho por drift | existe desde 18/09/2026: `src/retreino/gatilho.py`, chamado pelo orquestrador de alertas quando `score_drift` dispara, cooldown de 14 dias; cron `retreino-mensal-cron` no dia 1 às 06:00 | nada |

## Riscos conhecidos, e o que o desenho faz com eles

- **Modelo passado não é reproduzível** (memória do projeto: o universo era destruído no
  rebuild). O retrato no run (etapa 2) é a resposta: o run carrega o parquet e o hash do
  conjunto que o gerou, e o gate não deixa entrar run sem isso.
- **Treinar no runner do GitHub.** Não: o dado de lead não sai do projeto GCP. O job roda
  no Cloud Run, na mesma rede das outras rotinas.
- **Custo.** Um job mensal de até 60 minutos com 4 vCPU e 8 GiB fica na casa de centavos
  de real por execução. O custo de verdade é o tempo de quem revisa a PR.
- **Falso positivo de melhora.** A régua é a mesma do CI, e o CI julga a PR de novo. Dois
  julgamentos iguais não somam informação, mas garantem que ninguém contorna o gate
  abrindo a PR na mão.

## Etapas do projeto (uma semana de trabalho, uma PR por etapa)

1. **Treino headless** (2 dias): `train_pipeline` lê credenciais do ambiente; job
   `retreino-mensal` criado e rodado uma vez na mão; run no MLflow com `git_dirty=false`.
2. **Universo congelado**: entregue em 18/09/2026 sem tabela nova (seção acima); o gate
   do CI exige `dataset_hash`, `dataset_linhas` e o parquet no run.
3. **Julgamento e Slack**: entregue em 18/09/2026 (`src/retreino/pos_treino.py`, flag
   `--pos-treino` do treino; DM em qualquer veredito).
4. **PR automática**: entregue em 18/09/2026 pela API do GitHub; depende do segredo
   `github-pr-token` (sem ele, o DM traz o comando manual).
5. **Gatilhos**: entregues em 18/09/2026 (cron do dia 1 às 06:00 e `score_drift` com
   cooldown de 14 dias).

Fora deste projeto: mudar a régua (os limiares de `retreino_mensal.yaml` são decisão de
negócio), e retreinar com dado de outro cliente (o universo é o da DevClub).
