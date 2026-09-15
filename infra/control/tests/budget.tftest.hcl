mock_provider "aws" {}

variables {
  management_account_id = "111122223333"
  aws_profile           = "test-no-aws"
  region                = "us-east-1"
  budget = {
    name              = "test-mascotas"
    amount_usd        = 50
    alert_amounts_usd = [10, 20, 30]
    email_addresses   = ["organizador@example.com"]
    import_existing   = false
  }
}

run "consolidated_budget" {
  command = plan
  assert {
    condition     = tonumber(aws_budgets_budget.workshop.limit_amount) == 50 && aws_budgets_budget.workshop.limit_unit == "USD" && aws_budgets_budget.workshop.time_unit == "MONTHLY"
    error_message = "This test case requires a monthly budget of USD 50."
  }
  assert {
    condition     = length(aws_budgets_budget.workshop.cost_filter) == 0
    error_message = "The budget must cover all accounts without filters."
  }
  assert {
    condition = (
      one(aws_budgets_budget.workshop.cost_types).include_tax &&
      !one(aws_budgets_budget.workshop.cost_types).include_credit &&
      !one(aws_budgets_budget.workshop.cost_types).include_refund
    )
    error_message = "Budget costs must include taxes without deducting credits or refunds."
  }
  assert {
    condition = (
      toset([for n in aws_budgets_budget.workshop.notification : n.threshold]) == toset([10, 20, 30]) &&
      alltrue([for n in aws_budgets_budget.workshop.notification :
        n.notification_type == "ACTUAL" && n.threshold_type == "ABSOLUTE_VALUE" &&
        n.comparison_operator == "GREATER_THAN" && n.subscriber_email_addresses == toset(["organizador@example.com"])
      ])
    )
    error_message = "Alerts must preserve their thresholds, type, and recipients."
  }
}

run "reject_invalid_budget" {
  command = plan
  variables {
    budget = {
      name              = "test-invalid"
      amount_usd        = 50
      alert_amounts_usd = [60]
      email_addresses   = ["organizador@example.com"]
      import_existing   = false
    }
  }
  expect_failures = [var.budget]
}

run "reject_invalid_email" {
  command = plan
  variables {
    budget = {
      name              = "test-invalid"
      amount_usd        = 50
      alert_amounts_usd = [10]
      email_addresses   = ["no-es-correo"]
      import_existing   = false
    }
  }
  expect_failures = [var.budget]
}
