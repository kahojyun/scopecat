"""Internal helpers for updating run manifests."""

from __future__ import annotations

from collections.abc import Iterable

from scopecat._storage.local import LocalRunStore
from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry, RunRecordEntry
from scopecat.models.run import RunManifest
from scopecat.runs.access import upsert_artifacts, upsert_datasets, upsert_records


def write_manifest_artifacts(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    artifacts: Iterable[RunArtifactEntry],
) -> None:
    """Upsert artifact entries into a manifest and persist the manifest."""
    with storage.run_lock(manifest.run_id):
        current = storage.read_manifest(manifest.run_id)
        current.artifacts = upsert_artifacts(current.artifacts, list(artifacts))
        storage.write_manifest(current)


def write_manifest_datasets(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    datasets: Iterable[RunDatasetEntry],
) -> None:
    """Upsert dataset entries into a manifest and persist the manifest."""
    with storage.run_lock(manifest.run_id):
        current = storage.read_manifest(manifest.run_id)
        current.datasets = upsert_datasets(current.datasets, list(datasets))
        storage.write_manifest(current)


def write_manifest_records(
    *,
    storage: LocalRunStore,
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
    storage: LocalRunStore,
    run_id: str,
    records: Iterable[RunRecordEntry],
) -> None:
    """Merge records while the caller holds ``storage.run_lock(run_id)``."""

    manifest = storage.read_manifest(run_id)
    manifest.records = upsert_records(manifest.records, list(records))
    storage.write_manifest(manifest)
