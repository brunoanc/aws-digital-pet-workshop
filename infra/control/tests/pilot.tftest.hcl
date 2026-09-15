mock_provider "aws" {}

variables {
  management_account_id = "111122223333"
  aws_profile           = "test-no-aws"
  region                = "us-east-1"
  budget = {
    name            = "test", amount_usd = 50, alert_amounts_usd = [10]
    email_addresses = ["test@example.com"], import_existing = false
  }
  participant_access = {
    instance_arn      = "arn:aws:sso:::instance/ssoins-1111222233334444"
    identity_store_id = "d-1111222233", session_hours = 4
    environments = {
      live = {
        account_id            = "444455556666", workload_region = "us-east-1", model_id = "amazon.nova-lite-v1:0"
        emergency_policy_name = "DP-Live-Emergency", emergency_deny = false
        assignments_enabled   = true, assignment_teams = ["team-00"]
        teams = {
          team-00 = { permission_set_name = "DP-Live-team-00", group_name = "DP-Live-team-00", resource_name = "dp-live-team-00" }
          team-01 = { permission_set_name = "DP-Live-team-01", group_name = "DP-Live-team-01", resource_name = "dp-live-team-01" }
        }
      }
    }
  }
}

run "pilot_only" {
  command = plan
  assert {
    condition     = module.team_access["live/team-00"].assignment_count == 1 && module.team_access["live/team-01"].assignment_count == 0
    error_message = "Only the selected pilot team may receive an account assignment."
  }
}

run "global_switch_closes_pilot" {
  command = plan
  variables {
    participant_access = {
      instance_arn      = "arn:aws:sso:::instance/ssoins-1111222233334444"
      identity_store_id = "d-1111222233", session_hours = 4
      environments = {
        live = {
          account_id            = "444455556666", workload_region = "us-east-1", model_id = "amazon.nova-lite-v1:0"
          emergency_policy_name = "DP-Live-Emergency", emergency_deny = false
          assignments_enabled   = false, assignment_teams = ["team-00"]
          teams = {
            team-00 = { permission_set_name = "DP-Live-team-00", group_name = "DP-Live-team-00", resource_name = "dp-live-team-00" }
            team-01 = { permission_set_name = "DP-Live-team-01", group_name = "DP-Live-team-01", resource_name = "dp-live-team-01" }
          }
        }
      }
    }
  }
  assert {
    condition     = alltrue([for team in values(module.team_access) : team.assignment_count == 0])
    error_message = "The global switch must disable assignments even for selected teams."
  }
}
