"""The unified domain compiler for the demo quantum laboratory."""

from __future__ import annotations

import math
from collections.abc import Mapping
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
    PreparedDomainExecution,
    compiled_jobs,
)
from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import (
    PulseProgramId,
    TargetCompileEntryId,
    TargetCompilerId,
)
from scopecat_quantum.program_results import (
    CompiledQuantumTarget,
    QuantumTargetEntryPointBinding,
    QuantumTargetResultUseBinding,
    seal_quantum_target_result_mapping,
)
from scopecat_quantum.program_targets import (
    PreparedQuantumTargetBatch,
    PreparedQuantumTargetEntry,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
)
from scopecat_quantum.programs import (
    lower_quantum_program_to_pulses,
)
from scopecat_quantum.pulse_implementations import ResolvedPulseImplementations
from scopecat_quantum.pulse_recipes import PulseRecipeProfile
from scopecat_quantum.result_collections import ResultCollection
from scopecat_quantum.targets import (
    CompiledTargetArtifact,
    TargetResultAddress,
    compile_target,
)

from quantum_lab_demo.point_values import QuantumLabPointValues
from quantum_lab_demo.response_registry import (
    QuantumLabResponseRegistry,
    QuantumLabResponseRequest,
)
from quantum_lab_demo.targets.configuration import (
    FAKE_LIST_TARGET_KIND,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeAcquisitionResponse,
    FakeListArtifact,
    FakeListDomainRuntime,
    FakeListRun,
    FakeListRuntime,
    FakeListTarget,
    FakeListTargetCompiler,
    FakeSegmentedDigitizer,
    SelectedFakeMeasurementRealization,
    fake_measurement_invocation_spec,
    realize_fetched_fake_measurements,
    select_fake_measurement_realization,
)
from quantum_lab_demo.virtual_lab.compiler_parameters import QuantumCompilerParameters
from quantum_lab_demo.virtual_lab.parameters import QUBIT_PARAMETER_TABLE

_QUANTUM_LAB_TARGET_COMPILER_ID = TargetCompilerId(
    "quantum-lab-demo.fake-list-target.v1"
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
class _CompiledQuantumPoint:
    values: QuantumLabPointValues
    bound: quantum.BoundProgram = field(repr=False)
    implementations: ResolvedPulseImplementations = field(repr=False)


class _QuantumLabCompilerBase:
    def __init__(
        self,
        *,
        max_points: int,
        pulse_profile: PulseRecipeProfile[QuantumCompilerParameters],
    ) -> None:
        self._max_points = max_points
        self._pulse_profile = pulse_profile

    def compile(self, request: DomainCompileRequest) -> DomainCompilation:
        program = _quantum_program(request.call)
        _validate_call(request.call, program)
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

    Program and compiler input binders reflect the accepted snapshot and
    point-local overlays. ``compile`` resolves them into immutable artifact
    values through an injected static pulse recipe profile, so this
    implementation never reaches into mutable parameter state.
    """

    def __init__(
        self,
        *,
        target: FakeListTarget,
        runtime: FakeListDomainRuntime,
        response_registry: QuantumLabResponseRegistry,
        pulse_profile: PulseRecipeProfile[QuantumCompilerParameters],
    ) -> None:
        super().__init__(
            max_points=target.max_list_entries,
            pulse_profile=pulse_profile,
        )
        self._target = target
        self._runtime = runtime
        self._response_registry = response_registry
        self._target_compiler = FakeListTargetCompiler(
            _QUANTUM_LAB_TARGET_COMPILER_ID,
            self._target,
        )

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
        artifact = cast("_ListQuantumLabArtifact", job.artifact)
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
        return preparation.build(
            mapping=mapping.domain_mapping,
            invocation=invocation,
            runtime=runtime,
            realize=lambda fetched: _realize(realization, fetched),
        )


def _quantum_program(call: DomainCallView) -> quantum.Program:
    body = call.program.body
    if not (
        call.program.dialect_id == quantum.QUANTUM_PROGRAM_DIALECT_ID
        and call.program.dialect_version == quantum.QUANTUM_PROGRAM_DIALECT_VERSION
        and isinstance(body, quantum.Program)
    ):
        raise ValueError("quantum compiler requires a quantum Program")
    return body


def _validate_call(
    call: DomainCallView,
    program: quantum.Program,
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
        (axis.id, _result_axis_size(axis, values)) for axis in result.contract.axes
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


def _measurement_results(
    program: quantum.Program,
) -> tuple[quantum.MeasurementResult, ...]:
    return tuple(program.results)


def _response_runtime(response: FakeAcquisitionResponse) -> FakeListDomainRuntime:
    return FakeListDomainRuntime(
        FakeListRuntime(digitizer=FakeSegmentedDigitizer(response=response))
    )


def _realize(
    realization: SelectedFakeMeasurementRealization,
    fetched: CorrelatedDomainFetch[FakeListRun],
):
    return realize_fetched_fake_measurements(realization, fetched)


__all__ = [
    "QuantumLabCompiler",
]
