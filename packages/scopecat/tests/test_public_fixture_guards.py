from __future__ import annotations

import json
from pathlib import Path

from scopecat.experiments import ExperimentSpec, plan_experiment
from scopecat.models.config import (
    ConfigProfile,
    EnvironmentSpec,
    SystemSpec,
    load_config_profile,
)
from scopecat.models.parameter import ParameterState
from tests.support.records import read_model

REPO_ROOT = Path(__file__).parents[3]
FIXTURE_ROOT = REPO_ROOT / "fixtures"
DOCS_ROOT = REPO_ROOT / "docs"


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


def test_public_json_fixtures_do_not_reference_legacy_sources() -> None:
    json_files = sorted(FIXTURE_ROOT.glob("**/*.json"))

    assert json_files
    for path in json_files:
        data = _load_public_json_fixture_payload(path)
        assert not _json_contains_legacy_term(data), path


def test_public_json_fixtures_do_not_use_domain_metadata_key() -> None:
    json_files = sorted(FIXTURE_ROOT.glob("**/*.json"))

    assert json_files
    for path in json_files:
        data = _load_public_json_fixture_payload(path)
        assert not _json_contains_key(data, "domain"), path


def test_user_facing_docs_do_not_use_removed_acquisition_helper_examples() -> None:
    docs = sorted(DOCS_ROOT.glob("*.md"))

    assert docs
    for path in docs:
        assert "acquire=iq(" not in path.read_text(), path


def _json_contains_legacy_term(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            "legacy" in str(key).lower() or _json_contains_legacy_term(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_json_contains_legacy_term(item) for item in value)
    if isinstance(value, str):
        return "legacy" in value.lower()
    return False


def _json_contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _json_contains_key(child, key) for child in value.values()
        )
    if isinstance(value, list):
        return any(_json_contains_key(item, key) for item in value)
    return False


def _load_public_json_fixture_payload(path: Path) -> object:
    raw_text = path.read_text()
    match path.name:
        case "experiment.json":
            return ExperimentSpec.model_validate_json(raw_text).model_dump(mode="json")
        case "config-profile.json":
            return ConfigProfile.model_validate_json(raw_text).model_dump(mode="json")
        case "system-spec.json":
            return SystemSpec.model_validate_json(raw_text).model_dump(mode="json")
        case "environment-spec.json":
            return EnvironmentSpec.model_validate_json(raw_text).model_dump(mode="json")
        case "parameter-state.json":
            return ParameterState.model_validate_json(raw_text).model_dump(mode="json")
        case _:
            return json.loads(raw_text)
