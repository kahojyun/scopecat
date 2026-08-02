from __future__ import annotations

from typing import assert_type

from scopecat.sdk.instruments import (
    ComponentRef,
    InterfaceRef,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
)

from client_codegen_fixture_declarations import (
    CatalogProjectionObservation as DeclaredCatalogProjectionObservation,
)
from client_codegen_fixture_declarations import (
    CatalogProjectionState as DeclaredCatalogProjectionState,
)
from client_codegen_fixture_declarations import Desired as DeclaredDesired
from generated_interface_catalog_fixture import catalog_projection_interface
from generated_member_catalog_fixture import (
    CATALOG_PROJECTION,
    CATALOG_PROJECTION_ENABLED,
    CATALOG_PROJECTION_SIGNAL_OUTPUT,
    CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER,
    CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE,
    CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE_COUNT,
    CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE_LABEL,
    CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE_WIDTH,
    CATALOG_PROJECTION_STATUS,
)
from generated_state_catalog_fixture import (
    CatalogProjectionObservation,
    CatalogProjectionState,
    Desired,
)
from scopecat_instruments.interface_declarations import (
    TemperatureReadoutObservation as DeclaredTemperatureReadoutObservation,
)
from scopecat_instruments.states import TemperatureReadoutObservation


def test_generated_member_catalog_recurses_through_component_operations() -> None:
    assert_type(CATALOG_PROJECTION, InterfaceRef)
    assert_type(CATALOG_PROJECTION_ENABLED, PropertyRef)
    assert_type(CATALOG_PROJECTION_STATUS, PropertyRef)
    assert_type(CATALOG_PROJECTION_SIGNAL_OUTPUT, ComponentRef)
    assert_type(CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER, ComponentRef)
    assert_type(
        CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE,
        OperationRef,
    )
    assert_type(
        CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE_COUNT,
        OperationArgumentRef,
    )

    assert CATALOG_PROJECTION.interface_id == "test.generated_catalog_projection/v1"
    assert CATALOG_PROJECTION_ENABLED.property_id == "enabled"
    assert CATALOG_PROJECTION_STATUS.property_id == "status"
    operation = CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE
    assert CATALOG_PROJECTION_SIGNAL_OUTPUT.component_path == ("signal_output",)
    assert CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER.component_path == (
        "signal_output",
        "pulse_trigger",
    )
    assert operation.component_path == ("signal_output", "pulse_trigger")
    assert operation.operation_id == "emit_pulse"
    assert [
        CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE_COUNT.argument_id,
        CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE_WIDTH.argument_id,
        CATALOG_PROJECTION_SIGNAL_OUTPUT_PULSE_TRIGGER_EMIT_PULSE_LABEL.argument_id,
    ] == ["pulse_count", "pulse_width", "pulse_label"]


def test_generated_interface_factory_returns_fresh_deep_copies() -> None:
    first = catalog_projection_interface()
    second = catalog_projection_interface()

    assert first == second
    assert first is not second
    assert first.properties is not second.properties
    assert first.components is not second.components
    assert first.components[0] is not second.components[0]


def test_generated_state_catalog_reexports_authored_types() -> None:
    assert CatalogProjectionState is DeclaredCatalogProjectionState
    assert CatalogProjectionObservation is DeclaredCatalogProjectionObservation
    assert Desired is DeclaredDesired
    assert TemperatureReadoutObservation is DeclaredTemperatureReadoutObservation
