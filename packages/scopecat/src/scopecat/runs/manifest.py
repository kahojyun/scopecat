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
    with storage.run_lock(manifest.run_id):
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
    with storage.run_lock(manifest.run_id):
        write_manifest_records_locked(
            storage=storage,
            run_id=manifest.run_id,
            records=records,
        )


def write_manifest_records_locked(
    *,
    storage: RunRepository,
    run_id: str,
    records: Iterable[RunContentEntry],
) -> None:
    """Merge records while the caller holds ``storage.run_lock(run_id)``."""

    manifest = storage.read_manifest(run_id)
    updated = manifest.model_copy(
        update={"contents": upsert_contents(manifest.contents, tuple(records))}
    )
    storage.write_manifest(updated)
