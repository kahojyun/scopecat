"""Worker-only backend composition for the virtual instrument lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.sdk.instruments import InstrumentBackend

from .provider import InstrumentDemoProvider


def create_backend(_project_root: Path) -> InstrumentBackend:
    return InstrumentBackend(provider=InstrumentDemoProvider(seed=7))


__all__ = ["create_backend"]
