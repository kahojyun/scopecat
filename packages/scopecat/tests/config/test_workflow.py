from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.config.resolution import (
    resolve_experiment_config,
    validate_config_profile,
)
from scopecat.kernel.errors import CheckFailed
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.runtime import sqlite_project_services
from tests.testkit.workflow_fixtures import load_config


def test_resolve_experiment_config_normalizes_snapshot_and_profile(
    tmp_path: Path,
) -> None:
    services = sqlite_project_services(tmp_path)
    snapshot = load_config()

    direct = resolve_experiment_config(services=services, config=snapshot)
    profile = resolve_experiment_config(
        services=services,
        config="active",
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    assert direct.config == snapshot
    assert direct.config_source is None
    assert profile.config == snapshot
    assert profile.config_source is None


def test_config_workflow_validates_file_and_config_object() -> None:
    file_config = validate_config_profile(EXAMPLE_DIR / "config-profile.json")
    object_config = validate_config_profile(file_config)

    assert file_config.id == "simple-scan-profile"
    assert object_config == file_config


def test_config_workflow_validation_rejects_problems() -> None:
    config = load_config()
    binding = config.routing.bindings[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid_config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "routing": config.routing.model_copy(update={"bindings": [binding]})
                }
            )
        }
    )

    with pytest.raises(CheckFailed) as error:
        validate_config_profile(invalid_config)

    assert error.value.problems[0].code == (
        "configuration.unknown_routing_binding_instrument"
    )
