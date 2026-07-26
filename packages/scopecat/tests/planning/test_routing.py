from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.config.documents import load_config_snapshot_document
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.planning.routing import ResourceBindingError, RoutingView
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
    RoutingGraph,
)
from tests.testkit.paths import CORE_FIXTURE_DIR


def load_config() -> ConfigProfileSnapshot:
    return load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")


def _port(value: str) -> LogicalResourcePortId:
    return logical_resource_port_id(value)


def test_routing_view_builds_fixture_endpoint_manifest() -> None:
    routing = RoutingView.from_config(load_config())

    manifest = routing.bind_port(
        port_id=_port("drive"),
        capabilities=("set_frequency",),
    )
    binding = manifest.select_one(("q0",))

    assert binding.instrument_id == "source-0"
    assert [
        (item.entity_id, item.channel_id, item.capability)
        for item in binding.channel_bindings
    ] == [("q0", "drive-q0", "set_frequency")]


def test_explicit_entities_are_statically_partitioned_into_instrument_shards() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="set_frequency",
                entity_id="q0",
                channel_id="ch0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-1",
                capability="set_frequency",
                entity_id="q1",
                channel_id="ch1",
            ),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("drive"),
        capabilities=("set_frequency",),
    )
    shards = manifest.select_shards(("q1", "q0"))

    assert [
        (
            shard.instrument_id,
            shard.entity_ids,
            tuple(binding.channel_id for binding in shard.channel_bindings),
        )
        for shard in shards
    ] == [
        ("source-1", ("q1",), ("ch1",)),
        ("source-0", ("q0",), ("ch0",)),
    ]


def test_non_sharded_consumers_reject_a_multi_instrument_entity_scope() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="set_frequency",
                entity_id="q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-1",
                capability="set_frequency",
                entity_id="q1",
            ),
        ),
    )

    with pytest.raises(ResourceBindingError) as failure:
        manifest = routing.bind_port(
            port_id=_port("drive"),
            capabilities=("set_frequency",),
        )
        manifest.select_one(("q0", "q1"))

    assert failure.value.code == "module_resource_port_ambiguous"


def test_all_capabilities_must_bind_every_selected_entity() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="complete", capability="prepare", entity_id="q0"
            ),
            RoutingEndpointBinding(
                instrument_id="complete", capability="measure", entity_id="q0"
            ),
            RoutingEndpointBinding(
                instrument_id="partial", capability="prepare", entity_id="q0"
            ),
            RoutingEndpointBinding(instrument_id="partial", capability="measure"),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("stack"),
        capabilities=("prepare", "measure"),
    )
    binding = manifest.select_one(("q0",))

    assert binding.instrument_id == "complete"


def test_manifest_without_entity_reports_ambiguous_instrument() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0", capability="set_frequency"
            ),
            RoutingEndpointBinding(
                instrument_id="source-1", capability="set_frequency"
            ),
        ),
    )

    with pytest.raises(ResourceBindingError) as failure:
        manifest = routing.bind_port(
            port_id=_port("drive"),
            capabilities=("set_frequency",),
        )
        manifest.select_one()

    assert failure.value.code == "module_resource_port_ambiguous"


def test_unscoped_manifest_preserves_all_endpoints_on_its_unique_instrument() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="acquire_iq",
                entity_id="q0",
                channel_id="readout-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="acquire_iq",
                entity_id="q1",
                channel_id="readout-q1",
            ),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("readout"),
        capabilities=("acquire_iq",),
    )
    binding = manifest.select_one()

    assert binding.entity_ids == ()
    assert [item.entity_id for item in binding.channel_bindings] == ["q0", "q1"]


def test_manifest_defers_ambiguity_until_the_ambiguous_entity_is_selected() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="set_frequency",
                entity_id="q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="set_frequency",
                entity_id="q1",
            ),
            RoutingEndpointBinding(
                instrument_id="source-1",
                capability="set_frequency",
                entity_id="q1",
            ),
        ),
    )
    manifest = routing.bind_port(
        port_id=_port("drive"),
        capabilities=("set_frequency",),
    )

    assert manifest.select_one(("q0",)).instrument_id == "source-0"
    with pytest.raises(ResourceBindingError) as failure:
        manifest.select_one(("q1",))

    assert failure.value.code == "module_resource_endpoint_ambiguous"


def test_manifest_reports_missing_capability_or_entity_binding() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="set_frequency",
                entity_id="q0",
            ),
        ),
    )

    with pytest.raises(ResourceBindingError) as failure:
        manifest = routing.bind_port(
            port_id=_port("drive"),
            capabilities=("set_frequency",),
        )
        manifest.select_one(("q1",))

    assert failure.value.code == "module_resource_endpoint_not_found"


def test_channel_bindings_follow_selected_entity_order() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="set_frequency",
                entity_id="q0",
                channel_id="ch0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="set_frequency",
                entity_id="q1",
                channel_id="ch1",
            ),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("drive"),
        capabilities=("set_frequency",),
    )
    binding = manifest.select_one(("q1", "q0"))

    assert [item.entity_id for item in binding.channel_bindings] == ["q1", "q0"]


def test_one_capability_can_bind_multiple_explicit_channels() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="acquire_iq",
                entity_id="q0",
                channel_id="i0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="acquire_iq",
                entity_id="q0",
                channel_id="q0",
            ),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("readout"),
        capabilities=("acquire_iq",),
    )
    binding = manifest.select_one(("q0",))

    assert [item.channel_id for item in binding.channel_bindings] == ["i0", "q0"]


def test_endpoint_owns_resolved_line_and_group_identity() -> None:
    config = load_config()
    endpoint = config.routing.bindings[0].model_copy(
        update={"line_id": "drive-line", "group_ids": ["drive-group"]}
    )
    selected = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "routing": config.routing.model_copy(
                        update={"bindings": [endpoint]}
                    )
                }
            )
        }
    )

    manifest = RoutingView.from_config(selected).bind_port(
        port_id=_port("drive"),
        capabilities=("set_frequency",),
    )
    binding = manifest.select_one(("q0",))

    assert binding.channel_bindings[0].line_id == "drive-line"
    assert binding.channel_bindings[0].group_ids == ["drive-group"]


def test_duplicate_endpoint_binding_fails_model_validation() -> None:
    duplicate = {
        "instrument_id": "source-0",
        "capability": "set_frequency",
        "entity_id": "q0",
        "channel_id": "drive-q0",
    }

    with pytest.raises(ValidationError, match="duplicate routing endpoint binding"):
        RoutingGraph.model_validate(
            {
                "bindings": [duplicate, duplicate],
            }
        )


def test_one_channel_has_one_resource_identity_across_capabilities() -> None:
    with pytest.raises(ValidationError, match="must share line and group ids"):
        RoutingGraph(
            bindings=[
                RoutingEndpointBinding(
                    instrument_id="source-0",
                    capability="set_frequency",
                    entity_id="q0",
                    channel_id="drive-q0",
                    line_id="line-0",
                ),
                RoutingEndpointBinding(
                    instrument_id="source-0",
                    capability="set_power",
                    entity_id="q0",
                    channel_id="drive-q0",
                    line_id="line-1",
                ),
            ]
        )
