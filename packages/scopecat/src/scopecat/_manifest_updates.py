"""Internal helpers for updating run manifests."""

from __future__ import annotations

from collections.abc import Iterable

from scopecat._storage.local import LocalRunStore
from scopecat.models.artifact import Artifact
from scopecat.models.run import RunManifest
from scopecat.runs.access import upsert_artifacts


def write_manifest_artifacts(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    artifacts: Iterable[Artifact],
) -> None:
    """Upsert artifact refs into a manifest and persist the manifest."""
    manifest.artifact_refs = upsert_artifacts(manifest.artifact_refs, list(artifacts))
    storage.write_manifest(manifest)
