"""Internal helpers for updating run manifests."""

from __future__ import annotations

from collections.abc import Iterable

from scopecat.records.artifact import RunContentEntry
from scopecat.records.run import RunManifest
from scopecat.runs.access import upsert_contents
from scopecat.runs.repository import RunRepository


def write_manifest_artifacts(
    *,
    storage: RunRepository,
    manifest: RunManifest,
    artifacts: Iterable[RunContentEntry],
) -> None:
    """Upsert artifact entries into a manifest and persist the manifest."""
    current = storage.read_manifest(manifest.run_id)
    updated = current.model_copy(
        update={"contents": upsert_contents(current.contents, tuple(artifacts))}
    )
    storage.write_manifest(updated)


def write_manifest_records(
    *,
    storage: RunRepository,
    manifest: RunManifest,
    records: Iterable[RunContentEntry],
) -> None:
    """Upsert workflow record entries into a manifest and persist the manifest."""
    current = storage.read_manifest(manifest.run_id)
    updated = current.model_copy(
        update={"contents": upsert_contents(current.contents, tuple(records))}
    )
    storage.write_manifest(updated)
