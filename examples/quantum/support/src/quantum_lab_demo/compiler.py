"""The unified domain compiler for the demo quantum laboratory."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast, override

from scopecat.sdk.domain import (
    CorrelatedDomainFetch,
    DomainBatchContext,
    DomainCallView,
    DomainCompilation,
    DomainCompiledInputs,
    DomainCompiledJob,
    DomainCompileRequest,
    DomainExecutionView,
    DomainHostTransformBinding,
    DomainHostTransformImplementation,
    DomainMeasurementTransform,
    DomainResultBinding,
    PreparedDomainExecution,
    compiled_jobs,
)
from scopecat_quantum import (
    AcquisitionKind,
    CompiledQuantumTarget,
    CompiledTargetArtifact,
    PreparedQuantumTargetBatch,
    PreparedQuantumTargetEntry,
    PulseProgramId,
    PulseRecipeProfile,
    QuantumTargetEntryPointBinding,
    QuantumTargetResultUseBinding,
    ResolvedPulseImplementations,
    ResultCollection,
    TargetAcquisitionLayout,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetResultAddress,
    TargetResultAxisLayout,
    binary_iq_probability_host_implementation,
    compile_target,
    lower_quantum_program_to_pulses,
    lower_quantum_program_to_structured_pulses,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
    seal_quantum_target_result_mapping,
    target_result_acquisition_addresses,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.response_registry import (
    QuantumLabResponseRegistry,
    QuantumLabResponseRequest,
)
from quantum_lab_demo.targets.configuration import (
    FAKE_LIST_TARGET_KIND,
    FAKE_REALTIME_TARGET_KIND,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeAcquisitionResponse,
    FakeListArtifact,
    FakeListDomainRuntime,
    FakeListRun,
    FakeListRuntime,
    FakeListTarget,
    FakeListTargetCompiler,
    FakeMeasurementRealizationBinding,
    FakeSegmentedDigitizer,
    SelectedFakeMeasurementRealization,
    fake_measurement_invocation_spec,
    integrated_iq_shots,
    raw_trace_shots,
    realize_fetched_fake_measurements,
    select_fake_measurement_realization,
)
from quantum_lab_demo.targets.fake_realtime import (
    FakeRealtimeArtifact,
    FakeRealtimeCompiler,
    FakeRealtimeCompileRequest,
    FakeRealtimeDomainRuntime,
    FakeRealtimeTarget,
    fake_realtime_invocation_spec,
    prepare_fake_realtime_request,
    realize_fetched_realtime_results,
)
from quantum_lab_demo.trace import (
    QuantumLabPointValues,
    QuantumLabPreparationEvidence,
    QuantumLabTrace,
    QuantumRealtimePreparationEvidence,
)
from quantum_lab_demo.virtual_lab.compiler_parameters import QuantumCompilerParameters
from quantum_lab_demo.virtual_lab.parameters import QUBIT_PARAMETER_TABLE

_QUANTUM_LAB_COMPILER_ID = "quantum-lab-demo.compiler.v1"
_QUANTUM_LAB_TARGET_COMPILER_ID = TargetCompilerId(
    "quantum-lab-demo.fake-list-target.v1"
)
_QUANTUM_REALTIME_LAB_COMPILER_ID = "quantum-lab-demo.realtime-compiler.v1"
_QUANTUM_REALTIME_TARGET_COMPILER_ID = TargetCompilerId(
    "quantum-lab-demo.fake-realtime-target.v1"
)


@dataclass(frozen=True, slots=True)
class _QuantumLabArtifact:
    program: quantum.Program = field(repr=False)
    points: tuple[QuantumLabPointValues, ...]


@dataclass(frozen=True, slots=True)
class _ListQuantumLabArtifact(_QuantumLabArtifact):
    entries: tuple[PreparedQuantumTargetEntry, ...]
    batch: PreparedQuantumTargetBatch
    compiled: CompiledTargetArtifact[FakeListArtifact] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _RealtimeQuantumLabArtifact(_QuantumLabArtifact):
    request: FakeRealtimeCompileRequest
    compiled: CompiledTargetArtifact[FakeRealtimeArtifact] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _CompiledQuantumPoint:
    values: QuantumLabPointValues
    bound: quantum.BoundProgram = field(repr=False)
    implementations: ResolvedPulseImplementations = field(repr=False)


class _QuantumLabCompilerBase:
    def __init__(
        self,
        *,
        max_points: int,
        trace: QuantumLabTrace,
        pulse_profile: PulseRecipeProfile[QuantumCompilerParameters],
    ) -> None:
        self._max_points = max_points
        self._trace = trace
        self._pulse_profile = pulse_profile
        self._host_implementations = (binary_iq_probability_host_implementation(),)

    @property
    def compiler_id(self) -> str:
        raise NotImplementedError

    @property
    def trace(self) -> QuantumLabTrace:
        return self._trace

    def supports(self, call: DomainCallView) -> bool:
        program = _supported_program(call)
        if program is None:
            return False
        _validate_call(call, program, self._host_implementations)
        return True

    def compile(self, request: DomainCompileRequest) -> DomainCompilation | None:
        program = _supported_program(request.call)
        if program is None:
            return None
        _validate_call(request.call, program, self._host_implementations)
        shots = _shot_count(request.call)
        return compiled_jobs(
            request,
            max_points=self._max_points,
            artifact_input_ids=tuple(port.id for port in program.ports),
            compile_artifact=lambda inputs: self._compile_target_artifact(
                program,
                inputs,
                shots=shots,
            ),
        )

    def _compile_target_artifact(
        self,
        program: quantum.Program,
        inputs: DomainCompiledInputs,
        *,
        shots: int,
    ) -> _QuantumLabArtifact:
        raise NotImplementedError


class QuantumLabCompiler(_QuantumLabCompilerBase):
    """Own the demo lab's single domain-compilation boundary.

    Scopecat derives domain input normal forms from accepted experiment
    semantics; program and compiler inputs both reflect the accepted snapshot
    and point-local overlays. ``compile`` resolves them into immutable artifact
    values through an injected static pulse recipe profile, so this
    implementation never reaches into mutable parameter state. It also owns the
    internal target lowering stage; the injected response registry may select
    deterministic fake behavior by Program identity, but never a different
    compiler.
    """

    def __init__(
        self,
        *,
        target: FakeListTarget,
        runtime: FakeListDomainRuntime,
        response_registry: QuantumLabResponseRegistry,
        trace: QuantumLabTrace,
        pulse_profile: PulseRecipeProfile[QuantumCompilerParameters],
    ) -> None:
        super().__init__(
            max_points=target.max_list_entries,
            trace=trace,
            pulse_profile=pulse_profile,
        )
        self._target = target
        self._runtime = runtime
        self._response_registry = response_registry
        self._trace.register_runtime(runtime)
        self._target_compiler = FakeListTargetCompiler(
            _QUANTUM_LAB_TARGET_COMPILER_ID,
            self._target,
        )

    @property
    @override
    def compiler_id(self) -> str:
        return _QUANTUM_LAB_COMPILER_ID

    @property
    def target_id(self) -> str:
        return self._target.id.value

    @property
    def target_kind(self) -> str:
        return FAKE_LIST_TARGET_KIND

    @override
    def _compile_target_artifact(
        self,
        program: quantum.Program,
        inputs: DomainCompiledInputs,
        *,
        shots: int,
    ) -> _ListQuantumLabArtifact:
        points = _compile_points(program, inputs, self._pulse_profile)
        entries = tuple(
            prepare_quantum_target_entry(
                TargetCompileEntryId(f"{program.id}.point-{point.values.ordinal}"),
                lower_quantum_program_to_pulses(
                    point.bound.verified,
                    point.implementations,
                    output_id=PulseProgramId(
                        f"{program.id}.point-{point.values.ordinal}.pulses"
                    ),
                ),
            )
            for point in points
        )
        batch = prepare_quantum_target_batch(
            entries,
            target_id=self._target.id,
            compiler_id=self._target_compiler.id,
            capability_fingerprint=self._target.capability_fingerprint,
            repetitions=shots,
        )
        return _ListQuantumLabArtifact(
            program=program,
            points=tuple(point.values for point in points),
            entries=entries,
            batch=batch,
            compiled=compile_target(self._target_compiler, batch.request),
        )

    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        artifact = cast("_ListQuantumLabArtifact", job.take_artifact())
        execution = context.execution
        _validate_execution(execution, artifact)
        preparation = context.new_preparation()
        entries = artifact.entries
        batch = artifact.batch
        if _shot_count(execution) != batch.repetitions:
            raise ValueError("prepared quantum shots changed after compilation")
        mapping = seal_quantum_target_result_mapping(
            preparation,
            batch,
            tuple(
                QuantumTargetEntryPointBinding(entry.id, point)
                for entry, point in zip(entries, context.points, strict=True)
            ),
            tuple(
                QuantumTargetResultUseBinding(
                    _result_address(entry, result, point_values),
                    product_use,
                )
                for entry, point_values in zip(
                    entries,
                    artifact.points,
                    strict=True,
                )
                for result in _measurement_results(artifact.program)
                for product_use in execution.result(result.id).product_uses
            ),
        )
        compiled_target = CompiledQuantumTarget(
            mapping,
            artifact.compiled,
        )
        realization = select_fake_measurement_realization(
            compiled_target,
            self._target,
            tuple(
                _realization_binding(result.result_address, artifact.program)
                for result in mapping.domain_mapping.results
            ),
        )
        response = self._response_registry.response_for(
            QuantumLabResponseRequest(
                program=artifact.program,
                points=artifact.points,
                entries=entries,
                batch=batch,
            )
        )
        runtime = self._runtime if response is None else _response_runtime(response)
        if response is not None:
            self._trace.register_runtime(runtime)
        invocation = fake_measurement_invocation_spec(
            realization,
            invocation_id=(
                f"{artifact.program.id}.batch-{context.batch_ordinal}."
                f"point-{artifact.points[0].ordinal}"
            ),
            response_intent=(
                None
                if response is None
                else {
                    "schema": "quantum_lab_demo.response.v1",
                    "response_fingerprint": response.fingerprint,
                }
            ),
        )
        host_transforms = tuple(
            DomainHostTransformBinding(
                transform,
                _host_implementation(transform, self._host_implementations),
            )
            for transform in execution.measurement_transforms
        )
        prepared = preparation.build(
            mapping=mapping.domain_mapping,
            host_transforms=host_transforms,
            invocation=invocation,
            runtime=runtime,
            realize=lambda fetched: _realize(realization, fetched),
        )
        evidence = QuantumLabPreparationEvidence(
            program=artifact.program,
            points=artifact.points,
            _target=self._target,
            entries=entries,
            artifact=compiled_target.compiled.artifact,
            artifact_fingerprint=compiled_target.compiled.artifact_fingerprint,
        )
        self._trace.record_preparation(evidence)
        return prepared


class QuantumRealtimeLabCompiler(_QuantumLabCompilerBase):
    """Compile every accepted program for one statically selected realtime target.

    The domain compiler advertises the whole logical target, so scheduling does
    not split a feedback program across instruments. Wiring and device selection
    are already closed by the configured target. Lazy artifact materialization
    determines the finite instruction inventory; preparation only maps results
    and closes the runtime invocation.
    """

    def __init__(
        self,
        *,
        target: FakeRealtimeTarget,
        runtime: FakeRealtimeDomainRuntime,
        trace: QuantumLabTrace,
        pulse_profile: PulseRecipeProfile[QuantumCompilerParameters],
        measurement_bits: Mapping[str, Sequence[int]] | None = None,
    ) -> None:
        super().__init__(max_points=1, trace=trace, pulse_profile=pulse_profile)
        self._target = target
        self._runtime = runtime
        self._measurement_bits = {
            result_id: tuple(bits)
            for result_id, bits in (measurement_bits or {}).items()
        }
        self._target_compiler = FakeRealtimeCompiler(
            _QUANTUM_REALTIME_TARGET_COMPILER_ID,
            target,
        )
        self._trace.register_runtime(runtime)

    @property
    @override
    def compiler_id(self) -> str:
        return _QUANTUM_REALTIME_LAB_COMPILER_ID

    @property
    def target_id(self) -> str:
        return self._target.id.value

    @property
    def target_kind(self) -> str:
        return FAKE_REALTIME_TARGET_KIND

    @override
    def _compile_target_artifact(
        self,
        program: quantum.Program,
        inputs: DomainCompiledInputs,
        *,
        shots: int,
    ) -> _RealtimeQuantumLabArtifact:
        points = _compile_points(program, inputs, self._pulse_profile)
        if len(points) != 1:
            raise AssertionError("realtime artifacts contain exactly one point")
        [point] = points
        entry_id = TargetCompileEntryId(f"{program.id}.point-{point.values.ordinal}")
        structured = lower_quantum_program_to_structured_pulses(
            point.bound.verified,
            point.implementations,
            output_id=PulseProgramId(f"{entry_id.value}.pulses"),
        )
        layouts = _realtime_result_layouts(entry_id, program, point.values)
        request = prepare_fake_realtime_request(
            entry_id,
            structured,
            target=self._target,
            compiler_id=self._target_compiler.id,
            result_layouts=layouts,
            repetitions=shots,
        )
        return _RealtimeQuantumLabArtifact(
            program=program,
            points=(point.values,),
            request=request,
            compiled=compile_target(self._target_compiler, request),
        )

    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        artifact = cast("_RealtimeQuantumLabArtifact", job.take_artifact())
        _validate_execution(context.execution, artifact)
        if len(artifact.points) != 1 or len(context.points) != 1:
            raise AssertionError("realtime domain batches contain exactly one point")
        [point] = artifact.points
        [point_ref] = context.points
        target_request = artifact.request
        layouts = target_request.result_layouts
        shots = target_request.repetitions
        if _shot_count(context.execution) != shots:
            raise ValueError("prepared quantum shots changed after compilation")
        preparation = context.new_preparation()
        address_by_result_id = {
            layout.slot_id.local_id: layout.address for layout in layouts
        }
        mapping = preparation.map_measurements(
            results=tuple(
                DomainResultBinding(
                    result_address=address_by_result_id[result.id],
                    point=point_ref,
                    product_use=product_use,
                )
                for result in artifact.program.results
                for product_use in context.execution.result(result.id).product_uses
            )
        )
        measurements = self._measurements_for(
            artifact.program,
            layouts,
            shots=shots,
        )
        invocation = fake_realtime_invocation_spec(
            artifact.compiled,
            measurements,
            invocation_id=(
                f"{artifact.program.id}.batch-{context.batch_ordinal}."
                f"point-{point.ordinal}"
            ),
        )
        host_transforms = tuple(
            DomainHostTransformBinding(
                transform,
                _host_implementation(transform, self._host_implementations),
            )
            for transform in context.execution.measurement_transforms
        )
        prepared = preparation.build(
            mapping=mapping,
            host_transforms=host_transforms,
            invocation=invocation,
            runtime=self._runtime,
            realize=lambda fetched: realize_fetched_realtime_results(mapping, fetched),
        )
        self._trace.record_realtime_preparation(
            QuantumRealtimePreparationEvidence(
                program=artifact.program,
                points=artifact.points,
                _target=self._target,
                request=target_request,
                artifact=artifact.compiled.artifact,
                artifact_fingerprint=artifact.compiled.artifact_fingerprint,
            )
        )
        return prepared

    def _measurements_for(
        self,
        program: quantum.Program,
        layouts: tuple[TargetAcquisitionLayout, ...],
        *,
        shots: int,
    ) -> tuple[tuple[str, tuple[int, ...]], ...]:
        selected: list[tuple[str, tuple[int, ...]]] = []
        measurement_ids = {
            result.id
            for result in program.results
            if isinstance(result, quantum.MeasurementResult)
        }
        for layout in layouts:
            result_id = layout.slot_id.local_id
            if result_id not in measurement_ids:
                continue
            expected_count = shots * len(layout.acquisition_addresses)
            bits = self._measurement_bits.get(result_id, (0,) * expected_count)
            if len(bits) != expected_count or any(bit not in (0, 1) for bit in bits):
                raise ValueError(
                    f"realtime measurement script {result_id!r} must contain "
                    f"{expected_count} bits"
                )
            selected.append((result_id, bits))
        return tuple(selected)


def _supported_program(call: DomainCallView) -> quantum.Program | None:
    body = call.program.body
    if not (
        call.program.dialect_id == quantum.QUANTUM_PROGRAM_DIALECT_ID
        and call.program.dialect_version == quantum.QUANTUM_PROGRAM_DIALECT_VERSION
        and isinstance(body, quantum.Program)
    ):
        return None
    return body


def _validate_call(
    call: DomainCallView,
    program: quantum.Program,
    implementations: tuple[DomainHostTransformImplementation, ...],
) -> None:
    if tuple(port.id for port in call.program.inputs) != tuple(
        port.id for port in program.ports
    ):
        raise ValueError("quantum Program input ports changed before compilation")
    if tuple(port.id for port in call.program.results) != tuple(
        result.id for result in program.results
    ):
        raise ValueError("quantum Program result ports changed before compilation")
    compiler_input_ids = tuple(port.id for port in call.program.compiler_inputs)
    if compiler_input_ids not in ((), (QUBIT_PARAMETER_TABLE,)):
        raise ValueError("quantum compiler inputs must be the qubits collection")
    for result in program.results:
        binding = call.result(result.id)
        if binding.contract is not result:
            raise ValueError("quantum result contracts must retain authored handles")
    _shot_count(call)
    for transform in call.measurement_transforms:
        _host_implementation(transform, implementations)


def _validate_execution(
    execution: DomainExecutionView,
    artifact: _QuantumLabArtifact,
) -> None:
    body = execution.program.body
    if not isinstance(body, quantum.Program) or body.id != artifact.program.id:
        raise ValueError("prepared quantum Program does not match its compiled job")
    if tuple(point.ref.ordinal for point in execution.points) != tuple(
        point.ordinal for point in artifact.points
    ):
        raise ValueError("prepared quantum points do not match their compiled job")


def _shot_count(call: DomainCallView | DomainExecutionView) -> int:
    counts: list[int] = []
    for result in call.results:
        axes = result.product.axes
        if not axes or axes[0].kind != "shot":
            raise ValueError("quantum lab result products require a leading shot axis")
        counts.append(axes[0].size)
    if not counts or len(set(counts)) != 1:
        raise ValueError("quantum lab result products require one shared shot count")
    return counts[0]


def _compile_points(
    program: quantum.Program,
    inputs: DomainCompiledInputs,
    pulse_profile: PulseRecipeProfile[QuantumCompilerParameters],
) -> tuple[_CompiledQuantumPoint, ...]:
    program_inputs = inputs.program
    compiler_parameters = (
        tuple(QuantumCompilerParameters() for _ordinal in inputs.ordinals)
        if not inputs.compiler.columns
        else inputs.compiler.decode_collection(
            QUBIT_PARAMETER_TABLE,
            QuantumCompilerParameters.from_qubit_rows,
        )
    )
    points = tuple(
        QuantumLabPointValues(
            ordinal=ordinal,
            values=tuple(
                (name, values[index]) for name, values in program_inputs.columns
            ),
            compiler_parameter_fingerprint=compiler_parameters[index].fingerprint,
        )
        for index, ordinal in enumerate(program_inputs.ordinals)
    )
    compiled: list[_CompiledQuantumPoint] = []
    for point, parameters in zip(points, compiler_parameters, strict=True):
        bound = quantum.bind(program, dict(point.values))
        compiled.append(
            _CompiledQuantumPoint(
                values=point,
                bound=bound,
                implementations=pulse_profile.materialize(
                    parameters,
                    bound.verified.unresolved_circuit,
                ),
            )
        )
    return tuple(compiled)


def _result_address(
    entry: PreparedQuantumTargetEntry,
    result: quantum.MeasurementResult,
    point: QuantumLabPointValues,
) -> TargetResultAddress:
    addresses = tuple(
        address
        for address in entry.acquisition_addresses
        if address.slot_id.local_id == result.id
    )
    values = dict(point.values)
    axes = tuple(
        (axis.id, _result_axis_size(axis, values))
        for axis in result.contract.axes
        if axis.id not in result.contract.acquisition_shape
    )
    expected_count = math.prod(size for _axis_id, size in axes)
    if len(addresses) != expected_count:
        raise ValueError("quantum result axes do not cover its target acquisitions")
    if not axes:
        [address] = addresses
        return address

    next_address = iter(addresses)

    def collect(axis_index: int) -> TargetResultAddress:
        if axis_index == len(axes):
            return next(next_address)
        axis_id, size = axes[axis_index]
        return ResultCollection(
            axis_id,
            tuple(collect(axis_index + 1) for _index in range(size)),
        )

    return collect(0)


def _realtime_result_layouts(
    entry_id: TargetCompileEntryId,
    program: quantum.Program,
    point: QuantumLabPointValues,
) -> tuple[TargetAcquisitionLayout, ...]:
    values = dict(point.values)
    layouts: list[TargetAcquisitionLayout] = []
    for result in program.results:
        if (
            isinstance(result, quantum.MeasurementResult)
            and result.acquisition_kind is not AcquisitionKind.INTEGRATED_IQ
        ):
            raise ValueError("fake realtime target supports integrated-IQ results only")
        slot_id = (
            result.acquisition_slot_id
            if isinstance(result, quantum.MeasurementResult)
            else result.result_slot_id
        )
        acquisition_shape = (
            result.contract.acquisition_shape
            if isinstance(result, quantum.MeasurementResult)
            else ()
        )
        layouts.append(
            TargetAcquisitionLayout(
                entry_id=entry_id,
                slot_id=slot_id,
                axes=tuple(
                    TargetResultAxisLayout(axis.id, _result_axis_size(axis, values))
                    for axis in result.contract.axes
                    if axis.id not in acquisition_shape
                ),
            )
        )
    return tuple(layouts)


def _result_axis_size(
    axis: quantum.QuantumResultAxis,
    values: Mapping[str, object],
) -> int:
    selected = axis.size if isinstance(axis.size, int) else values[axis.size.id]
    if not isinstance(selected, int) or isinstance(selected, bool) or selected <= 0:
        raise AssertionError(
            "verified quantum result axes resolve to positive integers"
        )
    return selected


def _realization_binding(
    address: TargetResultAddress,
    program: quantum.Program,
) -> FakeMeasurementRealizationBinding:
    result_ids = {
        item.slot_id.local_id for item in target_result_acquisition_addresses(address)
    }
    if len(result_ids) != 1:
        raise ValueError("one quantum result tree must retain one logical result id")
    [result_id] = result_ids
    result = next(
        result for result in _measurement_results(program) if result.id == result_id
    )
    if result.acquisition_kind is AcquisitionKind.INTEGRATED_IQ:
        return integrated_iq_shots(address)
    return raw_trace_shots(address)


def _measurement_results(
    program: quantum.Program,
) -> tuple[quantum.MeasurementResult, ...]:
    results = tuple(
        result
        for result in program.results
        if isinstance(result, quantum.MeasurementResult)
    )
    if len(results) != len(program.results):
        raise ValueError("list-mode targets only support acquisition results")
    return results


def _host_implementation(
    transform: DomainMeasurementTransform,
    implementations: tuple[DomainHostTransformImplementation, ...],
) -> DomainHostTransformImplementation:
    semantic = transform.semantic
    selected = tuple(
        implementation
        for implementation in implementations
        if implementation.semantic_id == semantic.id
        and implementation.semantic_version == semantic.version
    )
    if len(selected) != 1:
        raise ValueError("host transform implementation selection must be exact")
    [implementation] = selected
    implementation.validate_transform(transform)
    return implementation


def _response_runtime(response: FakeAcquisitionResponse) -> FakeListDomainRuntime:
    return FakeListDomainRuntime(
        FakeListRuntime(digitizer=FakeSegmentedDigitizer(response=response))
    )


def _realize(
    realization: SelectedFakeMeasurementRealization,
    fetched: CorrelatedDomainFetch[FakeListRun],
):
    return realize_fetched_fake_measurements(realization, fetched).result_values


__all__ = [
    "QuantumLabCompiler",
    "QuantumRealtimeLabCompiler",
]
