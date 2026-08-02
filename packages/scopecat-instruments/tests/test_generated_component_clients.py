from __future__ import annotations

# pyright: reportPrivateUsage=false
import inspect
from collections.abc import Mapping
from typing import assert_type, cast

import pytest
from scopecat.api._instruments import (
    InstrumentClientChannel,
    OperationArgumentValue,
)
from scopecat.authoring import (
    IntType,
    ModuleContext,
    PerEntity,
    ScalarType,
    ValueRef,
    coordinate,
    each,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.program.bindings import InvocationIntent
from scopecat.sdk.instruments import (
    InvokeReceipt,
    OperationArgumentRef,
    OperationRef,
)

from client_codegen_fixture_declarations import COMPONENT_OPERATION_DECLARATION
from generated_client_fixture import (
    ComponentOperationClient,
    ComponentOperationOutputClient,
    ComponentOperationOutputTriggerClient,
    SymbolicComponentOperationClient,
    SymbolicComponentOperationGroup,
    SymbolicComponentOperationOutputClient,
    SymbolicComponentOperationOutputGroup,
    SymbolicComponentOperationOutputTriggerClient,
    SymbolicComponentOperationOutputTriggerGroup,
    component_operation,
)


class _RecordingInvokeChannel:
    def __init__(self) -> None:
        self.receipt = InvokeReceipt(metadata={"generated": "component-operation"})
        self.operation: OperationRef | None = None
        self.arguments: Mapping[OperationArgumentRef, OperationArgumentValue] | None = (
            None
        )
        self.instrument_id: str | None = None

    def invoke(
        self,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, OperationArgumentValue] | None = None,
        *,
        instrument_id: str,
    ) -> InvokeReceipt:
        self.operation = operation
        self.arguments = arguments
        self.instrument_id = instrument_id
        return self.receipt


def test_generated_live_components_share_root_target_and_lower_wire_names() -> None:
    channel = _RecordingInvokeChannel()
    root = ComponentOperationClient(
        cast("InstrumentClientChannel", cast("object", channel)),
        "pulse-source",
    )
    output = assert_type(root.output, ComponentOperationOutputClient)
    trigger = assert_type(output.trigger, ComponentOperationOutputTriggerClient)
    width = Quantity(0.25, "s")

    assert output._owner is root
    assert trigger._owner is root
    assert output._session is root._session
    assert trigger._session is root._session
    assert output.instrument_id == "pulse-source"
    assert trigger.instrument_id == "pulse-source"

    receipt = assert_type(
        trigger.emit(7, width, label="calibration"),
        InvokeReceipt,
    )

    assert receipt is channel.receipt
    assert channel.instrument_id == "pulse-source"
    assert channel.operation is not None
    assert (
        channel.operation.interface_id
        == COMPONENT_OPERATION_DECLARATION.ref.interface_id
    )
    assert channel.operation.component_path == ("signal_output", "pulse_trigger")
    assert channel.operation.operation_id == "emit_pulse"
    assert channel.arguments is not None
    assert {
        reference.argument_id: value for reference, value in channel.arguments.items()
    } == {
        "pulse_count": 7,
        "pulse_width": width,
        "pulse_label": "calibration",
    }


@pytest.mark.parametrize(
    "client_type",
    [
        ComponentOperationOutputTriggerClient,
        SymbolicComponentOperationOutputTriggerClient,
        SymbolicComponentOperationOutputTriggerGroup,
    ],
)
def test_generated_operation_signatures_preserve_parameter_kinds(
    client_type: (
        type[
            ComponentOperationOutputTriggerClient
            | SymbolicComponentOperationOutputTriggerClient
            | SymbolicComponentOperationOutputTriggerGroup
        ]
    ),
) -> None:
    signature = inspect.signature(client_type.emit)

    assert signature.parameters["count"].kind is inspect.Parameter.POSITIONAL_ONLY
    assert signature.parameters["width"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.parameters["label"].kind is inspect.Parameter.KEYWORD_ONLY
    if client_type is ComponentOperationOutputTriggerClient:
        assert "effect_id" not in signature.parameters
    else:
        assert signature.parameters["effect_id"].kind is inspect.Parameter.KEYWORD_ONLY


def test_generated_symbolic_components_share_and_clear_root_authoring_state() -> None:
    context = ModuleContext()
    root = assert_type(
        component_operation(context, "pulse"),
        SymbolicComponentOperationClient,
    )
    output = assert_type(root.output, SymbolicComponentOperationOutputClient)
    trigger = assert_type(
        output.trigger,
        SymbolicComponentOperationOutputTriggerClient,
    )
    count = assert_type(
        coordinate("pulse_count", ScalarType(IntType())),
        ValueRef,
    )
    width = Quantity(0.5, "s")
    root._state_assignments[
        COMPONENT_OPERATION_DECLARATION.ref.property("remembered")
    ] = True

    assert output._owner is root
    assert trigger._owner is root
    assert output._resource is root._resource
    assert trigger._resource is root._resource
    assert output._state_assignments is root._state_assignments
    assert trigger._state_assignments is root._state_assignments

    assert_type(
        trigger.emit(
            count,
            width,
            label="calibration",
            effect_id="first",
        ),
        None,
    )

    assert root._state_assignments == {}
    interface, body, _ = context.close_experiment_parts_internal()
    assert len(interface.resources) == 1
    [invocation] = body.invocations
    assert isinstance(invocation, InvocationIntent)
    assert invocation.id == "pulse.first"
    assert invocation.port_id == root.resource.port_id
    assert invocation.component_path == ("signal_output", "pulse_trigger")
    assert invocation.operation_id == "emit_pulse"
    assert [argument.id for argument in invocation.arguments] == [
        "pulse_count",
        "pulse_width",
        "pulse_label",
    ]
    assert [argument.value for argument in invocation.arguments] == [
        count,
        width,
        "calibration",
    ]


def test_generated_component_group_aligns_every_argument_before_effects() -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    context = ModuleContext()
    group = assert_type(
        component_operation(context, "pulse", for_=each(q0, q1)),
        SymbolicComponentOperationGroup,
    )
    output = assert_type(group.output, SymbolicComponentOperationOutputGroup)
    trigger = assert_type(
        output.trigger,
        SymbolicComponentOperationOutputTriggerGroup,
    )

    assert trigger.entities == (q0, q1)
    assert tuple(trigger.clients) == (q0, q1)
    with pytest.raises(ValueError, match=r"exactly match.*missing logical_device:q1"):
        trigger.emit(
            3,
            Quantity(0.25, "s"),
            label=PerEntity(((q0, "left"),)),
        )

    definition = context.close_definition_internal(id="test.generated-align-error")
    assert definition.body.invocations == ()


def test_generated_component_group_maps_every_argument_by_entity_identity() -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    context = ModuleContext()
    group = component_operation(context, "pulse", for_=each(q0, q1))
    width = Quantity(0.75, "s")

    group.output.trigger.emit(
        PerEntity(((q1, 9), (q0, 4))),
        width,
        label=PerEntity(((q1, "right"), (q0, "left"))),
    )

    definition = context.close_definition_internal(id="test.generated-align")
    assert len(definition.interface.resources) == 2
    invocations = definition.body.invocations
    assert len(invocations) == 2
    assert [invocation.arguments[0].value for invocation in invocations] == [4, 9]
    assert [invocation.arguments[1].value for invocation in invocations] == [
        width,
        width,
    ]
    assert [invocation.arguments[2].value for invocation in invocations] == [
        "left",
        "right",
    ]
    assert all(
        invocation.component_path == ("signal_output", "pulse_trigger")
        for invocation in invocations
    )
