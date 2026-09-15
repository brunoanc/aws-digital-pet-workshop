"""Check verified login identities against the private team list."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from types import MappingProxyType


@dataclass(frozen=True)
class AccessPolicy:
    """Store the issuer, client, event window, and organizer assignments."""

    issuer: str
    client_id: str
    opens_at: int
    closes_at: int
    max_session_seconds: int
    enabled: bool
    teams: tuple
    members: object


def load_policy(path):
    """Reload access settings on each check so revocations take effect."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = set(AccessPolicy.__dataclass_fields__)

    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Check the access configuration fields.")

    if (
        not isinstance(data["issuer"], str)
        or not re.fullmatch(
            r"https://cognito-idp\.[a-z0-9-]+\.amazonaws\.com/[A-Za-z0-9_-]+",
            data["issuer"],
        )
        or not isinstance(data["client_id"], str)
        or not re.fullmatch(r"[a-z0-9]{1,128}", data["client_id"])
        or type(data["enabled"]) is not bool
    ):
        raise ValueError("Check the access provider and enabled state.")

    if (
        any(
            type(data[key]) is not int
            for key in ("opens_at", "closes_at", "max_session_seconds")
        )
        or not 0 <= data["opens_at"] < data["closes_at"]
        or not 300 <= data["max_session_seconds"] <= 28800
    ):
        raise ValueError("Check the event window and session duration.")

    teams, members = data["teams"], data["members"]

    if (
        not isinstance(teams, list)
        or not teams
        or any(
            not isinstance(team, str) or not re.fullmatch(r"team-[0-9]{2}", team)
            for team in teams
        )
        or len(set(teams)) != len(teams)
        or not isinstance(members, dict)
        or any(not subject or team not in teams for subject, team in members.items())
    ):
        raise ValueError("Check the registered identities and authorized teams.")

    return AccessPolicy(
        **(data | {"teams": tuple(teams), "members": MappingProxyType(members)})
    )


def authorize(policy, claims, now=None):
    """Find the team using login claims verified by Streamlit."""

    current = time.time() if now is None else now

    if not policy.enabled or not policy.opens_at <= current < policy.closes_at:
        raise PermissionError("El acceso al taller no está habilitado en este momento.")

    if (
        claims.get("iss") != policy.issuer
        or claims.get("aud") != policy.client_id
        or claims.get("token_use") != "id"
        or not isinstance(claims.get("sub"), str)
    ):
        raise PermissionError("La sesión no corresponde al acceso de este taller.")

    issued, expires = claims.get("iat"), claims.get("exp")

    if (
        type(issued) is not int
        or type(expires) is not int
        or not issued <= current < expires
        or current >= issued + policy.max_session_seconds
    ):
        raise PermissionError("Tu sesión venció; vuelve a iniciar sesión.")

    team = policy.members.get(claims["sub"])

    if team is None:
        raise PermissionError(
            "Tu cuenta todavía no tiene un equipo asignado en la app."
        )

    return team
