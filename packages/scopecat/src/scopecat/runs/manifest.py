"""Internal helpers for updating run manifests."""

from __future__ import annotations

from collections.abc import Iterable

from scopecat.records.artifact import RunArtifactEntry, RunRecordEntry
from scopecat.records.run import RunManifest
from scopecat.runs.access import upsert_artifacts, upsert_records
from scopecat.runs.repository import RunRepository


def write_manifest_artifacts(
    *,
    storage: RunRepository,
    manifest: RunManifest,
    artifacts: Iterable[RunArtifactEntry],
) -> None:
    """Upsert artifact entries into a manifest and persist the manifest."""
    with storage.run_lock(manifest.run_id):
        current = storage.read_manifest(manifest.run_id)
        updated = current.model_copy(
            update={"artifacts": upsert_artifacts(current.artifacts, tuple(artifacts))}
        )
        storage.write_manifest(updated)


def write_manifest_records(
    *,
    storage: RunRepository,
    manifest: RunManifest,
    records: Iterable[RunRecordEntry],
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
    records: Iterable[RunRecordEntry],
) -> None:
    """Merge records while the caller holds ``storage.run_lock(run_id)``."""

    manifest = storage.read_manifest(run_id)
    updated = manifest.model_copy(
        update={"records": upsert_records(manifest.records, tuple(records))}
    )
    storage.write_manifest(updated)
