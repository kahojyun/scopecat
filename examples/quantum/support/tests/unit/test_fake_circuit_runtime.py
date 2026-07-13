from __future__ import annotations

import copy
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scopecat import Quantity
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import link_program
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.products import ProductAxisDef, ProductKind
from scopecat._compiler.program import (
    TypedProgram,
    product_axis,
    product_output,
    record_product,
    shot_axis,
)
from scopecat._point_domain_algebra import point_rows
from scopecat._relation_verification import RelationTypeBindings
from scopecat._relations import literal_rows
from scopecat._value_expressions import verify_table_value_expr
from scopecat.config_profiles import load_config_profile
from scopecat.domain_invocation import (
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.errors import CheckFailed
from scopecat.results import ComplexQuantity, MeasurementArray, MeasurementDType
from scopecat.value_types import Float, Scalar, Table, TableColumn
from scopecat_quantum import (
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    CalibrationCatalog,
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    CircuitProgram,
    CircuitSequence,
    CircuitTargetAcquisitionUseBinding,
    CircuitTargetEntryPointBinding,
    CircuitTargetResultMapping,
    CompiledCircuitTarget,
    Constant,
    Measure,
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
    Play,
    PulseEventId,
    PulseParallel,
    PulseProgram,
    PulseProgramId,
    QubitId,
    ReadoutSignal,
    TargetAcquisitionAddress,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompileRequest,
    TargetCompilerId,
    TargetId,
    bind_compiled_circuit_target,
    compile_target,
    prepare_circuit_target_batch,
    prepare_circuit_target_entry,
    seal_circuit_target_result_mapping,
    select_calibrations,
    verify_circuit_program,
)

from quantum_lab_demo.targets.fake_list_mode import (
    CorrelatedFakeListFrame,
    CorrelatedFakeListRun,
    FakeAwgPlayback,
    FakeDigitizerChannelId,
    FakeListArtifact,
    FakeListAwg,
    FakeListRun,
    FakeListRuntime,
    FakeListTargetCompiler,
    FakeMeasurementRealizationBinding,
    FakeMeasurementRealizationKind,
    RealizedFakeMeasurementRun,
    SelectedFakeMeasurementOutput,
    SelectedFakeMeasurementRealization,
    correlate_fake_list_run,
    default_fake_list_target,
    execute_correlated_fake_list,
    execute_realized_fake_measurements,
    integrated_iq_shots,
    raw_trace_shots,
    realize_fake_measurements,
    select_fake_measurement_realization,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
Q0 = QubitId("q0")
SHARED_SLOT = AcquisitionSlotId("result", scope=("circuit-local",))
MIXED_IQ_SLOT = AcquisitionSlotId("iq-result", scope=("circuit-local",))
MIXED_TRACE_SLOT = AcquisitionSlotId("trace-result", scope=("circuit-local",))


def _raw_trace_axes(
    repetitions: int,
    sample_count: int,
) -> tuple[ProductAxisDef, ProductAxisDef]:
    return (
        shot_axis(repetitions),
        product_axis("sample", size=sample_count, kind="sample", unit="count"),
    )


@dataclass(frozen=True, slots=True)
class _Scenario:
    linked_points: MaterializedLinkedPoints
    mapping: CircuitTargetResultMapping
    compiler: FakeListTargetCompiler
    compiled_target: CompiledCircuitTarget[FakeListArtifact]


@dataclass(frozen=True, slots=True)
class _FaultyAcquisitionCompiler:
    """Return a self-declared artifact whose acquisition disagrees with input."""

    inner: FakeListTargetCompiler
    mutation: str

    @property
    def id(self) -> TargetCompilerId:
        return self.inner.id

    @property
    def target_id(self) -> TargetId:
        return self.inner.target_id

    @property
    def capability_fingerprint(self) -> str:
        return self.inner.capability_fingerprint

    def compile(self, request: TargetCompileRequest) -> FakeListArtifact:
        artifact = self.inner.compile(request)
        if self.mutation == "sample_rate":
            return replace(
                artifact,
                id=TargetArtifactId("faulty-sample-rate"),
                artifact_fingerprint="sha256:faulty-sample-rate",
                sample_rate_hz=artifact.sample_rate_hz * 2,
            )
        entry = artifact.entries[0]
        window = entry.acquisitions[0]
        if self.mutation == "kind":
            bad_window = replace(window, kind=AcquisitionKind.RAW_TRACE)
        elif self.mutation == "event":
            bad_window = replace(window, event_id=PulseEventId("foreign-event"))
        elif self.mutation == "channel":
            bad_window = replace(
                window,
                channel_id=FakeDigitizerChannelId("foreign-channel"),
            )
        else:
            bad_window = replace(window, sample_count=window.sample_count - 1)
        bad_entry = replace(entry, acquisitions=(bad_window, *entry.acquisitions[1:]))
        return replace(
            artifact,
            id=TargetArtifactId(f"faulty-{self.mutation}"),
            artifact_fingerprint=f"sha256:faulty-{self.mutation}",
            entries=(bad_entry, *artifact.entries[1:]),
        )


class _CountingFakeListAwg(FakeListAwg):
    """Observe the host-visible fake AWG call without changing playback."""

    __slots__ = ("play_calls",)

    def __init__(self) -> None:
        object.__setattr__(self, "play_calls", 0)

    def play(self, artifact: FakeListArtifact) -> tuple[FakeAwgPlayback, ...]:
        object.__setattr__(self, "play_calls", self.play_calls + 1)
        return super().play(artifact)


def _integrated_iq_bindings(
    scenario: _Scenario,
) -> tuple[FakeMeasurementRealizationBinding, ...]:
    return tuple(
        integrated_iq_shots(result.result_address)
        for result in scenario.mapping.results
    )


def _raw_trace_bindings(
    scenario: _Scenario,
) -> tuple[FakeMeasurementRealizationBinding, ...]:
    return tuple(
        raw_trace_shots(result.result_address) for result in scenario.mapping.results
    )


def _linked_points(
    *,
    product_kind: ProductKind = "observable",
    product_dtype: MeasurementDType = "complex128",
    product_unit: str | None = None,
    product_axes: tuple[ProductAxisDef, ...] = (),
) -> MaterializedLinkedPoints:
    point_type = Table(
        columns=(TableColumn("coordinate", Scalar(Float())),),
        min_rows=3,
        max_rows=3,
    )
    point_domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(
                    (
                        {"coordinate": 10.0},
                        {"coordinate": 20.0},
                        {"coordinate": 30.0},
                    )
                ),
                bindings=RelationTypeBindings(),
                expected_type=point_type,
            )
        )
    )
    product = product_output(
        "raw-iq",
        kind=product_kind,
        dtype=product_dtype,
        unit=product_unit,
        axes=product_axes,
    )
    product_use, record = record_product(product)
    program = TypedProgram(
        id="fake-circuit-runtime",
        kind="fake_circuit_runtime_test",
        point_domain=point_domain,
        product_defs=(product,),
        product_uses=(product_use,),
        record_uses=(record,),
    )
    environment = validate_config_environment(
        load_config_profile(
            _REPO_ROOT / "fixtures/core/simple_scan/config-profile.json"
        )
    )
    return materialize_linked_points(link_program(program, environment))


def _mixed_linked_points(
    *,
    repetitions: int,
    sample_count: int,
) -> MaterializedLinkedPoints:
    point_type = Table(
        columns=(TableColumn("coordinate", Scalar(Float())),),
        min_rows=3,
        max_rows=3,
    )
    point_domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(
                    (
                        {"coordinate": 10.0},
                        {"coordinate": 20.0},
                        {"coordinate": 30.0},
                    )
                ),
                bindings=RelationTypeBindings(),
                expected_type=point_type,
            )
        )
    )
    iq_product = product_output(
        "iq-shots",
        dtype="complex128",
        unit="ratio",
        axes=(shot_axis(repetitions),),
    )
    trace_product = product_output(
        "raw-trace",
        dtype="complex128",
        unit="ratio",
        axes=_raw_trace_axes(repetitions, sample_count),
    )
    iq_use, iq_record = record_product(iq_product)
    trace_use, trace_record = record_product(trace_product)
    program = TypedProgram(
        id="mixed-fake-circuit-runtime",
        kind="mixed_fake_circuit_runtime_test",
        point_domain=point_domain,
        product_defs=(iq_product, trace_product),
        product_uses=(iq_use, trace_use),
        record_uses=(iq_record, trace_record),
    )
    environment = validate_config_environment(
        load_config_profile(
            _REPO_ROOT / "fixtures/core/simple_scan/config-profile.json"
        )
    )
    return materialize_linked_points(link_program(program, environment))


def _verified_measurement_circuit(
    acquisition_kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
    *,
    sample_count: int = 4,
):
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=Q0,
        acquisition_slot_id=SHARED_SLOT,
        acquisition_kind=acquisition_kind,
    )
    circuit = verify_circuit_program(
        CircuitProgram(
            id=CircuitId("shared-readout-circuit"),
            body=measurement,
        ),
        (),
    )
    template_slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-result"),
        kind=acquisition_kind,
        signal=AcquireSignal(Q0),
    )
    template = PulseProgram(
        id=PulseProgramId("readout-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("stimulus"),
                    signal=ReadoutSignal(Q0),
                    envelope=Constant(
                        duration=Quantity(sample_count, "ns"),
                        amplitude=Quantity(0.4, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("capture"),
                    signal=AcquireSignal(Q0),
                    slot_id=template_slot.id,
                    duration=Quantity(sample_count, "ns"),
                ),
            )
        ),
        acquisition_slots=(template_slot,),
    )
    calibration = MeasurementCalibration(
        id=CalibrationId("readout-q0"),
        key=MeasurementCalibrationKey.from_measurement(measurement),
        pulse_template=template,
    )
    selection = select_calibrations(
        circuit,
        CalibrationCatalog(
            measurements=MeasurementCalibrationCatalog((calibration,)),
        ),
    )
    return circuit, selection


def _verified_mixed_measurement_circuit(*, sample_count: int):
    iq_measurement = Measure(
        id=CircuitOperationId("measure-iq"),
        qubit=Q0,
        acquisition_slot_id=MIXED_IQ_SLOT,
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    trace_measurement = Measure(
        id=CircuitOperationId("measure-trace"),
        qubit=Q0,
        acquisition_slot_id=MIXED_TRACE_SLOT,
        acquisition_kind=AcquisitionKind.RAW_TRACE,
    )
    circuit = verify_circuit_program(
        CircuitProgram(
            id=CircuitId("mixed-readout-circuit"),
            body=CircuitSequence((iq_measurement, trace_measurement)),
        ),
        (),
    )

    def calibration(
        measurement: Measure,
        *,
        suffix: str,
    ) -> MeasurementCalibration:
        template_slot = AcquisitionSlot(
            id=AcquisitionSlotId(f"template-{suffix}"),
            kind=measurement.acquisition_kind,
            signal=AcquireSignal(Q0),
        )
        template = PulseProgram(
            id=PulseProgramId(f"readout-template-{suffix}"),
            body=PulseParallel(
                (
                    Play(
                        id=PulseEventId(f"stimulus-{suffix}"),
                        signal=ReadoutSignal(Q0),
                        envelope=Constant(
                            duration=Quantity(sample_count, "ns"),
                            amplitude=Quantity(0.4, "arb"),
                        ),
                    ),
                    Acquire(
                        id=PulseEventId(f"capture-{suffix}"),
                        signal=AcquireSignal(Q0),
                        slot_id=template_slot.id,
                        duration=Quantity(sample_count, "ns"),
                    ),
                )
            ),
            acquisition_slots=(template_slot,),
        )
        return MeasurementCalibration(
            id=CalibrationId(f"readout-q0-{suffix}"),
            key=MeasurementCalibrationKey.from_measurement(measurement),
            pulse_template=template,
        )

    selection = select_calibrations(
        circuit,
        CalibrationCatalog(
            measurements=MeasurementCalibrationCatalog(
                (
                    calibration(iq_measurement, suffix="iq"),
                    calibration(trace_measurement, suffix="trace"),
                )
            ),
        ),
    )
    return circuit, selection


def _scenario(
    *,
    repetitions: int = 2,
    product_kind: ProductKind = "observable",
    product_dtype: MeasurementDType = "complex128",
    product_unit: str | None = None,
    product_axes: tuple[ProductAxisDef, ...] = (),
    acquisition_kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
    sample_count: int = 4,
) -> _Scenario:
    linked_points = _linked_points(
        product_kind=product_kind,
        product_dtype=product_dtype,
        product_unit=product_unit,
        product_axes=product_axes,
    )
    circuit, selection = _verified_measurement_circuit(
        acquisition_kind,
        sample_count=sample_count,
    )
    adapter_point_order = (2, 0, 1)
    entries = tuple(
        prepare_circuit_target_entry(
            TargetCompileEntryId(f"entry-{point_index}"),
            circuit,
            selection,
            output_id=PulseProgramId("shared-readout-pulses"),
        )
        for point_index in adapter_point_order
    )
    target = default_fake_list_target()
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    batch = prepare_circuit_target_batch(
        entries,
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=repetitions,
    )
    points = linked_points.point_domain.points
    product_use = linked_points.linked_plan.product_uses[0]
    mapping = seal_circuit_target_result_mapping(
        linked_points,
        batch,
        tuple(
            CircuitTargetEntryPointBinding(
                entry.id,
                points[point_index].logical_id,
            )
            for entry, point_index in zip(
                batch.entries,
                adapter_point_order,
                strict=True,
            )
        ),
        tuple(
            CircuitTargetAcquisitionUseBinding(
                entry.acquisition_addresses[0],
                product_use.id,
            )
            for entry in batch.entries
        ),
    )
    compiled = compile_target(compiler, batch.request)
    return _Scenario(
        linked_points=linked_points,
        mapping=mapping,
        compiler=compiler,
        compiled_target=bind_compiled_circuit_target(mapping, compiled),
    )


def _mixed_scenario(
    *,
    repetitions: int = 2,
    sample_count: int = 4,
) -> _Scenario:
    linked_points = _mixed_linked_points(
        repetitions=repetitions,
        sample_count=sample_count,
    )
    circuit, selection = _verified_mixed_measurement_circuit(sample_count=sample_count)
    adapter_point_order = (2, 0, 1)
    entries = tuple(
        prepare_circuit_target_entry(
            TargetCompileEntryId(f"mixed-entry-{point_index}"),
            circuit,
            selection,
            output_id=PulseProgramId("mixed-readout-pulses"),
        )
        for point_index in adapter_point_order
    )
    target = default_fake_list_target()
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    batch = prepare_circuit_target_batch(
        entries,
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=repetitions,
    )
    points = linked_points.point_domain.points
    iq_use, trace_use = linked_points.linked_plan.product_uses
    mapping = seal_circuit_target_result_mapping(
        linked_points,
        batch,
        tuple(
            CircuitTargetEntryPointBinding(
                entry.id,
                points[point_index].logical_id,
            )
            for entry, point_index in zip(
                batch.entries,
                adapter_point_order,
                strict=True,
            )
        ),
        tuple(
            CircuitTargetAcquisitionUseBinding(
                address,
                iq_use.id if address.slot_id == MIXED_IQ_SLOT else trace_use.id,
            )
            for entry in batch.entries
            for address in entry.acquisition_addresses
        ),
    )
    compiled = compile_target(compiler, batch.request)
    return _Scenario(
        linked_points=linked_points,
        mapping=mapping,
        compiler=compiler,
        compiled_target=bind_compiled_circuit_target(mapping, compiled),
    )


def _mixed_bindings(
    scenario: _Scenario,
) -> tuple[FakeMeasurementRealizationBinding, ...]:
    return tuple(
        (
            integrated_iq_shots(result.result_address)
            if result.result_address.slot_id == MIXED_IQ_SLOT
            else raw_trace_shots(result.result_address)
        )
        for result in scenario.mapping.results
    )


def test_three_point_fake_circuit_run_correlates_target_and_logical_order() -> None:
    scenario = _scenario()

    correlated = execute_correlated_fake_list(
        FakeListRuntime(),
        scenario.compiled_target,
    )

    points = scenario.linked_points.point_domain.points
    product_use = scenario.linked_points.linked_plan.product_uses[0]
    assert tuple(
        address.slot_id for address in scenario.mapping.batch.acquisition_addresses
    ) == (
        SHARED_SLOT,
        SHARED_SLOT,
        SHARED_SLOT,
    )
    assert tuple(
        (frame.shot_index, frame.entry_id) for frame in correlated.raw_frames
    ) == tuple(
        (shot_index, TargetCompileEntryId(f"entry-{point_index}"))
        for shot_index in range(2)
        for point_index in (2, 0, 1)
    )
    assert tuple(
        (frame.logical_point_id, frame.product_use_id, frame.shot_index)
        for frame in correlated.frames
    ) == tuple(
        (point.logical_id, product_use.id, shot_index)
        for point in points
        for shot_index in range(2)
    )
    assert tuple(frame.frame.entry_id for frame in correlated.frames) == tuple(
        TargetCompileEntryId(f"entry-{point_index}")
        for point_index in range(3)
        for _shot_index in range(2)
    )

    for point_index, point in enumerate(points):
        logical_result = scenario.mapping.result_for_output(
            point.logical_id,
            product_use.id,
        )
        address = logical_result.result_address
        origin = scenario.mapping.batch.acquisition_origin_for(address)
        assert address.entry_id == TargetCompileEntryId(f"entry-{point_index}")
        assert origin.source_circuit_id == CircuitId("shared-readout-circuit")
        assert origin.provenance.measurement_id == CircuitOperationId("measure")
        assert origin.provenance.acquisition_slot_id == SHARED_SLOT
        output_frames = correlated.frames_for_output(
            point.logical_id,
            product_use.id,
        )
        assert tuple(frame.shot_index for frame in output_frames) == (0, 1)
        for shot_index, frame in enumerate(output_frames):
            assert frame is correlated.frame_for_output(
                point.logical_id,
                product_use.id,
                shot_index,
            )
            assert frame is correlated.frame_for_address(address, shot_index)
            assert frame.logical_result is logical_result
            assert frame.acquisition_origin is origin


def test_correlated_fake_frames_remain_raw_and_are_not_product_values() -> None:
    scenario = _scenario()

    correlated = execute_correlated_fake_list(
        FakeListRuntime(),
        scenario.compiled_target,
    )

    assert {field.name for field in fields(CorrelatedFakeListFrame)} == {
        "frame",
        "logical_result",
        "acquisition_origin",
    }
    assert all(isinstance(item.frame.value, complex) for item in correlated.frames)
    assert all(not hasattr(item, "value") for item in correlated.frames)
    assert all(item.logical_result.product.axes == () for item in correlated.frames)
    assert all(
        len(
            correlated.frames_for_output(
                result.logical_point_id,
                result.product_use_id,
            )
        )
        == 2
        for result in scenario.mapping.results
    )
    assert not hasattr(correlated, "measurements")
    assert not hasattr(correlated, "product_values")


def test_integrated_iq_shot_realization_accepts_exact_product_contract() -> None:
    scenario = _scenario(
        product_unit="ratio",
        product_axes=(shot_axis(2),),
    )
    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
        _integrated_iq_bindings(scenario),
    )
    realized = execute_realized_fake_measurements(
        FakeListRuntime(),
        selection,
    )
    correlated = realized.correlated_run

    assert realized.selection is selection
    assert realized.output_values.selection is selection.core_outputs
    assert realized.correlated_run is correlated
    assert realized.mapping is scenario.mapping
    assert realized.output_values.mapping is scenario.mapping.core_mapping
    assert (
        tuple(output.result for output in realized.outputs) == scenario.mapping.results
    )
    for output in realized.outputs:
        frames = realized.frames_for_output(
            output.logical_point_id,
            output.product_use_id,
        )
        assert (
            realized.output_for_output(
                output.logical_point_id,
                output.product_use_id,
            )
            is output
        )
        assert frames == correlated.frames_for_output(
            output.logical_point_id,
            output.product_use_id,
        )
        value = output.value
        assert isinstance(value, MeasurementArray)
        assert value.dtype == "complex128"
        assert value.unit == "ratio"
        assert value.shape == [2]
        assert value.values == [
            ComplexQuantity(
                real=cast("complex", frame.frame.value).real,
                imag=cast("complex", frame.frame.value).imag,
                unit="ratio",
            )
            for frame in frames
        ]
    assert not hasattr(realized, "measurements")


@given(repetitions=st.integers(min_value=1, max_value=8))
@settings(max_examples=8, deadline=None)
def test_integrated_iq_realization_preserves_generated_shot_cardinality(
    repetitions: int,
) -> None:
    scenario = _scenario(
        repetitions=repetitions,
        product_unit="ratio",
        product_axes=(shot_axis(repetitions),),
    )

    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
        _integrated_iq_bindings(scenario),
    )
    realized = execute_realized_fake_measurements(
        FakeListRuntime(),
        selection,
    )

    assert all(
        cast("MeasurementArray", output.value).shape == [repetitions]
        for output in realized.outputs
    )
    assert all(
        tuple(
            frame.shot_index
            for frame in realized.frames_for_output(
                output.logical_point_id,
                output.product_use_id,
            )
        )
        == tuple(range(repetitions))
        for output in realized.outputs
    )


@pytest.mark.parametrize(
    ("scenario_kwargs", "expected_code"),
    (
        ({"product_unit": "ratio"}, "fake_integrated_iq_product_axes_mismatch"),
        (
            {"product_unit": "ratio", "product_axes": (shot_axis(3),)},
            "fake_integrated_iq_shot_count_mismatch",
        ),
        (
            {
                "product_dtype": "float64",
                "product_unit": "ratio",
                "product_axes": (shot_axis(2),),
            },
            "fake_integrated_iq_product_dtype_mismatch",
        ),
        (
            {"product_axes": (shot_axis(2),)},
            "fake_integrated_iq_product_unit_mismatch",
        ),
        (
            {
                "product_unit": "ratio",
                "product_axes": (
                    product_axis("sample", size=2, kind="sample", unit="count"),
                ),
            },
            "fake_integrated_iq_shot_axis_mismatch",
        ),
        (
            {
                "product_kind": "readback",
                "product_unit": "ratio",
                "product_axes": (shot_axis(2),),
            },
            "fake_integrated_iq_product_kind_mismatch",
        ),
        (
            {
                "product_unit": "ratio",
                "product_axes": (shot_axis(2),),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_integrated_iq_acquisition_kind_mismatch",
        ),
    ),
)
def test_integrated_iq_realization_rejects_implicit_or_incompatible_policies(
    scenario_kwargs: dict[str, object],
    expected_code: str,
) -> None:
    scenario = _scenario(**scenario_kwargs)  # type: ignore[arg-type]

    with pytest.raises(CheckFailed) as captured:
        select_fake_measurement_realization(
            scenario.compiled_target,
            scenario.compiler.target,
            _integrated_iq_bindings(scenario),
        )

    assert expected_code in {problem.code for problem in captured.value.problems}
    assert all(problem.phase.value == "planning" for problem in captured.value.problems)


def test_raw_trace_realization_accepts_exact_shot_sample_contract() -> None:
    repetitions = 2
    sample_count = 4
    scenario = _scenario(
        repetitions=repetitions,
        product_unit="ratio",
        product_axes=_raw_trace_axes(repetitions, sample_count),
        acquisition_kind=AcquisitionKind.RAW_TRACE,
        sample_count=sample_count,
    )

    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
        _raw_trace_bindings(scenario),
    )
    realized = execute_realized_fake_measurements(FakeListRuntime(), selection)
    correlated = realized.correlated_run

    assert realized.selection is selection
    assert realized.output_values.selection is selection.core_outputs
    assert realized.correlated_run is correlated
    assert realized.mapping is scenario.mapping
    assert realized.output_values.mapping is scenario.mapping.core_mapping
    assert (
        tuple(output.result for output in realized.outputs) == scenario.mapping.results
    )
    for output in realized.outputs:
        frames = realized.frames_for_output(
            output.logical_point_id,
            output.product_use_id,
        )
        assert (
            realized.output_for_output(
                output.logical_point_id,
                output.product_use_id,
            )
            is output
        )
        assert frames == correlated.frames_for_output(
            output.logical_point_id,
            output.product_use_id,
        )
        value = output.value
        assert isinstance(value, MeasurementArray)
        assert value.dtype == "complex128"
        assert value.unit == "ratio"
        assert value.shape == [repetitions, sample_count]
        assert value.values == [
            [
                ComplexQuantity(
                    real=sample.real,
                    imag=sample.imag,
                    unit="ratio",
                )
                for sample in cast("tuple[complex, ...]", frame.frame.value)
            ]
            for frame in frames
        ]
    assert not hasattr(realized, "measurements")


@given(
    repetitions=st.integers(min_value=1, max_value=6),
    sample_count=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=12, deadline=None)
def test_raw_trace_realization_preserves_generated_shot_sample_cardinality(
    repetitions: int,
    sample_count: int,
) -> None:
    scenario = _scenario(
        repetitions=repetitions,
        product_unit="ratio",
        product_axes=_raw_trace_axes(repetitions, sample_count),
        acquisition_kind=AcquisitionKind.RAW_TRACE,
        sample_count=sample_count,
    )

    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
        _raw_trace_bindings(scenario),
    )
    realized = execute_realized_fake_measurements(FakeListRuntime(), selection)

    for output in realized.outputs:
        value = output.value
        assert isinstance(value, MeasurementArray)
        assert value.shape == [repetitions, sample_count]
        assert len(value.values) == repetitions
        assert all(
            len(cast("list[ComplexQuantity]", samples)) == sample_count
            for samples in value.values
        )
        frames = realized.frames_for_output(
            output.logical_point_id,
            output.product_use_id,
        )
        assert tuple(frame.shot_index for frame in frames) == tuple(range(repetitions))
        assert all(
            len(cast("tuple[complex, ...]", frame.frame.value)) == sample_count
            for frame in frames
        )


@pytest.mark.parametrize(
    ("scenario_kwargs", "expected_code"),
    (
        (
            {
                "product_unit": "ratio",
                "product_axes": (shot_axis(2),),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_raw_trace_product_axes_mismatch",
        ),
        (
            {
                "product_unit": "ratio",
                "product_axes": _raw_trace_axes(3, 4),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_raw_trace_shot_count_mismatch",
        ),
        (
            {
                "product_unit": "ratio",
                "product_axes": _raw_trace_axes(2, 3),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_raw_trace_sample_count_mismatch",
        ),
        (
            {
                "product_dtype": "float64",
                "product_unit": "ratio",
                "product_axes": _raw_trace_axes(2, 4),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_raw_trace_product_dtype_mismatch",
        ),
        (
            {
                "product_axes": _raw_trace_axes(2, 4),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_raw_trace_product_unit_mismatch",
        ),
        (
            {
                "product_unit": "ratio",
                "product_axes": (
                    product_axis(
                        "sample",
                        size=4,
                        kind="sample",
                        unit="count",
                    ),
                    shot_axis(2),
                ),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_raw_trace_shot_axis_mismatch",
        ),
        (
            {
                "product_unit": "ratio",
                "product_axes": (
                    shot_axis(2),
                    product_axis(
                        "time",
                        size=4,
                        kind="sample",
                        unit="ns",
                    ),
                ),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_raw_trace_sample_axis_mismatch",
        ),
        (
            {
                "product_kind": "readback",
                "product_unit": "ratio",
                "product_axes": _raw_trace_axes(2, 4),
                "acquisition_kind": AcquisitionKind.RAW_TRACE,
            },
            "fake_raw_trace_product_kind_mismatch",
        ),
        (
            {
                "product_unit": "ratio",
                "product_axes": _raw_trace_axes(2, 4),
            },
            "fake_raw_trace_acquisition_kind_mismatch",
        ),
    ),
)
def test_raw_trace_realization_rejects_incompatible_policy_before_effects(
    scenario_kwargs: dict[str, object],
    expected_code: str,
) -> None:
    scenario = _scenario(**scenario_kwargs)  # type: ignore[arg-type]

    with pytest.raises(CheckFailed) as captured:
        select_fake_measurement_realization(
            scenario.compiled_target,
            scenario.compiler.target,
            _raw_trace_bindings(scenario),
        )

    assert expected_code in {problem.code for problem in captured.value.problems}
    assert all(problem.phase.value == "planning" for problem in captured.value.problems)


@pytest.mark.parametrize(
    ("mutation", "expected_code", "expected_category"),
    (
        (
            "missing",
            "fake_measurement_realization_binding_missing",
            "invalid_input",
        ),
        (
            "duplicate",
            "fake_measurement_realization_binding_duplicate",
            "conflict",
        ),
        (
            "unknown",
            "fake_measurement_realization_binding_unknown",
            "invalid_input",
        ),
    ),
)
def test_measurement_realization_bindings_require_exact_result_coverage(
    mutation: str,
    expected_code: str,
    expected_category: str,
) -> None:
    scenario = _scenario(
        product_unit="ratio",
        product_axes=(shot_axis(2),),
    )
    bindings = _integrated_iq_bindings(scenario)
    if mutation == "missing":
        selected_bindings = bindings[:-1]
    elif mutation == "duplicate":
        selected_bindings = (*bindings, bindings[0])
    else:
        selected_bindings = (
            *bindings,
            integrated_iq_shots(
                TargetAcquisitionAddress(
                    entry_id=TargetCompileEntryId("foreign-entry"),
                    slot_id=SHARED_SLOT,
                )
            ),
        )

    with pytest.raises(CheckFailed) as captured:
        select_fake_measurement_realization(
            scenario.compiled_target,
            scenario.compiler.target,
            selected_bindings,
        )

    assert {problem.code for problem in captured.value.problems} == {expected_code}
    assert all(
        problem.category.value == expected_category
        and problem.phase.value == "planning"
        for problem in captured.value.problems
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("kind", "fake_measurement_artifact_acquisition_mismatch"),
        ("event", "fake_measurement_artifact_acquisition_mismatch"),
        ("channel", "fake_measurement_artifact_acquisition_mismatch"),
        ("sample_count", "fake_measurement_artifact_acquisition_mismatch"),
        ("sample_rate", "fake_measurement_artifact_capability_mismatch"),
    ),
)
def test_measurement_selection_rejects_faulty_artifact_acquisition_before_effects(
    mutation: str,
    expected_code: str,
) -> None:
    scenario = _scenario(
        product_unit="ratio",
        product_axes=(shot_axis(2),),
    )
    faulty_compiled = compile_target(
        _FaultyAcquisitionCompiler(scenario.compiler, mutation),
        scenario.mapping.batch.request,
    )
    faulty_target = bind_compiled_circuit_target(
        scenario.mapping,
        faulty_compiled,
    )

    with pytest.raises(CheckFailed) as captured:
        select_fake_measurement_realization(
            faulty_target,
            scenario.compiler.target,
            _integrated_iq_bindings(scenario),
        )

    assert {problem.code for problem in captured.value.problems} == {expected_code}
    assert all(
        problem.category.value == "provider_contract"
        and problem.phase.value == "planning"
        for problem in captured.value.problems
    )


def test_measurement_selection_rejects_a_different_target_capability() -> None:
    scenario = _scenario(
        product_unit="ratio",
        product_axes=(shot_axis(2),),
    )
    different_target = replace(
        scenario.compiler.target,
        sample_rate_hz=scenario.compiler.target.sample_rate_hz * 2,
    )

    with pytest.raises(CheckFailed) as captured:
        select_fake_measurement_realization(
            scenario.compiled_target,
            different_target,
            _integrated_iq_bindings(scenario),
        )

    assert {problem.code for problem in captured.value.problems} == {
        "fake_measurement_target_mismatch"
    }
    assert all(
        problem.category.value == "conflict" and problem.phase.value == "planning"
        for problem in captured.value.problems
    )


def test_mixed_iq_and_raw_trace_policies_share_one_batch_execution() -> None:
    repetitions = 2
    sample_count = 4
    scenario = _mixed_scenario(
        repetitions=repetitions,
        sample_count=sample_count,
    )
    bindings = _mixed_bindings(scenario)

    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
        bindings,
    )
    awg = _CountingFakeListAwg()
    realized = execute_realized_fake_measurements(
        FakeListRuntime(awg=awg),
        selection,
    )

    expected_kind_by_address = {
        binding.result_address: binding.kind for binding in bindings
    }
    assert len(bindings) == len(scenario.mapping.results) == 6
    assert awg.play_calls == 1
    assert tuple(output.result for output in selection.outputs) == (
        scenario.mapping.results
    )
    assert tuple(output.result for output in realized.outputs) == (
        scenario.mapping.results
    )
    assert {output.kind for output in selection.outputs} == {
        FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS,
        FakeMeasurementRealizationKind.RAW_TRACE_SHOTS,
    }
    assert all(
        output.kind == expected_kind_by_address[output.result_address]
        for output in selection.outputs
    )

    for output in realized.outputs:
        selected_output = selection.output_for_address(output.result_address)
        frames = realized.frames_for_output(
            output.logical_point_id,
            output.product_use_id,
        )
        value = output.value
        assert isinstance(value, MeasurementArray)
        assert value.dtype == "complex128"
        assert value.unit == "ratio"
        if selected_output.kind is FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS:
            assert value.shape == [repetitions]
            assert value.values == [
                ComplexQuantity(
                    real=cast("complex", frame.frame.value).real,
                    imag=cast("complex", frame.frame.value).imag,
                    unit="ratio",
                )
                for frame in frames
            ]
        else:
            assert value.shape == [repetitions, sample_count]
            assert value.values == [
                [
                    ComplexQuantity(
                        real=sample.real,
                        imag=sample.imag,
                        unit="ratio",
                    )
                    for sample in cast("tuple[complex, ...]", frame.frame.value)
                ]
                for frame in frames
            ]


@given(order=st.permutations(tuple(range(6))))
@settings(max_examples=8, deadline=None)
def test_mixed_realization_binding_order_does_not_change_canonical_values(
    order: list[int],
) -> None:
    scenario = _mixed_scenario(repetitions=2, sample_count=4)
    canonical_bindings = _mixed_bindings(scenario)
    reordered_bindings = tuple(canonical_bindings[index] for index in order)

    canonical = execute_realized_fake_measurements(
        FakeListRuntime(),
        select_fake_measurement_realization(
            scenario.compiled_target,
            scenario.compiler.target,
            canonical_bindings,
        ),
    )
    reordered = execute_realized_fake_measurements(
        FakeListRuntime(),
        select_fake_measurement_realization(
            scenario.compiled_target,
            scenario.compiler.target,
            reordered_bindings,
        ),
    )

    assert tuple(output.result for output in reordered.selection.outputs) == (
        scenario.mapping.results
    )
    assert tuple(output.result for output in reordered.outputs) == (
        scenario.mapping.results
    )
    assert tuple(output.value for output in reordered.outputs) == tuple(
        output.value for output in canonical.outputs
    )


def test_correlation_uses_artifact_content_identity_not_python_identity() -> None:
    scenario = _scenario()
    equivalent_compiled = compile_target(
        scenario.compiler,
        scenario.mapping.batch.request,
    )
    equivalent_run = FakeListRuntime().execute(equivalent_compiled)

    assert equivalent_compiled.artifact == scenario.compiled_target.compiled.artifact
    assert (
        equivalent_compiled.artifact is not scenario.compiled_target.compiled.artifact
    )
    correlated = correlate_fake_list_run(scenario.compiled_target, equivalent_run)
    assert correlated.target_run == equivalent_run


def test_correlation_rejects_a_run_from_another_compiled_artifact() -> None:
    scenario = _scenario()
    foreign_compiled = compile_target(
        scenario.compiler,
        replace(scenario.mapping.batch.request, repetitions=1),
    )
    foreign_run = FakeListRuntime().execute(foreign_compiled)

    with pytest.raises(
        ValueError, match="does not retain the compiled target artifact"
    ):
        correlate_fake_list_run(scenario.compiled_target, foreign_run)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing", "exactly cover artifact acquisition windows"),
        ("duplicate", "addresses must be unique"),
        ("foreign", "acquisition window"),
    ),
)
def test_correlation_rejects_invalid_frame_coverage(
    mutation: str,
    message: str,
) -> None:
    scenario = _scenario()
    target_run = FakeListRuntime().execute(scenario.compiled_target.compiled)
    frames = target_run.frames
    if mutation == "missing":
        selected_frames = frames[:-1]
    elif mutation == "duplicate":
        first = frames[0]
        selected_frames = (
            *frames[:-1],
            replace(
                frames[-1],
                segment_index=first.segment_index,
                shot_index=first.shot_index,
                list_index=first.list_index,
                entry_id=first.entry_id,
                slot_id=first.slot_id,
                channel_id=first.channel_id,
                kind=first.kind,
                value=first.value,
            ),
        )
    else:
        selected_frames = (
            replace(
                frames[0],
                slot_id=AcquisitionSlotId(
                    "foreign",
                    scope=("circuit-local",),
                ),
            ),
            *frames[1:],
        )
    tampered = copy.copy(target_run)
    object.__setattr__(tampered, "frames", selected_frames)

    with pytest.raises(ValueError, match=message):
        correlate_fake_list_run(scenario.compiled_target, tampered)


def test_correlated_fake_runtime_types_are_sealed() -> None:
    scenario = _scenario()
    correlated = execute_correlated_fake_list(
        FakeListRuntime(),
        scenario.compiled_target,
    )
    first = correlated.frames[0]

    with pytest.raises(TypeError, match="can only be created"):
        CorrelatedFakeListFrame(
            first.frame,
            first.logical_result,
            first.acquisition_origin,
        )
    with pytest.raises(TypeError, match="can only be created"):
        CorrelatedFakeListRun(
            scenario.compiled_target,
            correlated.target_run,
            correlated.frames,
        )
    with pytest.raises(TypeError, match="CompiledCircuitTarget"):
        correlate_fake_list_run(
            cast("CompiledCircuitTarget[FakeListArtifact]", object()),
            correlated.target_run,
        )
    with pytest.raises(TypeError, match="FakeListRun"):
        correlate_fake_list_run(
            scenario.compiled_target,
            cast("FakeListRun", object()),
        )
    with pytest.raises(TypeError, match="FakeListRuntime"):
        execute_correlated_fake_list(
            cast("FakeListRuntime", object()),
            scenario.compiled_target,
        )
    with pytest.raises(TypeError, match="CompiledCircuitTarget"):
        execute_correlated_fake_list(
            FakeListRuntime(),
            cast("CompiledCircuitTarget[FakeListArtifact]", object()),
        )

    shot_scenario = _scenario(
        product_unit="ratio",
        product_axes=(shot_axis(2),),
    )
    selection = select_fake_measurement_realization(
        shot_scenario.compiled_target,
        shot_scenario.compiler.target,
        _integrated_iq_bindings(shot_scenario),
    )
    realized = execute_realized_fake_measurements(
        FakeListRuntime(),
        selection,
    )
    selected_output = selection.outputs[0]
    with pytest.raises(TypeError, match="can only be created"):
        SelectedFakeMeasurementOutput(
            selected_output.result,
            selected_output.acquisition_origin,
            selected_output.acquisition_window,
            selected_output.kind,
        )
    with pytest.raises(TypeError, match="can only be created"):
        SelectedFakeMeasurementRealization(
            shot_scenario.compiled_target,
            shot_scenario.compiler.target,
            selection.core_outputs,
            selection.outputs,
        )
    with pytest.raises(TypeError, match="can only be created"):
        RealizedFakeMeasurementRun(
            selection,
            realized.correlated_run,
            realized.output_values,
        )
    with pytest.raises(TypeError, match="selected policy"):
        realize_fake_measurements(
            cast("SelectedFakeMeasurementRealization", object()),
            realized.correlated_run,
        )
    with pytest.raises(TypeError, match="CorrelatedFakeListRun"):
        realize_fake_measurements(
            selection,
            cast("CorrelatedFakeListRun", object()),
        )
    with pytest.raises(TypeError, match="selected policy"):
        execute_realized_fake_measurements(
            FakeListRuntime(),
            cast("SelectedFakeMeasurementRealization", object()),
        )
    with pytest.raises(TypeError, match="TargetAcquisitionAddress"):
        FakeMeasurementRealizationBinding(
            cast("TargetAcquisitionAddress", object()),
            FakeMeasurementRealizationKind.INTEGRATED_IQ_SHOTS,
        )
    with pytest.raises(TypeError, match="realization kind"):
        FakeMeasurementRealizationBinding(
            selected_output.result_address,
            cast("FakeMeasurementRealizationKind", object()),
        )
    with pytest.raises(TypeError, match="realization bindings"):
        select_fake_measurement_realization(
            shot_scenario.compiled_target,
            shot_scenario.compiler.target,
            cast("tuple[FakeMeasurementRealizationBinding, ...]", (object(),)),
        )
    with pytest.raises(KeyError, match="no selected fake policy"):
        selection.output_for_address(
            TargetAcquisitionAddress(
                entry_id=TargetCompileEntryId("foreign"),
                slot_id=SHARED_SLOT,
            )
        )

    raw_trace_scenario = _scenario(
        product_unit="ratio",
        product_axes=_raw_trace_axes(2, 4),
        acquisition_kind=AcquisitionKind.RAW_TRACE,
    )
    raw_trace_selection = select_fake_measurement_realization(
        raw_trace_scenario.compiled_target,
        raw_trace_scenario.compiler.target,
        _raw_trace_bindings(raw_trace_scenario),
    )
    raw_trace_realized = execute_realized_fake_measurements(
        FakeListRuntime(),
        raw_trace_selection,
    )
    assert raw_trace_realized.selection is raw_trace_selection
