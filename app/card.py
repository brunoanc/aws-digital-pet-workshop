"""Show the pet's real state without sending it to the agent."""

from datetime import datetime, timezone
from uuid import uuid4

import boto3
import streamlit as st

from app.backend import PetBackend
from app.scene import render_scene


def load_snapshot(settings):
    """Read and check pet data without changing it."""

    session = boto3.Session(profile_name=settings.profile, region_name=settings.region)
    backend = PetBackend(settings, session)

    backend.preflight()

    result = backend.invoke("inspect", {}, str(uuid4()))
    pet = result.get("pet")

    if result.get("success") is not True or not isinstance(pet, dict):
        raise ValueError("The pet snapshot could not be retrieved.")

    return validated_snapshot(pet, settings.team_id)


def validated_snapshot(pet, team_id):
    """Check the pet's fields and team, then record the read time."""

    if not isinstance(pet, dict) or pet.get("pet_id") != team_id:
        raise ValueError("The snapshot does not match the configured team.")

    for field in ("name", "species"):
        if not isinstance(pet.get(field), str) or not 1 <= len(pet[field]) <= 100:
            raise ValueError("The pet name or species is invalid.")

    for field in ("health", "fullness", "energy", "happiness"):
        if type(pet.get(field)) is not int or not 0 <= pet[field] <= 100:
            raise ValueError("The snapshot contains an out-of-range metric.")

    for field, minimum in (("experience", 0), ("version", 1)):
        if type(pet.get(field)) is not int or not minimum <= pet[field] <= 10**9:
            raise ValueError("The pet experience or version is invalid.")

    inventory = pet.get("inventory")

    if not isinstance(inventory, dict) or any(
        type(inventory.get(food)) is not int or not 0 <= inventory[food] <= 1000
        for food in ("healthy_meal", "cake")
    ):
        raise ValueError("The pet inventory is invalid.")

    return {"pet": pet, "read_at": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")}


def render_card(settings, visual=False):
    """Show the latest valid card and refresh on load, after chat or on request."""

    if st.session_state.get("card_settings") != settings:
        st.session_state.card_settings = settings
        st.session_state.pet_snapshot = None
        st.session_state.card_refresh = True
        st.session_state.card_error = False

    with st.container(border=True, key="pet_card"):
        if not visual:
            st.subheader("🐾 Tu mascota")

        refresh = st.button("Actualizar ficha", key="refresh_pet_card")

        if refresh or st.session_state.get("card_refresh", False):
            st.session_state.card_refresh = False

            try:
                with st.spinner("Leyendo la mascota…"):
                    st.session_state.pet_snapshot = load_snapshot(settings)

                st.session_state.card_error = False
            except Exception:
                st.session_state.card_error = True

        if st.session_state.card_error:
            st.warning(
                "No se pudo actualizar la ficha; revisa la sesión SSO y los permisos y pulsa Actualizar ficha."
            )

        snapshot = st.session_state.pet_snapshot

        if snapshot is None:
            st.session_state.pop("scene_pending", None)
            st.info("Estado no disponible.")

            return

        pet = snapshot["pet"]

        if visual:
            render_scene(settings, snapshot, not st.session_state.card_error)
        else:
            st.text(f"{pet['name']} · {pet['species']}")

        freshness = (
            "Última lectura válida, sin actualizar"
            if st.session_state.card_error
            else "Última lectura"
        )

        st.caption(f"{freshness}: {snapshot['read_at']}")

        render_indicators(pet)


def render_indicators(pet):
    """Show pet stats with large icons and labeled inventory counts."""

    indicators = (
        ("❤️", "Salud", "health"),
        ("🍽️", "Saciedad", "fullness"),
        ("⚡", "Energía", "energy"),
        ("😊", "Felicidad", "happiness"),
    )

    st.html("""<style>
            .st-key-pet_indicators [data-testid="stMetricLabel"] p {
                font-size: 2.25rem;
                line-height: 1.35;
            }
        </style>""")

    with st.container(key="pet_indicators"):
        for column, (icon, label, field) in zip(st.columns(4), indicators):
            with column:
                st.metric(icon, f"{pet[field]}/100", help=label)
                st.progress(pet[field])

    experience, meals, cakes = st.columns(3)

    experience.metric("Experiencia", f"{pet['experience']} puntos")
    meals.metric("Comidas saludables", pet["inventory"]["healthy_meal"])
    cakes.metric("Pasteles", pet["inventory"]["cake"])
