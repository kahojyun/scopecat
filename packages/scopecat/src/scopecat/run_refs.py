"""Shared run reference helpers."""

from __future__ import annotations

from scopecat.models.run import RunManifest
from scopecat.workflows._types import StartRunResult

RunRef = str | RunManifest | StartRunResult


def run_id(run: RunRef) -> str:
    if isinstance(run, str):
        return run
    if isinstance(run, StartRunResult):
        return run.manifest.run_id
    return run.run_id


__all__ = ["RunRef", "run_id"]
