variable "login_secret" {
  description = "Creates optional secret storage without saving credentials in Terraform."
  type = object({
    name                    = string
    recovery_window_in_days = optional(number, 7)
  })
  default = null
  validation {
    condition = var.login_secret == null ? true : (
      can(regex("^[A-Za-z0-9/_+=.@-]{3,128}$", var.login_secret.name)) &&
      var.login_secret.recovery_window_in_days >= 7 &&
      var.login_secret.recovery_window_in_days <= 30 &&
      floor(var.login_secret.recovery_window_in_days) == var.login_secret.recovery_window_in_days
    )
    error_message = "Specify a valid secret name and an integer recovery window of 7–30 days."
  }
}

resource "aws_secretsmanager_secret" "login" {
  count                   = var.login_secret == null ? 0 : 1
  name                    = var.login_secret.name
  description             = "Stores OIDC credentials and cookie signing material for the shared login."
  recovery_window_in_days = var.login_secret.recovery_window_in_days
}

resource "aws_iam_role_policy" "login" {
  count = var.login_secret == null ? 0 : 1
  name  = "${var.host.name}-login-read"
  role  = aws_iam_role.host.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.login[0].arn
    }]
  })
}

output "login_secret_arn" {
  description = "Identifies the login secret without exposing its value."
  value       = var.login_secret == null ? null : aws_secretsmanager_secret.login[0].arn
}
