from __future__ import annotations

from typing import assert_type

from scopecat.sdk.instruments import (
    InterfaceRef,
    PropertyRef,
)

from client_codegen_fixture_declarations import (
    CatalogProjectionObservation as DeclaredCatalogProjectionObservation,
)
from generated_interface_catalog_fixture import catalog_projection_interface
from generated_member_catalog_fixture import (
    CATALOG_PROJECTION,
    CATALOG_PROJECTION_ENABLED,
    CATALOG_PROJECTION_STATUS,
)
from generated_state_catalog_fixture import (
    CatalogProjectionGroupTarget,
    CatalogProjectionObservation,
    CatalogProjectionPatch,
    CatalogProjectionTarget,
)
from scopecat_instruments.interface_declarations import (
    TemperatureReadoutObservation as DeclaredTemperatureReadoutObservation,
)
from scopecat_instruments.states import TemperatureReadoutObservation


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
    assert CatalogProjectionObservation is DeclaredCatalogProjectionObservation
    assert TemperatureReadoutObservation is DeclaredTemperatureReadoutObservation
