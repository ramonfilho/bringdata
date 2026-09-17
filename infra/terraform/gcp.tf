# Identidade que o GitHub Actions assume no GCP, e só o que ela pode fazer.

resource "google_project_service" "sts" {
  project            = var.project_id
  service            = "sts.googleapis.com"
  disable_on_destroy = false
}

resource "google_service_account" "github_deployer" {
  project      = var.project_id
  account_id   = "github-deployer"
  display_name = "GitHub Actions deployer (CI/CD)"
}

# Papéis no projeto: gerir serviços Cloud Run, ler logs (taxa de 5xx do gate), invocar.
resource "google_project_iam_member" "deployer" {
  for_each = toset([
    "roles/run.admin",
    "roles/logging.viewer",
    "roles/run.invoker",
  ])
  project = var.project_id
  role    = each.value
  member  = local.sa_member
}

# Agir como a conta de runtime dos serviços (deploy precisa) e cunhar token de identidade
# na própria conta e na scheduler-invoker (gates chamam os endpoints autenticados).
resource "google_service_account_iam_member" "act_as_runtime" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.project_id}@appspot.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = local.sa_member
}

resource "google_service_account_iam_member" "token_creator_self" {
  service_account_id = google_service_account.github_deployer.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.sa_member
}

resource "google_service_account_iam_member" "token_creator_scheduler_invoker" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/scheduler-invoker@${var.project_id}.iam.gserviceaccount.com"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.sa_member
}

# Bucket do gate (lock, ledger) e dos artefatos do modelo.
resource "google_storage_bucket_iam_member" "mlflow_bucket" {
  bucket = "smart-ads-mlflow"
  role   = "roles/storage.objectAdmin"
  member = local.sa_member
}

# Publicar a imagem.
resource "google_artifact_registry_repository_iam_member" "gcr_writer" {
  project    = var.project_id
  location   = "us"
  repository = "gcr.io"
  role       = "roles/artifactregistry.writer"
  member     = local.sa_member
}

# Ler os segredos que o deploy injeta na revisão e que os gates usam.
resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = toset([
    "railway-db-password",
    "ledger-db-password",
    "api-internal-token",
    "hotmart-basic",
    "slack-webhook-url",
    "mlflow-db-password",
  ])
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = local.sa_member
}

# Federação: só o repositório ramonfilho/bringdata pode assumir a conta.
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"
  attribute_condition                = "assertion.repository == '${var.github_owner}/${var.github_repo}'"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "workload_identity_user" {
  service_account_id = google_service_account.github_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.repo_subject
}
