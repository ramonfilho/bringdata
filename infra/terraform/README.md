# Infraestrutura do CI/CD em Terraform

O que a pipeline precisa fora do código: a identidade que o GitHub Actions assume no GCP
e as configurações do repositório. Tudo aqui já existe (criado em 14/09/2026 pelo
`scripts/bootstrap_identidade_ci.sh` e por chamadas de API); os blocos em `imports.tf`
adotam esses recursos, então o primeiro `apply` grava o estado e não muda nada.

## Rodar

```bash
cd infra/terraform
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)   # dono do projeto
export GITHUB_TOKEN=$(gh auth token)                                # admin do repositório
terraform init
terraform plan      # esperado na primeira vez: N to import, 0 to add, 0 to change, 0 to destroy
terraform apply
```

O estado fica em `gs://smart-ads-mlflow/terraform/ci-cd/`. Depois do primeiro `apply`,
qualquer mudança nessa infraestrutura passa a ser uma PR nesta pasta, e `terraform plan`
mostra o drift do que alguém tenha mexido na mão.

## O que entra

| Arquivo | Recursos |
|---|---|
| `gcp.tf` | conta `github-deployer`; papéis no projeto (run.admin, logging.viewer, run.invoker); agir como a conta de runtime; token creator nela mesma e na `scheduler-invoker`; objectAdmin no bucket `smart-ads-mlflow`; writer no Artifact Registry `gcr.io`; secretAccessor em 6 segredos; pool e provider OIDC restritos a `ramonfilho/bringdata`; API `sts` |
| `github.tf` | environments `canary-10`, `canary-50`, `production` com reviewer; variáveis `GCP_DEPLOYER_SA`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `PROMOTION_ENABLED`; proteção da `main` (checks obrigatórios, sem force push, linear, vale para admin) |

## O que fica de fora, e por quê

- Serviços Cloud Run, jobs e agendamentos: nascem do deploy e dos scripts de cada job, com
  variáveis de ambiente que mudam por deploy. Colocar aqui criaria dois donos.
- Os segredos em si: só o acesso a eles está aqui. O valor nunca passa por estado.
- Chaves de segurança do repositório (secret scanning, Dependabot): o provider só as
  gerencia junto com o recurso inteiro do repositório, o que traria dezenas de atributos
  para dentro do estado por três toggles. Estão ligadas por API e documentadas em
  `docs/DEPLOY_GATEKEEPER.md`.
