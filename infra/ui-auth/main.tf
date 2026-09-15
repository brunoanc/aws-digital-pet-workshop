terraform {
  required_version = "~> 1.15.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "= 6.64.0" }
  }
  backend "s3" {}
}

variable "auth" {
  description = "Sets up federation separately from app hosting."
  type = object({
    account_id            = string
    management_account_id = string
    aws_profile           = string
    region                = string
    name                  = string
    domain_prefix         = string
    app_origin            = string
    tags                  = map(string)
    saml_metadata_url     = optional(string)
    saml_provider_name    = optional(string, "IdentityCenter")
    max_session_seconds   = optional(number, 3600)
  })
  validation {
    condition = (
      var.auth.max_session_seconds >= 300 && var.auth.max_session_seconds <= 28800 &&
      floor(var.auth.max_session_seconds) == var.auth.max_session_seconds
    )
    error_message = "Use a session duration between 300 and 28800 whole seconds."
  }
  validation {
    condition = (
      var.auth.saml_metadata_url == null ? true :
      can(regex("^https://[A-Za-z0-9.-]+/[^?#]+$", var.auth.saml_metadata_url))
    )
    error_message = "Use an HTTPS metadata endpoint without query parameters or fragments."
  }
  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9]{0,31}$", var.auth.saml_provider_name)) && var.auth.saml_provider_name != "COGNITO"
    error_message = "Choose a distinct alphanumeric federation provider name."
  }
  validation {
    condition = (
      can(regex("^[0-9]{12}$", var.auth.account_id)) &&
      can(regex("^[0-9]{12}$", var.auth.management_account_id)) &&
      var.auth.account_id != var.auth.management_account_id &&
      length(trimspace(var.auth.aws_profile)) > 0 &&
      can(regex("^us-[a-z]+-[0-9]+$", var.auth.region))
    )
    error_message = "Use a member account and an explicit profile in a supported US commercial region."
  }
  validation {
    condition = (
      can(regex("^[A-Za-z0-9_-]{3,64}$", var.auth.name)) &&
      can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.auth.domain_prefix)) &&
      can(regex("^https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?\\.[a-z]{2,}$", var.auth.app_origin))
    )
    error_message = "Provide valid resource names and an HTTPS application origin without a path."
  }
}

provider "aws" {
  profile             = var.auth.aws_profile
  region              = var.auth.region
  allowed_account_ids = [var.auth.account_id]
  default_tags {
    tags = merge(var.auth.tags, { ManagedBy = "Terraform" })
  }
}

resource "aws_cognito_user_pool" "workshop" {
  name                = var.auth.name
  user_pool_tier      = "LITE"
  deletion_protection = "INACTIVE"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  username_configuration {
    case_sensitive = false
  }
}

resource "aws_cognito_user_pool_domain" "workshop" {
  domain                = var.auth.domain_prefix
  user_pool_id          = aws_cognito_user_pool.workshop.id
  managed_login_version = 1
}

resource "aws_cognito_identity_provider" "workshop" {
  count         = var.auth.saml_metadata_url == null ? 0 : 1
  user_pool_id  = aws_cognito_user_pool.workshop.id
  provider_name = var.auth.saml_provider_name
  provider_type = "SAML"
  provider_details = {
    MetadataURL = var.auth.saml_metadata_url
    IDPInit     = "false"
    IDPSignout  = "false"
  }
  attribute_mapping = { email = "email" }

  lifecycle {
    # Cognito derives these fields from the provider metadata.
    ignore_changes = [
      provider_details["ActiveEncryptionCertificate"],
      provider_details["SLORedirectBindingURI"],
      provider_details["SSORedirectBindingURI"],
    ]
  }
}

resource "aws_cognito_user_pool_client" "workshop" {
  count                                = var.auth.saml_metadata_url == null ? 0 : 1
  name                                 = "${var.auth.name}-web"
  user_pool_id                         = aws_cognito_user_pool.workshop.id
  generate_secret                      = true
  supported_identity_providers         = [aws_cognito_identity_provider.workshop[0].provider_name]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  callback_urls                        = ["${var.auth.app_origin}/oauth2callback"]
  logout_urls                          = [var.auth.app_origin]
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  read_attributes                      = ["email", "email_verified", "sub"]
  write_attributes                     = ["email"]
  access_token_validity                = var.auth.max_session_seconds
  id_token_validity                    = var.auth.max_session_seconds
  refresh_token_validity               = 8
  token_validity_units {
    access_token  = "seconds"
    id_token      = "seconds"
    refresh_token = "hours"
  }
}

output "oidc_setup" {
  description = "Identifies the federated client without exposing its secret."
  value = var.auth.saml_metadata_url == null ? null : {
    client_id           = aws_cognito_user_pool_client.workshop[0].id
    provider_name       = var.auth.saml_provider_name
    server_metadata_url = "https://cognito-idp.${var.auth.region}.amazonaws.com/${aws_cognito_user_pool.workshop.id}/.well-known/openid-configuration"
    redirect_uri        = "${var.auth.app_origin}/oauth2callback"
  }
}

output "federation_setup" {
  description = "Supplies the manual Identity Center application settings without credentials."
  value = {
    user_pool_id = aws_cognito_user_pool.workshop.id
    audience     = "urn:amazon:cognito:sp:${aws_cognito_user_pool.workshop.id}"
    acs_url      = "https://${aws_cognito_user_pool_domain.workshop.domain}.auth.${var.auth.region}.amazoncognito.com/saml2/idpresponse"
    app_origin   = var.auth.app_origin
    callback_url = "${var.auth.app_origin}/oauth2callback"
  }
}
