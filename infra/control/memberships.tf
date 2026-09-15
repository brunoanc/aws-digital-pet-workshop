variable "participant_memberships" {
  description = "Memberships created outside Terraform are not removed by this map."
  type        = map(string)
  default     = {}
  nullable    = false
  validation {
    condition = alltrue([for user_id, team in var.participant_memberships :
      can(regex("^([0-9a-f]{10}-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", user_id)) &&
      contains(keys(local.access_teams), team)
    ])
    error_message = "Each membership requires a valid UserId and an environment/team configured in participant_access."
  }
}

resource "aws_identitystore_group_membership" "participant" {
  for_each          = var.participant_memberships
  identity_store_id = var.participant_access.identity_store_id
  group_id          = module.team_access[each.value].group_id
  member_id         = each.key
}
