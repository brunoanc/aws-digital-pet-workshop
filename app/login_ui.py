"""Handle login and check the user's assigned team."""

import os

import streamlit as st

from app.access import authorize, load_policy


def require_team(path):
    """Check login and access before returning the user's team."""

    if not st.user.is_logged_in:
        st.session_state.clear()
        st.button("Iniciar sesión", on_click=st.login)
        st.stop()

    st.sidebar.button("Cerrar sesión", on_click=st.logout)

    try:
        policy = load_policy(path)
        claims = dict(st.user)
        team = authorize(policy, claims)
    except PermissionError as error:
        st.session_state.clear()
        st.warning(str(error))
        st.stop()
    except (OSError, ValueError, TypeError):
        st.session_state.clear()
        st.error("El acceso no está listo; avisa al organizador.")
        st.stop()

    identity = (policy.issuer, claims["sub"], team)

    if st.session_state.get("authorized_identity") != identity:
        st.session_state.clear()

        st.session_state["authorized_identity"] = identity

    return team


def main():
    """Show a standalone login check without loading the pet or chat."""

    st.set_page_config(page_title="Acceso al taller", page_icon="🐾")

    if st.get_option("server.address") not in ("127.0.0.1", "localhost", "::1"):
        st.error("El ensayo de acceso debe ejecutarse en loopback.")
        st.stop()

    path = os.environ.get("PET_ACCESS_CONFIG")

    if not path:
        st.error("Falta la configuración del acceso.")
        st.stop()

    team = require_team(path)

    st.success(f"Acceso confirmado: {team}")


if __name__ == "__main__":
    main()
