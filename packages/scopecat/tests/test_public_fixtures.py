from __future__ import annotations

from pathlib import Path

from scopecat.config_profiles import load_config_profile
from scopecat.experiments import ExperimentSpec, plan_experiment
from tests.support.records import read_model

REPO_ROOT = Path(__file__).parents[3]
FIXTURE_ROOT = REPO_ROOT / "fixtures"


def test_public_experiment_json_fixtures_are_specs() -> None:
    experiment_files = sorted(FIXTURE_ROOT.glob("**/experiment.json"))

    assert experiment_files
    for path in experiment_files:
        experiment = read_model(path, ExperimentSpec)
        assert experiment.schema_version == "scopecat.experiment_spec.v1", path


def test_public_experiment_json_fixtures_plan_with_local_config() -> None:
    experiment_files = sorted(FIXTURE_ROOT.glob("**/experiment.json"))

    assert experiment_files
    for path in experiment_files:
        config = load_config_profile(path.parent / "config-profile.json")
        assert config.parameter_build is not None, path
        experiment = read_model(path, ExperimentSpec)
        plan = plan_experiment(experiment, config.parameter_build)
        assert plan.schema_version == "scopecat.plan_snapshot.v1", path
        assert plan.points, path
        assert plan.acquisition.estimated_records > 0, path
