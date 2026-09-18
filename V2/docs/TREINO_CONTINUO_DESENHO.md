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

## Entrada, processamento, saída

| Etapa | O que entra | O que acontece | O que sai |
|---|---|---|---|
| 1. Gatilho | dia 1 de cada mês às 06:00 (Cloud Scheduler), ou um alerta de drift do monitoring | dispara o Cloud Run Job `retreino-mensal` | uma execução do job |
| 2. Universo | `leads_treino_prod` no Cloud SQL, com corte temporal do dia | o job congela o universo numa tabela datada (`leads_treino_prod_YYYYMMDD`) antes de treinar | universo reproduzível |
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
| régua de comparação | existe (`ci_check_active_model.py`, PR #262) | expor `julgar()` para o job chamar |
| abrir a PR do modelo | existe (`abrir_pr_modelo.sh`, usa worktree e `gh`) | versão para runner: sem worktree, `gh` autenticado por token do repositório, push por HTTPS |
| Cloud Run Job `retreino-mensal` | não existe | criar com a imagem da API, 8 GiB, 4 vCPU, timeout 60 min, conta de serviço com leitura do Cloud SQL e escrita no bucket e no MLflow |
| congelar o universo | não existe | uma tabela por corte; o treino lê só dela |
| gatilho por drift | não existe | o alerta de drift do monitoring chama o job (uma linha no orquestrador de alertas) |

## Riscos conhecidos, e o que o desenho faz com eles

- **Modelo passado não é reproduzível** (memória do projeto: o universo era destruído no
  rebuild). O congelamento por corte na etapa 2 é a resposta: o run aponta para a tabela
  que o gerou.
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
2. **Universo congelado** (1 dia): tabela por corte e o treino lendo dela; teste que
   compara o run com a tabela.
3. **Julgamento e Slack** (1 dia): o job chama `julgar()` e manda o card no DM em
   qualquer veredito.
4. **PR automática** (1 dia): versão do `abrir_pr_modelo.sh` para runner; o job abre a PR
   quando o veredito permite.
5. **Gatilhos** (1 dia): Cloud Scheduler mensal e a chamada a partir do alerta de drift.

Fora deste projeto: mudar a régua (os limiares de `retreino_mensal.yaml` são decisão de
negócio), e retreinar com dado de outro cliente (o universo é o da DevClub).
