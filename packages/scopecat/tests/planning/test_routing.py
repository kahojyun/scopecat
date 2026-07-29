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
        interfaces=("test.set_frequency/v1",),
    )
    binding = manifest.select_one(("q0",))

    assert binding.instrument_id == "source-0"
    assert [
        (item.entity_id, item.channel_id, item.interface_id)
        for item in binding.channel_bindings
    ] == [("q0", "drive-q0", "test.set_frequency/v1")]


def test_entities_spanning_instruments_are_ambiguous() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.set_frequency/v1",
                entity_id="q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-1",
                interface_id="test.set_frequency/v1",
                entity_id="q1",
            ),
        ),
    )

    with pytest.raises(ResourceBindingError) as failure:
        manifest = routing.bind_port(
            port_id=_port("drive"),
            interfaces=("test.set_frequency/v1",),
        )
        manifest.select_one(("q0", "q1"))

    assert failure.value.code == "module_resource_port_ambiguous"


def test_all_interfaces_must_bind_every_selected_entity() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="complete", interface_id="test.prepare/v1", entity_id="q0"
            ),
            RoutingEndpointBinding(
                instrument_id="complete", interface_id="test.measure/v1", entity_id="q0"
            ),
            RoutingEndpointBinding(
                instrument_id="partial", interface_id="test.prepare/v1", entity_id="q0"
            ),
            RoutingEndpointBinding(
                instrument_id="partial", interface_id="test.measure/v1"
            ),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("stack"),
        interfaces=("test.prepare/v1", "test.measure/v1"),
    )
    binding = manifest.select_one(("q0",))

    assert binding.instrument_id == "complete"


def test_manifest_without_entity_reports_ambiguous_instrument() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0", interface_id="test.set_frequency/v1"
            ),
            RoutingEndpointBinding(
                instrument_id="source-1", interface_id="test.set_frequency/v1"
            ),
        ),
    )

    with pytest.raises(ResourceBindingError) as failure:
        manifest = routing.bind_port(
            port_id=_port("drive"),
            interfaces=("test.set_frequency/v1",),
        )
        manifest.select_one()

    assert failure.value.code == "module_resource_port_ambiguous"


def test_unscoped_manifest_preserves_all_endpoints_on_its_unique_instrument() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.acquire_iq/v1",
                entity_id="q0",
                channel_id="readout-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.acquire_iq/v1",
                entity_id="q1",
                channel_id="readout-q1",
            ),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("readout"),
        interfaces=("test.acquire_iq/v1",),
    )
    binding = manifest.select_one()

    assert binding.entity_ids == ()
    assert [item.entity_id for item in binding.channel_bindings] == ["q0", "q1"]


def test_manifest_defers_ambiguity_until_the_ambiguous_entity_is_selected() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.set_frequency/v1",
                entity_id="q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.set_frequency/v1",
                entity_id="q1",
            ),
            RoutingEndpointBinding(
                instrument_id="source-1",
                interface_id="test.set_frequency/v1",
                entity_id="q1",
            ),
        ),
    )
    manifest = routing.bind_port(
        port_id=_port("drive"),
        interfaces=("test.set_frequency/v1",),
    )

    assert manifest.select_one(("q0",)).instrument_id == "source-0"
    with pytest.raises(ResourceBindingError) as failure:
        manifest.select_one(("q1",))

    assert failure.value.code == "module_resource_endpoint_ambiguous"


def test_manifest_reports_missing_interface_or_entity_binding() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.set_frequency/v1",
                entity_id="q0",
            ),
        ),
    )

    with pytest.raises(ResourceBindingError) as failure:
        manifest = routing.bind_port(
            port_id=_port("drive"),
            interfaces=("test.set_frequency/v1",),
        )
        manifest.select_one(("q1",))

    assert failure.value.code == "module_resource_endpoint_not_found"


def test_channel_bindings_follow_selected_entity_order() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.set_frequency/v1",
                entity_id="q0",
                channel_id="ch0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.set_frequency/v1",
                entity_id="q1",
                channel_id="ch1",
            ),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("drive"),
        interfaces=("test.set_frequency/v1",),
    )
    binding = manifest.select_one(("q1", "q0"))

    assert [item.entity_id for item in binding.channel_bindings] == ["q1", "q0"]


def test_one_interface_can_bind_multiple_explicit_channels() -> None:
    routing = RoutingView(
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.acquire_iq/v1",
                entity_id="q0",
                channel_id="i0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.acquire_iq/v1",
                entity_id="q0",
                channel_id="q0",
            ),
        ),
    )

    manifest = routing.bind_port(
        port_id=_port("readout"),
        interfaces=("test.acquire_iq/v1",),
    )
    binding = manifest.select_one(("q0",))

    assert [item.channel_id for item in binding.channel_bindings] == ["i0", "q0"]


def test_duplicate_endpoint_binding_fails_model_validation() -> None:
    duplicate = {
        "instrument_id": "source-0",
        "interface_id": "test.set_frequency/v1",
        "entity_id": "q0",
        "channel_id": "drive-q0",
    }

    with pytest.raises(ValidationError, match="duplicate routing endpoint binding"):
        RoutingGraph.model_validate(
            {
                "bindings": [duplicate, duplicate],
            }
        )
