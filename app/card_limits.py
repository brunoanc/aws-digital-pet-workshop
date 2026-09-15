"""Limit card reads across sessions on the shared host."""

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import time


class CardReadLimitError(Exception):
    """Report a blocked card read without blocking the chat."""


@contextmanager
def card_read_slot(team, directory="/var/lib/workshop-login", interval=None):
    """Reserve one read per team and keep the cooldown after failed AWS calls."""

    if not re.fullmatch(r"team-[0-9]{2}", team):
        raise ValueError("Specify a valid team for the card counter.")

    interval = float(
        os.environ.get("PET_CARD_MIN_INTERVAL_SECONDS", "2")
        if interval is None
        else interval
    )

    if not math.isfinite(interval) or not 1 <= interval <= 60:
        raise ValueError("Set the card read interval between 1 and 60 seconds.")

    path = Path(directory) / (team + "-card-reads.json")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)

    with os.fdopen(descriptor, "r+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CardReadLimitError(
                "Tu equipo ya está consultando la ficha; espera un momento y actualízala."
            ) from None

        raw = stream.read()
        last = json.loads(raw)["last"] if raw else None

        if last is not None and (
            type(last) not in (int, float) or not math.isfinite(last) or last < 0
        ):
            raise ValueError("Check the saved card read timestamp.")

        now = time.time()

        if last is not None and now - last < interval:
            raise CardReadLimitError(
                "Espera unos segundos y pulsa Actualizar ficha para ver el estado actual."
            )

        stream.seek(0)
        json.dump({"last": now}, stream)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())

        yield
