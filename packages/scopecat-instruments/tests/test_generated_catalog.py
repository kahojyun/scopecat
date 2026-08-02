from __future__ import annotations

from typing import assert_type

from scopecat.sdk.instruments import (
    InterfaceRef,
    PropertyRef,
)
from scopecat.sdk.instruments.declarations import state_projection_assignments

from client_codegen_fixture_declarations import (
    CatalogProjectionState as DeclaredCatalogProjectionState,
)
from client_codegen_fixture_declarations import (
    SharedFixtureState as DeclaredSharedFixtureState,
)
from generated_driver_state_catalog_fixture import (
    encode_shared_state_first_state,
    encode_shared_state_second_state,
)
from generated_interface_catalog_fixture import catalog_projection_interface
from generated_member_catalog_fixture import (
    CATALOG_PROJECTION,
    CATALOG_PROJECTION_ENABLED,
    CATALOG_PROJECTION_STATUS,
    SHARED_STATE_FIRST_ENABLED,
    SHARED_STATE_SECOND_ENABLED,
)
from generated_state_catalog_fixture import (
    CatalogProjectionGroupTarget,
    CatalogProjectionPatch,
    CatalogProjectionState,
    CatalogProjectionTarget,
    SharedFixtureState,
    SharedStateFirstPatch,
    SharedStateSecondPatch,
)
from scopecat_instruments.interface_declarations import (
    TemperatureReadoutState as DeclaredTemperatureReadoutState,
)
from scopecat_instruments.states import TemperatureReadoutState


def test_generated_member_catalog_projects_root_properties() -> None:
    assert_type(CATALOG_PROJECTION, InterfaceRef)
    assert_type(CATALOG_PROJECTION_ENABLED, PropertyRef)
    assert_type(CATALOG_PROJECTION_STATUS, PropertyRef)

    assert CATALOG_PROJECTION.interface_id == "test.generated_catalog_projection/v1"
    assert CATALOG_PROJECTION_ENABLED.property_id == "enabled"
    assert CATALOG_PROJECTION_STATUS.property_id == "status"


def test_generated_interface_factory_returns_fresh_deep_copies() -> None:
    first = catalog_projection_interface()
    second = catalog_projection_interface()

    assert first == second
    assert first is not second
    assert first.properties is not second.properties
    assert not first.components


def test_generated_state_catalog_projects_concrete_schema_types() -> None:
    assert_type(CatalogProjectionPatch(enabled=True), CatalogProjectionPatch)
    assert_type(CatalogProjectionTarget(enabled=True), CatalogProjectionTarget)
    assert_type(
        CatalogProjectionGroupTarget(enabled=True),
        CatalogProjectionGroupTarget,
    )
    assert CatalogProjectionState is DeclaredCatalogProjectionState
    assert TemperatureReadoutState is DeclaredTemperatureReadoutState


def test_shared_schema_projections_keep_each_interface_identity() -> None:
    assert SharedFixtureState is DeclaredSharedFixtureState
    assert state_projection_assignments(SharedStateFirstPatch(enabled=True)) == {
        SHARED_STATE_FIRST_ENABLED: True
    }
    assert state_projection_assignments(SharedStateSecondPatch(enabled=False)) == {
        SHARED_STATE_SECOND_ENABLED: False
    }
    state = SharedFixtureState(enabled=True)
    assert encode_shared_state_first_state(state) == {SHARED_STATE_FIRST_ENABLED: True}
    assert encode_shared_state_second_state(state) == {
        SHARED_STATE_SECOND_ENABLED: True
    }
