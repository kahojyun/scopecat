"""Integrity checks for the durable run configuration evidence chain."""

from __future__ import annotations

from scopecat.kernel.errors import DataIntegrityError
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import RunManifest
from scopecat.runs.refs import CONFIG_PROFILE_SNAPSHOT_REF


def validate_run_config_provenance(
    *,
    manifest: RunManifest,
    config: ConfigProfileSnapshot,
) -> None:
    """Require the manifest and persisted accepted snapshot hashes to agree."""

    actual_hash = config_content_hash(config)
    hashes = {
        "config_snapshot": actual_hash,
        "manifest": manifest.config_content_hash,
    }
    if manifest.config_source is not None:
        hashes["manifest_config_source"] = manifest.config_source.content_hash
    if len(set(hashes.values())) == 1:
        return
    raise DataIntegrityError(
        [
            blocking_problem(
                "run.config_provenance_mismatch",
                "run configuration hash evidence does not match the accepted snapshot",
                category=ProblemCategory.DATA_INTEGRITY,
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(
                    run_id=manifest.run_id,
                    ref=CONFIG_PROFILE_SNAPSHOT_REF,
                ),
                details=hashes,
            )
        ]
    )
