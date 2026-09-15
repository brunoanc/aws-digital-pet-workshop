terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 6.64.0, < 7.0.0" }
  }
}

variable "teams" {
  type = map(string)
}

variable "zip_path" {
  type = string
}

variable "zip_hash" {
  type = string
}

variable "package_overrides" {
  type    = map(object({ path = string, hash = string }))
  default = {}
}

variable "read_only" {
  description = "Blocks pet state changes for capacity rehearsals."
  type        = bool
  default     = false
  nullable    = false
}

variable "runtime" {
  type = string
}

variable "memory_mb" {
  type = number
}

variable "timeout_seconds" {
  type = number
}

variable "log_retention_days" {
  type = number
}


resource "aws_dynamodb_table" "pet" {
  for_each                    = var.teams
  name                        = each.value
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pet_id"
  deletion_protection_enabled = false
  attribute {
    name = "pet_id"
    type = "S"
  }
}

resource "aws_cloudwatch_log_group" "pet" {
  for_each          = var.teams
  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "pet" {
  for_each = var.teams
  name     = "${each.value}-execution"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "pet" {
  for_each = var.teams
  name     = "pet-data-and-logs"
  role     = aws_iam_role.pet[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      # Transaction authorization uses the underlying item actions.
      {
        Effect   = "Allow"
        Action   = var.read_only ? ["dynamodb:GetItem"] : ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = aws_dynamodb_table.pet[each.key].arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.pet[each.key].arn}:*"
      }
      ], var.read_only ? [{
        Effect    = "Deny"
        NotAction = "dynamodb:GetItem"
        Resource  = aws_dynamodb_table.pet[each.key].arn
    }] : [])
  })
}

resource "aws_lambda_function" "pet" {
  for_each                       = var.teams
  function_name                  = each.value
  role                           = aws_iam_role.pet[each.key].arn
  runtime                        = var.runtime
  handler                        = "handler.lambda_handler"
  filename                       = try(var.package_overrides[each.key].path, var.zip_path)
  source_code_hash               = try(var.package_overrides[each.key].hash, var.zip_hash)
  architectures                  = ["x86_64"]
  memory_size                    = var.memory_mb
  timeout                        = var.timeout_seconds
  reserved_concurrent_executions = -1
  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.pet[each.key].name
      TEAM_ID    = each.key
    }
  }
  depends_on = [aws_iam_role_policy.pet, aws_cloudwatch_log_group.pet]
}

output "teams" {
  value = { for key, name in var.teams : key => {
    table_name    = aws_dynamodb_table.pet[key].name
    function_name = aws_lambda_function.pet[key].function_name
    log_group     = aws_cloudwatch_log_group.pet[key].name
  } }
}
