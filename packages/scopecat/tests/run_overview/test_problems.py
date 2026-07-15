from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.composition.local import local_run_repository, local_workspace_services
from scopecat.kernel.errors import DataIntegrityError
from scopecat.records.artifact import RunArtifactEntry
from scopecat.run_overview import build_run_overview
from scopecat.runs.access import (
    artifact_storage_ref,
)
from tests.testkit.run_overview import run_signal_experiment


def test_run_local_artifact_rejects_path_id() -> None:
    with pytest.raises(ValueError):
        RunArtifactEntry(id="../escape", kind="bad")


def test_build_run_overview_rejects_directory_artifact(tmp_path: Path) -> None:
    run_id = run_signal_experiment(tmp_path)
    storage = local_run_repository(tmp_path)
    manifest = storage.read_manifest(run_id)
    artifact = RunArtifactEntry(
        id="bad-dir",
        kind="bad",
        media_type="application/json",
    )
    storage.write_manifest(
        manifest.model_copy(update={"artifacts": (*manifest.artifacts, artifact)})
    )
    storage.ref_path(run_id, artifact_storage_ref(artifact)).mkdir(parents=True)

    with pytest.raises(DataIntegrityError) as error:
        build_run_overview(run_id=run_id, services=local_workspace_services(tmp_path))

    assert error.value.problems[0].code == "overview_ref_is_directory"
