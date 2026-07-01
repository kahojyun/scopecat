from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.reporting import build_run_overview
from scopecat.runs import open_run_store
from tests.support.config_registry import seed_best_signal_proposal
from tests.support.reporting import simulate


def test_build_run_overview_rejects_proposal_path_escape(tmp_path: Path) -> None:
    run_id = simulate(tmp_path)
    seed_best_signal_proposal(tmp_path=tmp_path, run_id=run_id)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    proposal_artifact = next(
        artifact
        for artifact in manifest.artifact_refs
        if artifact.kind == "parameter_change_set"
    )
    proposal_artifact.path = "../escape.json"
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        build_run_overview(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "artifact_path_escape"


def test_build_run_overview_rejects_directory_artifact(tmp_path: Path) -> None:
    run_id = simulate(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    manifest.artifact_refs.append(
        Artifact(
            id="bad-dir",
            kind="bad",
            path="artifacts",
            media_type="application/json",
        )
    )
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        build_run_overview(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "report_artifact_is_directory"
