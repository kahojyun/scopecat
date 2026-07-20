import pytest
from pydantic import ValidationError

from scopecat.config.profiles import load_config_profile
from scopecat.kernel.problems import has_blocking_problems
from scopecat.planning.validation import validate_config
from scopecat.records.config import ConfigProfileSnapshot
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def _problem_codes(config: ConfigProfileSnapshot) -> set[str]:
    return {problem.code for problem in validate_config(config)}


def test_valid_example_has_no_blocking_problems() -> None:
    config = load_config()

    problems = validate_config(config)

    assert not has_blocking_problems(problems)


def test_primary_entity_must_be_declared_in_topology() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["primary_entity_id"] = "missing"
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert "configuration.unknown_primary_entity" in _problem_codes(config)


def test_channel_group_must_match_group_members() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["groups"] = [
        {"id": "lo.xy0", "kind": "lo", "members": ["readout-q0"]}
    ]
    config_data["system"]["topology"]["channels"][0]["group_ids"] = ["lo.xy0"]
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert "configuration.topology_channel_group_mismatch" in _problem_codes(config)


def test_group_member_must_match_channel_group_ids() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["groups"] = [
        {"id": "lo.xy0", "kind": "lo", "members": ["drive-q0"]},
        {"id": "lo.xy1", "kind": "lo", "members": ["drive-q0"]},
    ]
    config_data["system"]["topology"]["channels"][0]["group_ids"] = ["lo.xy1"]
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert "configuration.topology_group_member_mismatch" in _problem_codes(config)


def test_group_member_can_reference_channel_line() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["lines"] = [
        {"id": "q0.xy", "kind": "control_line", "signal": "drive"}
    ]
    config_data["system"]["topology"]["groups"] = [
        {"id": "lo.xy0", "kind": "lo", "members": ["q0.xy"]}
    ]
    config_data["system"]["topology"]["channels"][0]["line_id"] = "q0.xy"
    config_data["system"]["topology"]["channels"][0]["group_ids"] = ["lo.xy0"]
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert not has_blocking_problems(validate_config(config))


def test_channel_line_endpoint_must_include_channel_device() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["devices"].append(
        {"id": "source-0", "kind": "logical_instrument"}
    )
    config_data["system"]["topology"]["lines"] = [
        {
            "id": "q0.xy",
            "kind": "control_line",
            "signal": "drive",
            "endpoints": ["q0"],
        }
    ]
    config_data["system"]["topology"]["channels"][0]["line_id"] = "q0.xy"
    config_data["system"]["topology"]["channels"][0]["device_id"] = "source-0"
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert "configuration.topology_channel_line_endpoint_mismatch" in _problem_codes(
        config
    )


def test_channel_line_endpoint_can_explain_channel_device() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["devices"].append(
        {"id": "source-0", "kind": "logical_instrument"}
    )
    config_data["system"]["topology"]["lines"] = [
        {
            "id": "q0.xy",
            "kind": "control_line",
            "signal": "drive",
            "endpoints": ["q0", "source-0"],
        }
    ]
    config_data["system"]["topology"]["channels"][0]["line_id"] = "q0.xy"
    config_data["system"]["topology"]["channels"][0]["device_id"] = "source-0"
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert not has_blocking_problems(validate_config(config))


def test_routing_binding_must_reference_registered_instrument() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"]["bindings"][0]["instrument_id"] = "missing"
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert "configuration.unknown_routing_binding_instrument" in _problem_codes(config)


def test_routing_binding_must_reference_declared_entity() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"]["bindings"][0]["entity_id"] = "missing"
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert "configuration.unknown_routing_binding_entity" in _problem_codes(config)


def test_routing_binding_must_reference_declared_channel() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"]["bindings"][0]["channel_id"] = "missing"
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert "configuration.unknown_routing_binding_channel" in _problem_codes(config)


def test_routing_channel_binding_requires_an_entity() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"]["bindings"][0]["entity_id"] = None
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert "configuration.routing_binding_channel_without_entity" in _problem_codes(
        config
    )


def test_one_endpoint_key_can_map_to_multiple_explicit_channels() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"]["bindings"].append(
        {
            "instrument_id": "source-0",
            "capability": "set_frequency",
            "entity_id": "q0",
            "channel_id": "readout-q0",
        }
    )
    config = ConfigProfileSnapshot.model_validate(config_data)

    assert not has_blocking_problems(validate_config(config))


def test_unsupported_unit_fails_model_validation() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["parameter_snapshot"]["values"][0]["value"]["unit"] = "furlong"

    with pytest.raises(ValidationError):
        ConfigProfileSnapshot.model_validate(config_data)


def test_parameter_value_without_definition_is_error() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["parameter_catalog"]["definitions"] = []
    config = ConfigProfileSnapshot.model_validate(config_data)

    problems = validate_config(config)

    assert has_blocking_problems(problems)
    assert problems[0].code == "unknown_parameter_definition"


def test_duplicate_parameter_id_fails_model_validation() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["parameter_snapshot"]["values"].append(
        config_data["parameter_snapshot"]["values"][0]
    )

    with pytest.raises(ValidationError):
        ConfigProfileSnapshot.model_validate(config_data)


def test_incompatible_parameter_value_unit_is_error() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["parameter_snapshot"]["values"][0]["value"]["unit"] = "dBm"
    config = ConfigProfileSnapshot.model_validate(config_data)

    problems = validate_config(config)

    assert has_blocking_problems(problems)
    assert problems[0].code == "incompatible_parameter_quantity_unit"


def test_parameter_value_outside_declared_bounds_is_error() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["parameter_snapshot"]["values"][0]["value"]["value"] = 7.0
    config = ConfigProfileSnapshot.model_validate(config_data)

    problems = validate_config(config)

    assert has_blocking_problems(problems)
    assert problems[0].code == "invalid_parameter_quantity"


def test_parameter_table_rows_are_validated_against_catalog() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["parameter_catalog"]["definitions"].append(
        {
            "id": "readout_steps",
            "value_type": {
                "shape": "table",
                "primary_key": ["step_id"],
                "columns": [
                    {"id": "step_id", "value_type": {"type": "string"}},
                    {
                        "id": "frequency",
                        "value_type": {"type": "quantity", "unit": "GHz"},
                    },
                ],
            },
        }
    )
    config_data["parameter_snapshot"]["values"].append(
        {
            "id": "readout_steps",
            "shape": "table",
            "rows": [
                {
                    "step_id": "prepare",
                    "frequency": {"value": 120.0, "unit": "ns"},
                }
            ],
        }
    )
    config = ConfigProfileSnapshot.model_validate(config_data)

    problems = validate_config(config)

    assert has_blocking_problems(problems)
    assert problems[0].code == "incompatible_parameter_quantity_unit"


def test_quantity_primary_keys_are_normalized_before_duplicate_detection() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["parameter_catalog"]["definitions"].append(
        {
            "id": "frequencies",
            "value_type": {
                "shape": "table",
                "primary_key": ["frequency"],
                "columns": [
                    {
                        "id": "frequency",
                        "value_type": {
                            "type": "quantity",
                            "dimension": "frequency",
                        },
                    }
                ],
            },
        }
    )
    config_data["parameter_snapshot"]["values"].append(
        {
            "id": "frequencies",
            "shape": "table",
            "rows": [
                {"frequency": {"value": 5.0, "unit": "GHz"}},
                {"frequency": {"value": 5000.0, "unit": "MHz"}},
            ],
        }
    )
    config = ConfigProfileSnapshot.model_validate(config_data)

    problems = validate_config(config)

    assert "duplicate_parameter_table_primary_key" in {
        problem.code for problem in problems
    }
