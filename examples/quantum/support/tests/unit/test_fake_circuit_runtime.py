from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TypedDict, cast, override

import pytest
from scopecat import Quantity
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    TypedDomainResultBinding,
    core_domain_executions,
    product_axis,
    record_product,
    shot_axis,
)
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.environment import build_config_environment
from scopecat.domain.program import DomainProgramDef, DomainResultPort
from scopecat.execution.effects.domain import execute_domain_job_values
from scopecat.execution.measurement_recording import (
    append_measurement_dataset,
    seal_measurement_dataset,
)
from scopecat.graph.relations.point_domain import point_axis_values
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.product_identity import product_id
from scopecat.kernel.value_types import Float, Scalar
from scopecat.measurements.products import ProductAxisDef, ProductDef
from scopecat.measurements.projection import (
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurements.results import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementDType,
)
from scopecat.measurements.values import seal_measurement_values
from scopecat.sdk.domain import DomainPreparationBuilder
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    make_domain_compile_template,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
)
from scopecat.sdk.domain.runtime import (
    CorrelatedDomainFetch,
    DomainRuntime,
    KnownDomainSubmission,
    fetch_domain_invocation,
    plan_domain_submission,
    submit_domain_invocation,
)
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    GateId,
    PulseEventId,
    PulseImplementationId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.gates import GateCall, GateDefinition
from scopecat_quantum.program_results import (
    CompiledQuantumTarget,
    QuantumTargetEntryPointBinding,
    QuantumTargetResultMapping,
    QuantumTargetResultUseBinding,
    seal_quantum_target_result_mapping,
)
from scopecat_quantum.program_targets import (
    QuantumTargetAcquisitionOrigin,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
)
from scopecat_quantum.programs import (
    AuthoredPulseAcquisitionProvenance,
    CircuitPulseAcquisitionProvenance,
    ImplementedGate,
    ImplementedGatePulseEventProvenance,
    PulseBlock,
    QuantumProgramIR,
    lower_quantum_program_to_pulses,
    verify_quantum_program,
)
from scopecat_quantum.programs import (
    Sequence as QuantumSequence,
)
from scopecat_quantum.pulse_implementations import (
    MeasurementPulseImplementation,
    MeasurementPulseImplementationKey,
    ResolvedPulseImplementations,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Delay,
    DriveSignal,
    Play,
    PulseProgram,
    ReadoutSignal,
)
from scopecat_quantum.pulses import (
    Parallel as PulseParallel,
)
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetCompileRequest,
    TargetResultAddress,
    compile_target,
    target_result_acquisition_addresses,
    target_result_entry_id,
)
from tests.testkit.runtime import (
    FakeExecutionJournal,
    FakeMeasurementDatasetRepository,
)

from quantum_lab_demo.targets.fake_list_mode import (
    FakeAwgPlayback,
    FakeDigitizerChannelId,
    FakeListArtifact,
    FakeListAwg,
    FakeListDomainRuntime,
    FakeListRun,
    FakeListRuntime,
    FakeListTargetCompiler,
    SelectedFakeMeasurementRealization,
    configured_fake_list_target,
    correlate_fake_list_run,
    fake_measurement_invocation_spec,
    realize_fake_measurements,
    realize_fetched_fake_measurements,
    select_fake_measurement_realization,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile

from .demo_lab_experiment_testkit import link_program

_REPO_ROOT = Path(__file__).resolve().parents[5]
Q0 = QubitId("q0")
SHARED_SLOT = AcquisitionSlotId("result", scope=("circuit-local",))


def _only_acquisition_address(
    address: TargetResultAddress,
) -> TargetAcquisitionAddress:
    [selected] = target_result_acquisition_addresses(address)
    return selected


MIXED_IQ_SLOT = AcquisitionSlotId("iq-result", scope=("circuit-local",))
MIXED_AUX_SLOT = AcquisitionSlotId("aux-result", scope=("circuit-local",))
_DOMAIN_DIALECT_ID = "test.quantum.fake-list-runtime"
_SINGLE_RESULT_ID = "result"
_MIXED_IQ_RESULT_ID = "iq-result"
_MIXED_AUX_RESULT_ID = "aux-result"


@dataclass(frozen=True, slots=True)
class _Scenario:
    linked_points: MaterializedLinkedPoints
    preparation: DomainPreparationBuilder
    mapping: QuantumTargetResultMapping
    compiler: FakeListTargetCompiler
    compiled_target: CompiledQuantumTarget[FakeListArtifact]


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
        if self.mutation == "event":
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

    play_calls: int = 0

    @override
    def play(self, artifact: FakeListArtifact) -> tuple[FakeAwgPlayback, ...]:
        object.__setattr__(self, "play_calls", self.play_calls + 1)
        return super().play(artifact)


def _preparation_for_all_points(
    linked_points: MaterializedLinkedPoints,
) -> DomainPreparationBuilder:
    typed_execution = core_domain_executions(linked_points.linked_plan.program)[0]
    execution_id = typed_execution.id
    closure = domain_result_closure(linked_points.linked_plan.program, execution_id)
    point_ordinals = tuple(range(len(linked_points.point_domain.points)))
    request = make_domain_compile_template(
        linked_points.linked_plan,
        execution_id,
        closure,
    ).bind_points(
        point_ordinals,
        lambda input_ids, ordinals, max_points: linked_points.bind_domain_inputs(
            execution_id,
            "program",
            input_ids,
            ordinals,
            max_points=max_points,
        ),
        lambda input_ids, ordinals, max_points: linked_points.bind_domain_inputs(
            execution_id,
            "compiler",
            input_ids,
            ordinals,
            max_points=max_points,
        ),
    )
    context = make_domain_batch_context(
        request,
        linked_points,
        point_ordinals,
        batch_ordinal=0,
    )
    return context.new_preparation()


def _linked_points(
    *,
    product_use_count: int = 1,
    product_dtype: MeasurementDType = "complex128",
    product_unit: str | None = None,
    product_axes: tuple[ProductAxisDef, ...] = (),
) -> MaterializedLinkedPoints:
    point_domain = PointDomain(
        root=point_axis_values(
            "coordinate",
            Scalar(Float()),
            (10.0, 20.0, 30.0),
        )
    )
    product = ProductDef(
        id=product_id("raw-iq"),
        dtype=product_dtype,
        unit=product_unit,
        axes=product_axes,
    )
    selections = tuple(
        record_product(product, record_id=f"raw-iq-record-{index}")
        for index in range(product_use_count)
    )
    program = CoreProgram(
        id="fake-circuit-runtime",
        kind="fake_circuit_runtime_test",
        point_domain=point_domain,
        product_defs=(product,),
        effects=(
            TypedDomainExecution(
                id="domain",
                program=DomainProgramDef(
                    id="program",
                    dialect_id=_DOMAIN_DIALECT_ID,
                    dialect_version="1",
                    body=object(),
                    result_ports=(DomainResultPort(_SINGLE_RESULT_ID),),
                ),
                results=(
                    TypedDomainResultBinding(
                        id=_SINGLE_RESULT_ID,
                        product_id=product.id,
                        product_use_ids=tuple(use.id for use, _record in selections),
                    ),
                ),
            ),
        ),
        product_uses=tuple(use for use, _record in selections),
        record_uses=tuple(record for _use, record in selections),
    )
    environment = build_config_environment(
        load_config_snapshot_document(
            _REPO_ROOT / "fixtures/core/simple_scan/config-snapshot.json"
        )
    )
    return materialize_linked_points(link_program(program, environment))


def _mixed_linked_points(
    *,
    repetitions: int,
    include_iq_alias: bool = False,
) -> MaterializedLinkedPoints:
    point_domain = PointDomain(
        root=point_axis_values(
            "coordinate",
            Scalar(Float()),
            (10.0, 20.0, 30.0),
        )
    )
    iq_product = ProductDef(
        id=product_id("iq-shots"),
        dtype="complex128",
        unit="ratio",
        axes=(shot_axis(repetitions),),
    )
    aux_product = ProductDef(
        id=product_id("aux-shots"),
        dtype="complex128",
        unit="ratio",
        axes=(shot_axis(repetitions),),
    )
    iq_use, iq_record = record_product(iq_product)
    aux_use, aux_record = record_product(aux_product)
    program = CoreProgram(
        id="mixed-fake-circuit-runtime",
        kind="mixed_fake_circuit_runtime_test",
        point_domain=point_domain,
        product_defs=(iq_product, aux_product),
        effects=(
            TypedDomainExecution(
                id="domain",
                program=DomainProgramDef(
                    id="program",
                    dialect_id=_DOMAIN_DIALECT_ID,
                    dialect_version="1",
                    body=object(),
                    result_ports=(
                        DomainResultPort(_MIXED_IQ_RESULT_ID),
                        DomainResultPort(_MIXED_AUX_RESULT_ID),
                    ),
                ),
                results=(
                    TypedDomainResultBinding(
                        id=_MIXED_IQ_RESULT_ID,
                        product_id=iq_product.id,
                        product_use_ids=(iq_use.id,),
                    ),
                    TypedDomainResultBinding(
                        id=_MIXED_AUX_RESULT_ID,
                        product_id=aux_product.id,
                        product_use_ids=(aux_use.id,),
                    ),
                ),
            ),
        ),
        product_uses=(iq_use, aux_use),
        record_uses=(
            iq_record,
            *((replace(iq_record, id="iq-shots-alias"),) if include_iq_alias else ()),
            aux_record,
        ),
    )
    environment = build_config_environment(
        load_config_snapshot_document(
            _REPO_ROOT / "fixtures/core/simple_scan/config-snapshot.json"
        )
    )
    return materialize_linked_points(link_program(program, environment))


def _lowered_measurement_program(
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
    program = verify_quantum_program(
        QuantumProgramIR(
            id=QuantumProgramId("shared-readout-program"),
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
    implementation = MeasurementPulseImplementation(
        id=PulseImplementationId("readout-q0"),
        key=MeasurementPulseImplementationKey.from_measurement(measurement),
        pulse_template=template,
    )
    return lower_quantum_program_to_pulses(
        program,
        ResolvedPulseImplementations(
            measurements=(implementation,),
        ),
        output_id=PulseProgramId("shared-readout-pulses"),
    )


def _lowered_mixed_measurement_program(*, sample_count: int):
    iq_measurement = Measure(
        id=CircuitOperationId("measure-iq"),
        qubit=Q0,
        acquisition_slot_id=MIXED_IQ_SLOT,
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    aux_measurement = Measure(
        id=CircuitOperationId("measure-aux"),
        qubit=Q0,
        acquisition_slot_id=MIXED_AUX_SLOT,
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    program = verify_quantum_program(
        QuantumProgramIR(
            id=QuantumProgramId("mixed-readout-program"),
            body=QuantumSequence((iq_measurement, aux_measurement)),
        ),
        (),
    )

    def implementation(
        measurement: Measure,
        *,
        suffix: str,
    ) -> MeasurementPulseImplementation:
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
        return MeasurementPulseImplementation(
            id=PulseImplementationId(f"readout-q0-{suffix}"),
            key=MeasurementPulseImplementationKey.from_measurement(measurement),
            pulse_template=template,
        )

    return lower_quantum_program_to_pulses(
        program,
        ResolvedPulseImplementations(
            measurements=(implementation(iq_measurement, suffix="iq"),),
        ),
        output_id=PulseProgramId("mixed-readout-pulses"),
    )


def _prepared_mixed_quantum_entry(
    entry_id: TargetCompileEntryId,
):
    gate = GateDefinition(GateId("x90"), qubit_arity=1)
    implemented_gate = ImplementedGate(
        call=GateCall(
            id=CircuitOperationId("x90-reference"),
            gate_id=gate.id,
            qubits=(Q0,),
        ),
        pulse_template=PulseProgram(
            id=PulseProgramId("x90-template"),
            body=Delay(
                id=PulseEventId("drive"),
                signal=DriveSignal(Q0),
                duration=Quantity(4, "ns"),
            ),
        ),
        candidate_id="x90.reference",
    )
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(Q0),
    )
    readout = PulseBlock(
        id=CircuitOperationId("inline-readout"),
        pulse_template=PulseProgram(
            id=PulseProgramId("inline-readout-template"),
            body=PulseParallel(
                (
                    Play(
                        id=PulseEventId("stimulus"),
                        signal=ReadoutSignal(Q0),
                        envelope=Constant(
                            duration=Quantity(4, "ns"),
                            amplitude=Quantity(0.25, "arb"),
                        ),
                    ),
                    Acquire(
                        id=PulseEventId("capture"),
                        signal=slot.signal,
                        slot_id=slot.id,
                        duration=Quantity(4, "ns"),
                    ),
                )
            ),
            acquisition_slots=(slot,),
        ),
    )
    source = QuantumProgramIR(
        id=QuantumProgramId("mixed-gate-pulse-program"),
        body=QuantumSequence((implemented_gate, readout)),
    )
    lowered = lower_quantum_program_to_pulses(
        verify_quantum_program(source, (gate,)),
        ResolvedPulseImplementations(),
        output_id=PulseProgramId("mixed-gate-pulse-program-pulses"),
    )
    return prepare_quantum_target_entry(entry_id, lowered)


def _scenario(
    *,
    repetitions: int = 2,
    product_use_count: int = 1,
    product_dtype: MeasurementDType = "complex128",
    product_unit: str | None = None,
    product_axes: tuple[ProductAxisDef, ...] = (),
    acquisition_kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
    sample_count: int = 4,
) -> _Scenario:
    linked_points = _linked_points(
        product_use_count=product_use_count,
        product_dtype=product_dtype,
        product_unit=product_unit,
        product_axes=product_axes,
    )
    lowered = _lowered_measurement_program(
        acquisition_kind,
        sample_count=sample_count,
    )
    adapter_point_order = (2, 0, 1)
    entries = tuple(
        prepare_quantum_target_entry(
            TargetCompileEntryId(f"entry-{point_index}"),
            lowered,
        )
        for point_index in adapter_point_order
    )
    target = configured_fake_list_target(quantum_wiring_config_profile())
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    batch = prepare_quantum_target_batch(
        entries,
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=repetitions,
    )
    preparation = _preparation_for_all_points(linked_points)
    points = preparation.context.points
    product_uses = preparation.context.execution.result(_SINGLE_RESULT_ID).product_uses
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        tuple(
            QuantumTargetEntryPointBinding(
                entry.id,
                points[point_index],
            )
            for entry, point_index in zip(
                batch.entries,
                adapter_point_order,
                strict=True,
            )
        ),
        tuple(
            QuantumTargetResultUseBinding(
                entry.acquisition_addresses[0],
                product_use,
            )
            for entry in batch.entries
            for product_use in product_uses
        ),
    )
    compiled = compile_target(compiler, batch.request)
    return _Scenario(
        linked_points=linked_points,
        preparation=preparation,
        mapping=mapping,
        compiler=compiler,
        compiled_target=CompiledQuantumTarget(mapping, compiled),
    )


class _ScenarioKwargs(TypedDict, total=False):
    repetitions: int
    product_use_count: int
    product_dtype: MeasurementDType
    product_unit: str | None
    product_axes: tuple[ProductAxisDef, ...]
    acquisition_kind: AcquisitionKind
    sample_count: int


def _mixed_scenario(
    *,
    repetitions: int = 2,
    sample_count: int = 4,
    include_iq_alias: bool = False,
) -> _Scenario:
    linked_points = _mixed_linked_points(
        repetitions=repetitions,
        include_iq_alias=include_iq_alias,
    )
    lowered = _lowered_mixed_measurement_program(sample_count=sample_count)
    adapter_point_order = (2, 0, 1)
    entries = tuple(
        prepare_quantum_target_entry(
            TargetCompileEntryId(f"mixed-entry-{point_index}"),
            lowered,
        )
        for point_index in adapter_point_order
    )
    target = configured_fake_list_target(quantum_wiring_config_profile())
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    batch = prepare_quantum_target_batch(
        entries,
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=repetitions,
    )
    preparation = _preparation_for_all_points(linked_points)
    points = preparation.context.points
    iq_use = preparation.context.execution.result(
        _MIXED_IQ_RESULT_ID
    ).require_one_product_use()
    aux_use = preparation.context.execution.result(
        _MIXED_AUX_RESULT_ID
    ).require_one_product_use()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        tuple(
            QuantumTargetEntryPointBinding(
                entry.id,
                points[point_index],
            )
            for entry, point_index in zip(
                batch.entries,
                adapter_point_order,
                strict=True,
            )
        ),
        tuple(
            QuantumTargetResultUseBinding(
                address,
                iq_use if address.slot_id == MIXED_IQ_SLOT else aux_use,
            )
            for entry in batch.entries
            for address in entry.acquisition_addresses
        ),
    )
    compiled = compile_target(compiler, batch.request)
    return _Scenario(
        linked_points=linked_points,
        preparation=preparation,
        mapping=mapping,
        compiler=compiler,
        compiled_target=CompiledQuantumTarget(mapping, compiled),
    )


def _prepared_mixed_execution(
    scenario: _Scenario,
    runtime: DomainRuntime[SelectedFakeMeasurementRealization, FakeListRun],
    *,
    response_intent: object | None = None,
) -> PreparedDomainExecution:
    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
    )
    return scenario.preparation.build(
        mapping=scenario.mapping.domain_mapping,
        invocation=fake_measurement_invocation_spec(
            selection,
            invocation_id="mixed-readout",
            response_intent=response_intent,
        ),
        runtime=runtime,
        realize=lambda fetched: realize_fetched_fake_measurements(selection, fetched),
    )


type _ClosedMixedInvocation = ClosedDomainInvocation[
    TargetResultAddress,
    SelectedFakeMeasurementRealization,
]


def _closed_mixed_invocation(
    scenario: _Scenario,
    runtime: DomainRuntime[SelectedFakeMeasurementRealization, FakeListRun],
    *,
    response_intent: object | None = None,
) -> _ClosedMixedInvocation:
    prepared = _prepared_mixed_execution(
        scenario,
        runtime,
        response_intent=response_intent,
    )
    return cast("_ClosedMixedInvocation", prepared.invocation)


def test_three_point_fake_quantum_run_correlates_target_and_logical_order() -> None:
    scenario = _scenario()

    correlated = correlate_fake_list_run(
        scenario.compiled_target,
        FakeListRuntime().execute(scenario.compiled_target.compiled),
    )

    points = scenario.preparation.context.points
    product_use = scenario.preparation.context.execution.result(
        _SINGLE_RESULT_ID
    ).product_uses[0]
    assert tuple(
        address.slot_id for address in scenario.mapping.batch.acquisition_addresses
    ) == (
        SHARED_SLOT,
        SHARED_SLOT,
        SHARED_SLOT,
    )
    assert tuple(
        (frame.shot_index, frame.entry_id) for frame in correlated.target_run.frames
    ) == tuple(
        (shot_index, TargetCompileEntryId(f"entry-{point_index}"))
        for shot_index in range(2)
        for point_index in (2, 0, 1)
    )
    assert tuple(
        (frame.point, frame.product_uses, frame.shot_index)
        for frame in correlated.frames
    ) == tuple(
        (point, (product_use,), shot_index)
        for point in points
        for shot_index in range(2)
    )
    assert tuple(frame.frame.entry_id for frame in correlated.frames) == tuple(
        TargetCompileEntryId(f"entry-{point_index}")
        for point_index in range(3)
        for _shot_index in range(2)
    )

    mapping = scenario.mapping.domain_mapping
    for point_index, point in enumerate(points):
        mapped_result = next(
            result
            for result in mapping.results
            if result.point is point and product_use in result.product_uses
        )
        address = _only_acquisition_address(mapped_result.result_address)
        origin = scenario.mapping.batch.acquisition_origin_for(address)
        assert address.entry_id == TargetCompileEntryId(f"entry-{point_index}")
        assert origin.source_program_id == QuantumProgramId("shared-readout-program")
        assert isinstance(origin.provenance, CircuitPulseAcquisitionProvenance)
        assert origin.provenance.measurement_id == CircuitOperationId("measure")
        assert origin.provenance.acquisition_slot_id == SHARED_SLOT
        output_frames = tuple(
            frame for frame in correlated.frames if frame.mapped_result is mapped_result
        )
        assert tuple(frame.shot_index for frame in output_frames) == (0, 1)
        for shot_index, frame in enumerate(output_frames):
            assert frame.shot_index == shot_index
            assert frame.mapped_result is mapped_result


def test_mixed_quantum_program_reuses_fake_selection_and_correlation() -> None:
    linked_points = _linked_points(
        product_unit="ratio",
        product_axes=(shot_axis(2),),
    )
    preparation = _preparation_for_all_points(linked_points)
    adapter_point_order = (2, 0, 1)
    entries = tuple(
        _prepared_mixed_quantum_entry(
            TargetCompileEntryId(f"mixed-program-entry-{point_index}")
        )
        for point_index in adapter_point_order
    )
    target = configured_fake_list_target(quantum_wiring_config_profile())
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    batch = prepare_quantum_target_batch(
        entries,
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=2,
    )
    points = preparation.context.points
    product_use = preparation.context.execution.result(
        _SINGLE_RESULT_ID
    ).require_one_product_use()
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        tuple(
            QuantumTargetEntryPointBinding(entry.id, points[point_index])
            for entry, point_index in zip(
                batch.entries,
                adapter_point_order,
                strict=True,
            )
        ),
        tuple(
            QuantumTargetResultUseBinding(
                entry.acquisition_addresses[0],
                product_use,
            )
            for entry in batch.entries
        ),
    )
    compiled_target = CompiledQuantumTarget(
        mapping,
        compile_target(compiler, batch.request),
    )
    selection = select_fake_measurement_realization(
        compiled_target,
        target,
    )
    correlated = correlate_fake_list_run(
        selection.compiled_target,
        FakeListRuntime().execute(selection.compiled_target.compiled),
    )
    realized = realize_fake_measurements(selection, correlated)

    assert isinstance(compiled_target, CompiledQuantumTarget)
    assert isinstance(mapping, QuantumTargetResultMapping)
    assert selection.compiled_target is compiled_target
    assert tuple(result.point for result in mapping.domain_mapping.results) == points
    assert tuple(
        target_result_entry_id(result.result_address)
        for result in mapping.domain_mapping.results
    ) == tuple(
        TargetCompileEntryId(f"mixed-program-entry-{index}") for index in range(3)
    )
    assert len({address.slot_id for address in batch.acquisition_addresses}) == 1
    assert len(set(batch.acquisition_addresses)) == len(points)
    assert tuple(value.result_address for value in realized) == tuple(
        result.result_address for result in mapping.domain_mapping.results
    )

    for entry in batch.entries:
        address = entry.acquisition_addresses[0]
        origin = batch.acquisition_origin_for(address)
        assert isinstance(origin, QuantumTargetAcquisitionOrigin)
        assert origin.source_program_id == QuantumProgramId("mixed-gate-pulse-program")
        assert isinstance(origin.provenance, AuthoredPulseAcquisitionProvenance)
        assert origin.provenance.source_id == CircuitOperationId("inline-readout")
        assert any(
            isinstance(
                event_origin.provenance,
                ImplementedGatePulseEventProvenance,
            )
            for event_origin in entry.event_origins
        )

        mapped_result = next(
            result
            for result in mapping.domain_mapping.results
            if result.result_address == address
        )
        frames = tuple(frame for frame in correlated.frames if frame.address == address)
        assert tuple(frame.shot_index for frame in frames) == (0, 1)
        assert all(frame.mapped_result is mapped_result for frame in frames)


def test_one_physical_fake_result_fans_out_to_every_product_use() -> None:
    scenario = _scenario(
        product_use_count=2,
        product_unit="ratio",
        product_axes=(shot_axis(2),),
    )
    points = scenario.preparation.context.points
    uses = scenario.preparation.context.execution.result(_SINGLE_RESULT_ID).product_uses
    correlated = correlate_fake_list_run(
        scenario.compiled_target,
        FakeListRuntime().execute(scenario.compiled_target.compiled),
    )

    mapping = scenario.mapping.domain_mapping
    assert len(mapping.results) == len(points)
    assert len(correlated.frames) == len(points) * 2
    assert all(result.product_uses == uses for result in mapping.results)
    for point in points:
        result = next(result for result in mapping.results if result.point is point)
        assert all(use in result.product_uses for use in uses)
        physical_frames = tuple(
            frame for frame in correlated.frames if frame.mapped_result is result
        )
        for shot_index, frame in enumerate(physical_frames):
            assert frame.product_uses == uses
            assert frame.shot_index == shot_index

    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
    )
    realized = realize_fake_measurements(selection, correlated)

    assert len(realized) == len(points)
    values_by_address = {value.result_address: value for value in realized}
    for point in points:
        result = next(result for result in mapping.results if result.point is point)
        value = values_by_address[result.result_address]
        assert all(use in result.product_uses for use in uses)
        assert isinstance(value.value, MeasurementArray)


def test_integrated_iq_shot_realization_accepts_exact_product_contract() -> None:
    scenario = _scenario(
        product_unit="ratio",
        product_axes=(shot_axis(2),),
    )
    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
    )
    correlated = correlate_fake_list_run(
        selection.compiled_target,
        FakeListRuntime().execute(selection.compiled_target.compiled),
    )
    realized = realize_fake_measurements(selection, correlated)

    assert tuple(output.result for output in selection.outputs) == (
        scenario.mapping.domain_mapping.results
    )
    assert tuple(value.result_address for value in realized) == tuple(
        result.result_address for result in scenario.mapping.domain_mapping.results
    )
    for output, result_value in zip(
        selection.outputs,
        realized,
        strict=True,
    ):
        frames = tuple(
            frame for frame in correlated.frames if frame.mapped_result is output.result
        )
        value = result_value.value
        assert isinstance(value, MeasurementArray)
        assert value.dtype == "complex128"
        assert value.unit == "ratio"
        assert value.shape == [2]
        assert value.values == [
            ComplexQuantity(
                real=frame.frame.value.real,
                imag=frame.frame.value.imag,
                unit="ratio",
            )
            for frame in frames
        ]


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
    ),
)
def test_integrated_iq_realization_rejects_implicit_or_incompatible_policies(
    scenario_kwargs: _ScenarioKwargs,
    expected_code: str,
) -> None:
    scenario = _scenario(**scenario_kwargs)

    with pytest.raises(CheckFailed) as captured:
        select_fake_measurement_realization(
            scenario.compiled_target,
            scenario.compiler.target,
        )

    assert expected_code in {problem.code for problem in captured.value.problems}
    assert all(problem.phase.value == "planning" for problem in captured.value.problems)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
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
    faulty_target = CompiledQuantumTarget(
        scenario.mapping,
        faulty_compiled,
    )

    with pytest.raises(CheckFailed) as captured:
        select_fake_measurement_realization(
            faulty_target,
            scenario.compiler.target,
        )

    assert {problem.code for problem in captured.value.problems} == {expected_code}
    assert all(problem.phase.value == "planning" for problem in captured.value.problems)


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
        )

    assert {problem.code for problem in captured.value.problems} == {
        "fake_measurement_target_mismatch"
    }
    assert all(problem.phase.value == "planning" for problem in captured.value.problems)


def test_two_integrated_results_share_one_batch_execution() -> None:
    repetitions = 2
    scenario = _mixed_scenario(
        repetitions=repetitions,
        sample_count=4,
    )

    selection = select_fake_measurement_realization(
        scenario.compiled_target,
        scenario.compiler.target,
    )
    awg = _CountingFakeListAwg()
    runtime = FakeListRuntime(awg=awg)
    correlated = correlate_fake_list_run(
        selection.compiled_target,
        runtime.execute(selection.compiled_target.compiled),
    )
    realized = realize_fake_measurements(selection, correlated)

    assert len(selection.outputs) == len(scenario.mapping.domain_mapping.results) == 6
    assert awg.play_calls == 1
    assert tuple(output.result for output in selection.outputs) == (
        scenario.mapping.domain_mapping.results
    )
    assert tuple(value.result_address for value in realized) == tuple(
        result.result_address for result in scenario.mapping.domain_mapping.results
    )

    for output, result_value in zip(
        selection.outputs,
        realized,
        strict=True,
    ):
        frames = tuple(
            frame for frame in correlated.frames if frame.mapped_result is output.result
        )
        value = result_value.value
        assert isinstance(value, MeasurementArray)
        assert value.dtype == "complex128"
        assert value.unit == "ratio"
        assert value.shape == [repetitions]
        assert value.values == [
            ComplexQuantity(
                real=frame.frame.value.real,
                imag=frame.frame.value.imag,
                unit="ratio",
            )
            for frame in frames
        ]


def test_fake_measurement_invocation_closes_exact_intent() -> None:
    scenario = _mixed_scenario(repetitions=2, sample_count=4)
    invocation = _closed_mixed_invocation(scenario, FakeListDomainRuntime())
    compiled = scenario.compiled_target.compiled

    assert tuple(
        result.result_address for result in invocation.result_mapping.results
    ) == tuple(
        result.result_address for result in scenario.mapping.domain_mapping.results
    )
    assert invocation.payload.compiled_target is scenario.compiled_target
    assert invocation.intent.invocation_id == "mixed-readout"
    assert invocation.intent.target_id == compiled.target_id.value
    assert invocation.intent.compiler_id == compiled.compiler_id.value
    assert invocation.intent.capability_fingerprint == compiled.capability_fingerprint
    assert invocation.intent.artifact_id == compiled.artifact_id.value
    assert invocation.intent.artifact_fingerprint == compiled.artifact_fingerprint


def test_fake_measurement_invocation_identity_covers_response_intent() -> None:
    scenario = _mixed_scenario(repetitions=2, sample_count=4)
    first = _closed_mixed_invocation(
        scenario,
        FakeListDomainRuntime(),
        response_intent={"response_fingerprint": "response:a"},
    )
    second = _closed_mixed_invocation(
        scenario,
        FakeListDomainRuntime(),
        response_intent={"response_fingerprint": "response:b"},
    )

    assert first.intent.artifact_fingerprint == second.intent.artifact_fingerprint
    assert (
        first.intent.target_intent_fingerprint
        != second.intent.target_intent_fingerprint
    )
    assert first.intent.intent_fingerprint != second.intent.intent_fingerprint


def test_fake_domain_submit_fetch_and_realize_preserve_canonical_outputs() -> None:
    scenario = _mixed_scenario(repetitions=2, sample_count=4)
    runtime = FakeListDomainRuntime()
    invocation = _closed_mixed_invocation(scenario, runtime)
    journal = FakeExecutionJournal()
    submission_id = plan_domain_submission(
        invocation,
        run_id="fake-domain-run",
        semantic_operation_id="mixed-readout",
    )

    submission = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
    )
    fetched = fetch_domain_invocation(
        runtime,
        invocation.intent,
        submission,
        journal=journal,
    )
    assert isinstance(submission, KnownDomainSubmission)
    assert isinstance(fetched, CorrelatedDomainFetch)
    realized = realize_fetched_fake_measurements(invocation.payload, fetched)

    assert submission.submission_id is submission_id
    assert fetched.receipt.status == "fetched"
    assert tuple(value.result_address for value in realized) == tuple(
        result.result_address for result in scenario.mapping.domain_mapping.results
    )
    assert [(entry.stage, entry.effect, entry.state) for entry in journal.entries] == [
        ("domain_submit", "acquisition", "started"),
        ("domain_submit", "acquisition", "completed"),
        ("domain_fetch", "read", "started"),
        ("domain_fetch", "read", "completed"),
    ]


def test_fake_domain_values_reach_receipt_bearing_host_recording() -> None:
    scenario = _mixed_scenario(
        repetitions=2,
        sample_count=4,
        include_iq_alias=True,
    )
    runtime = FakeListDomainRuntime()
    prepared = _prepared_mixed_execution(scenario, runtime)
    journal = FakeExecutionJournal()
    record_committer = FakeMeasurementDatasetRepository()
    run_id = "fake-host-recording-run"

    context = scenario.preparation.context
    assembled = seal_measurement_values(
        context.measurement_catalog,
        execute_domain_job_values(
            prepared,
            semantic_operation_id="mixed-readout",
            run_id=run_id,
            journal=journal,
        ),
        points=context.run_points,
    )
    projection = select_measurement_projection(
        context.measurement_catalog,
        scenario.linked_points.linked_plan.program.record_uses,
    )
    projected = project_measurement_records(
        projection,
        assembled,
        run_id=run_id,
        points=context.run_points,
    )
    committed = append_measurement_dataset(
        projected,
        record_committer,
        journal,
    )
    assert committed is not None
    assert projected.schema is not None
    seal_measurement_dataset(
        run_id=run_id,
        recording_contract_fingerprint=projected.recording_contract_fingerprint,
        point_count=len(projected.records),
        append_content_hashes=(committed.dataset_content_hash,),
        writer=record_committer,
        journal=journal,
    )

    record_ids = {
        record.id for record in scenario.linked_points.linked_plan.program.record_uses
    }
    assert len(projected.records) == len(scenario.linked_points.point_domain.points)
    assert all(set(record.observables) == record_ids for record in projected.records)
    assert [record.coordinates for record in projected.records] == [
        {"coordinate": 10.0},
        {"coordinate": 20.0},
        {"coordinate": 30.0},
    ]
    assert projected.schema is not None
    assert set(projected.schema.primary_observables) == record_ids
    assert len(record_ids) > len(
        scenario.linked_points.linked_plan.program.product_uses
    )

    appends = record_committer.appends
    assert len(appends) == 1
    assert appends[0].records == projected.records
    assert committed.dataset_content_hash == appends[0].content_hash
    append_receipt, seal_receipt = record_committer.receipts
    assert append_receipt.operation_id == appends[0].operation_id
    assert append_receipt.dataset_content_hash == appends[0].content_hash
    assert append_receipt.dataset_ref
    assert seal_receipt.dataset_ref

    record_transitions = tuple(
        transition
        for transition in journal.entries
        if transition.stage in {"append_measurement", "seal_measurement"}
    )
    assert tuple(transition.state for transition in record_transitions) == (
        "started",
        "completed",
        "started",
        "completed",
    )
    assert tuple(
        transition.evidence["receipt"]
        for transition in record_transitions
        if transition.state == "completed"
    ) == tuple(receipt.model_dump(mode="json") for receipt in record_committer.receipts)
    allowed_evidence_keys = {
        "dataset_id",
        "start_index",
        "record_count",
        "append_content_hash",
        "point_count",
        "dataset_content_hash",
        "receipt",
    }
    assert all(
        set(transition.evidence) <= allowed_evidence_keys
        for transition in record_transitions
    )
    assert all(
        all(
            term not in repr(transition.evidence)
            for term in (
                "entry_address",
                "result_address",
                "target_run",
                "raw_frame",
                "raw_frames",
            )
        )
        for transition in record_transitions
    )


def test_fake_domain_submit_is_idempotent_for_one_submission_id() -> None:
    scenario = _mixed_scenario(repetitions=2, sample_count=4)
    awg = _CountingFakeListAwg()
    runtime = FakeListDomainRuntime(FakeListRuntime(awg=awg))
    invocation = _closed_mixed_invocation(scenario, runtime)
    journal = FakeExecutionJournal()
    submission_id = plan_domain_submission(
        invocation,
        run_id="fake-idempotent-run",
        semantic_operation_id="mixed-readout",
    )

    first = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
    )
    repeated = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
    )

    assert isinstance(first, KnownDomainSubmission)
    assert isinstance(repeated, KnownDomainSubmission)
    assert repeated == first
    assert awg.play_calls == 1
    assert [entry.state for entry in journal.entries] == [
        "started",
        "completed",
        "started",
        "completed",
    ]


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
        ("missing", "exactly cover every mapped acquisition"),
        ("duplicate", "duplicate acquisition-address shots"),
        ("foreign", "exactly cover every mapped acquisition"),
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
