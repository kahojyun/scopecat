"""Terminal run manifest updates."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.records.artifact import RunContentEntry
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.access import upsert_contents


def merge_terminal_manifest(
    current: RunManifest,
    *,
    run_id: str,
    outcome: RunOutcome,
    contents: Sequence[RunContentEntry] = (),
) -> RunManifest:
    """Apply terminal evidence to the latest durable manifest.

    The repository owns provenance so a stale executor cannot erase content or
    replace the accepted configuration baseline.
    """

    if current.run_id != run_id or outcome.run_id != run_id:
        raise ValueError("terminal merge run id does not match durable state")
    applied_outcome = current.outcome if current.outcome is not None else outcome
    return current.model_copy(
        update={
            "outcome": applied_outcome,
            "contents": upsert_contents(current.contents, contents),
        }
    )


__all__ = ["merge_terminal_manifest"]
