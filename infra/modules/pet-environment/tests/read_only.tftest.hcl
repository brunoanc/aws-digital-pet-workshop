mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::444455556666:role/dp-capacity-team-81-execution"
    }
  }
  mock_resource "aws_dynamodb_table" {
    defaults = {
      arn = "arn:aws:dynamodb:us-east-1:444455556666:table/dp-capacity-team-81"
    }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-1:444455556666:log-group:/aws/lambda/dp-capacity-team-81"
    }
  }
}

variables {
  teams              = { team-81 = "dp-capacity-team-81" }
  zip_path           = "unused.zip"
  zip_hash           = "unused"
  runtime            = "python3.13"
  memory_mb          = 128
  timeout_seconds    = 30
  log_retention_days = 1
}

run "default_keeps_care_permissions" {
  command = apply

  assert {
    condition     = jsondecode(aws_iam_role_policy.pet["team-81"].policy).Statement[0].Action == ["dynamodb:GetItem", "dynamodb:PutItem"]
    error_message = "Default permissions must preserve pet care."
  }
  assert {
    condition     = length(jsondecode(aws_iam_role_policy.pet["team-81"].policy).Statement) == 2
    error_message = "Default permissions must not add a read-only deny."
  }
}

run "capacity_blocks_mutations" {
  command = apply
  variables {
    read_only = true
  }

  assert {
    condition     = jsondecode(aws_iam_role_policy.pet["team-81"].policy).Statement[0].Action == ["dynamodb:GetItem"]
    error_message = "Capacity roles must allow only pet reads."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.pet["team-81"].policy).Statement[2].Effect == "Deny" &&
      jsondecode(aws_iam_role_policy.pet["team-81"].policy).Statement[2].NotAction == "dynamodb:GetItem" &&
      jsondecode(aws_iam_role_policy.pet["team-81"].policy).Statement[2].Resource == aws_dynamodb_table.pet["team-81"].arn
    )
    error_message = "Capacity roles must deny other actions on their pet table."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.pet["team-81"].policy).Statement[1].Action == ["logs:CreateLogStream", "logs:PutLogEvents"]
    error_message = "Capacity roles must retain logging permissions."
  }
}
