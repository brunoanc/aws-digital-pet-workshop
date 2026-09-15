terraform {
  required_version = "~> 1.15.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "= 6.64.0" }
  }
  backend "s3" {}
}

variable "hosting" {
  description = "Configures presentation hosting in a member account."
  type = object({
    account_id            = string
    management_account_id = string
    aws_profile           = string
    domain                = string
    bucket_name           = string
  })
  validation {
    condition = (
      can(regex("^[0-9]{12}$", var.hosting.account_id)) &&
      can(regex("^[0-9]{12}$", var.hosting.management_account_id)) &&
      var.hosting.account_id != var.hosting.management_account_id &&
      length(trimspace(var.hosting.aws_profile)) > 0 &&
      can(regex("^[a-z0-9.-]+\\.[a-z]{2,}$", var.hosting.domain))
    )
    error_message = "Choose a member account, explicit profile, and valid domain."
  }
}

variable "create_distribution" {
  description = "Creates CloudFront after the external DNS validation record is ready."
  type        = bool
  default     = false
}

variable "serve_content" {
  description = "Enables delivery only after the Free pricing plan has been verified."
  type        = bool
  default     = false
}

provider "aws" {
  profile             = var.hosting.aws_profile
  region              = "us-east-1"
  allowed_account_ids = [var.hosting.account_id]
  default_tags {
    tags = { ManagedBy = "Terraform", Component = "slides-hosting" }
  }
}

resource "aws_acm_certificate" "slides" {
  domain_name       = var.hosting.domain
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "slides" {
  count                   = var.create_distribution ? 1 : 0
  certificate_arn         = aws_acm_certificate.slides.arn
  validation_record_fqdns = [for record in aws_acm_certificate.slides.domain_validation_options : record.resource_record_name]
  timeouts {
    create = "5m"
  }
}

resource "aws_s3_bucket" "slides" {
  bucket        = var.hosting.bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "slides" {
  bucket                  = aws_s3_bucket.slides.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "slides" {
  bucket = aws_s3_bucket.slides.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "slides" {
  bucket = aws_s3_bucket.slides.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "slides" {
  count                             = var.create_distribution ? 1 : 0
  name                              = var.hosting.bucket_name
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "slides" {
  count               = var.create_distribution ? 1 : 0
  enabled             = var.serve_content
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = [var.hosting.domain]
  comment             = "Static workshop presentation."
  wait_for_deployment = true
  web_acl_id          = aws_wafv2_web_acl.slides[0].arn

  origin {
    domain_name              = aws_s3_bucket.slides.bucket_regional_domain_name
    origin_id                = "slides"
    origin_access_control_id = aws_cloudfront_origin_access_control.slides[0].id
  }

  default_cache_behavior {
    target_origin_id       = "slides"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.slides[0].id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.slides[0].certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

data "aws_cloudfront_cache_policy" "slides" {
  count = var.create_distribution ? 1 : 0
  name  = "Managed-CachingOptimized"
}

resource "aws_wafv2_web_acl" "slides" {
  count = var.create_distribution ? 1 : 0
  name  = var.hosting.bucket_name
  scope = "CLOUDFRONT"
  default_action {
    allow {}
  }
  visibility_config {
    cloudwatch_metrics_enabled = false
    metric_name                = "slides"
    sampled_requests_enabled   = false
  }
}

resource "aws_s3_bucket_policy" "slides" {
  bucket = aws_s3_bucket.slides.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.slides.arn, "${aws_s3_bucket.slides.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
      ], var.create_distribution ? [{
        Sid       = "AllowCloudFrontReadOnly"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.slides.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.slides[0].arn } }
    }] : [])
  })
}

output "certificate_dns_records" {
  description = "Lists the CNAME records to add at the external DNS provider."
  value = [for record in aws_acm_certificate.slides.domain_validation_options : {
    name = record.resource_record_name, type = record.resource_record_type, value = record.resource_record_value
  }]
}

output "bucket_name" {
  description = "Identifies the bucket reserved for the static build."
  value       = aws_s3_bucket.slides.id
}

output "distribution_id" {
  description = "Identifies the distribution for cache invalidations."
  value       = try(aws_cloudfront_distribution.slides[0].id, null)
}

output "distribution_arn" {
  description = "Identifies the distribution for the Free pricing subscription."
  value       = try(aws_cloudfront_distribution.slides[0].arn, null)
}

output "web_acl_arn" {
  description = "Identifies the web ACL required by the Free pricing subscription."
  value       = try(aws_wafv2_web_acl.slides[0].arn, null)
}

output "site_dns_record" {
  description = "Provides the public CNAME after CloudFront is created."
  value = var.create_distribution ? {
    name = var.hosting.domain, type = "CNAME", value = aws_cloudfront_distribution.slides[0].domain_name
  } : null
}
