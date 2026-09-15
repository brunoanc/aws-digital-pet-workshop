mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
}

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
      rehearsal = {
        account_id            = "444455556666", workload_region = "us-east-1", model_id = "amazon.nova-lite-v1:0"
        emergency_policy_name = "DP-Test-Emergency", emergency_deny = false
        teams = {
          team-01 = { permission_set_name = "DP-Rehearsal-team-01", group_name = "DP-Rehearsal-team-01", resource_name = "dp-rehearsal-team-01" }
          team-02 = { permission_set_name = "DP-Rehearsal-team-02", group_name = "DP-Rehearsal-team-02", resource_name = "dp-rehearsal-team-02" }
        }
      }
    }
  }
}

run "two_teams_isolated_and_emergency_off" {
  command = plan
  assert {
    condition     = length(module.team_access) == 2 && length(aws_organizations_policy_attachment.participant_emergency) == 0
    error_message = "The initial configuration must contain two teams with no emergency SCP attached."
  }
  assert {
    condition = alltrue([for key, team in module.team_access :
      jsondecode(team.policy_json).Statement[1].Resource[0] == "arn:aws:dynamodb:us-east-1:444455556666:table/dp-rehearsal-${split("/", key)[1]}" &&
      jsondecode(team.policy_json).Statement[2].Resource[0] == "arn:aws:lambda:us-east-1:444455556666:function:dp-rehearsal-${split("/", key)[1]}" &&
      jsondecode(team.policy_json).Statement[3].Resource[0] == "arn:aws:logs:us-east-1:444455556666:log-group:/aws/lambda/dp-rehearsal-${split("/", key)[1]}:*"
    ])
    error_message = "Each team must have access only to its own table, function, and logs."
  }
  assert {
    condition = alltrue(flatten([for team in values(module.team_access) : [for s in jsondecode(team.policy_json).Statement :
      s.Condition.StringEquals["aws:RequestedRegion"] == "us-east-1"
    ]]))
    error_message = "Every allow statement must restrict access to the configured region."
  }
  assert {
    condition = alltrue(flatten([for team in values(module.team_access) : [for s in jsondecode(team.policy_json).Statement : [for action in s.Action :
      !strcontains(action, "*") && !startswith(action, "iam:") && !startswith(action, "secretsmanager:") && action != "lambda:UpdateFunctionConfiguration"
    ]]]))
    error_message = "Policies must not allow wildcard actions, IAM access, secrets access, or Lambda configuration changes."
  }
  assert {
    condition = toset(output.emergency_role_patterns.rehearsal) == toset([
      "arn:aws:iam::444455556666:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_DP-Rehearsal-team-01_*",
      "arn:aws:iam::444455556666:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_DP-Rehearsal-team-02_*"
    ])
    error_message = "The deny policy must match only the configured DP roles and omit the region from the us-east-1 SSO path."
  }
}

run "optional_agent_is_scoped_and_covered_by_emergency" {
  command = plan
  variables {
    participant_access = {
      instance_arn      = "arn:aws:sso:::instance/ssoins-1111222233334444"
      identity_store_id = "d-1111222233", session_hours = 4
      environments = {
        rehearsal = {
          account_id            = "444455556666", workload_region = "us-east-1", model_id = "amazon.nova-lite-v1:0"
          emergency_policy_name = "DP-Test-Emergency", emergency_deny = false
          teams = {
            team-01 = { permission_set_name = "DP-Rehearsal-team-01", group_name = "DP-Rehearsal-team-01", resource_name = "dp-rehearsal-team-01" }
            team-02 = { permission_set_name = "DP-Rehearsal-team-02", group_name = "DP-Rehearsal-team-02", resource_name = "dp-rehearsal-team-02", agent_resource_name = "dp-rehearsal-team-02-agent" }
          }
        }
      }
    }
  }
  assert {
    condition = (
      length(jsondecode(module.team_access["rehearsal/team-01"].policy_json).Statement[2].Resource) == 1 &&
      jsondecode(module.team_access["rehearsal/team-02"].policy_json).Statement[2].Resource[1] == "arn:aws:lambda:us-east-1:444455556666:function:dp-rehearsal-team-02-agent" &&
      jsondecode(module.team_access["rehearsal/team-02"].policy_json).Statement[3].Resource[1] == "arn:aws:logs:us-east-1:444455556666:log-group:/aws/lambda/dp-rehearsal-team-02-agent:*" &&
      length(output.emergency_role_patterns.rehearsal) == 3 &&
      contains(output.emergency_role_patterns.rehearsal, "arn:aws:iam::444455556666:role/dp-rehearsal-team-02-agent-execution") &&
      length(aws_organizations_policy_attachment.participant_emergency) == 0
    )
    error_message = "Only the assigned team may access the agent and its role must be covered by the inactive emergency policy."
  }
}

run "explicit_memberships" {
  command = plan
  variables {
    participant_memberships = {
      "11111111-1111-1111-1111-111111111111" = "rehearsal/team-01"
      "22222222-2222-2222-2222-222222222222" = "rehearsal/team-02"
    }
  }
  assert {
    condition = (
      length(aws_identitystore_group_membership.participant) == 2 &&
      aws_identitystore_group_membership.participant["11111111-1111-1111-1111-111111111111"].member_id == "11111111-1111-1111-1111-111111111111" &&
      aws_identitystore_group_membership.participant["22222222-2222-2222-2222-222222222222"].identity_store_id == "d-1111222233"
    )
    error_message = "Only the two explicit memberships must be created in the expected directory."
  }
}

run "regional_sso_path" {
  command = plan
  variables { region = "eu-west-1" }
  assert {
    condition     = alltrue([for arn in output.emergency_role_patterns.rehearsal : strcontains(arn, "/sso.amazonaws.com/eu-west-1/AWSReservedSSO_DP-")])
    error_message = "Identity Center outside us-east-1 must include the region in the IAM role path."
  }
}

run "emergency_on" {
  command = plan
  variables {
    participant_access = {
      instance_arn      = "arn:aws:sso:::instance/ssoins-1111222233334444"
      identity_store_id = "d-1111222233", session_hours = 4
      environments = {
        rehearsal = {
          account_id            = "444455556666", workload_region = "us-east-1", model_id = "amazon.nova-lite-v1:0"
          emergency_policy_name = "DP-Test-Emergency", emergency_deny = true, assignments_enabled = false
          teams                 = { team-01 = { permission_set_name = "DP-Rehearsal-team-01", group_name = "DP-Rehearsal-team-01", resource_name = "dp-rehearsal-team-01" } }
        }
      }
    }
  }
  assert {
    condition = (
      length(aws_organizations_policy_attachment.participant_emergency) == 1 &&
      module.team_access["rehearsal/team-01"].assignment_count == 0 &&
      aws_organizations_policy_attachment.participant_emergency["rehearsal"].target_id == "444455556666" &&
      jsondecode(aws_organizations_policy.participant_emergency["rehearsal"].content).Statement[0].Effect == "Deny"
    )
    error_message = "The enabled emergency policy must be attached only to the rehearsal account."
  }
}
