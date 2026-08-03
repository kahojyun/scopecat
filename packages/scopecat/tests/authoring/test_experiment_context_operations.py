# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

import scopecat as sc
from scopecat.authoring._module_context import DefinitionResource
from scopecat.authoring.finalization import FinalizationTarget
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.measurements.results import MeasurementValue
from scopecat.program.logical import (
    AcquireEffect,
    LogicalEnsureState,
    LogicalInvocation,
    LogicalStateAssignment,
)
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


def _device_assignments(
    state: _DeviceTarget,
    /,
) -> Mapping[PropertyRef, StateBinding]:
    return {
        _DEVICE_LEVEL: state.level,
        _DEVICE_ENABLED: state.enabled,
    }


@dataclass(frozen=True)
class _TypedDevice:
    resource: DefinitionResource

    def finalization_targets(
        self,
        state: _DeviceTarget,
        /,
    ) -> tuple[FinalizationTarget, ...]:
        return ((self.resource, _device_assignments(state)),)


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
        device = experiment._resource("device", requires=(_DEVICE,))
        trigger_payload = experiment.compute(
            "build-trigger",
            fn=_build_trigger,
            inputs={"level": level},
            output_type=sc.ScalarType(sc.PayloadType("trigger")),
        )
        experiment._ensure(
            device,
            _device_assignments(_DeviceTarget(level=level, enabled=True)),
        )
        experiment._bind_property(device, _DEVICE_MODE, value="measurement")
        experiment._invoke(
            "trigger",
            resource=device,
            operation=_DEVICE_TRIGGER,
            arguments={_DEVICE_TRIGGER_LEVEL: trigger_payload},
        )
        raw = experiment._product("raw", metadata={"stage": "capture"})
        derived = experiment._product("derived")
        experiment._acquire(
            "read-signal",
            resource=device,
            results={_DEVICE_SIGNAL: raw},
            metadata={"mode": "fast"},
        )
        experiment._postprocess(
            "derive",
            input=raw,
            outputs={"derived": derived},
            kernel=_derive_signal,
        )
        experiment.record(raw, derived)
        experiment.finalize(
            _TypedDevice(device),
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
        selection.product_id.qualified_name
        for selection in logical.product_record_selections
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


def test_template_and_experiment_factory_share_direct_root_authoring() -> None:
    def body(experiment: sc.ExperimentContext) -> None:
        device = experiment._resource("device", requires=(_DEVICE,))
        signal = experiment._product("signal")
        experiment._acquire(
            "read-signal",
            resource=device,
            results={_DEVICE_SIGNAL: signal},
        )
        experiment.record(signal)

    template = sc.template(id="test.direct.template", kind="direct")(body)
    factory = sc.experiment_factory(id="test.direct.factory", kind="direct")(body)

    template_program = compile_invocation(template()).program.program
    factory_program = compile_invocation(factory()).program.program

    assert template_program.resource_ports == factory_program.resource_ports
    assert template_program.product_declarations == factory_program.product_declarations
    assert template_program.effects == factory_program.effects
    template_records = [
        selection.product_id for selection in template_program.product_record_selections
    ]
    factory_records = [
        selection.product_id for selection in factory_program.product_record_selections
    ]
    assert template_records == factory_records


def test_template_records_a_compute_result_as_a_named_dataset_value() -> None:
    @sc.template(id="test.direct.value-record", kind="direct")
    def direct(experiment: sc.ExperimentContext) -> None:
        score = experiment.compute(
            "score",
            fn=lambda: 2.5,
            output_type=sc.ScalarType(sc.FloatType()),
        )
        experiment.record(score)

    logical = compile_invocation(direct()).program.program

    assert logical.product_record_selections == ()
    [record] = logical.value_record_selections
    assert record.id == "score"
    assert record.source_value_id == "score"
    assert record.value_id == logical.compute_nodes[0].result_id


def test_template_derives_value_record_id_after_resolving_a_module_result() -> None:
    @sc.module(id="test.value_source")
    def value_source(module: sc.ModuleContext) -> sc.ValueRef:
        return module.compute(
            "score",
            fn=lambda: 2.5,
            output_type=sc.ScalarType(sc.FloatType()),
        )

    @sc.template(id="test.module-value-record", kind="direct")
    def direct(experiment: sc.ExperimentContext) -> None:
        call = experiment.run(value_source())
        trace = experiment._product("trace")
        experiment.record(call.result, trace)

    logical = compile_invocation(direct()).program.program

    [record] = logical.value_record_selections
    [trace] = logical.product_record_selections
    assert logical.record_selections == (record, trace)
    assert record.id == "value_source/score"
    assert record.source_value_id == "value_source/score"
    assert record.value_id == logical.compute_nodes[0].result_id


def test_value_record_namespaces_preserve_segment_identity() -> None:
    @sc.template(id="test.value-record.namespace", kind="direct")
    def direct(experiment: sc.ExperimentContext) -> None:
        score = experiment.compute(
            "score",
            fn=lambda: 2.5,
            output_type=sc.ScalarType(sc.FloatType()),
        )
        experiment.record(score, namespace="analysis%2Fdaily")
        experiment.record(score, namespace="analysis/daily")

    logical = compile_invocation(direct()).program.program

    assert [record.id for record in logical.value_record_selections] == [
        "analysis%2Fdaily/score",
        "analysis/daily/score",
    ]
