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


def test_primary_entity_must_be_declared_in_topology() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["primary_entity_id"] = "missing"
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "unknown_primary_entity"


def test_channel_group_must_match_group_members() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["groups"] = [
        {"id": "lo.xy0", "kind": "lo", "members": ["readout-q0"]}
    ]
    config_data["system"]["topology"]["channels"][0]["group_ids"] = ["lo.xy0"]
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "topology_channel_group_mismatch"
    }


def test_group_member_must_match_channel_group_ids() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["groups"] = [
        {"id": "lo.xy0", "kind": "lo", "members": ["drive-q0"]},
        {"id": "lo.xy1", "kind": "lo", "members": ["drive-q0"]},
    ]
    config_data["system"]["topology"]["channels"][0]["group_ids"] = ["lo.xy1"]
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "topology_group_member_mismatch"
    }


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

    diagnostics = validate_config(config)

    assert not has_blocking_diagnostics(diagnostics)


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

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "topology_channel_line_endpoint_mismatch"
    }


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

    diagnostics = validate_config(config)

    assert not has_blocking_diagnostics(diagnostics)


def test_routing_resource_served_entities_must_be_declared_in_topology() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
                "served_entities": ["missing"],
            }
        ]
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "unknown_routing_resource_served_entity"


def test_routing_resource_channels_must_be_declared_in_topology() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
                "channels": ["missing"],
            }
        ]
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "unknown_routing_resource_channel"


def test_instrument_routing_resource_must_reference_registered_instrument() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "missing",
                "capabilities": ["set_frequency"],
            }
        ]
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "unknown_routing_resource_instrument"


def test_routing_edge_must_reference_declared_resource() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [],
        "edges": [
            {
                "id": "missing-resource-edge",
                "resource_id": "missing",
                "entity_ids": ["q0"],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "unknown_routing_edge_resource"


def test_routing_edge_must_reference_declared_entities() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
            }
        ],
        "edges": [
            {
                "id": "missing-entity-edge",
                "resource_id": "source-0",
                "entity_ids": ["missing"],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "unknown_routing_edge_entity"


def test_routing_edge_capabilities_must_be_declared_by_resource() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
            }
        ],
        "edges": [
            {
                "id": "missing-capability-edge",
                "resource_id": "source-0",
                "entity_ids": ["q0"],
                "capabilities": ["acquire_signal"],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert has_blocking_diagnostics(diagnostics)
    assert diagnostics[0].code == "unknown_routing_edge_capability"


def test_routing_edge_entities_must_match_resource_served_entities() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
                "served_entities": ["drive-q0"],
            }
        ],
        "edges": [
            {
                "id": "source-0-q0-drive",
                "resource_id": "source-0",
                "entity_ids": ["q0"],
                "capabilities": ["set_frequency"],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_edge_resource_entity_mismatch"
    }


def test_routing_edge_channels_must_match_resource_channels() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
                "channels": ["readout-q0"],
            }
        ],
        "edges": [
            {
                "id": "source-0-q0-drive",
                "resource_id": "source-0",
                "entity_ids": ["q0"],
                "capabilities": ["set_frequency"],
                "channels": ["drive-q0"],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_edge_resource_channel_mismatch"
    }


def test_routing_binding_entities_must_match_edge_entities() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
            }
        ],
        "edges": [
            {
                "id": "source-0-drive",
                "resource_id": "source-0",
                "entity_ids": ["drive-q0"],
                "capabilities": ["set_frequency"],
                "bindings": [
                    {
                        "entity_id": "q0",
                        "channel_id": "drive-q0",
                        "capability": "set_frequency",
                    }
                ],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_binding_edge_entity_mismatch"
    }


def test_routing_binding_entities_must_match_resource_served_entities() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
                "served_entities": ["drive-q0"],
            }
        ],
        "edges": [
            {
                "id": "source-0-drive",
                "resource_id": "source-0",
                "capabilities": ["set_frequency"],
                "bindings": [
                    {
                        "entity_id": "q0",
                        "channel_id": "drive-q0",
                        "capability": "set_frequency",
                    }
                ],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_binding_resource_entity_mismatch"
    }


def test_routing_binding_capability_must_match_edge_capabilities() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency", "acquire_signal"],
            }
        ],
        "edges": [
            {
                "id": "source-0-drive",
                "resource_id": "source-0",
                "entity_ids": ["q0"],
                "capabilities": ["set_frequency"],
                "bindings": [
                    {
                        "entity_id": "q0",
                        "channel_id": "drive-q0",
                        "capability": "acquire_signal",
                    }
                ],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_binding_edge_capability_mismatch"
    }


def test_routing_binding_capability_must_match_resource_capabilities() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
            }
        ],
        "edges": [
            {
                "id": "source-0-drive",
                "resource_id": "source-0",
                "entity_ids": ["q0"],
                "bindings": [
                    {
                        "entity_id": "q0",
                        "channel_id": "drive-q0",
                        "capability": "acquire_signal",
                    }
                ],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_binding_resource_capability_mismatch"
    }


def test_routing_binding_channels_must_match_edge_channels() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
            }
        ],
        "edges": [
            {
                "id": "source-0-drive",
                "resource_id": "source-0",
                "entity_ids": ["q0"],
                "capabilities": ["set_frequency"],
                "channels": ["readout-q0"],
                "bindings": [
                    {
                        "entity_id": "q0",
                        "channel_id": "drive-q0",
                        "capability": "set_frequency",
                    }
                ],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_binding_edge_channel_mismatch"
    }


def test_routing_binding_line_must_match_channel_topology() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["lines"] = [
        {"id": "q0.xy", "kind": "control_line", "signal": "drive"},
        {"id": "q0.bad", "kind": "control_line", "signal": "drive"},
    ]
    config_data["system"]["topology"]["channels"][0]["line_id"] = "q0.xy"
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
            }
        ],
        "edges": [
            {
                "id": "source-0-q0-drive",
                "resource_id": "source-0",
                "entity_ids": ["q0"],
                "capabilities": ["set_frequency"],
                "bindings": [
                    {
                        "entity_id": "q0",
                        "channel_id": "drive-q0",
                        "line_id": "q0.bad",
                        "capability": "set_frequency",
                    }
                ],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_binding_line_mismatch"
    }


def test_routing_binding_groups_must_match_channel_topology() -> None:
    config_data = load_config().model_dump(mode="json")
    config_data["system"]["topology"]["groups"] = [
        {"id": "lo.good", "kind": "lo", "members": ["drive-q0"]},
        {"id": "lo.bad", "kind": "lo", "members": ["drive-q0"]},
    ]
    config_data["system"]["topology"]["channels"][0]["group_ids"] = ["lo.good"]
    config_data["system"]["routing"] = {
        "resources": [
            {
                "id": "source-0",
                "capabilities": ["set_frequency"],
            }
        ],
        "edges": [
            {
                "id": "source-0-q0-drive",
                "resource_id": "source-0",
                "entity_ids": ["q0"],
                "capabilities": ["set_frequency"],
                "bindings": [
                    {
                        "entity_id": "q0",
                        "channel_id": "drive-q0",
                        "group_ids": ["lo.bad"],
                        "capability": "set_frequency",
                    }
                ],
            }
        ],
    }
    config = ConfigProfileSnapshot.model_validate(config_data)

    diagnostics = validate_config(config)

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_binding_group_mismatch"
    }


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
