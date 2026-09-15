mock_provider "aws" {}

override_resource {
  target = aws_cognito_identity_provider.workshop
  values = { provider_name = "IdentityCenter" }
}

variables {
  auth = {
    account_id            = "111122223333"
    management_account_id = "444455556666"
    aws_profile           = "test-no-aws"
    region                = "us-east-1"
    name                  = "test-workshop"
    domain_prefix         = "test-workshop"
    app_origin            = "https://workshop.example.com"
    tags                  = {}
  }
}

run "federation_only" {
  command = plan
  variables {
    auth = {
      account_id            = "111122223333"
      management_account_id = "444455556666"
      aws_profile           = "test-no-aws"
      region                = "us-east-1"
      name                  = "test-workshop"
      domain_prefix         = "test-workshop"
      app_origin            = "https://workshop.example.com"
      tags                  = {}
      saml_metadata_url     = "https://idp.example.com/metadata"
      max_session_seconds   = 14400
    }
  }
  assert {
    condition = (
      aws_cognito_user_pool_client.workshop[0].supported_identity_providers == toset(["IdentityCenter"]) &&
      aws_cognito_user_pool_client.workshop[0].allowed_oauth_flows == toset(["code"]) &&
      aws_cognito_user_pool_client.workshop[0].generate_secret &&
      aws_cognito_user_pool_client.workshop[0].explicit_auth_flows == toset(["ALLOW_REFRESH_TOKEN_AUTH"]) &&
      aws_cognito_user_pool_client.workshop[0].callback_urls == toset(["https://workshop.example.com/oauth2callback"])
    )
    error_message = "The confidential client must only permit federation and the configured authorization-code callback."
  }
  assert {
    condition = (
      aws_cognito_user_pool_client.workshop[0].access_token_validity == 14400 &&
      aws_cognito_user_pool_client.workshop[0].id_token_validity == 14400 &&
      aws_cognito_user_pool_client.workshop[0].token_validity_units[0].access_token == "seconds" &&
      aws_cognito_user_pool_client.workshop[0].token_validity_units[0].id_token == "seconds"
    )
    error_message = "Both tokens must use the configured session duration in seconds."
  }
}

run "closed_foundation" {
  command = plan
  assert {
    condition = (
      aws_cognito_user_pool.workshop.admin_create_user_config[0].allow_admin_create_user_only &&
      aws_cognito_user_pool.workshop.user_pool_tier == "LITE" &&
      aws_cognito_user_pool_domain.workshop.managed_login_version == 1
    )
    error_message = "The foundation must disable public registration and avoid premium login features."
  }
  assert {
    condition     = output.federation_setup.callback_url == "https://workshop.example.com/oauth2callback"
    error_message = "The callback must remain bound to the configured application origin."
  }
}
