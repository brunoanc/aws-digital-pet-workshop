terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 6.64.0, < 7.0.0" }
  }
}

variable "account_id" {
  type = string
}

variable "partition" {
  type = string
}

variable "workload_region" {
  type = string
}

variable "instance_arn" {
  type = string
}

variable "identity_store_id" {
  type = string
}

variable "permission_set_name" {
  type = string
}

variable "group_name" {
  type = string
}

variable "resource_name" {
  type = string
}

variable "agent_resource_name" {
  type    = string
  default = null
}

variable "model_id" {
  type = string
}

variable "session_hours" {
  type = number
}

variable "assignments_enabled" {
  type = bool
}


locals {
  table_arn    = "arn:${var.partition}:dynamodb:${var.workload_region}:${var.account_id}:table/${var.resource_name}"
  function_arn = "arn:${var.partition}:lambda:${var.workload_region}:${var.account_id}:function:${var.resource_name}"
  log_arn      = "arn:${var.partition}:logs:${var.workload_region}:${var.account_id}:log-group:/aws/lambda/${var.resource_name}"
  model_arn    = "arn:${var.partition}:bedrock:${var.workload_region}::foundation-model/${var.model_id}"
  condition    = { StringEquals = { "aws:RequestedRegion" = var.workload_region } }
  policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "ConsoleDiscovery"
        Effect    = "Allow"
        Resource  = "*"
        Condition = local.condition
        Action    = ["dynamodb:ListTables", "lambda:ListFunctions", "logs:DescribeLogGroups", "bedrock:ListFoundationModels"]
      },
      {
        Sid       = "OwnPetData"
        Effect    = "Allow"
        Resource  = [local.table_arn]
        Condition = local.condition
        Action = [
          "dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
          "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
          "dynamodb:PartiQLSelect", "dynamodb:PartiQLInsert", "dynamodb:PartiQLUpdate", "dynamodb:PartiQLDelete"
        ]
      },
      {
        Sid    = "OwnFunctionCode"
        Effect = "Allow"
        Resource = concat(
          [local.function_arn],
          var.agent_resource_name == null ? [] : ["arn:${var.partition}:lambda:${var.workload_region}:${var.account_id}:function:${var.agent_resource_name}"]
        )
        Condition = local.condition
        Action    = ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionUrlConfig", "lambda:ListFunctionUrlConfigs", "lambda:GetPolicy", "lambda:ListVersionsByFunction", "lambda:InvokeFunction", "lambda:UpdateFunctionCode"]
      },
      {
        Sid    = "OwnLogs"
        Effect = "Allow"
        Resource = concat(
          ["${local.log_arn}:*"],
          var.agent_resource_name == null ? [] : ["arn:${var.partition}:logs:${var.workload_region}:${var.account_id}:log-group:/aws/lambda/${var.agent_resource_name}:*"]
        )
        Condition = local.condition
        Action    = ["logs:DescribeLogStreams", "logs:GetLogEvents", "logs:FilterLogEvents"]
      },
      {
        Sid       = "ApprovedModel"
        Effect    = "Allow"
        Resource  = [local.model_arn]
        Condition = local.condition
        Action    = ["bedrock:GetFoundationModel", "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      }
    ]
  }
}

resource "aws_identitystore_group" "team" {
  identity_store_id = var.identity_store_id
  display_name      = var.group_name
  description       = "Members share one pet while keeping individual sign-in credentials."
}

resource "aws_ssoadmin_permission_set" "team" {
  instance_arn     = var.instance_arn
  name             = var.permission_set_name
  description      = "Allows the guided Console exercises without administrative access."
  session_duration = "PT${var.session_hours}H"
}

resource "aws_ssoadmin_permission_set_inline_policy" "team" {
  instance_arn       = var.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.team.arn
  inline_policy      = jsonencode(local.policy)
}

resource "aws_ssoadmin_account_assignment" "team" {
  count              = var.assignments_enabled ? 1 : 0
  instance_arn       = var.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.team.arn
  principal_id       = aws_identitystore_group.team.group_id
  principal_type     = "GROUP"
  target_id          = var.account_id
  target_type        = "AWS_ACCOUNT"
  depends_on         = [aws_ssoadmin_permission_set_inline_policy.team]
}

output "policy_json" {
  value = jsonencode(local.policy)
}

output "group_id" {
  value = aws_identitystore_group.team.group_id
}

output "permission_set_arn" {
  value = aws_ssoadmin_permission_set.team.arn
}

output "assignment_count" {
  value = length(aws_ssoadmin_account_assignment.team)
}
