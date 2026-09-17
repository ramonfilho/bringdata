# Configurações do repositório que sustentam a pipeline.

data "github_repository" "repo" {
  name = var.github_repo
}

data "github_user" "reviewer" {
  username = var.github_owner
}

# Um environment por degrau de tráfego, com o dono como reviewer obrigatório. A promoção
# no deploy.yml só roda quando alguém aprova aqui.
resource "github_repository_environment" "stage" {
  for_each            = toset(["canary-10", "canary-50", "production"])
  repository          = data.github_repository.repo.name
  environment         = each.value
  prevent_self_review = false
  can_admins_bypass   = true

  reviewers {
    users = [data.github_user.reviewer.id]
  }
}

# Variáveis lidas pelos workflows (não são segredos).
resource "github_actions_variable" "vars" {
  for_each = {
    GCP_DEPLOYER_SA                = local.sa_email
    GCP_WORKLOAD_IDENTITY_PROVIDER = "${local.pool_name}/providers/github"
    PROMOTION_ENABLED              = "true"
  }
  repository    = data.github_repository.repo.name
  variable_name = each.key
  value         = each.value
}

# Proteção da main: checks do CI obrigatórios, sem push direto, sem force push, histórico
# linear, vale para o admin. Sem exigência de revisão porque há um único desenvolvedor.
resource "github_branch_protection" "main" {
  repository_id                   = data.github_repository.repo.node_id
  pattern                         = "main"
  enforce_admins                  = true
  required_linear_history         = true
  allows_force_pushes             = false
  allows_deletions                = false
  require_conversation_resolution = true

  required_status_checks {
    strict = false
    contexts = [
      "lint mínimo (ruff E9,F63,F7,F82)",
      "pytest (Python 3.10, artefatos do bucket quando ha identidade)",
      "gate do modelo (run que a PR troca no YAML)",
    ]
  }
}
