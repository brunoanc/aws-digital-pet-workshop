# Provider installation still requires network access during init.
mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = {
      id  = "mascotas-tfstate-test"
      arn = "arn:aws:s3:::mascotas-tfstate-test"
    }
  }
}

variables {
  management_account_id = "111122223333"
  aws_profile           = "test-no-aws"
  region                = "us-east-1"
  state_bucket_name     = "mascotas-tfstate-test"
}

run "private_encrypted_versioned_state" {
  command = apply

  assert {
    condition = (
      aws_s3_bucket_public_access_block.state.block_public_acls &&
      aws_s3_bucket_public_access_block.state.block_public_policy &&
      aws_s3_bucket_public_access_block.state.ignore_public_acls &&
      aws_s3_bucket_public_access_block.state.restrict_public_buckets
    )
    error_message = "The bucket must block all public access."
  }
  assert {
    condition     = one(aws_s3_bucket_versioning.state.versioning_configuration).status == "Enabled"
    error_message = "The state bucket must have versioning enabled."
  }
  assert {
    condition     = one(aws_s3_bucket_ownership_controls.state.rule).object_ownership == "BucketOwnerEnforced"
    error_message = "ACLs must be disabled."
  }
  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "The state bucket must have default encryption enabled."
  }
  assert {
    condition     = aws_s3_bucket.state.force_destroy == false
    error_message = "The state bucket must not allow automatic deletion of its contents."
  }
  assert {
    condition = (
      jsondecode(aws_s3_bucket_policy.state.policy).Statement[0].Effect == "Deny" &&
      jsondecode(aws_s3_bucket_policy.state.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false" &&
      length(jsondecode(aws_s3_bucket_policy.state.policy).Statement[0].Resource) == 2
    )
    error_message = "The policy must deny HTTP access to the bucket and its objects."
  }
}

run "reject_invalid_account" {
  command = plan
  variables {
    management_account_id = "123"
  }
  expect_failures = [var.management_account_id]
}

run "reject_invalid_bucket" {
  command = plan
  variables {
    state_bucket_name = "Nombre Invalido"
  }
  expect_failures = [var.state_bucket_name]
}
