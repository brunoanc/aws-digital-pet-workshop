provider "aws" {
  profile             = var.aws_profile
  region              = var.region
  allowed_account_ids = [var.management_account_id]
  # Omit default_tags to preserve existing budget tags during import.
}

resource "aws_budgets_budget" "workshop" {
  account_id        = var.management_account_id
  name              = var.budget.name
  budget_type       = "COST"
  time_unit         = "MONTHLY"
  limit_unit        = "USD"
  limit_amount      = tostring(var.budget.amount_usd)
  time_period_start = var.budget.start_utc
  time_period_end   = var.budget.end_utc
  tags              = var.budget.tags

  # Credits and refunds must not mask workshop spending.
  cost_types {
    include_tax                = true
    include_subscription       = true
    include_refund             = false
    include_credit             = false
    include_upfront            = true
    include_recurring          = true
    include_other_subscription = true
    include_support            = true
    include_discount           = true
    use_amortized              = false
    use_blended                = false
  }

  dynamic "notification" {
    for_each = { for amount in var.budget.alert_amounts_usd : tostring(amount) => amount }
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.budget.email_addresses
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

import {
  for_each = var.budget.import_existing ? { workshop = var.budget.name } : {}
  to       = aws_budgets_budget.workshop
  id       = "${var.management_account_id}:${each.value}"
}

output "budget_id" {
  description = "Budget reference for billing checks after the event."
  value       = aws_budgets_budget.workshop.id
}
