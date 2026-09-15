mock_provider "aws" {
  mock_data "aws_ami" {
    defaults = { id = "ami-00000000000000000" }
  }
}

variables {
  host = {
    account_id            = "111122223333"
    management_account_id = "444455556666"
    aws_profile           = "test-no-aws"
    region                = "us-east-1"
    availability_zone     = "us-east-1a"
    name                  = "test-host"
    domain                = "workshop-test.example.com"
    ami_id                = "ami-00000000000000000"
    instance_type         = "t3.small"
    disk_gb               = 20
    vpc_cidr              = "10.70.0.0/16"
    subnet_cidr           = "10.70.1.0/24"
    tags                  = {}
  }
}

run "restricted_host" {
  command = plan
  assert {
    condition     = length(aws_iam_role.card) == 0 && length(aws_iam_role_policy.assume_card) == 0
    error_message = "The base host must not grant pet access without explicit configuration."
  }
  assert {
    condition     = length(aws_secretsmanager_secret.login) == 0 && length(aws_iam_role_policy.login) == 0
    error_message = "The base host must not create login storage or permissions unless configured."
  }
  assert {
    condition = (
      aws_instance.host.metadata_options[0].http_tokens == "required" &&
      aws_instance.host.root_block_device[0].encrypted &&
      aws_instance.host.credit_specification[0].cpu_credits == "standard" &&
      aws_instance.host.associate_public_ip_address == false
    )
    error_message = "The host must require IMDSv2, encrypt its disk, avoid surplus CPU charges, and use only its reserved IP."
  }
  assert {
    condition = (
      keys(aws_vpc_security_group_ingress_rule.web) == ["443", "80"] &&
      aws_vpc_security_group_egress_rule.https.to_port == 443 &&
      aws_iam_role_policy_attachment.ssm.policy_arn == "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    )
    error_message = "The host must expose only web ports and start with management permissions only."
  }
}

run "scoped_login_secret" {
  command = apply
  variables {
    login_secret = { name = "test-host/login" }
  }
  assert {
    condition = (
      aws_secretsmanager_secret.login[0].recovery_window_in_days == 7 &&
      length(jsondecode(aws_iam_role_policy.login[0].policy).Statement) == 1 &&
      jsondecode(aws_iam_role_policy.login[0].policy).Statement[0].Action == "secretsmanager:GetSecretValue" &&
      jsondecode(aws_iam_role_policy.login[0].policy).Statement[0].Resource == aws_secretsmanager_secret.login[0].arn
    )
    error_message = "Login permissions must allow only reading the exact secret while retaining a recovery window."
  }
}

run "reject_immediate_secret_deletion" {
  command = plan
  variables {
    login_secret = { name = "test-host/login", recovery_window_in_days = 0 }
  }
  expect_failures = [var.login_secret]
}

run "scoped_pet_card" {
  command = apply
  variables {
    pet_cards = { team-01 = { table_name = "test-team-01" } }
  }
  assert {
    condition = (
      length(jsondecode(aws_iam_role_policy.card["team-01"].policy).Statement) == 1 &&
      jsondecode(aws_iam_role_policy.card["team-01"].policy).Statement[0].Action == "dynamodb:GetItem" &&
      jsondecode(aws_iam_role_policy.card["team-01"].policy).Statement[0].Resource == "arn:aws:dynamodb:us-east-1:111122223333:table/test-team-01" &&
      jsondecode(aws_iam_role_policy.card["team-01"].policy).Statement[0].Condition["ForAllValues:StringEquals"]["dynamodb:LeadingKeys"] == ["team-01"] &&
      jsondecode(aws_iam_role_policy.assume_card[0].policy).Statement[0].Action == "sts:AssumeRole" &&
      jsondecode(aws_iam_role_policy.assume_card[0].policy).Statement[0].Resource == [aws_iam_role.card["team-01"].arn]
    )
    error_message = "The card role must read only its pet item and the host must assume only registered roles."
  }
}

run "scoped_agent_url" {
  command = apply
  variables {
    pet_cards = { team-01 = { table_name = "test-team-01", agent_function_name = "test-team-01-agent" } }
  }
  assert {
    condition = (
      length(aws_iam_role_policy.agent) == 1 &&
      jsondecode(aws_iam_role_policy.agent["team-01"].policy).Statement[1].Condition.StringEquals["lambda:FunctionUrlAuthType"] == "AWS_IAM" &&
      jsondecode(aws_iam_role_policy.agent["team-01"].policy).Statement[2].Condition.Bool["lambda:InvokedViaFunctionUrl"] == "true" &&
      jsondecode(aws_iam_role_policy.agent["team-01"].policy).Statement[2].Resource == "arn:aws:lambda:us-east-1:111122223333:function:test-team-01-agent" &&
      jsondecode(aws_iam_role_policy.agent["team-01"].policy).Statement[3].Condition["ForAllValues:StringLike"]["dynamodb:LeadingKeys"] == ["_op#*"]
    )
    error_message = "Agent permissions must require the assigned IAM URL and limit receipt reads to the team table."
  }
}
