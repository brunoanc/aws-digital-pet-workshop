"""Show the chat for the agent written in the Lambda console."""

import boto3
import streamlit as st

from app.card import render_card
from app.browser_url import remember_url, restore_url, url_scope
from app.remote import RemoteAgent, RequestLimitError, load_remote_settings


def render_remote(
    settings,
    config_path=None,
    *,
    remote_settings=None,
    agent_factory=None,
    card_renderer=None,
):
    """Show the pet and chat without extra prompt or tool controls."""

    try:
        remote = remote_settings or load_remote_settings(config_path)
    except (OSError, ValueError, TypeError):
        st.error("Revisa PET_AGENT_CONFIG antes de conectar el chat a Lambda.")
        st.stop()

    signature = (settings, remote)

    if st.session_state.get("remote_signature") != signature:
        st.session_state.remote_signature = signature
        st.session_state.remote_history = []
        st.session_state.remote_tools = None
        st.session_state.connected_url = None
        st.session_state.saved_url_attempted = False
        st.session_state.scene_pending = []
        st.session_state.scene_seen = []

    st.sidebar.caption(f"Agente: {remote.function_name}")

    saved = None
    if remote.function_url is not None:
        scope = url_scope(settings, remote)
        saved = remember_url(scope, st.session_state.get("connected_url"))
        restore_url(
            scope,
            remote,
            saved,
            st.session_state,
            lambda url: make_agent(settings, remote, agent_factory).connect(url),
        )

    connected = (
        remote.function_url is None
        or st.session_state.get("connected_url") == remote.function_url
    )

    if remote.function_url is not None:
        saved_url = (
            remote.function_url
            if isinstance(saved, dict)
            and saved.get("scope") == scope
            and saved.get("url") == remote.function_url
            else ""
        )
        with st.expander("Conexión del agente", expanded=not connected):
            with st.form("connect_agent_url"):
                submitted_url = st.text_input(
                    "Function URL de tu agente",
                    value=st.session_state.get("connected_url") or saved_url,
                    max_chars=256,
                )
                connect = st.form_submit_button("Conectar")
            if isinstance(saved, dict) and saved.get("available") is False:
                st.caption(
                    "El navegador bloqueó el guardado de la URL; puedes conectarla manualmente."
                )
            else:
                st.caption("La URL validada se recuerda en este navegador para este equipo.")

        if connect:
            st.session_state.saved_url_attempted = True
            st.session_state.connected_url = None
            st.session_state.remote_history = []
            st.session_state.remote_tools = None
            st.session_state.scene_pending = []

            try:
                agent = make_agent(settings, remote, agent_factory)
                st.session_state.connected_url = agent.connect(submitted_url)
            except Exception:
                st.error(
                    "No se pudo conectar; revisa la URL de tu equipo, tu sesión y los permisos."
                )
            else:
                st.rerun()

            connected = False

        if connected:
            st.caption("● Agente conectado")

    if st.sidebar.button("Limpiar historial", key="clear_remote_history"):
        st.session_state.remote_history = []
        st.session_state.remote_tools = None

    tools = st.session_state.remote_tools

    st.sidebar.text(
        "Herramientas disponibles en el agente: "
        + ("sin consultar" if tools is None else ", ".join(tools) or "ninguna")
    )

    habitat, chat = st.columns([1.15, 1], gap="large")

    with habitat:
        if card_renderer is None:
            render_card(settings, visual=True)
        else:
            card_renderer()

    with chat:
        with st.container(border=True, key="agent_chat"):
            st.subheader("Habla con su cuidador")
            st.caption("Sin memoria entre mensajes")
            render_chat(settings, remote, connected, agent_factory)


def render_chat(settings, remote, connected, agent_factory=None):
    """Show messages and keep new tool activity for animation checks."""

    for entry in st.session_state.remote_history:
        with st.chat_message(entry["role"]):
            st.markdown(entry["text"], unsafe_allow_html=False)

            if entry.get("activity"):
                with st.expander("Actividad de las herramientas"):
                    st.json(entry["activity"])

    message = st.chat_input(
        "Envía un mensaje...",
        max_chars=settings.max_input_chars,
        disabled=not connected,
    )

    if message:
        try:
            with st.spinner("Ejecutando tu agente en Lambda…"):
                result = make_agent(settings, remote, agent_factory).send(message)

            st.session_state.remote_tools = result["registered_tools"]
        except RequestLimitError as error:
            result = {"message": str(error), "activity": []}
        except Exception:
            st.session_state.remote_tools = None
            result = {
                "message": "No se pudo confirmar el resultado; revisa la ficha y los logs antes de repetir un cuidado.",
                "activity": [],
            }

        st.session_state.remote_history.extend(
            [
                {"role": "user", "text": message},
                {
                    "role": "assistant",
                    "text": result["message"],
                    "activity": result["activity"],
                },
            ]
        )

        st.session_state.remote_history = st.session_state.remote_history[
            -2 * settings.max_messages :
        ]
        st.session_state.card_refresh = True
        st.session_state.scene_pending = result.get("activity", [])

        st.rerun()


def make_agent(settings, remote, factory=None):
    """Use the shared adapter if supplied or the local SSO session otherwise."""

    if factory is not None:
        return factory()

    session = boto3.Session(profile_name=settings.profile, region_name=settings.region)

    return RemoteAgent(settings, remote, session)
