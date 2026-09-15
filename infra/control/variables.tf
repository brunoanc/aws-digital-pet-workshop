variable "management_account_id" {
  description = "Account that owns billing and organization-wide access controls."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.management_account_id))
    error_message = "Specify a 12-digit account ID."
  }
}

variable "aws_profile" {
  description = "Administrative credentials configured separately from backend access."
  type        = string
  nullable    = false
  validation {
    condition     = length(trimspace(var.aws_profile)) > 0
    error_message = "Specify an explicit AWS profile."
  }
}

variable "region" {
  description = "Must match the IAM Identity Center home region when participant access is enabled."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.region))
    error_message = "Specify a valid AWS region."
  }
}

variable "budget" {
  description = "Set import_existing to adopt a matching budget without creating a duplicate."
  type = object({
    name              = string
    amount_usd        = number
    alert_amounts_usd = set(number)
    email_addresses   = set(string)
    import_existing   = bool
    start_utc         = optional(string)
    end_utc           = optional(string)
    tags              = optional(map(string), {})
  })
  nullable = false
  validation {
    condition     = length(trimspace(var.budget.name)) > 0 && length(var.budget.name) <= 100
    error_message = "The budget name must contain 1–100 characters."
  }
  validation {
    condition     = var.budget.amount_usd > 0
    error_message = "The budget amount must be greater than zero."
  }
  validation {
    condition = (
      length(var.budget.alert_amounts_usd) >= 1 && length(var.budget.alert_amounts_usd) <= 5 &&
      alltrue([for amount in var.budget.alert_amounts_usd : amount > 0 && amount <= var.budget.amount_usd])
    )
    error_message = "Configure 1–5 unique positive thresholds that do not exceed the budget."
  }
  validation {
    condition = (
      length(var.budget.email_addresses) >= 1 && length(var.budget.email_addresses) <= 10 &&
      alltrue([for address in var.budget.email_addresses : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", address))])
    )
    error_message = "Specify 1–10 valid email addresses."
  }
  validation {
    condition = alltrue([
      for date in [var.budget.start_utc, var.budget.end_utc] :
      date == null ? true : can(formatdate("YYYY-MM-DD", "${replace(date, "_", "T")}:00Z"))
    ])
    error_message = "Optional dates must use UTC in YYYY-MM-DD_hh:mm format."
  }
}
