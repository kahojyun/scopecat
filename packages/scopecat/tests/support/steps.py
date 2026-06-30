from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from scopecat._steps import ArtifactInputDiagnostics, StepArtifactDiagnostics
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import load_config_profile
from tests.support.records import read_model
from tests.support.signal_testkit import execute_signal_native_run

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simulated_scan"


class StepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def artifact_diagnostics() -> StepArtifactDiagnostics:
    return StepArtifactDiagnostics(
        missing_id_code="test_missing_id",
        duplicate_id_code="test_duplicate_artifact",
        missing_kind_code="test_missing_kind",
        invalid_filename_code="test_invalid_filename",
        duplicate_filename_code="test_duplicate_artifact_filename",
        noun="test artifact",
        path_prefix="artifacts",
    )


def input_diagnostics() -> ArtifactInputDiagnostics:
    return ArtifactInputDiagnostics(
        not_found_code="test_input_not_found",
        invalid_kind_code="test_input_invalid_kind",
        path_escape_code="test_input_path_escape",
        not_found_message="test input artifact not found",
        invalid_kind_message="test input artifact kind is unsupported",
        path_escape_message="test input selector escapes run directory",
        diagnostic_path="input",
    )


def make_simulated_run(tmp_path: Path) -> str:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    experiment = read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)
    manifest, _snapshot = execute_signal_native_run(
        config=config,
        experiment=experiment,
        workspace=tmp_path,
    )
    return manifest.run_id
