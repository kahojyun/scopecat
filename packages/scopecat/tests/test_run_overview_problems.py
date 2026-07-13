from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import DataIntegrityError
from scopecat.models.artifact import RunArtifactEntry
from scopecat.run_overview import build_run_overview
from scopecat.runs import artifact_storage_ref, open_run_store
from tests.support.run_overview import run_signal_experiment


def test_run_local_artifact_rejects_path_id() -> None:
    with pytest.raises(ValueError):
        RunArtifactEntry(id="../escape", kind="bad")


def test_build_run_overview_rejects_directory_artifact(tmp_path: Path) -> None:
    run_id = run_signal_experiment(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    artifact = RunArtifactEntry(
        id="bad-dir",
        kind="bad",
        media_type="application/json",
    )
    manifest.artifacts.append(artifact)
    storage.write_manifest(manifest)
    storage.ref_path(run_id, artifact_storage_ref(artifact)).mkdir(parents=True)

    with pytest.raises(DataIntegrityError) as error:
        build_run_overview(run_id=run_id, workspace=tmp_path)

    assert error.value.problems[0].code == "overview_ref_is_directory"
