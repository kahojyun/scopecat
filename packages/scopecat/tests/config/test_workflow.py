from __future__ import annotations

import pytest
from testkit.workflow_fixtures import load_config

from scopecat.config.resolution import validate_config_profile
from scopecat.kernel.errors import CheckFailed


def test_config_workflow_validates_complete_snapshot() -> None:
    config = load_config()

    assert validate_config_profile(config) == config


def test_config_workflow_validation_rejects_problems() -> None:
    config = load_config()
    route = config.routing.routes[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid_config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "routing": config.routing.model_copy(update={"routes": [route]})
                }
            )
        }
    )

    with pytest.raises(CheckFailed) as error:
        validate_config_profile(invalid_config)

    assert error.value.problems[0].code == (
        "configuration.unknown_resource_route_instrument"
    )
