"""Shared run reference helpers."""

from __future__ import annotations

from scopecat.models.run import RunManifest

RunRef = str | RunManifest


def run_id(run: RunRef) -> str:
    if isinstance(run, str):
        return run
    return run.run_id


__all__ = ["RunRef", "run_id"]
