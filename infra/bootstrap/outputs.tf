output "state_bucket_name" {
  description = "Shared backend bucket for downstream stacks."
  value       = aws_s3_bucket.state.id
}

output "state_region" {
  value = var.region
}

output "management_account_id" {
  value = var.management_account_id
}
