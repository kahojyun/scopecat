"""Identifier helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def new_run_id() -> str:
    """Return a sortable, human-readable run id."""

    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{stamp}_{uuid4().hex[:8]}"
