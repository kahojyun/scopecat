from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from scopecat.adapters.filesystem.steps import (
    ArtifactInputContract,
    StepArtifactContract,
)
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.problems import model_location
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.signal_testkit import execute_signal_run
from tests.testkit.workflow_fixtures import load_invocation


class StepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def artifact_contract() -> StepArtifactContract:
    return StepArtifactContract(
        missing_id_code="test_missing_id",
        duplicate_id_code="test_duplicate_artifact",
        missing_kind_code="test_missing_kind",
        noun="test artifact",
        location_root="artifacts",
    )


def input_contract() -> ArtifactInputContract:
    return ArtifactInputContract(
        not_found_code="test_input_not_found",
        invalid_kind_code="test_input_invalid_kind",
        path_escape_code="test_input_path_escape",
        not_found_message="test input artifact not found",
        invalid_kind_message="test input artifact kind is unsupported",
        path_escape_message="test input selector escapes run directory",
        location=model_location("run_access", "input"),
    )


def make_signal_run(tmp_path: Path) -> str:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    manifest, _snapshot = execute_signal_run(
        config=config,
        experiment=load_invocation(),
        workspace=tmp_path,
    )
    return manifest.run_id
