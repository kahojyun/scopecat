"""The unified domain compiler for the demo quantum laboratory."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

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
    PreparedDomainExecution,
    compiled_jobs,
)
from scopecat_quantum import (
    AcquisitionKind,
    CalibrationCatalog,
    CompiledQuantumTarget,
    PreparedQuantumTargetEntry,
    PulseProgramId,
    QuantumTargetEntryPointBinding,
    QuantumTargetResultUseBinding,
    ResultCollection,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetResultAddress,
    binary_iq_probability_host_implementation,
    compile_target,
    lower_quantum_program_to_pulses,
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
from quantum_lab_demo.targets.fake_list_mode import (
    FakeAcquisitionResponse,
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
from quantum_lab_demo.trace import (
    QuantumLabPointValues,
    QuantumLabPreparationEvidence,
    QuantumLabTrace,
)
from quantum_lab_demo.virtual_lab.calibrations import (
    calibration_catalog_from_qubit_parameters,
)
from quantum_lab_demo.virtual_lab.parameters import QUANTUM_CALIBRATIONS_INPUT

_QUANTUM_LAB_COMPILER_ID = "quantum-lab-demo.compiler.v1"
_QUANTUM_LAB_TARGET_COMPILER_ID = TargetCompilerId(
    "quantum-lab-demo.fake-list-target.v1"
)


@dataclass(frozen=True, slots=True)
class _QuantumLabArtifact:
    program: quantum.Program = field(repr=False)
    points: tuple[QuantumLabPointValues, ...]
    calibrations: tuple[CalibrationCatalog, ...] = field(repr=False)


class QuantumLabCompiler:
    """Own the demo lab's single domain-compilation boundary.

    Scopecat derives domain input normal forms from accepted experiment
    semantics; program and compiler inputs both reflect the accepted snapshot
    and point-local overlays. ``compile`` resolves them into immutable artifact
    values, so this implementation never reaches into mutable parameter state.
    It also owns the internal target lowering stage; the injected response
    registry may select deterministic fake behavior by Program identity, but
    never a different compiler.
    """

    def __init__(
        self,
        *,
        target: FakeListTarget,
        runtime: FakeListDomainRuntime,
        response_registry: QuantumLabResponseRegistry,
        trace: QuantumLabTrace,
    ) -> None:
        self._target = target
        self._runtime = runtime
        self._response_registry = response_registry
        self._trace = trace
        self._trace.register_runtime(runtime)
        self._target_compiler = FakeListTargetCompiler(
            _QUANTUM_LAB_TARGET_COMPILER_ID,
            self._target,
        )
        self._host_implementations = (binary_iq_probability_host_implementation(),)

    @property
    def compiler_id(self) -> str:
        return _QUANTUM_LAB_COMPILER_ID

    @property
    def target_id(self) -> str:
        return self._target.id.value

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
        input_ids = tuple(port.id for port in program.ports)
        return compiled_jobs(
            request,
            max_points=self._target.max_list_entries,
            artifact_input_ids=input_ids,
            compile_artifact=lambda inputs: _compile_artifact(program, inputs),
        )

    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        artifact = cast("_QuantumLabArtifact", job.take_artifact())
        execution = context.execution
        _validate_execution(execution, artifact)
        preparation = context.new_preparation()
        entries = tuple(
            prepare_quantum_target_entry(
                TargetCompileEntryId(
                    f"{artifact.program.id}.batch-{context.batch_ordinal}."
                    f"point-{point.ordinal}"
                ),
                lower_quantum_program_to_pulses(
                    quantum.bind(artifact.program, dict(point.values)).verified,
                    calibrations,
                    output_id=PulseProgramId(
                        f"{artifact.program.id}.batch-{context.batch_ordinal}."
                        f"point-{point.ordinal}.pulses"
                    ),
                ),
            )
            for point, calibrations in zip(
                artifact.points,
                artifact.calibrations,
                strict=True,
            )
        )
        shots = _shot_count(execution)
        batch = prepare_quantum_target_batch(
            entries,
            target_id=self._target.id,
            compiler_id=self._target_compiler.id,
            capability_fingerprint=self._target.capability_fingerprint,
            repetitions=shots,
        )
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
                for result in artifact.program.results
                for product_use in execution.result(result.id).product_uses
            ),
        )
        compiled_target = CompiledQuantumTarget(
            mapping,
            compile_target(self._target_compiler, batch.request),
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
    if compiler_input_ids not in ((), (QUANTUM_CALIBRATIONS_INPUT,)):
        raise ValueError("quantum compiler inputs must be the calibration collection")
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


def _compile_artifact(
    program: quantum.Program,
    inputs: DomainCompiledInputs,
) -> _QuantumLabArtifact:
    program_inputs = inputs.program
    calibrations = (
        tuple(CalibrationCatalog() for _ordinal in inputs.ordinals)
        if not inputs.compiler.columns
        else tuple(
            calibration_catalog_from_qubit_parameters(
                cast("Sequence[Mapping[str, object]]", rows)
            )
            for rows in inputs.compiler.input(QUANTUM_CALIBRATIONS_INPUT)
        )
    )
    return _QuantumLabArtifact(
        program=program,
        points=tuple(
            QuantumLabPointValues(
                ordinal=ordinal,
                values=tuple(
                    (name, values[index]) for name, values in program_inputs.columns
                ),
            )
            for index, ordinal in enumerate(program_inputs.ordinals)
        ),
        calibrations=calibrations,
    )


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
    result = next(result for result in program.results if result.id == result_id)
    if result.acquisition_kind is AcquisitionKind.INTEGRATED_IQ:
        return integrated_iq_shots(address)
    return raw_trace_shots(address)


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
]
