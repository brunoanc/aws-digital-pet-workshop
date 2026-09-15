terraform {
  required_version = "~> 1.15.0"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "= 6.64.0" }
    archive = { source = "hashicorp/archive", version = "= 2.8.0" }
  }
  backend "s3" {}
}

variable "agent" {
  description = "Deploys an editable agent independently of existing pet resources."
  type = object({
    account_id            = string
    management_account_id = string
    aws_profile           = string
    region                = string
    function_name         = string
    layer_name            = string
    layer_zip_path        = string
    runtime_config_path   = string
    memory_mb             = number
    timeout_seconds       = number
    log_retention_days    = number
    tags                  = map(string)
    builder_source_path   = optional(string, "../../agent_lambda/agent_builder.py")
    function_url_enabled  = optional(bool, false)
  })
  validation {
    condition = (
      can(regex("^[0-9]{12}$", var.agent.account_id)) &&
      can(regex("^[0-9]{12}$", var.agent.management_account_id)) &&
      var.agent.account_id != var.agent.management_account_id &&
      length(trimspace(var.agent.aws_profile)) > 0 &&
      can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.agent.region)) &&
      can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{2,53}$", var.agent.function_name)) &&
      can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$", var.agent.layer_name))
    )
    error_message = "Specify a distinct member account, an explicit profile, a valid region, and valid function and layer names."
  }
  validation {
    condition = (
      contains([512, 1024], var.agent.memory_mb) &&
      var.agent.timeout_seconds >= 30 && var.agent.timeout_seconds <= 150 && floor(var.agent.timeout_seconds) == var.agent.timeout_seconds &&
      contains([1, 3, 5, 7, 14], var.agent.log_retention_days)
    )
    error_message = "Use 512 or 1024 MB, an integer timeout of 30–150 seconds, and log retention of 1, 3, 5, 7, or 14 days."
  }
}

provider "aws" {
  profile             = var.agent.aws_profile
  region              = var.agent.region
  allowed_account_ids = [var.agent.account_id]
  default_tags {
    tags = merge(var.agent.tags, { ManagedBy = "Terraform" })
  }
}

data "aws_partition" "current" {}

locals {
  runtime          = jsondecode(file(var.agent.runtime_config_path))
  prefix           = "arn:${data.aws_partition.current.partition}"
  pet_arn          = "${local.prefix}:lambda:${var.agent.region}:${var.agent.account_id}:function:${local.runtime.function_name}"
  model_arn        = "${local.prefix}:bedrock:${var.agent.region}::foundation-model/${local.runtime.model_id}"
  region_condition = { StringEquals = { "aws:RequestedRegion" = var.agent.region } }
  sources = {
    "agent_lambda/__init__.py"      = "../../agent_lambda/__init__.py"
    "agent_lambda/agent_builder.py" = var.agent.builder_source_path
    "agent_lambda/handler.py"       = "../../agent_lambda/handler.py"
    "agent_lambda/tools.py"         = "../../agent_lambda/tools.py"
    "app/__init__.py"               = "../../app/__init__.py"
    "app/agent.py"                  = "../../app/agent.py"
    "app/backend.py"                = "../../app/backend.py"
    "app/config.py"                 = "../../app/config.py"
    "app/tools.py"                  = "../../app/tools.py"
  }
  source_contents = { for name, source in local.sources : name => file("${path.module}/${source}") }
}

data "archive_file" "agent" {
  type        = "zip"
  output_path = "${path.root}/.terraform/agent-${sha256(jsonencode(local.source_contents))}.zip"
  dynamic "source" {
    for_each = local.source_contents
    content {
      filename = source.key
      content  = source.value
    }
  }
}

resource "aws_lambda_layer_version" "agent" {
  layer_name               = var.agent.layer_name
  description              = "Pinned agent dependencies kept outside the editable source package."
  filename                 = var.agent.layer_zip_path
  source_code_hash         = filebase64sha256(var.agent.layer_zip_path)
  compatible_runtimes      = ["python3.13"]
  compatible_architectures = ["x86_64"]
}

resource "aws_cloudwatch_log_group" "agent" {
  name              = "/aws/lambda/${var.agent.function_name}"
  retention_in_days = var.agent.log_retention_days
}

resource "aws_iam_role" "agent" {
  name = "${var.agent.function_name}-execution"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "agent" {
  name = "own-pet-and-model"
  role = aws_iam_role.agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = ["lambda:GetFunctionConfiguration", "lambda:InvokeFunction"]
        Resource  = [local.pet_arn]
        Condition = local.region_condition
      },
      {
        Effect    = "Allow"
        Action    = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource  = [local.model_arn]
        Condition = local.region_condition
      },
      {
        Effect    = "Allow"
        Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource  = ["${aws_cloudwatch_log_group.agent.arn}:*"]
        Condition = local.region_condition
      }
    ]
  })
}

resource "aws_lambda_function" "agent" {
  function_name                  = var.agent.function_name
  description                    = "Team-owned agent assembly exercise with authenticated invocation."
  role                           = aws_iam_role.agent.arn
  runtime                        = "python3.13"
  handler                        = "agent_lambda.handler.lambda_handler"
  filename                       = data.archive_file.agent.output_path
  source_code_hash               = data.archive_file.agent.output_base64sha256
  layers                         = [aws_lambda_layer_version.agent.arn]
  architectures                  = ["x86_64"]
  memory_size                    = var.agent.memory_mb
  timeout                        = var.agent.timeout_seconds
  reserved_concurrent_executions = -1
  environment {
    variables = { APP_SETTINGS = jsonencode(local.runtime) }
  }

  lifecycle {
    precondition {
      condition = (
        local.runtime.account_id == var.agent.account_id && local.runtime.region == var.agent.region &&
        local.runtime.function_name != var.agent.function_name &&
        can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{2,53}$", local.runtime.function_name)) &&
        can(regex("^amazon\\.nova-[a-z0-9-]+-v[0-9]+:[0-9]+$", local.runtime.model_id)) &&
        local.runtime.timeout_seconds + 10 <= var.agent.timeout_seconds
      )
      error_message = "Runtime settings must match the deployment account and region, target a distinct valid pet, use a direct Nova model, and leave ten seconds for cleanup."
    }
  }
  depends_on = [aws_iam_role_policy.agent, aws_cloudwatch_log_group.agent]
}

resource "aws_lambda_function_url" "agent" {
  count              = var.agent.function_url_enabled ? 1 : 0
  function_name      = aws_lambda_function.agent.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "BUFFERED"
}

output "inventory" {
  value = {
    function_name = aws_lambda_function.agent.function_name
    role_arn      = aws_iam_role.agent.arn
    layer_arn     = aws_lambda_layer_version.agent.arn
    log_group     = aws_cloudwatch_log_group.agent.name
    pet_function  = local.runtime.function_name
    team_id       = local.runtime.team_id
    function_url  = try(aws_lambda_function_url.agent[0].function_url, null)
  }
}
