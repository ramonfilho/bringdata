# Infraestrutura do CI/CD como código.
#
# O que está aqui é o que o scripts/bootstrap_identidade_ci.sh e as chamadas de API de
# 14/09/2026 criaram na mão: a identidade que o GitHub Actions assume no GCP (conta de
# serviço, federação OIDC, papéis mínimos, acesso a segredos) e as configurações do
# repositório que sustentam a pipeline (environments com reviewer, variáveis, proteção
# da main). O código é a descrição; os blocos em imports.tf adotam o que já existe, então
# o primeiro `terraform apply` não cria nem muda nada, só grava o estado.
#
# Fora daqui, de propósito: os serviços Cloud Run, os jobs e o Cloud Scheduler (nascem
# do deploy e dos scripts de cada job), os segredos em si (só o acesso a eles), e as
# chaves de segurança do repositório (secret scanning, Dependabot), que o provider do
# GitHub só gerencia junto com o recurso inteiro do repositório.
#
# Uso (ver README.md nesta pasta):
#   export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
#   export GITHUB_TOKEN=$(gh auth token)
#   terraform init && terraform plan

terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }

  # Estado no bucket do projeto, prefixo próprio. O bucket já existe (artefatos do MLflow).
  backend "gcs" {
    bucket = "smart-ads-mlflow"
    prefix = "terraform/ci-cd"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "github" {
  owner = var.github_owner
}

variable "project_id" {
  type    = string
  default = "smart-ads-451319"
}

variable "project_number" {
  type    = string
  default = "12955519745"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "github_owner" {
  type    = string
  default = "ramonfilho"
}

variable "github_repo" {
  type    = string
  default = "bringdata"
}

locals {
  sa_email     = "github-deployer@${var.project_id}.iam.gserviceaccount.com"
  sa_member    = "serviceAccount:${local.sa_email}"
  pool_name    = "projects/${var.project_number}/locations/global/workloadIdentityPools/github"
  repo_subject = "principalSet://iam.googleapis.com/${local.pool_name}/attribute.repository/${var.github_owner}/${var.github_repo}"
}
