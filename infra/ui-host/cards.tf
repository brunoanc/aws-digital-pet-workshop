variable "pet_cards" {
  description = "Links each team to its existing pet table and optional agent."
  type        = map(object({ table_name = string, agent_function_name = optional(string) }))
  default     = {}
  validation {
    condition = alltrue([
      for team, target in var.pet_cards :
      can(regex("^team-[0-9]{2}$", team)) && can(regex("^[A-Za-z0-9_.-]{3,255}$", target.table_name)) &&
      (target.agent_function_name == null ? true : can(regex("^[A-Za-z0-9_-]{3,64}$", target.agent_function_name)))
    ])
    error_message = "Use valid team IDs, table names, and optional agent function names."
  }
}

resource "aws_iam_role_policy" "agent" {
  for_each = { for team, target in var.pet_cards : team => target if target.agent_function_name != null }
  name     = "team-agent-url"
  role     = aws_iam_role.card[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:GetFunctionConfiguration", "lambda:GetFunctionUrlConfig"]
        Resource = "arn:aws:lambda:${var.host.region}:${var.host.account_id}:function:${each.value.agent_function_name}"
      },
      {
        Effect    = "Allow"
        Action    = "lambda:InvokeFunctionUrl"
        Resource  = "arn:aws:lambda:${var.host.region}:${var.host.account_id}:function:${each.value.agent_function_name}"
        Condition = { StringEquals = { "lambda:FunctionUrlAuthType" = "AWS_IAM" } }
      },
      {
        Effect    = "Allow"
        Action    = "lambda:InvokeFunction"
        Resource  = "arn:aws:lambda:${var.host.region}:${var.host.account_id}:function:${each.value.agent_function_name}"
        Condition = { Bool = { "lambda:InvokedViaFunctionUrl" = "true" } }
      },
      {
        Effect   = "Allow"
        Action   = "dynamodb:GetItem"
        Resource = "arn:aws:dynamodb:${var.host.region}:${var.host.account_id}:table/${each.value.table_name}"
        Condition = {
          "ForAllValues:StringLike" = { "dynamodb:LeadingKeys" = ["_op#*"] }
          "Null"                    = { "dynamodb:LeadingKeys" = "false" }
        }
      }
    ]
  })
}

resource "aws_iam_role" "card" {
  for_each = var.pet_cards
  name     = "${var.host.name}-${each.key}-card"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { AWS = aws_iam_role.host.arn }
    }]
  })
}

resource "aws_iam_role_policy" "card" {
  for_each = var.pet_cards
  name     = "pet-item-read"
  role     = aws_iam_role.card[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "dynamodb:GetItem"
      Resource = "arn:aws:dynamodb:${var.host.region}:${var.host.account_id}:table/${each.value.table_name}"
      Condition = {
        "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = [each.key] }
        "Null"                      = { "dynamodb:LeadingKeys" = "false" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "assume_card" {
  count = length(var.pet_cards) == 0 ? 0 : 1
  name  = "${var.host.name}-assume-card"
  role  = aws_iam_role.host.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sts:AssumeRole"
      Resource = [for role in aws_iam_role.card : role.arn]
    }]
  })
}

output "pet_card_config" {
  description = "Provides server-owned destinations without temporary credentials."
  value = {
    account_id = var.host.account_id
    region     = var.host.region
    teams = { for team, target in var.pet_cards : team => {
      role_arn   = aws_iam_role.card[team].arn
      table_name = target.table_name
    } }
  }
}
