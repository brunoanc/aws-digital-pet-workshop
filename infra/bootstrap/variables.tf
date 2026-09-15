variable "management_account_id" {
  description = "Account that owns the shared Terraform state bucket."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.management_account_id))
    error_message = "management_account_id must contain exactly 12 digits."
  }
}

variable "aws_profile" {
  description = "Organizer profile used to provision the state bucket."
  type        = string
  nullable    = false
  validation {
    condition     = length(trimspace(var.aws_profile)) > 0
    error_message = "Specify an explicit management account profile."
  }
}

variable "region" {
  description = "State storage location, independent of the workload region."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.region))
    error_message = "Specify a valid AWS region, such as us-east-1."
  }
}

variable "state_bucket_name" {
  description = "Bucket name to retain across workshop events."
  type        = string
  nullable    = false
  validation {
    condition = (
      length(var.state_bucket_name) >= 3 && length(var.state_bucket_name) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9-]*[a-z0-9]$", var.state_bucket_name)) &&
      !can(regex("^(xn--|sthree-|amzn-s3-demo-)", var.state_bucket_name)) &&
      !can(regex("(-s3alias|--ol-s3|--x-s3|--table-s3)$", var.state_bucket_name))
    )
    error_message = "Use 3–63 lowercase letters, digits, or hyphens without S3-reserved prefixes or suffixes."
  }
}

variable "tags" {
  description = "Tags must not contain participant details or secrets."
  type        = map(string)
  default     = {}
  nullable    = false
}
