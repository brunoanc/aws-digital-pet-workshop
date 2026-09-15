mock_provider "aws" {}

variables {
  hosting = {
    account_id            = "111122223333"
    management_account_id = "444455556666"
    aws_profile           = "test-no-aws"
    domain                = "slides.example.com"
    bucket_name           = "test-slides-111122223333"
  }
}

run "private_preparation" {
  command = plan
  assert {
    condition     = length(aws_cloudfront_distribution.slides) == 0 && length(aws_acm_certificate_validation.slides) == 0
    error_message = "Preparation must not create CloudFront or wait for external DNS."
  }
  assert {
    condition = (
      aws_s3_bucket_public_access_block.slides.block_public_acls &&
      aws_s3_bucket_public_access_block.slides.block_public_policy &&
      aws_s3_bucket_public_access_block.slides.ignore_public_acls &&
      aws_s3_bucket_public_access_block.slides.restrict_public_buckets &&
      !aws_s3_bucket.slides.force_destroy &&
      aws_s3_bucket_ownership_controls.slides.rule[0].object_ownership == "BucketOwnerEnforced"
    )
    error_message = "The bucket must stay private and refuse destructive cleanup of its contents."
  }
}

run "disabled_distribution" {
  command = plan
  variables {
    create_distribution = true
  }
  assert {
    condition = (
      !aws_cloudfront_distribution.slides[0].enabled &&
      aws_cloudfront_distribution.slides[0].default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https" &&
      aws_cloudfront_distribution.slides[0].viewer_certificate[0].minimum_protocol_version == "TLSv1.2_2021" &&
      aws_cloudfront_origin_access_control.slides[0].signing_behavior == "always"
    )
    error_message = "CloudFront must start disabled and use HTTPS with signed origin requests."
  }
}

run "reject_management_account" {
  command = plan
  variables {
    hosting = {
      account_id            = "444455556666"
      management_account_id = "444455556666"
      aws_profile           = "test-no-aws"
      domain                = "slides.example.com"
      bucket_name           = "test-slides-444455556666"
    }
  }
  expect_failures = [var.hosting]
}
