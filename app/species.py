"""Resolve catalog species independently of the system locale."""

from pathlib import Path
import unicodedata


ASSETS = Path(__file__).resolve().parent / "assets"
SPECIES = {"dragon": "Dragón", "gato": "Gato", "zorro": "Zorro", "ajolote": "Ajolote"}


def species_key(value):
    """Normalize Unicode, case, accents, and outer whitespace without accepting aliases."""

    if not isinstance(value, str):
        return None

    normalized = unicodedata.normalize("NFKD", value.strip().casefold())
    key = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )

    return key if key in SPECIES else None


def species_art(value):
    """Load only a local catalog illustration or the generic pet asset."""

    key = species_key(value)

    return (ASSETS / f"{key or 'unknown'}.svg").read_text(encoding="utf-8")
