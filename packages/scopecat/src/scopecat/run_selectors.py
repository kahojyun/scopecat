"""Shared run selector helpers."""

from __future__ import annotations

from scopecat.models.run import RunManifest

RunSelector = str | RunManifest


def selected_run_id(run: RunSelector) -> str:
    if isinstance(run, str):
        return run
    return run.run_id


__all__ = ["RunSelector", "selected_run_id"]
