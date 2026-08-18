"""Integrity checks for the durable run configuration evidence chain."""

from __future__ import annotations

from scopecat.kernel.errors import DataIntegrityError
from scopecat.kernel.problems import (
    ProblemPhase,
    StorageLocation,
    problem,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import RunSnapshot
from scopecat.runs.refs import CONFIG_PROFILE_SNAPSHOT_REF


def validate_run_config_provenance(
    *,
    snapshot: RunSnapshot,
    config: ConfigProfileSnapshot,
) -> None:
    """Require persisted configuration evidence hashes to agree."""

    actual_hash = config_content_hash(config)
    hashes = {
        "config_snapshot": actual_hash,
        "run_snapshot": snapshot.config_content_hash,
    }
    if snapshot.config_source is not None:
        hashes["snapshot_config_source"] = snapshot.config_source.content_hash
    if len(set(hashes.values())) == 1:
        return
    raise DataIntegrityError(
        [
            problem(
                "run.config_provenance_mismatch",
                "run configuration hash evidence does not match the accepted snapshot",
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(
                    run_id=snapshot.run_id,
                    ref=CONFIG_PROFILE_SNAPSHOT_REF,
                ),
                details=hashes,
            )
        ]
    )
