mock_provider "aws" {}
mock_provider "archive" {}

variables {
  workload = {
    account_id  = "444455556666", management_account_id = "111122223333"
    aws_profile = "test-no-aws", region = "us-east-1"
    teams       = { team-01 = "dp-rehearsal-team-01", team-02 = "dp-rehearsal-team-02" }
    runtime     = "python3.13", memory_mb = 128, timeout_seconds = 10, log_retention_days = 7
    tags        = {}
  }
}

run "two_team_inventory" {
  command = plan
  assert {
    condition = (
      length(output.inventory.teams) == 2 &&
      output.inventory.account_id == "444455556666" &&
      output.inventory.teams["team-01"].table_name == "dp-rehearsal-team-01" &&
      output.inventory.teams["team-02"].function_name == "dp-rehearsal-team-02"
    )
    error_message = "The inventory must reference separate resources for both teams in the member account."
  }
}
