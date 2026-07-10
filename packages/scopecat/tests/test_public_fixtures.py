from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat.config_profiles import load_config_profile
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import build_config_parameters
from tests.support.experiment_preview import preview_contract
from tests.support.records import read_model

REPO_ROOT = Path(__file__).parents[3]
FIXTURE_ROOT = REPO_ROOT / "fixtures"


def test_public_experiment_json_fixtures_are_specs() -> None:
    experiment_files = sorted(FIXTURE_ROOT.glob("**/experiment.json"))

    assert experiment_files
    for path in experiment_files:
        experiment = read_model(path, ExperimentSpec)
        assert experiment.schema_version == "scopecat.experiment_spec.v7", path


def test_experiment_spec_rejects_previous_wire_version() -> None:
    path = next(iter(sorted(FIXTURE_ROOT.glob("**/experiment.json"))))
    payload = path.read_text().replace(
        "scopecat.experiment_spec.v7",
        "scopecat.experiment_spec.v6",
    )

    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate_json(payload)


def test_public_experiment_json_fixtures_plan_with_local_config() -> None:
    experiment_files = sorted(FIXTURE_ROOT.glob("**/experiment.json"))

    assert experiment_files
    for path in experiment_files:
        config = load_config_profile(path.parent / "config-profile.json")
        parameter_view = build_config_parameters(config)
        experiment = read_model(path, ExperimentSpec)
        preview = preview_contract(experiment, parameter_view)
        assert preview.points, path
        assert preview.records, path
