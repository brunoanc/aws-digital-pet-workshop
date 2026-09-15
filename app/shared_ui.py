"""Show the assigned pet and optional chat after login without using local SSO profiles."""

import os

import streamlit as st

from app.login_ui import require_team
from app.access import authorize, load_policy
from app.card import render_indicators
from app.card_limits import CardReadLimitError
from app.scene import ASSETS, scene_html
from app.shared_card import read_card
from app.shared_card import load_targets
from app.shared_agent import SharedAgent
from app.remote_ui import render_remote
from app.scene import render_scene, verified_action


def main():
    """Check access and show the team's pet and configured chat."""

    st.set_page_config(page_title="Mi mascota en AWS", page_icon="🐾", layout="wide")

    access = os.environ.get("PET_ACCESS_CONFIG")
    targets = os.environ.get("PET_CARD_CONFIG")

    if (
        st.get_option("server.address") not in ("127.0.0.1", "localhost", "::1")
        or not access
        or not targets
    ):
        st.error("La app no está lista; avisa al organizador.")
        st.stop()

    team = require_team(access)

    st.html("<style>" + (ASSETS / "theme.css").read_text() + "</style>")

    if "agent" not in load_targets(targets)["teams"].get(team, {}):
        with st.container(border=True, key="pet_card"):
            render_authenticated_card(access, targets)

        return

    adapter = SharedAgent(access, targets, dict(st.user))

    def factory():
        """Create a checked adapter for each connection or message."""

        return SharedAgent(access, targets, dict(st.user))

    def card():
        """Show the team's pet beside the chat."""

        with st.container(border=True, key="pet_card"):
            render_authenticated_card(access, targets, adapter)

    render_remote(
        adapter.settings,
        remote_settings=adapter.remote,
        agent_factory=factory,
        card_renderer=card,
    )


def render_authenticated_card(access, targets, adapter=None):
    """Keep the session's card and check access on every render."""

    refresh = st.button("Actualizar ficha", key="refresh_pet_card")
    claims = dict(st.user)

    try:
        policy = load_policy(access)
        team = authorize(policy, claims)
        destinations = load_targets(targets)
        target = destinations["teams"].get(team)
        if target is None:
            raise PermissionError("La ficha de tu equipo todavía no está habilitada.")

        scope = (
            policy.issuer, claims.get("sub"), team,
            destinations["account_id"], destinations["region"], target,
        )
    except PermissionError as error:
        st.session_state.pop("shared_card", None)
        st.warning(str(error))
        st.stop()
    except Exception:
        st.session_state.pop("shared_card", None)
        st.error(
            "No pude leer tu mascota; intenta actualizar la ficha o avisa al organizador."
        )
        st.stop()

    if st.session_state.get("shared_card", {}).get("scope") != scope:
        st.session_state.shared_card = {
            "scope": scope, "snapshot": None, "error": None,
        }

    card = st.session_state.shared_card
    requested = st.session_state.pop("card_refresh", False)
    fresh = False
    if refresh or requested or card["snapshot"] is None:
        try:
            _, snapshot = read_card(access, targets, claims)
            card["snapshot"] = snapshot
            card["error"] = None
            fresh = True
        except CardReadLimitError as error:
            card["error"] = str(error)
        except PermissionError as error:
            st.session_state.pop("shared_card", None)
            st.warning(str(error))
            st.stop()
        except Exception:
            card["error"] = (
                "No pude actualizar la ficha; intenta de nuevo o avisa al organizador."
            )

    if card["error"]:
        st.info(card["error"])

    snapshot = card["snapshot"]
    if snapshot is None:
        st.session_state.pop("scene_pending", None)
        return

    pet = snapshot["pet"]

    if adapter is None:
        st.iframe(scene_html(pet, scope=team), height=400)
    else:

        def verify(settings, event, current):
            """Verify action receipts using the team's temporary role."""

            result = verified_action(
                settings, event, current, session_factory=adapter.session
            )

            adapter.check()

            return result

        render_scene(adapter.settings, snapshot, fresh, verifier=verify)

    label = "Última lectura válida, sin actualizar" if card["error"] else "Última lectura"
    st.caption(label + ": " + snapshot["read_at"])

    render_indicators(pet)


if __name__ == "__main__":
    main()
