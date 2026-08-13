from __future__ import annotations

import pytest
from pydantic import ValidationError
from scopecat_testkit.paths import CORE_FIXTURE_DIR

from scopecat.config.documents import load_config_snapshot_document
from scopecat.kernel.resource_identity import (
    ANY_RESOURCE_ROLE,
    LogicalResourcePortId,
    logical_resource_port_id,
    resource_role,
)
from scopecat.planning.routing import ResourceBindingError, RoutingView
from scopecat.records.config import (
    ConfigProfileSnapshot,
    ResourceRoleSpec,
    ResourceRoute,
    RoutingEndpoint,
    RoutingGraph,
)


def load_config() -> ConfigProfileSnapshot:
    return load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")


def _port(value: str) -> LogicalResourcePortId:
    return logical_resource_port_id(value)


def _route(
    route_id: str,
    instrument_id: str,
    *endpoints: tuple[str, str | None, str | None],
    role_id: str | None = None,
    entity_ids: tuple[str, ...] | None = None,
) -> ResourceRoute:
    return ResourceRoute(
        id=route_id,
        instrument_id=instrument_id,
        role_id=role_id,
        entity_ids=list(entity_ids)
        if entity_ids is not None
        else list(
            dict.fromkeys(
                endpoint_entity_id
                for _, endpoint_entity_id, _ in endpoints
                if endpoint_entity_id is not None
            )
        ),
        endpoints=[
            RoutingEndpoint(
                interface_id=interface_id,
                entity_id=entity_id,
                channel_id=channel_id,
            )
            for interface_id, entity_id, channel_id in endpoints
        ],
    )


def test_routing_view_builds_fixture_route_manifest() -> None:
    manifest = RoutingView.from_config(load_config()).bind_port(
        port_id=_port("drive"),
        interfaces=("test.set_frequency/v1",),
    )

    binding = manifest.select_one(("q0",))

    assert binding.instrument_id == "source-0"
    assert binding.route_id == "source-0"
    assert binding.port_id == _port("drive")
    assert [
        (item.entity_id, item.channel_id, item.interface_id)
        for item in binding.channel_bindings
    ] == [("q0", "drive-q0", "test.set_frequency/v1")]


def test_entities_must_be_served_by_one_complete_route() -> None:
    routing = RoutingView(
        routes=(
            _route("q0-drive", "source-0", ("test.set_frequency/v1", "q0", None)),
            _route("q1-drive", "source-1", ("test.set_frequency/v1", "q1", None)),
        )
    )

    with pytest.raises(ResourceBindingError) as failure:
        routing.bind_port(
            port_id=_port("drive"),
            interfaces=("test.set_frequency/v1",),
        ).select_one(("q0", "q1"))

    assert failure.value.code == "module_resource_route_not_found"


def test_all_interfaces_must_bind_every_selected_entity() -> None:
    routing = RoutingView(
        routes=(
            _route(
                "complete",
                "complete",
                ("test.prepare/v1", "q0", None),
                ("test.measure/v1", "q0", None),
            ),
            _route(
                "partial",
                "partial",
                ("test.prepare/v1", "q0", None),
                ("test.measure/v1", "q1", None),
            ),
        )
    )

    binding = routing.bind_port(
        port_id=_port("stack"),
        interfaces=("test.prepare/v1", "test.measure/v1"),
    ).select_one(("q0",))

    assert binding.instrument_id == "complete"


def test_manifest_candidate_footprint_excludes_incomplete_routes() -> None:
    routing = RoutingView(
        routes=(
            _route(
                "complete",
                "complete",
                ("test.prepare/v1", "q0", None),
                ("test.measure/v1", "q0", None),
            ),
            _route(
                "prepare-only",
                "prepare-only",
                ("test.prepare/v1", "q1", None),
            ),
        )
    )

    manifest = routing.bind_port(
        port_id=_port("stack"),
        interfaces=("test.prepare/v1", "test.measure/v1"),
    )

    assert manifest.candidate_instrument_ids == ("complete",)


def test_shared_endpoint_serves_only_the_route_entity_scope() -> None:
    routing = RoutingView(
        routes=(
            _route(
                "drive-a",
                "drive-lo-a",
                ("test.set_frequency/v1", None, "shared-lo"),
                entity_ids=("q0", "q1"),
            ),
            _route(
                "guard",
                "guard-source",
                ("test.set_frequency/v1", None, None),
            ),
        )
    )
    manifest = routing.bind_port(
        port_id=_port("drive"),
        interfaces=("test.set_frequency/v1",),
    )

    assert manifest.select_one(("q0", "q1")).instrument_id == "drive-lo-a"
    assert [
        (binding.entity_id, binding.channel_id)
        for binding in manifest.select_one(("q1", "q0")).channel_bindings
    ] == [("q1", "shared-lo"), ("q0", "shared-lo")]
    with pytest.raises(ResourceBindingError) as failure:
        manifest.select_one(("q2",))

    assert failure.value.code == "module_resource_route_not_found"


def test_unscoped_manifest_reports_ambiguous_routes() -> None:
    routing = RoutingView(
        routes=(
            _route("source-0", "source-0", ("test.set_frequency/v1", None, None)),
            _route("source-1", "source-1", ("test.set_frequency/v1", None, None)),
        )
    )

    with pytest.raises(ResourceBindingError) as failure:
        routing.bind_port(
            port_id=_port("drive"),
            interfaces=("test.set_frequency/v1",),
        ).select_one()

    assert failure.value.code == "module_resource_route_ambiguous"
    assert "source-0 (source-0)" in str(failure.value)


def test_unscoped_manifest_preserves_all_endpoints_on_its_route() -> None:
    routing = RoutingView(
        routes=(
            _route(
                "readout",
                "source-0",
                ("test.acquire_iq/v1", "q0", "readout-q0"),
                ("test.acquire_iq/v1", "q1", "readout-q1"),
            ),
        )
    )

    binding = routing.bind_port(
        port_id=_port("readout"),
        interfaces=("test.acquire_iq/v1",),
    ).select_one()

    assert binding.entity_ids == ()
    assert [item.entity_id for item in binding.channel_bindings] == ["q0", "q1"]


def test_manifest_defers_entity_ambiguity_until_selection() -> None:
    routing = RoutingView(
        routes=(
            _route(
                "source-0",
                "source-0",
                ("test.set_frequency/v1", "q0", None),
                ("test.set_frequency/v1", "q1", None),
            ),
            _route("source-1", "source-1", ("test.set_frequency/v1", "q1", None)),
        )
    )
    manifest = routing.bind_port(
        port_id=_port("drive"),
        interfaces=("test.set_frequency/v1",),
    )

    assert manifest.select_one(("q0",)).instrument_id == "source-0"
    with pytest.raises(ResourceBindingError) as failure:
        manifest.select_one(("q1",))

    assert failure.value.code == "module_resource_route_ambiguous"


def test_default_exact_and_any_roles_are_distinct() -> None:
    routing = RoutingView(
        routes=(
            _route(
                "drive",
                "drive-source",
                ("test.set_frequency/v1", "q0", "drive-q0"),
                role_id="drive",
            ),
            _route(
                "readout",
                "readout-source",
                ("test.set_frequency/v1", "q0", "readout-q0"),
                role_id="readout",
            ),
        )
    )

    exact = routing.bind_port(
        port_id=_port("source"),
        interfaces=("test.set_frequency/v1",),
        role=resource_role("readout"),
    ).select_one(("q0",))
    assert exact.instrument_id == "readout-source"
    assert exact.route_role_id == "readout"

    with pytest.raises(ResourceBindingError) as default_failure:
        routing.bind_port(
            port_id=_port("default-source"),
            interfaces=("test.set_frequency/v1",),
        ).select_one(("q0",))
    assert default_failure.value.code == "module_resource_route_not_found"

    with pytest.raises(ResourceBindingError) as any_failure:
        routing.bind_port(
            port_id=_port("any-source"),
            interfaces=("test.set_frequency/v1",),
            role=ANY_RESOURCE_ROLE,
        ).select_one(("q0",))
    assert any_failure.value.code == "module_resource_route_ambiguous"


def test_manifest_reports_missing_interface_or_entity_route() -> None:
    routing = RoutingView(
        routes=(_route("source-0", "source-0", ("test.set_frequency/v1", "q0", None)),)
    )

    with pytest.raises(ResourceBindingError) as failure:
        routing.bind_port(
            port_id=_port("drive"),
            interfaces=("test.set_frequency/v1",),
        ).select_one(("q1",))

    assert failure.value.code == "module_resource_route_not_found"


def test_channel_bindings_follow_selected_entity_order() -> None:
    routing = RoutingView(
        routes=(
            _route(
                "source-0",
                "source-0",
                ("test.set_frequency/v1", "q0", "ch0"),
                ("test.set_frequency/v1", "q1", "ch1"),
            ),
        )
    )

    binding = routing.bind_port(
        port_id=_port("drive"),
        interfaces=("test.set_frequency/v1",),
    ).select_one(("q1", "q0"))

    assert [item.entity_id for item in binding.channel_bindings] == ["q1", "q0"]


def test_one_route_can_bind_multiple_explicit_channels() -> None:
    routing = RoutingView(
        routes=(
            _route(
                "readout",
                "source-0",
                ("test.acquire_iq/v1", "q0", "i0"),
                ("test.acquire_iq/v1", "q0", "q0"),
            ),
        )
    )

    binding = routing.bind_port(
        port_id=_port("readout"),
        interfaces=("test.acquire_iq/v1",),
    ).select_one(("q0",))

    assert [item.channel_id for item in binding.channel_bindings] == ["i0", "q0"]


def test_duplicate_route_endpoint_fails_model_validation() -> None:
    endpoint = {
        "interface_id": "test.set_frequency/v1",
        "entity_id": "q0",
        "channel_id": "drive-q0",
    }

    with pytest.raises(ValidationError, match="duplicate resource route endpoint"):
        ResourceRoute.model_validate(
            {
                "id": "drive",
                "instrument_id": "source-0",
                "entity_ids": ["q0"],
                "endpoints": [endpoint, endpoint],
            }
        )


def test_routing_graph_rejects_unknown_role_and_conflicting_ownership() -> None:
    with pytest.raises(ValidationError, match="references unknown role"):
        RoutingGraph(
            routes=[
                _route(
                    "drive",
                    "source-0",
                    ("test.set_frequency/v1", "q0", None),
                    role_id="drive",
                )
            ]
        )

    with pytest.raises(ValidationError, match="multiple routes for the same role"):
        RoutingGraph(
            roles=[ResourceRoleSpec(id="drive")],
            routes=[
                _route(
                    "drive-a",
                    "source-0",
                    ("test.set_frequency/v1", "q0", None),
                    role_id="drive",
                ),
                _route(
                    "drive-b",
                    "source-1",
                    ("test.set_frequency/v1", "q0", None),
                    role_id="drive",
                ),
            ],
        )
