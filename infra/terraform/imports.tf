# Adoção do que já existe. Com estes blocos, o primeiro `terraform plan` deve mostrar
# "N to import, 0 to add, 0 to change, 0 to destroy". Depois do primeiro apply os
# blocos podem ser removidos; ficam versionados como registro de origem.

import {
  to = google_project_service.sts
  id = "smart-ads-451319/sts.googleapis.com"
}

import {
  to = google_service_account.github_deployer
  id = "projects/smart-ads-451319/serviceAccounts/github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_project_iam_member.deployer["roles/run.admin"]
  id = "smart-ads-451319 roles/run.admin serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_project_iam_member.deployer["roles/logging.viewer"]
  id = "smart-ads-451319 roles/logging.viewer serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_project_iam_member.deployer["roles/run.invoker"]
  id = "smart-ads-451319 roles/run.invoker serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_service_account_iam_member.act_as_runtime
  id = "projects/smart-ads-451319/serviceAccounts/smart-ads-451319@appspot.gserviceaccount.com roles/iam.serviceAccountUser serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_service_account_iam_member.token_creator_self
  id = "projects/smart-ads-451319/serviceAccounts/github-deployer@smart-ads-451319.iam.gserviceaccount.com roles/iam.serviceAccountTokenCreator serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_service_account_iam_member.token_creator_scheduler_invoker
  id = "projects/smart-ads-451319/serviceAccounts/scheduler-invoker@smart-ads-451319.iam.gserviceaccount.com roles/iam.serviceAccountTokenCreator serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_storage_bucket_iam_member.mlflow_bucket
  id = "b/smart-ads-mlflow roles/storage.objectAdmin serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_artifact_registry_repository_iam_member.gcr_writer
  id = "projects/smart-ads-451319/locations/us/repositories/gcr.io roles/artifactregistry.writer serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret_iam_member.accessor["railway-db-password"]
  id = "projects/smart-ads-451319/secrets/railway-db-password roles/secretmanager.secretAccessor serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret_iam_member.accessor["ledger-db-password"]
  id = "projects/smart-ads-451319/secrets/ledger-db-password roles/secretmanager.secretAccessor serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret_iam_member.accessor["api-internal-token"]
  id = "projects/smart-ads-451319/secrets/api-internal-token roles/secretmanager.secretAccessor serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret_iam_member.accessor["hotmart-basic"]
  id = "projects/smart-ads-451319/secrets/hotmart-basic roles/secretmanager.secretAccessor serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret_iam_member.accessor["slack-webhook-url"]
  id = "projects/smart-ads-451319/secrets/slack-webhook-url roles/secretmanager.secretAccessor serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret_iam_member.accessor["mlflow-db-password"]
  id = "projects/smart-ads-451319/secrets/mlflow-db-password roles/secretmanager.secretAccessor serviceAccount:github-deployer@smart-ads-451319.iam.gserviceaccount.com"
}

import {
  to = google_iam_workload_identity_pool.github
  id = "projects/smart-ads-451319/locations/global/workloadIdentityPools/github"
}

import {
  to = google_iam_workload_identity_pool_provider.github
  id = "projects/smart-ads-451319/locations/global/workloadIdentityPools/github/providers/github"
}

import {
  to = google_service_account_iam_member.workload_identity_user
  id = "projects/smart-ads-451319/serviceAccounts/github-deployer@smart-ads-451319.iam.gserviceaccount.com roles/iam.workloadIdentityUser principalSet://iam.googleapis.com/projects/12955519745/locations/global/workloadIdentityPools/github/attribute.repository/ramonfilho/bringdata"
}

import {
  to = github_repository_environment.stage["canary-10"]
  id = "bringdata:canary-10"
}

import {
  to = github_repository_environment.stage["canary-50"]
  id = "bringdata:canary-50"
}

import {
  to = github_repository_environment.stage["production"]
  id = "bringdata:production"
}

import {
  to = github_actions_variable.vars["GCP_DEPLOYER_SA"]
  id = "bringdata:GCP_DEPLOYER_SA"
}

import {
  to = github_actions_variable.vars["GCP_WORKLOAD_IDENTITY_PROVIDER"]
  id = "bringdata:GCP_WORKLOAD_IDENTITY_PROVIDER"
}

import {
  to = github_actions_variable.vars["PROMOTION_ENABLED"]
  id = "bringdata:PROMOTION_ENABLED"
}

import {
  to = github_branch_protection.main
  id = "bringdata:main"
}
