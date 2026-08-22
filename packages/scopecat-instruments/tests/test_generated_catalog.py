from __future__ import annotations

from typing import assert_type

from scopecat.sdk.instruments import (
    InterfaceRef,
    PropertyRef,
)
from scopecat.sdk.instruments.declarations import member_projection_assignments
from scopecat_testkit.instrument_codegen_fixtures.generated_interfaces import (
    catalog_projection_interface,
)
from scopecat_testkit.instrument_codegen_fixtures.generated_members import (
    CATALOG_PROJECTION,
    CATALOG_PROJECTION_ENABLED,
    CATALOG_PROJECTION_STATUS,
    DRIVER_MONITOR_ENABLED,
    DRIVER_SOURCE_ENABLED,
    SHARED_PROPERTY_FIRST_ENABLED,
    SHARED_PROPERTY_SECOND_ENABLED,
)
from scopecat_testkit.instrument_codegen_fixtures.generated_projections import (
    CatalogProjectionGroupTarget,
    CatalogProjectionPatch,
    CatalogProjectionTarget,
    MonitorCompositeGroupTarget,
    MonitorCompositePatch,
    MonitorCompositeTarget,
    SharedPropertyFirstPatch,
    SharedPropertySecondPatch,
)


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


def test_generated_member_projection_catalog_projects_concrete_schema_types() -> None:
    assert_type(CatalogProjectionPatch(enabled=True), CatalogProjectionPatch)
    assert_type(CatalogProjectionTarget(enabled=True), CatalogProjectionTarget)
    assert_type(
        CatalogProjectionGroupTarget(enabled=True),
        CatalogProjectionGroupTarget,
    )


def test_shared_schema_projections_keep_each_interface_identity() -> None:
    assert member_projection_assignments(SharedPropertyFirstPatch(enabled=True)) == {
        SHARED_PROPERTY_FIRST_ENABLED: True
    }
    assert member_projection_assignments(SharedPropertySecondPatch(enabled=False)) == {
        SHARED_PROPERTY_SECOND_ENABLED: False
    }


def test_composite_projection_aliases_keep_each_property_identity() -> None:
    assert_type(
        MonitorCompositeGroupTarget(source_enabled=True),
        MonitorCompositeGroupTarget,
    )
    assert_type(
        MonitorCompositeTarget(monitor_enabled=True),
        MonitorCompositeTarget,
    )
    assert member_projection_assignments(
        MonitorCompositePatch(
            source_enabled=True,
            monitor_enabled=False,
        )
    ) == {
        DRIVER_SOURCE_ENABLED: True,
        DRIVER_MONITOR_ENABLED: False,
    }
