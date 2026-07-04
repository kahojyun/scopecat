from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat.config_profiles import load_config_profile
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.planning.validation import (
    has_blocking_diagnostics,
    validate_config,
)

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def test_valid_example_has_no_blocking_diagnostics() -> None:
    config = load_config()

    diagnostics = validate_config(config)

    assert not has_blocking_diagnostics(diagnostics)


def test_unsupported_unit_fails_model_validation() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["parameter_state"]["scalar_values"]["values"][0]["quantity"]["unit"] = (
        "furlong"
    )

    with pytest.raises(ValidationError):
        ConfigProfileSnapshot.model_validate(config_data)


def test_parameter_value_without_definition_is_error() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["parameter_catalog"]["scalar_definitions"] = []
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "unknown_parameter_value_definition"


def test_duplicate_parameter_id_fails_model_validation() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["parameter_state"]["scalar_values"]["values"].append(
        config_data["parameter_state"]["scalar_values"]["values"][0]
    )

    with pytest.raises(ValidationError):
        ConfigProfileSnapshot.model_validate(config_data)


def test_incompatible_parameter_value_unit_is_error() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["parameter_state"]["scalar_values"]["values"][0]["quantity"]["unit"] = (
        "dBm"
    )
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "incompatible_parameter_value_unit"


def test_parameter_value_outside_safety_limits_is_error() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["parameter_state"]["scalar_values"]["values"][0]["quantity"][
        "value"
    ] = 7.0
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "parameter_value_outside_safety_limits"


def test_parameter_table_rows_are_validated_against_catalog() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["parameter_catalog"]["table_definitions"] = [
        {
            "id": "readout_steps",
            "primary_key": ["step_id"],
            "columns": [
                {"id": "step_id", "kind": "string"},
                {"id": "frequency", "kind": "quantity", "unit": "GHz"},
            ],
        }
    ]
    config_data["parameter_state"]["tables"] = [
        {
            "id": "readout_steps",
            "rows": [
                {
                    "step_id": "prepare",
                    "frequency": {"value": 120.0, "unit": "ns"},
                }
            ],
        }
    ]
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "incompatible_parameter_table_quantity_unit"
