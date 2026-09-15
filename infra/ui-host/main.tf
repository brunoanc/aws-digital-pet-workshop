terraform {
  required_version = "~> 1.15.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "= 6.64.0" }
  }
  backend "s3" {}
}

variable "host" {
  description = "Configures an isolated host independently of student resources."
  type = object({
    account_id            = string
    management_account_id = string
    aws_profile           = string
    region                = string
    availability_zone     = string
    name                  = string
    domain                = string
    ami_id                = string
    instance_type         = string
    disk_gb               = number
    vpc_cidr              = string
    subnet_cidr           = string
    tags                  = map(string)
  })
  validation {
    condition = (
      can(regex("^[0-9]{12}$", var.host.account_id)) &&
      can(regex("^[0-9]{12}$", var.host.management_account_id)) &&
      var.host.account_id != var.host.management_account_id &&
      length(trimspace(var.host.aws_profile)) > 0 &&
      can(regex("^us-[a-z]+-[0-9]+$", var.host.region)) &&
      can(regex("^${var.host.region}[a-z]$", var.host.availability_zone))
    )
    error_message = "Choose a member account, explicit profile, and matching US region and availability zone."
  }
  validation {
    condition = (
      can(regex("^[a-z][a-z0-9-]{2,39}$", var.host.name)) &&
      can(regex("^[a-z0-9][a-z0-9.-]+\\.[a-z]{2,}$", var.host.domain)) &&
      can(regex("^ami-[a-f0-9]{17}$", var.host.ami_id)) &&
      contains(["t3.small", "t3.medium"], var.host.instance_type) &&
      var.host.disk_gb >= 20 && var.host.disk_gb <= 40 && floor(var.host.disk_gb) == var.host.disk_gb &&
      can(cidrnetmask(var.host.vpc_cidr)) && can(cidrnetmask(var.host.subnet_cidr))
    )
    error_message = "Provide valid names, a pinned AMI, a supported instance size, 20–40 GiB of disk, and IPv4 networks."
  }
}

provider "aws" {
  profile             = var.host.aws_profile
  region              = var.host.region
  allowed_account_ids = [var.host.account_id]
  default_tags {
    tags = merge(var.host.tags, { ManagedBy = "Terraform" })
  }
}

data "aws_ami" "host" {
  owners = ["amazon"]
  filter {
    name   = "image-id"
    values = [var.host.ami_id]
  }
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_vpc" "host" {
  cidr_block           = var.host.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.host.name }
}

resource "aws_default_security_group" "closed" {
  vpc_id = aws_vpc.host.id
}

resource "aws_internet_gateway" "host" {
  vpc_id = aws_vpc.host.id
}

resource "aws_subnet" "host" {
  vpc_id                  = aws_vpc.host.id
  cidr_block              = var.host.subnet_cidr
  availability_zone       = var.host.availability_zone
  map_public_ip_on_launch = false
}

resource "aws_route_table" "host" {
  vpc_id = aws_vpc.host.id
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.host.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.host.id
}

resource "aws_route_table_association" "host" {
  subnet_id      = aws_subnet.host.id
  route_table_id = aws_route_table.host.id
}

resource "aws_security_group" "host" {
  name        = var.host.name
  description = "Restricts inbound access to the HTTPS proxy and certificate validation."
  vpc_id      = aws_vpc.host.id
}

resource "aws_vpc_security_group_ingress_rule" "web" {
  for_each          = toset(["80", "443"])
  security_group_id = aws_security_group.host.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = tonumber(each.key)
  to_port           = tonumber(each.key)
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.host.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_iam_role" "host" {
  name = var.host.name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "host" {
  name = var.host.name
  role = aws_iam_role.host.name
}

resource "aws_instance" "host" {
  ami                         = data.aws_ami.host.id
  instance_type               = var.host.instance_type
  subnet_id                   = aws_subnet.host.id
  vpc_security_group_ids      = [aws_security_group.host.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.host.name
  monitoring                  = false
  tags                        = { Name = var.host.name }

  lifecycle {
    # The provider reads an attached Elastic IP as public IP auto-assignment after creation.
    ignore_changes = [associate_public_ip_address]
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.host.disk_gb
    encrypted             = true
    delete_on_termination = true
  }

  credit_specification {
    cpu_credits = "standard"
  }

  depends_on = [aws_iam_role_policy_attachment.ssm, aws_route_table_association.host, aws_route.internet]
}

resource "aws_eip" "host" {
  domain     = "vpc"
  instance   = aws_instance.host.id
  depends_on = [aws_internet_gateway.host]
}

output "hosting" {
  description = "Identifies the host and DNS target before application installation."
  value = {
    instance_id = aws_instance.host.id
    public_ip   = aws_eip.host.public_ip
    domain      = var.host.domain
    role_arn    = aws_iam_role.host.arn
  }
}
