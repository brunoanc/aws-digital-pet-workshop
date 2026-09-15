mock_provider "aws" {
  mock_data "aws_partition" { defaults = { partition = "aws" } }
}

override_resource {
  override_during = plan
  target          = aws_cloudwatch_log_group.agent
  values          = { arn = "arn:aws:logs:us-east-1:111122223333:log-group:/aws/lambda/dp-rehearsal-team-01-agent" }
}

variables {
  agent = {
    account_id            = "111122223333"
    management_account_id = "444455556666"
    aws_profile           = "test-no-aws"
    region                = "us-east-1"
    function_name         = "dp-rehearsal-team-01-agent"
    layer_name            = "test-dependencies"
    layer_zip_path        = "../../agent_lambda/layer/requirements.in"
    runtime_config_path   = "../../scripts/config_defaults/app.json"
    memory_mb             = 512
    timeout_seconds       = 90
    log_retention_days    = 7
    tags                  = {}
    function_url_enabled  = true
  }
}

run "isolated_agent" {
  command = plan
  assert {
    condition     = aws_lambda_function_url.agent[0].authorization_type == "AWS_IAM" && aws_lambda_function_url.agent[0].invoke_mode == "BUFFERED"
    error_message = "The endpoint must require IAM authentication and buffered responses."
  }
  assert {
    condition = (
      aws_lambda_function.agent.handler == "agent_lambda.handler.lambda_handler" &&
      aws_lambda_function.agent.runtime == "python3.13" &&
      aws_lambda_function.agent.timeout == 90 &&
      !jsondecode(aws_lambda_function.agent.environment[0].variables.APP_SETTINGS).allow_mutations
    )
    error_message = "The starter must use the intended handler and begin without mutation permission."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.agent.policy).Statement[0].Resource == ["arn:aws:lambda:us-east-1:111122223333:function:dp-rehearsal-team-01"] &&
      length(jsondecode(aws_iam_role_policy.agent.policy).Statement) == 3 &&
      !strcontains(aws_iam_role_policy.agent.policy, "dynamodb:") &&
      length(local.sources) == 9 && contains(keys(local.sources), "agent_lambda/tools.py") && !contains(keys(local.sources), "app/ui.py")
    )
    error_message = "The role must target its pet without DynamoDB access while the ZIP excludes the user interface."
  }
}
