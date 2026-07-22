from __future__ import annotations

import pytest

import scopecat.authoring as authoring
from scopecat.authoring.scans import axis
from scopecat.authoring.scans import zip as zip_scans
from scopecat.execution.local.program import ApplyStateOperation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
    RoutingGraph,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity
from tests.testkit.authoring import load_config, template_fixture
from tests.testkit.local_materialization import operations_of_type
from tests.testkit.materialized_effects import materialized_effects_contract

_ENTITY = authoring.ScalarType(authoring.EntityType(entity_kind="logical_device"))
_BIAS = authoring.ScalarType(authoring.QuantityType(unit="V"))
_BIAS_ROWS = authoring.TableType(
    columns=(
        authoring.TableColumn("entity", _ENTITY),
        authoring.TableColumn("background_bias", _BIAS),
    ),
)
_ENTITIES = ("q0", "q1", "q2", "q3")
_BACKGROUND_BIAS = {
    "q0": 0.01,
    "q1": 0.02,
    "q2": -0.03,
    "q3": 0.04,
}
_TARGETS = ("q0", "q2", "q1", "q3")
_SCAN_BIAS = (0.11, -0.12, 0.13, -0.14)


def _bias_config(*, duplicate_q0_owner: bool = False) -> ConfigProfileSnapshot:
    seed = load_config()
    seed_instrument = seed.instrument_registry.instruments[0]
    seed_connection = seed.connection_profile.connections[0]
    seed_device = seed.topology.devices[0]
    seed_channel = seed.topology.channels[0]

    bindings = [
        RoutingEndpointBinding(
            instrument_id="bias-a" if entity_id in {"q0", "q1"} else "bias-b",
            capability="set_bias",
            entity_id=entity_id,
            channel_id=f"bias-{entity_id}",
        )
        for entity_id in _ENTITIES
    ]
    if duplicate_q0_owner:
        bindings.append(
            RoutingEndpointBinding(
                instrument_id="bias-b",
                capability="set_bias",
                entity_id="q0",
                channel_id="bias-q0-secondary",
            )
        )

    channel_owners = {
        f"bias-{entity_id}": "bias-a" if entity_id in {"q0", "q1"} else "bias-b"
        for entity_id in _ENTITIES
    }
    if duplicate_q0_owner:
        channel_owners["bias-q0-secondary"] = "bias-b"

    topology = seed.topology.model_copy(
        update={
            "entities": [
                EntityRef(id=entity_id, kind="logical_device")
                for entity_id in _ENTITIES
            ],
            "devices": [
                seed_device.model_copy(
                    update={
                        "id": entity_id,
                        "channels": [
                            channel_id
                            for channel_id in channel_owners
                            if channel_id == f"bias-{entity_id}"
                            or (entity_id == "q0" and channel_id == "bias-q0-secondary")
                        ],
                    }
                )
                for entity_id in _ENTITIES
            ]
            + [
                seed_device.model_copy(
                    update={
                        "id": instrument_id,
                        "kind": "logical_instrument",
                        "channels": [],
                    }
                )
                for instrument_id in ("bias-a", "bias-b")
            ],
            "channels": [
                seed_channel.model_copy(
                    update={
                        "id": channel_id,
                        "kind": "bias",
                        "device_id": instrument_id,
                        "direction": "control",
                    }
                )
                for channel_id, instrument_id in channel_owners.items()
            ],
        }
    )
    system = seed.system.model_copy(
        update={
            "topology": topology,
            "instrument_registry": seed.instrument_registry.model_copy(
                update={
                    "instruments": [
                        seed_instrument.model_copy(
                            update={"id": instrument_id, "kind": "dc_bias"}
                        )
                        for instrument_id in ("bias-a", "bias-b")
                    ]
                }
            ),
            "routing": RoutingGraph(bindings=bindings),
        }
    )
    environment = seed.environment.model_copy(
        update={
            "connection_profile": seed.connection_profile.model_copy(
                update={
                    "connections": [
                        seed_connection.model_copy(
                            update={
                                "id": f"{instrument_id}-offline",
                                "instrument_id": instrument_id,
                            }
                        )
                        for instrument_id in ("bias-a", "bias-b")
                    ]
                }
            )
        }
    )
    return seed.model_copy(update={"system": system, "environment": environment})


def _bias_invocation() -> authoring.ExperimentInvocation:
    bias_rows = authoring.input("bias_rows", _BIAS_ROWS)
    target = authoring.input("target", _ENTITY)
    scan_bias = authoring.input("scan_bias", _BIAS)
    background_rows = bias_rows.filter(lambda row: row["entity"].ne(target))
    target_rows = bias_rows.filter(lambda row: row["entity"].eq(target))
    module = (
        authoring.module_body(id="test.bias-shards.scan-target")
        .inputs(bias_rows, target, scan_bias)
        .resource(
            "bias",
            requires=("set_bias",),
            for_entities=(bias_rows.entities("entity"),),
        )
        .state_each(
            background_rows,
            resource_port="bias",
            capability="set_bias",
            field="offset",
            value=lambda row: row["background_bias"],
            target_entities=(lambda row: row["entity"],),
        )
        .state_each(
            target_rows,
            resource_port="bias",
            capability="set_bias",
            field="offset",
            value=scan_bias,
            target_entities=(lambda row: row["entity"],),
        )
        .build()
    )
    target_point = authoring.point("target", _ENTITY)
    bias_point = authoring.point("scan_bias", _BIAS)
    template = template_fixture(
        module,
        id="test.bias-shards.scan-target",
        kind="bias_scan",
        scans=(
            zip_scans(
                axis(target_point, _TARGETS),
                axis(
                    bias_point,
                    tuple(Quantity(value=value, unit="V") for value in _SCAN_BIAS),
                ),
            ),
        ),
    )
    return template.bind(
        bias_rows=tuple(
            {
                "entity": EntityRef(id=entity_id, kind="logical_device"),
                "background_bias": Quantity(
                    value=_BACKGROUND_BIAS[entity_id],
                    unit="V",
                ),
            }
            for entity_id in _ENTITIES
        )
    )


def _values_by_entity(operation: ApplyStateOperation) -> dict[str, float]:
    selected: dict[str, float] = {}
    for state in operation.targets:
        [entity_id] = state.entity_ids
        value = state.value.root
        assert isinstance(value, Quantity)
        assert value.unit == "V"
        assert [binding.entity_id for binding in state.channel_bindings] == [entity_id]
        assert [binding.channel_id for binding in state.channel_bindings] == [
            f"bias-{entity_id}"
        ]
        selected[entity_id] = value.value
    return selected


def test_bias_state_is_statically_sharded_while_the_scan_target_switches_devices() -> (
    None
):
    config = _bias_config()
    resolved = resolve_experiment(_bias_invocation(), config_profile=config)

    preview = materialized_effects_contract(
        resolved.experiment,
        resolved.parameters,
        config=config,
    )

    for point_index, (target, scan_bias) in enumerate(
        zip(_TARGETS, _SCAN_BIAS, strict=True)
    ):
        operations = operations_of_type(
            preview,
            ApplyStateOperation,
            point_index=point_index,
        )
        assert len(operations) == 2
        assert {operation.instrument_id for operation in operations} == {
            "bias-a",
            "bias-b",
        }
        values_by_entity = {
            entity_id: value
            for operation in operations
            for entity_id, value in _values_by_entity(operation).items()
        }
        assert values_by_entity == {
            **_BACKGROUND_BIAS,
            target: scan_bias,
        }
        assert {
            operation.instrument_id: set(_values_by_entity(operation))
            for operation in operations
        } == {
            "bias-a": {"q0", "q1"},
            "bias-b": {"q2", "q3"},
        }

    assert set(preview.resource_claims) == {
        ResourceClaim("bias-a"),
        ResourceClaim("bias-b"),
        *(ResourceClaim(f"bias-{entity_id}", "channel") for entity_id in _ENTITIES),
    }


def test_bias_shard_rejects_one_entity_owned_by_two_instruments() -> None:
    config = _bias_config(duplicate_q0_owner=True)
    resolved = resolve_experiment(_bias_invocation(), config_profile=config)

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(
            resolved.experiment,
            resolved.parameters,
            config=config,
        )

    assert "module_resource_endpoint_ambiguous" in {
        problem.code for problem in failure.value.problems
    }


def test_multi_instrument_scope_is_not_implicitly_broadcast_to_an_action() -> None:
    bias_rows = authoring.input("bias_rows", _BIAS_ROWS)
    module = (
        authoring.module_body(id="test.bias-shards.action")
        .inputs(bias_rows)
        .resource(
            "bias",
            requires=("set_bias",),
            for_entities=(bias_rows.entities("entity"),),
        )
        .action(
            "latch",
            resource="bias",
            capability="set_bias",
            fields={"offset": Quantity(value=0.0, unit="V")},
        )
        .build()
    )
    invocation = template_fixture(
        module,
        id="test.bias-shards.action",
        kind="bias_action",
    ).bind(
        bias_rows=tuple(
            {
                "entity": EntityRef(id=entity_id, kind="logical_device"),
                "background_bias": Quantity(value=0.0, unit="V"),
            }
            for entity_id in _ENTITIES
        )
    )
    config = _bias_config()
    resolved = resolve_experiment(invocation, config_profile=config)

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(
            resolved.experiment,
            resolved.parameters,
            config=config,
        )

    assert "module_resource_port_ambiguous" in {
        problem.code for problem in failure.value.problems
    }
