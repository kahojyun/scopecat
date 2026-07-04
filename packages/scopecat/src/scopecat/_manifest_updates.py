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
    manifest.artifacts = upsert_artifacts(manifest.artifacts, list(artifacts))
    storage.write_manifest(manifest)


def write_manifest_datasets(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    datasets: Iterable[RunDatasetEntry],
) -> None:
    """Upsert dataset entries into a manifest and persist the manifest."""
    manifest.datasets = upsert_datasets(manifest.datasets, list(datasets))
    storage.write_manifest(manifest)


def write_manifest_records(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    records: Iterable[RunRecordEntry],
) -> None:
    """Upsert workflow record entries into a manifest and persist the manifest."""
    manifest.records = upsert_records(manifest.records, list(records))
    storage.write_manifest(manifest)
