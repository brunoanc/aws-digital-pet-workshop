"""Generate deployment files from the environment and team inventory."""

import argparse
import json
from pathlib import Path
import re

from app.config import settings_from_dict


ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = Path(__file__).resolve().parent / "config_defaults"


def defaults(name):
    """Read defaults for a runtime contract."""

    return json.loads((DEFAULTS / f"{name}.json").read_text())


def fields(data, required, optional=()):
    """Reject missing fields and typing mistakes."""

    if not isinstance(data, dict) or set(data) - set(required) - set(optional) or set(required) - set(data):
        raise ValueError(f"Expected fields {', '.join(required)}; optional fields {', '.join(optional)}.")


def match(value, pattern, name):
    """Check a named string against its format."""

    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"Check {name}.")


def validate(env, teams):
    """Check destinations and explicit membership assignments."""

    fields(env, ("region", "availability_zone", "name", "resource_prefix", "management", "workload",
                 "state_bucket_name", "budget", "identity_center", "model", "layer_zip_path", "web", "access", "deployment"))
    match(env["region"], r"us-(east|west)-[12]", "region")
    match(env["availability_zone"], re.escape(env["region"]) + r"[a-z]", "availability_zone")
    match(env["name"], r"[a-z][a-z0-9-]{1,14}", "name")
    match(env["resource_prefix"], r"[a-z][a-z0-9-]{1,30}", "resource_prefix")

    for key in ("management", "workload"):
        fields(env[key], ("account_id", "profile"))
        match(env[key]["account_id"], r"[0-9]{12}", f"{key}.account_id")
        match(env[key]["profile"], r"[A-Za-z0-9_-]+", f"{key}.profile")

    if env["management"]["account_id"] == env["workload"]["account_id"]:
        raise ValueError("Use a member account for the workshop.")

    match(env["state_bucket_name"], r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", "state_bucket_name")
    fields(env["budget"], ("name", "amount_usd", "alert_amounts_usd", "email_addresses", "import_existing"),
           ("start_utc", "end_utc", "tags"))

    identity = env["identity_center"]

    fields(identity, ("instance_arn", "identity_store_id", "session_hours", "assignments_enabled", "emergency_deny"), ("region", "assignment_teams"))
    match(identity["instance_arn"], r"arn:aws:sso:::instance/ssoins-[a-zA-Z0-9-]+", "instance_arn")
    match(identity["identity_store_id"], r"d-[a-f0-9]{10}", "identity_store_id")
    match(identity.get("region", env["region"]), r"us-(east|west)-[12]", "identity_center.region")

    if type(identity["session_hours"]) is not int or not 1 <= identity["session_hours"] <= 12:
        raise ValueError("Use 1 to 12 hours for the Identity Center session.")

    web = env["web"]

    fields(web, ("domain", "ami_id", "cognito_domain_prefix", "saml_metadata_url", "cards_enabled", "chat_enabled"),
           ("instance_type", "disk_gb", "vpc_cidr", "subnet_cidr"))
    match(web["domain"], r"[a-z0-9][a-z0-9.-]+\.[a-z]{2,}", "web.domain")
    match(web["ami_id"], r"ami-[a-f0-9]{17}", "web.ami_id")
    match(web["cognito_domain_prefix"], r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", "cognito_domain_prefix")

    if web["saml_metadata_url"] is not None:
        match(web["saml_metadata_url"], r"https://[A-Za-z0-9.-]+/[^?#]+", "saml_metadata_url")

    if web["chat_enabled"] and not web["cards_enabled"]:
        raise ValueError("Enable cards before enabling chat.")

    access = env["access"]

    fields(access, ("opens_at", "closes_at", "max_session_seconds", "enabled"))

    for section, keys in ((identity, ("assignments_enabled", "emergency_deny")),
                          (web, ("cards_enabled", "chat_enabled")), (access, ("enabled",))):
        if any(type(section[key]) is not bool for key in keys):
            raise ValueError("Use true or false for access and web switches.")

    if (any(type(access[key]) is not int for key in ("opens_at", "closes_at", "max_session_seconds"))
            or not 0 <= access["opens_at"] < access["closes_at"] or not 300 <= access["max_session_seconds"] <= 28800):
        raise ValueError("Check the access window and session duration.")

    fields(env["deployment"], (), ("instance_id", "user_pool_id", "client_id", "secret_arn"))
    fields(env["model"], ("model_id",), set(defaults("app")) - {"account_id", "profile", "region", "team_id", "function_name", "model_id"})

    if not isinstance(teams, dict) or not 1 <= len(teams) <= 20:
        raise ValueError("Configure 1 to 20 teams.")

    if "assignment_teams" in identity:
        selected = identity["assignment_teams"]
        if (not isinstance(selected, list) or any(not isinstance(team, str) or team not in teams for team in selected)
                or len(selected) != len(set(selected))):
            raise ValueError("Choose distinct configured teams for assignment_teams.")

    names, user_ids, subjects = set(), set(), set()

    for team, data in teams.items():
        match(team, r"team-[0-9]{2}", "team ID")
        fields(data, ("identity_center_user_ids", "cognito_subjects"), ("resource_name", "function_url"))

        resource = data.get("resource_name", f'{env["resource_prefix"]}-{team}')

        match(resource, r"[A-Za-z0-9][A-Za-z0-9_-]{2,47}", "resource_name")

        if names.intersection((resource, resource + "-agent")):
            raise ValueError("Use distinct resource names for every team.")

        names.update((resource, resource + "-agent"))

        for key, seen in (("identity_center_user_ids", user_ids), ("cognito_subjects", subjects)):
            if not isinstance(data[key], list):
                raise ValueError(f"Use a list for {key}.")

            for value in data[key]:
                match(value, r"[A-Za-z0-9_-]+", key)

                if value in seen:
                    raise ValueError(f"Assign each {key} value to one team.")

                seen.add(value)

        if "function_url" in data:
            match(data["function_url"], r"https://[a-z0-9]{32}\.lambda-url\." + re.escape(env["region"]) + r"\.on\.aws/", "function_url")


def render(env, teams, directory):
    """Build coherent files for one environment without changing AWS."""

    validate(env, teams)

    output = Path(directory).resolve()
    region, name, prefix = env["region"], env["name"], env["resource_prefix"]
    management, workload = env["management"], env["workload"]
    common = {"account_id": workload["account_id"], "profile": workload["profile"], "region": region}
    provider = {"account_id": workload["account_id"], "management_account_id": management["account_id"],
                "aws_profile": workload["profile"], "region": region}
    tags = {"Project": "digital-pet", "Environment": name}
    resources = {team: data.get("resource_name", f"{prefix}-{team}") for team, data in sorted(teams.items())}
    files = {}

    def emit(filename, data):
        """Serialize one generated configuration."""

        files[filename] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    admin = {"management_account_id": management["account_id"], "aws_profile": management["profile"], "region": region}

    emit("bootstrap.tfvars.json", admin | {"state_bucket_name": env["state_bucket_name"], "tags": tags})

    identity = env["identity_center"]
    access_teams = {team: {"permission_set_name": f"DP-{name}-{team}", "group_name": f"DP-{name}-{team}",
        "resource_name": resource, "agent_resource_name": resource + "-agent"} for team, resource in resources.items()}

    emit("control.tfvars.json", admin | {"region": identity.get("region", region), "budget": env["budget"],
        "participant_access": {key: identity[key] for key in ("instance_arn", "identity_store_id", "session_hours")} | {
            "environments": {name: {"account_id": workload["account_id"], "workload_region": region,
                "model_id": env["model"]["model_id"], "emergency_policy_name": f"DP-{name}-Emergency",
                "emergency_deny": identity["emergency_deny"], "assignments_enabled": identity["assignments_enabled"], "teams": access_teams} |
                ({"assignment_teams": identity["assignment_teams"]} if "assignment_teams" in identity else {})}},
        "participant_memberships": {user: f"{name}/{team}" for team, data in teams.items() for user in data["identity_center_user_ids"]}})
    emit("pets.tfvars.json", {"workload": provider | {"teams": resources, "runtime": "python3.13", "memory_mb": 128,
        "timeout_seconds": 10, "log_retention_days": 7, "tags": tags}})
    emit("operations.json", common | {"teams": resources, "pet_fixture": str(ROOT / "fixtures/starter.json")})

    model_defaults = defaults("app")

    fields(env["model"], ("model_id",), set(model_defaults) - set(common) - {"team_id", "function_name", "model_id"})

    if not isinstance(env["layer_zip_path"], str) or not env["layer_zip_path"].strip():
        raise ValueError("Specify layer_zip_path.")

    layer = Path(env["layer_zip_path"])

    if not layer.is_absolute():
        layer = ROOT / layer

    for team, resource in resources.items():
        runtime = model_defaults | env["model"] | common | {"team_id": team, "function_name": resource}

        settings_from_dict(runtime)
        emit(f"{team}-runtime.json", runtime)
        emit(f"{team}-agent.tfvars.json", {"agent": provider | {"function_name": resource + "-agent",
            "layer_name": f"{prefix}-{team}-dependencies", "layer_zip_path": str(layer.resolve()),
            "runtime_config_path": str(output / f"{team}-runtime.json"), "memory_mb": 512,
            "timeout_seconds": 90, "log_retention_days": 7, "tags": tags,
            "function_url_enabled": env["web"]["chat_enabled"]}})

        remote = defaults("remote-agent") | {"function_name": resource + "-agent"}

        if "function_url" in teams[team]:
            remote["function_url"] = teams[team]["function_url"]

        emit(f"{team}-remote-agent.json", remote)

    web = env["web"]
    host_name = prefix + "-ui"
    host = provider | {"availability_zone": env["availability_zone"], "name": host_name,
        "domain": web["domain"], "ami_id": web["ami_id"], "instance_type": web.get("instance_type", "t3.small"),
        "disk_gb": web.get("disk_gb", 20), "vpc_cidr": web.get("vpc_cidr", "10.70.0.0/16"),
        "subnet_cidr": web.get("subnet_cidr", "10.70.1.0/24"), "tags": tags}
    cards = {team: {"table_name": resource} | ({"agent_function_name": resource + "-agent"} if web["chat_enabled"] else {})
             for team, resource in resources.items()} if web["cards_enabled"] else {}

    emit("ui-host.tfvars.json", {"host": host, "pet_cards": cards, "login_secret": {"name": host_name + "/login"}})
    emit("ui-auth.tfvars.json", {"auth": provider | {"name": prefix + "-login",
        "domain_prefix": web["cognito_domain_prefix"], "app_origin": "https://" + web["domain"],
        "tags": tags, "saml_metadata_url": web["saml_metadata_url"], "saml_provider_name": "IdentityCenter",
        "max_session_seconds": env["access"]["max_session_seconds"]}})

    deployed = env["deployment"]

    if "instance_id" in deployed:
        match(deployed["instance_id"], r"i-[a-f0-9]{17}", "instance_id")
        emit("proxy.json", defaults("proxy") | common | {"instance_id": deployed["instance_id"],
            "instance_name": host_name, "domain": web["domain"]})

    if any(key in deployed for key in ("user_pool_id", "client_id", "secret_arn")):
        if not all(key in deployed for key in ("user_pool_id", "client_id", "secret_arn")):
            raise ValueError("Provide user_pool_id, client_id and secret_arn together.")

        match(deployed["user_pool_id"], re.escape(region) + r"_[A-Za-z0-9]+", "user_pool_id")
        match(deployed["client_id"], r"[a-z0-9]{1,128}", "client_id")
        match(deployed["secret_arn"], f'arn:aws:secretsmanager:{region}:{workload["account_id"]}:secret:[A-Za-z0-9/_+=.@-]+-[A-Za-z0-9]{{6}}', "secret_arn")
        emit("login-bootstrap.json", common | {key: deployed[key] for key in ("user_pool_id", "client_id", "secret_arn")} |
             {"app_origin": "https://" + web["domain"], "provider_name": "IdentityCenter"})
        emit("access.json", env["access"] | {"issuer": f'https://cognito-idp.{region}.amazonaws.com/{deployed["user_pool_id"]}',
             "client_id": deployed["client_id"], "teams": sorted(teams),
             "members": {subject: team for team, data in teams.items() for subject in data["cognito_subjects"]}})
    elif env["access"]["enabled"]:
        raise ValueError("Complete the login deployment before enabling access.")

    if web["cards_enabled"]:
        targets = {}

        for team, resource in resources.items():
            target = {"role_arn": f'arn:aws:iam::{workload["account_id"]}:role/{host_name}-{team}-card', "table_name": resource}

            if web["chat_enabled"]:
                if "function_url" not in teams[team]:
                    continue

                target["agent"] = defaults("shared-agent")["teams"]["team-01"]["agent"] | {
                    "function_name": resource + "-agent", "function_url": teams[team]["function_url"], "model_id": env["model"]["model_id"]}

                for key in ("max_input_chars", "max_messages", "max_tool_calls"):
                    target["agent"][key] = env["model"].get(key, model_defaults[key])

            targets[team] = target

        if len(targets) == len(teams):
            emit("shared-card.json", {"account_id": workload["account_id"], "region": region, "teams": targets})

    return files


def write_new(directory, rendered):
    """Write a private directory while preserving existing configurations."""

    directory = Path(directory).resolve()
    local = ROOT / ".local"

    if (directory == ROOT or ROOT in directory.parents) and not (directory == local or local in directory.parents):
        raise ValueError("Use .local or a directory outside the repository.")

    if any(Path(name).name != name or name in (".", "..") for name in rendered):
        raise ValueError("Use plain output filenames.")

    directory.mkdir(mode=0o700, parents=False, exist_ok=False)

    for name, content in rendered.items():
        with (directory / name).open("x", encoding="utf-8") as stream:
            (directory / name).chmod(0o600)
            stream.write(content)


def main():
    """Preview or write configuration from two private inputs."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--environment", required=True, type=Path)
    parser.add_argument("--teams", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--write", action="store_true")

    args = parser.parse_args()
    rendered = render(json.loads(args.environment.read_text()), json.loads(args.teams.read_text()), args.output)

    if args.write:
        write_new(args.output, rendered)

    print(json.dumps({"written": args.write, "files": sorted(rendered)}, indent=2))


if __name__ == "__main__":
    main()
