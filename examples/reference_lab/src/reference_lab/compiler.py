"""The unified domain compiler for the reference quantum laboratory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from scopecat.sdk.domain import (
    DomainBatchInputs,
    DomainBatchRequest,
    DomainCallView,
    DomainExecutionResult,
    DomainPreparationBuilder,
    PreparedDomainExecution,
)
from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import (
    PulseProgramId,
    TargetCompileEntryId,
    TargetCompilerId,
)
from scopecat_quantum.program_results import (
    MappedQuantumTarget,
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
from scopecat_quantum.targets import TargetAcquisitionAddress

from reference_lab.parameters import QUBITS
from reference_lab.point_values import QuantumLabPointValues
from reference_lab.quantum_compilation.compiler_parameters import (
    QuantumCompilerParameters,
)
from reference_lab.quantum_compilation.pulse_profile import QUANTUM_PULSE_PROFILE
from reference_lab.targets.configuration import (
    LIST_MODE_TARGET_KIND,
)
from reference_lab.targets.list_mode import (
    ListModeArtifact,
    ListModeDomainRuntime,
    ListModeRun,
    ListModeTarget,
    ListModeTargetCompiler,
    MappedListModeTarget,
    inspect_list_mode_artifact,
    list_mode_measurement_invocation_spec,
    list_mode_realtime_write_footprint,
    list_mode_setup_state_invalidations,
    list_mode_state_requirements,
    realize_executed_measurements,
)

_QUANTUM_LAB_TARGET_COMPILER_ID = TargetCompilerId("reference-lab.list-mode-target.v1")
_INITIAL_BATCH_SIZE = 1
_MAX_BATCH_WAVEFORM_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _QuantumLabArtifact:
    program: quantum.Program = field(repr=False)
    points: tuple[QuantumLabPointValues, ...]


@dataclass(frozen=True, slots=True)
class _ListQuantumLabArtifact(_QuantumLabArtifact):
    entries: tuple[PreparedQuantumTargetEntry, ...]
    batch: PreparedQuantumTargetBatch
    target_artifact: ListModeArtifact = field(repr=False)


@dataclass(frozen=True, slots=True)
class _CompiledQuantumPoint:
    values: QuantumLabPointValues
    bound: quantum.BoundProgram = field(repr=False)
    implementations: ResolvedPulseImplementations = field(repr=False)


@dataclass(frozen=True, slots=True)
class QuantumRuntimeContext:
    """Compiled logical context available to an optional execution adapter."""

    program: quantum.Program = field(repr=False)
    points: tuple[QuantumLabPointValues, ...]
    entries: tuple[PreparedQuantumTargetEntry, ...]
    repetitions: int


@dataclass(frozen=True, slots=True)
class QuantumRuntimeSelection:
    """Runtime plus stable response intent selected by a lab composition."""

    runtime: ListModeDomainRuntime
    response_intent: object | None = None


class QuantumRuntimeSelector(Protocol):
    """Select execution behavior without changing target compilation."""

    def __call__(self, context: QuantumRuntimeContext) -> QuantumRuntimeSelection: ...


class QuantumLabCompiler:
    """Own the reference lab's single domain-compilation boundary.

    Every bounded request contains the accepted point-local program and
    calibration inputs. Compilation closes the target artifact, result
    mapping, and runtime invocation without reaching into mutable state.
    """

    def __init__(
        self,
        *,
        target: ListModeTarget,
        runtime_selector: QuantumRuntimeSelector | None = None,
    ) -> None:
        self._target = target
        self._runtime = ListModeDomainRuntime()
        self._runtime_selector = runtime_selector
        self._target_compiler = ListModeTargetCompiler(
            _QUANTUM_LAB_TARGET_COMPILER_ID,
            self._target,
        )

    @property
    def target_id(self) -> str:
        return self._target.id.value

    @property
    def target_kind(self) -> str:
        return LIST_MODE_TARGET_KIND

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    *(
                        channel.instrument_id
                        for binding in self._target.output_bindings
                        for channel in binding.channel_ids
                    ),
                    *(
                        binding.input_id.instrument_id
                        for binding in self._target.acquisition_bindings
                    ),
                    self._target.preparation.timing.trigger_instrument_id,
                }
            )
        )

    def initial_batch_size(self, point_count: int) -> int:
        """Bound the first preparation without materializing program inputs."""

        return min(
            point_count,
            _INITIAL_BATCH_SIZE,
            self._target.max_list_entries,
        )

    def _compile_target_artifact(
        self,
        program: quantum.Program,
        inputs: DomainBatchInputs,
        point_ordinals: tuple[int, ...],
        *,
        shots: int,
    ) -> _ListQuantumLabArtifact:
        points = _compile_points(program, inputs, point_ordinals)
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
            repetitions=shots,
        )
        return _ListQuantumLabArtifact(
            program=program,
            points=tuple(point.values for point in points),
            entries=entries,
            batch=batch,
            target_artifact=self._target_compiler.compile(batch.request),
        )

    def compile_batch(
        self,
        request: DomainBatchRequest,
    ) -> PreparedDomainExecution:
        program = _quantum_program(request.call)
        _validate_call(request.call, program)
        artifact = self._compile_target_artifact(
            program,
            request.inputs,
            request.point_ordinals,
            shots=_shot_count(request.call),
        )
        preparation = DomainPreparationBuilder(request)
        entries = artifact.entries
        batch = artifact.batch
        mapping = seal_quantum_target_result_mapping(
            preparation,
            batch,
            tuple(
                QuantumTargetEntryPointBinding(entry.id, point)
                for entry, point in zip(entries, request.points, strict=True)
            ),
            tuple(
                QuantumTargetResultUseBinding(
                    _result_address(entry, result),
                    product_use,
                )
                for entry in entries
                for result in _measurement_results(artifact.program)
                for product_use in request.call.result(result.id).product_uses
            ),
        )
        mapped_target = MappedQuantumTarget(
            artifact.target_artifact,
            mapping,
        )
        selection = self._select_runtime(
            QuantumRuntimeContext(
                program=artifact.program,
                points=artifact.points,
                entries=entries,
                repetitions=batch.request.repetitions,
            )
        )
        runtime = selection.runtime
        invocation = list_mode_measurement_invocation_spec(
            mapped_target,
            invocation_id=(
                f"{artifact.program.id}.batch-{request.batch_ordinal}."
                f"point-{artifact.points[0].ordinal}"
            ),
            response_intent=selection.response_intent,
        )
        return preparation.build(
            instrument_ids=artifact.target_artifact.instrument_ids,
            setup=runtime,
            setup_state_invalidations=list_mode_setup_state_invalidations(
                artifact.target_artifact
            ),
            state_requirements=list_mode_state_requirements(artifact.target_artifact),
            realtime_write_footprint=list_mode_realtime_write_footprint(
                artifact.target_artifact
            ),
            realtime_state_invalidations=(),
            next_batch_max_points=_next_batch_max_points(
                artifact.target_artifact,
                max_list_entries=self._target.max_list_entries,
            ),
            inspection=inspect_list_mode_artifact(artifact.target_artifact).payload(),
            mapping=mapping,
            invocation=invocation,
            runtime=runtime,
            realize=lambda fetched: _realize(mapped_target, fetched),
        )

    def _select_runtime(
        self,
        context: QuantumRuntimeContext,
    ) -> QuantumRuntimeSelection:
        if self._runtime_selector is None:
            return QuantumRuntimeSelection(self._runtime)
        return self._runtime_selector(context)


def _next_batch_max_points(
    artifact: ListModeArtifact,
    *,
    max_list_entries: int,
) -> int:
    largest_entry_bytes = max(
        sum(waveform.samples.nbytes for waveform in entry.waveforms)
        for entry in artifact.entries
    )
    return min(
        max_list_entries,
        max(1, _MAX_BATCH_WAVEFORM_BYTES // max(largest_entry_bytes, 1)),
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
    if compiler_input_ids not in ((), (QUBITS.id,)):
        raise ValueError("quantum compiler inputs must be the qubits collection")
    for result in program.results:
        binding = call.result(result.id)
        if binding.contract is not result:
            raise ValueError("quantum result contracts must retain authored handles")
    _shot_count(call)


def _shot_count(call: DomainCallView) -> int:
    counts: list[int] = []
    for result in call.results:
        axes = result.product.axes
        if not axes or axes[0].kind != "shot":
            raise ValueError("quantum lab result products require a leading shot axis")
        size = axes[0].size
        if size is None:
            raise ValueError("quantum lab result products require fixed shot counts")
        counts.append(size)
    if not counts or len(set(counts)) != 1:
        raise ValueError("quantum lab result products require one shared shot count")
    return counts[0]


def _compile_points(
    program: quantum.Program,
    inputs: DomainBatchInputs,
    point_ordinals: tuple[int, ...],
) -> tuple[_CompiledQuantumPoint, ...]:
    program_inputs = inputs.program
    compiler_parameters = (
        tuple(QuantumCompilerParameters() for _ordinal in point_ordinals)
        if not inputs.compiler
        else inputs.decode_compiler_collection(
            QUBITS.id,
            QuantumCompilerParameters.from_qubit_rows,
        )
    )
    points = tuple(
        QuantumLabPointValues(
            ordinal=ordinal,
            values=tuple((name, values[index]) for name, values in program_inputs),
        )
        for index, ordinal in enumerate(point_ordinals)
    )
    compiled: list[_CompiledQuantumPoint] = []
    for point, parameters in zip(points, compiler_parameters, strict=True):
        bound = quantum.bind(program, dict(point.values))
        compiled.append(
            _CompiledQuantumPoint(
                values=point,
                bound=bound,
                implementations=QUANTUM_PULSE_PROFILE.materialize(
                    parameters,
                    bound.verified.unresolved,
                ),
            )
        )
    return tuple(compiled)


def _result_address(
    entry: PreparedQuantumTargetEntry,
    result: quantum.MeasurementResult,
) -> TargetAcquisitionAddress:
    addresses = tuple(
        address
        for address in entry.acquisition_addresses
        if address.slot_id.local_id == result.id
    )
    if len(addresses) != 1:
        raise ValueError("quantum lab results must have one acquisition address")
    return addresses[0]


def _measurement_results(
    program: quantum.Program,
) -> tuple[quantum.MeasurementResult, ...]:
    return tuple(program.results)


def _realize(
    mapped_target: MappedListModeTarget,
    executed: DomainExecutionResult[ListModeRun],
):
    return realize_executed_measurements(mapped_target, executed)


__all__ = [
    "QuantumLabCompiler",
    "QuantumRuntimeContext",
    "QuantumRuntimeSelection",
    "QuantumRuntimeSelector",
]
