variable "participant_access" {
  description = "Configure memberships separately to grant existing users access to these teams."
  type = object({
    instance_arn      = string
    identity_store_id = string
    session_hours     = number
    environments = map(object({
      account_id            = string
      workload_region       = string
      model_id              = string
      emergency_policy_name = string
      emergency_deny        = bool
      assignments_enabled   = optional(bool, true)
      assignment_teams      = optional(set(string))
      teams = map(object({
        permission_set_name = string
        group_name          = string
        resource_name       = string
        agent_resource_name = optional(string)
      }))
    }))
  })
  default = null
  validation {
    condition = var.participant_access == null ? true : (
      var.participant_access.session_hours >= 1 && var.participant_access.session_hours <= 12 &&
      floor(var.participant_access.session_hours) == var.participant_access.session_hours &&
      alltrue([for env in values(var.participant_access.environments) :
        (env.assignment_teams == null ? true : alltrue([for team in env.assignment_teams : contains(keys(env.teams), team)])) &&
        can(regex("^[0-9]{12}$", env.account_id)) && env.account_id != var.management_account_id &&
        can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", env.workload_region)) &&
        can(regex("^amazon\\.nova-[a-z0-9-]+:[0-9]+$", env.model_id)) &&
        length(env.teams) > 0 && length(env.teams) <= 20 &&
        length(env.emergency_policy_name) > 0 && length(env.emergency_policy_name) <= 128 &&
        alltrue([for team in values(env.teams) :
          can(regex("^DP-[A-Za-z0-9-]{1,29}$", team.permission_set_name)) &&
          can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", team.resource_name)) &&
          (team.agent_resource_name == null ? true : can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{2,53}$", team.agent_resource_name))) &&
          length(team.group_name) > 0 && length(team.group_name) <= 128
        ])
      ])
    )
    error_message = "Check member accounts, 1–12-hour sessions, regions, direct Nova model IDs, teams, and DP-prefixed names of at most 32 characters."
  }
  validation {
    condition = var.participant_access == null ? true : (
      length(distinct([for env in values(var.participant_access.environments) : env.account_id])) == length(var.participant_access.environments) &&
      length(distinct(flatten([for env in values(var.participant_access.environments) : [for team in values(env.teams) : team.permission_set_name]]))) == length(flatten([for env in values(var.participant_access.environments) : keys(env.teams)])) &&
      length(distinct(flatten([for env in values(var.participant_access.environments) : [for team in values(env.teams) : team.group_name]]))) == length(flatten([for env in values(var.participant_access.environments) : keys(env.teams)])) &&
      alltrue([for env in values(var.participant_access.environments) :
        length(distinct(concat([for team in values(env.teams) : team.resource_name], [for team in values(env.teams) : team.agent_resource_name if team.agent_resource_name != null]))) ==
        length(env.teams) + length([for team in values(env.teams) : team.agent_resource_name if team.agent_resource_name != null])
      ])
    )
    error_message = "Each environment requires a distinct account, unique groups and permission sets, and separate resources for each team."
  }
}

data "aws_partition" "current" {}

locals {
  access_environments = var.participant_access == null ? {} : var.participant_access.environments
  access_teams = merge({}, [for env_key, env in local.access_environments : {
    for team_key, team in env.teams : "${env_key}/${team_key}" => merge(team, {
      account_id          = env.account_id, workload_region = env.workload_region, model_id = env.model_id,
      assignments_enabled = env.assignments_enabled && (env.assignment_teams == null ? true : contains(env.assignment_teams, team_key))
    })
  }]...)
  # Identity Center omits us-east-1 from generated role paths.
  sso_role_path = var.region == "us-east-1" ? "aws-reserved/sso.amazonaws.com" : "aws-reserved/sso.amazonaws.com/${var.region}"
  emergency_principals = { for key, env in local.access_environments : key => concat([
    for team in values(env.teams) : "arn:${data.aws_partition.current.partition}:iam::${env.account_id}:role/${local.sso_role_path}/AWSReservedSSO_${team.permission_set_name}_*"
  ], [for team in values(env.teams) : "arn:${data.aws_partition.current.partition}:iam::${env.account_id}:role/${team.agent_resource_name}-execution" if team.agent_resource_name != null]) }
}

module "team_access" {
  for_each            = local.access_teams
  source              = "../modules/team-access"
  partition           = data.aws_partition.current.partition
  account_id          = each.value.account_id
  workload_region     = each.value.workload_region
  model_id            = each.value.model_id
  instance_arn        = var.participant_access.instance_arn
  identity_store_id   = var.participant_access.identity_store_id
  session_hours       = var.participant_access.session_hours
  assignments_enabled = each.value.assignments_enabled
  permission_set_name = each.value.permission_set_name
  group_name          = each.value.group_name
  resource_name       = each.value.resource_name
  agent_resource_name = each.value.agent_resource_name
}

# Keep the policy unattached until emergency access revocation is needed.
resource "aws_organizations_policy" "participant_emergency" {
  for_each    = local.access_environments
  name        = each.value.emergency_policy_name
  description = "Blocks participant access during an emergency or event cleanup."
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyWorkshopParticipants", Effect = "Deny", Action = "*", Resource = "*"
      Condition = { ArnLike = { "aws:PrincipalArn" = local.emergency_principals[each.key] } }
    }]
  })
}

resource "aws_organizations_policy_attachment" "participant_emergency" {
  for_each  = { for key, env in local.access_environments : key => env if env.emergency_deny }
  policy_id = aws_organizations_policy.participant_emergency[each.key].id
  target_id = each.value.account_id
}

output "participant_groups" {
  value = { for key, team in module.team_access : key => team.group_id }
}

output "emergency_role_patterns" {
  value = local.emergency_principals
}
