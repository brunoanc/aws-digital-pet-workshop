terraform {
  required_version = "~> 1.15.0"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "= 6.64.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.7" }
  }
  backend "s3" {}
}

variable "workload" {
  type = object({
    account_id            = string
    management_account_id = string
    aws_profile           = string
    region                = string
    teams                 = map(string)
    runtime               = string
    memory_mb             = number
    timeout_seconds       = number
    log_retention_days    = number
    tags                  = map(string)
    package_overrides     = optional(map(string), {})
    read_only             = optional(bool, false)
  })
  nullable = false
  validation {
    condition     = alltrue([for team in keys(var.workload.package_overrides) : contains(keys(var.workload.teams), team)])
    error_message = "Package overrides must reference configured teams."
  }
  validation {
    condition = (
      can(regex("^[0-9]{12}$", var.workload.account_id)) &&
      can(regex("^[0-9]{12}$", var.workload.management_account_id)) &&
      var.workload.account_id != var.workload.management_account_id &&
      length(trimspace(var.workload.aws_profile)) > 0 &&
      can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.workload.region))
    )
    error_message = "Specify a member account distinct from management, an explicit AWS profile, and a valid region."
  }
  validation {
    condition = (
      length(var.workload.teams) > 0 && length(var.workload.teams) <= 20 &&
      length(distinct(values(var.workload.teams))) == length(var.workload.teams) &&
      alltrue([for key, name in var.workload.teams : can(regex("^[a-z0-9][a-z0-9-]{0,31}$", key)) && can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{2,53}$", name))])
    )
    error_message = "Configure 1–20 teams with valid IDs and unique resource names of 3–54 characters."
  }
  validation {
    condition = (
      var.workload.runtime == "python3.13" &&
      contains([128, 256, 512], var.workload.memory_mb) &&
      var.workload.timeout_seconds >= 5 && var.workload.timeout_seconds <= 30 && floor(var.workload.timeout_seconds) == var.workload.timeout_seconds &&
      contains([1, 3, 5, 7, 14], var.workload.log_retention_days)
    )
    error_message = "Use python3.13 with 128, 256, or 512 MB of memory, an integer timeout of 5–30 seconds, and log retention of 1, 3, 5, 7, or 14 days."
  }
}

provider "aws" {
  profile             = var.workload.aws_profile
  region              = var.workload.region
  allowed_account_ids = [var.workload.account_id]
  default_tags {
    tags = merge(var.workload.tags, { ManagedBy = "Terraform" })
  }
}

# Explicit sources keep private files and caches out of the deployment package.
data "archive_file" "pet" {
  type        = "zip"
  output_path = "${path.root}/.terraform/pet.zip"
  source {
    filename = "handler.py"
    content  = file("${path.module}/../../lambda/handler.py")
  }
  source {
    filename = "rules.py"
    content  = file("${path.module}/../../lambda/rules.py")
  }
  source {
    filename = "custom_action.py"
    content  = file("${path.module}/../../lambda/custom_action.py")
  }
}

module "pets" {
  source             = "../modules/pet-environment"
  teams              = var.workload.teams
  runtime            = var.workload.runtime
  memory_mb          = var.workload.memory_mb
  timeout_seconds    = var.workload.timeout_seconds
  log_retention_days = var.workload.log_retention_days
  read_only          = var.workload.read_only
  zip_path           = data.archive_file.pet.output_path
  zip_hash           = data.archive_file.pet.output_base64sha256
  package_overrides  = { for team, package in var.workload.package_overrides : team => { path = package, hash = filebase64sha256(package) } }
}

output "inventory" {
  value = { account_id = var.workload.account_id, region = var.workload.region, teams = module.pets.teams }
}
