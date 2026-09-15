"""Remember a checked Function URL in this browser for each team and agent."""

import hashlib
import json
from pathlib import Path

import streamlit as st


url_storage = st.components.v2.component(
    "agent_url_storage",
    js=(Path(__file__).parent / "assets" / "browser_url.js").read_text(),
)


def url_scope(settings, remote):
    """Separate saved URLs by account, region, team and function."""

    target = [
        settings.account_id,
        settings.region,
        settings.team_id,
        remote.function_name,
    ]
    return hashlib.sha256(json.dumps(target).encode()).hexdigest()


def remember_url(scope, connected_url):
    """Read local storage or save the URL after its connection check."""

    result = url_storage(
        key="agent_url_" + scope,
        data={"scope": scope, "url": connected_url},
        default={"stored": None},
        on_stored_change=lambda: None,
        height=0,
    )
    return getattr(result, "stored", None)


def restore_url(scope, remote, saved, state, connect):
    """Recheck a saved URL once per session; browser storage grants no access."""

    if (
        state.get("saved_url_attempted")
        or not isinstance(saved, dict)
        or saved.get("scope") != scope
    ):
        return

    state["saved_url_attempted"] = True
    url = saved.get("url")
    if not isinstance(url, str) or url != remote.function_url:
        return

    try:
        checked = connect(url)
    except Exception:
        return

    if checked == remote.function_url:
        state["connected_url"] = checked
