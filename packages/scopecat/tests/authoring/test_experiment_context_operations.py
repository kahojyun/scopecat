# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

import scopecat as sc
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.measurements.results import MeasurementValue
from scopecat.program.logical import (
    AcquireEffect,
    LogicalEnsureState,
    LogicalInvocation,
    LogicalStateAssignment,
)
from scopecat.program.measurements import measurement_postprocessor
from scopecat.program.state import StateBinding
from scopecat.sdk.instruments import InterfaceRef, PropertyRef

_DEVICE = InterfaceRef("test.experiment_context_device/v1")
_DEVICE_LEVEL = _DEVICE.property("level")
_DEVICE_ENABLED = _DEVICE.property("enabled")
_DEVICE_MODE = _DEVICE.property("mode")
_DEVICE_TRIGGER = _DEVICE.operation("trigger")
_DEVICE_TRIGGER_LEVEL = _DEVICE_TRIGGER.argument("level")
_DEVICE_SIGNAL = _DEVICE.acquisition("sample").result("signal")
_LEVEL_TYPE = sc.FloatType()


@dataclass(frozen=True)
class _DeviceTarget:
    level: StateBinding
    enabled: StateBinding

    def target_assignments(self) -> Mapping[PropertyRef, StateBinding]:
        return {
            _DEVICE_LEVEL: self.level,
            _DEVICE_ENABLED: self.enabled,
        }


def _build_trigger(*, level: object) -> object:
    return {"level": level}


def _derive_signal(value: MeasurementValue) -> dict[str, MeasurementValue]:
    return {"derived": value}


def test_template_authors_root_device_operations_without_a_module() -> None:
    @sc.template(id="test.experiment-context.direct", kind="direct")
    def direct(
        experiment: sc.ExperimentContext,
        level: Annotated[sc.Input[float], _LEVEL_TYPE] = 1.5,
    ) -> None:
        device = experiment.resource("device", requires=(_DEVICE,))
        trigger_payload = experiment.compute(
            "build-trigger",
            fn=_build_trigger,
            inputs={"level": level},
            output_type=sc.ScalarType(sc.PayloadType("trigger")),
        )
        experiment.ensure(
            device,
            _DeviceTarget(level=level, enabled=True),
        )
        experiment.bind_property(device, _DEVICE_MODE, value="measurement")
        experiment.invoke(
            "trigger",
            resource=device,
            operation=_DEVICE_TRIGGER,
            arguments={_DEVICE_TRIGGER_LEVEL: trigger_payload},
        )
        raw = experiment.product("raw", metadata={"stage": "capture"})
        derived = experiment.product("derived")
        experiment.acquire(
            "read-signal",
            resource=device,
            results={_DEVICE_SIGNAL: raw},
            metadata={"mode": "fast"},
        )
        experiment.measurement_postprocessor(
            measurement_postprocessor(
                "derive",
                input=raw,
                outputs={"derived": derived},
                kernel=_derive_signal,
            )
        )
        experiment.record(raw, derived)
        experiment.finalize(
            device,
            _DeviceTarget(level=0.0, enabled=False),
        )

    invocation = direct()
    root_resources = invocation.definition.interface.resources
    assert [port.qualified_id for port in root_resources] == ["device"]

    logical = compile_invocation(invocation).program.program
    assert [product.qualified_id for product in logical.product_declarations] == [
        "raw",
        "derived",
    ]
    selected_products = [
        selection.product_id.qualified_name for selection in logical.record_selections
    ]
    assert selected_products == [
        "raw",
        "derived",
    ]
    assert [node.id.local_id for node in logical.compute_nodes] == ["build-trigger"]
    postprocessor_ids = [
        postprocessor.id.qualified_name
        for postprocessor in logical.measurement_postprocessors
    ]
    assert postprocessor_ids == ["derive"]
    assert [type(effect) for effect in logical.effects] == [
        LogicalEnsureState,
        LogicalStateAssignment,
        LogicalInvocation,
        AcquireEffect,
    ]
    [invocation_effect] = logical.invocations
    assert invocation_effect.port_id.qualified_name == "device"
    assert invocation_effect.arguments[0].id == "level"
    [acquisition] = logical.acquisitions
    assert acquisition.resource_port_id.qualified_name == "device"
    assert acquisition.results[0].metadata == {"mode": "fast"}
    assert isinstance(logical.final_state, LogicalEnsureState)
    assert [
        assignment.property_id for assignment in logical.final_state.assignments
    ] == ["level", "enabled"]


def test_template_and_scratch_share_direct_root_authoring() -> None:
    def body(experiment: sc.ExperimentContext) -> None:
        device = experiment.resource("device", requires=(_DEVICE,))
        signal = experiment.product("signal")
        experiment.acquire(
            "read-signal",
            resource=device,
            results={_DEVICE_SIGNAL: signal},
        )
        experiment.record(signal)

    template = sc.template(id="test.direct.template", kind="direct")(body)
    scratch = sc.scratch(id="test.direct.scratch", kind="direct")(body)

    template_program = compile_invocation(template()).program.program
    scratch_program = compile_invocation(scratch()).program.program

    assert template_program.resource_ports == scratch_program.resource_ports
    assert template_program.product_declarations == scratch_program.product_declarations
    assert template_program.effects == scratch_program.effects
    template_records = [
        selection.product_id for selection in template_program.record_selections
    ]
    scratch_records = [
        selection.product_id for selection in scratch_program.record_selections
    ]
    assert template_records == scratch_records
