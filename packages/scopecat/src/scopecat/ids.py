"""Identifier helpers."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

SAFE_ARTIFACT_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


def new_run_id() -> str:
    """Return a sortable, human-readable run id."""

    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{stamp}_{uuid4().hex[:8]}"


def artifact_slug(value: str, *, fallback: str = "artifact") -> str:
    slug = SAFE_ARTIFACT_ID_RE.sub("-", value.strip()).strip("-").lower()
    return slug or fallback
