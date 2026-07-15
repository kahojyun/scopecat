"""Unified two-qubit gate and coupler-pulse conditional-phase calibration."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from scopecat import IntType, Quantity, QuantityType, ScalarType
from scopecat.sdk.domain.measurements import (
    DomainHostTransformBinding,
    DomainHostTransformImplementation,
)
from scopecat.sdk.domain.preparation import (
    DomainMeasurementPlan,
    DomainPreparationBuilder,
)
from scopecat.sdk.domain.view import (
    DomainMeasurementTransform,
    DomainPointRef,
    DomainProductUseRef,
)
from scopecat_quantum import (
    AcquisitionSlotId,
    CalibrationCatalog,
    CalibrationId,
    CompiledQuantumTarget,
    Constant,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateId,
    ImplementedGatePulseEventProvenance,
    Play,
    PreparedQuantumTargetEntry,
    PulseEventId,
    PulseProgram,
    PulseProgramId,
    QuantumTargetAcquisitionUseBinding,
    QuantumTargetEntryPointBinding,
    QubitId,
    TargetAcquisitionAddress,
    TargetCompileEntryId,
    TargetCompilerId,
    binary_iq_probability_host_implementation,
    bind_compiled_quantum_target,
    compile_target,
    lower_quantum_program_to_pulses,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
    seal_quantum_target_result_mapping,
)
from scopecat_quantum import authoring as q

from quantum_lab_demo.reference_experiments.cz_phase_response import (
    CzPhaseAcquisitionResponse,
    CzPhaseResponsePoint,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListArtifact,
    FakeListDomainRuntime,
    FakeListRuntime,
    FakeListTarget,
    FakeListTargetCompiler,
    FakeMeasurementInvocationSpec,
    FakeSegmentedDigitizer,
    SelectedFakeMeasurementRealization,
    default_fake_list_target,
    fake_measurement_invocation_spec,
    integrated_iq_shots,
    select_fake_measurement_realization,
)

CZ_CANDIDATE_ID = "cz.conditional-phase"
CZ_AMPLITUDE_INPUT = q.input(
    "coupler_amplitude",
    ScalarType(QuantityType(unit="arb")),
)
CONTROL_STATE_INPUT = q.input(
    "control_state",
    ScalarType(IntType(minimum=0, maximum=1)),
)
ANALYZER_PHASE_INPUT = q.input(
    "analyzer_phase",
    ScalarType(QuantityType(unit="rad")),
)

_CONTROL = q.qubit("q0")
_TARGET = q.qubit("q1")
_COUPLER = q.coupler("coupler-q0-q1")
_CONTROL_ID = QubitId("q0")
_TARGET_ID = QubitId("q1")
_X = q.single_qubit_gate("x")
_X90 = q.single_qubit_gate("x90")
_CZ = q.two_qubit_gate("cz")
_FORMAL_QUBIT = q.qubit("formal-qubit")
_FORMAL_COUPLER = q.coupler("formal-coupler")
_FORMAL_CZ_AMPLITUDE = q.input(
    "amplitude",
    ScalarType(QuantityType(unit="arb")),
)

_SINGLE_QUBIT_DURATION = Quantity(16, "ns")
_X_AMPLITUDE = Quantity(0.4, "arb")
_X90_AMPLITUDE = Quantity(0.2, "arb")
_CZ_DURATION = Quantity(32, "ns")
_READOUT_DURATION = Quantity(24, "ns")
_READOUT_AMPLITUDE = Quantity(0.35, "arb")

X_CONTROL_CALIBRATION_ID = CalibrationId("cz-phase.baseline.x.q0")
X90_TARGET_CALIBRATION_ID = CalibrationId("cz-phase.baseline.x90.q1")
CZ_PHASE_COMPILER_ID = TargetCompilerId("quantum-lab-demo.cz-phase.v1")

CZ_FLUX_PULSE_TEMPLATE = q.pulse_template(
    "cz-phase.coupler-flux",
    q.play(
        q.flux(_FORMAL_COUPLER),
        q.constant(
            duration=_CZ_DURATION,
            amplitude=_FORMAL_CZ_AMPLITUDE,
        ),
    ),
    elements=(_FORMAL_COUPLER,),
)

CZ_READOUT_PULSE_TEMPLATE = q.pulse_template(
    "cz-phase.readout-stimulus",
    q.play(
        q.readout(_FORMAL_QUBIT),
        q.constant(
            duration=_READOUT_DURATION,
            amplitude=_READOUT_AMPLITUDE,
        ),
    ),
    elements=(_FORMAL_QUBIT,),
)


def cz_conditional_phase_program() -> q.Program:
    """Declare one conditional-phase Ramsey point in the unified DSL."""

    control_capture = q.acquire(
        _CONTROL,
        duration=_READOUT_DURATION,
        result="control_iq_shots",
    )
    target_capture = q.acquire(
        _TARGET,
        duration=_READOUT_DURATION,
        result="target_iq_shots",
    )
    candidate = q.implements(
        _CZ(_CONTROL, _TARGET),
        CZ_FLUX_PULSE_TEMPLATE(
            _COUPLER,
            amplitude=CZ_AMPLITUDE_INPUT,
        ),
        resources=(_COUPLER,),
        candidate=CZ_CANDIDATE_ID,
    )
    return q.program(
        "cz-conditional-phase",
        q.sequence(
            q.repeat(_X(_CONTROL), CONTROL_STATE_INPUT),
            _X90(_TARGET),
            candidate,
            q.shift_phase(q.drive(_TARGET), ANALYZER_PHASE_INPUT),
            _X90(_TARGET),
            q.parallel(
                CZ_READOUT_PULSE_TEMPLATE(_CONTROL),
                control_capture,
                CZ_READOUT_PULSE_TEMPLATE(_TARGET),
                target_capture,
            ),
        ),
    )


def cz_phase_calibration_catalog() -> CalibrationCatalog:
    """Return accepted single-qubit calibrations surrounding the CZ candidate."""

    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=X_CONTROL_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x"), (_CONTROL_ID,)),
                    pulse_template=_drive_template(
                        "cz-phase.baseline-x-q0",
                        qubit=_CONTROL_ID,
                        amplitude=_X_AMPLITUDE,
                    ),
                ),
                GateCalibration(
                    id=X90_TARGET_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (_TARGET_ID,)),
                    pulse_template=_drive_template(
                        "cz-phase.baseline-x90-q1",
                        qubit=_TARGET_ID,
                        amplitude=_X90_AMPLITUDE,
                    ),
                ),
            )
        )
    )


def prepare_cz_phase_entry(
    declaration: q.Program,
    *,
    amplitude: Quantity,
    control_state: int,
    analyzer_phase: Quantity,
    entry_id: TargetCompileEntryId,
    calibration_catalog: CalibrationCatalog | None = None,
) -> PreparedQuantumTargetEntry:
    """Bind and prepare one conditional-phase Ramsey point."""

    bound = q.bind(
        declaration,
        {
            CZ_AMPLITUDE_INPUT.id: _normalized_amplitude(amplitude),
            CONTROL_STATE_INPUT.id: _validated_control_state(control_state),
            ANALYZER_PHASE_INPUT.id: _normalized_phase(analyzer_phase),
        },
    )
    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        cz_phase_calibration_catalog()
        if calibration_catalog is None
        else calibration_catalog,
        output_id=PulseProgramId(f"{entry_id.value}.pulses"),
    )
    prepared = prepare_quantum_target_entry(entry_id, lowered)
    _validate_candidate_coverage(prepared)
    return prepared


@dataclass(frozen=True, slots=True)
class CzPhaseProductBinding:
    """Context-owned direct IQ products and their two host transforms."""

    control_iq_shots: tuple[DomainProductUseRef, ...]
    target_iq_shots: tuple[DomainProductUseRef, ...]
    control_transform: DomainMeasurementTransform
    target_transform: DomainMeasurementTransform

    def __post_init__(self) -> None:
        for name, values in (
            ("control", tuple(self.control_iq_shots)),
            ("target", tuple(self.target_iq_shots)),
        ):
            if not values:
                msg = f"CZ phase {name} IQ bindings require product uses"
                raise ValueError(msg)
            if len(set(values)) != len(values):
                msg = f"CZ phase {name} IQ product uses must be distinct"
                raise ValueError(msg)
            object.__setattr__(self, f"{name}_iq_shots", values)
        if self.control_transform == self.target_transform:
            msg = "CZ phase control and target transforms must differ"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PreparedCzPhaseReference:
    """Fully correlated two-qubit program, target, response, and measurement plan."""

    preparation: DomainPreparationBuilder = field(repr=False)
    products: CzPhaseProductBinding
    amplitudes: tuple[Quantity, ...]
    control_states: tuple[int, ...]
    analyzer_phases: tuple[Quantity, ...]
    declaration: q.Program
    target: FakeListTarget
    compiler: FakeListTargetCompiler
    calibration_catalog: CalibrationCatalog
    entries: tuple[PreparedQuantumTargetEntry, ...]
    compiled_target: CompiledQuantumTarget[FakeListArtifact]
    response: CzPhaseAcquisitionResponse = field(repr=False)
    runtime: FakeListDomainRuntime = field(repr=False)
    realization: SelectedFakeMeasurementRealization = field(repr=False)
    invocation: FakeMeasurementInvocationSpec = field(repr=False)
    measurements: DomainMeasurementPlan[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ] = field(repr=False)

    @property
    def shots(self) -> int:
        return self.compiled_target.compiled.repetitions


def prepare_cz_phase_reference(
    preparation: DomainPreparationBuilder,
    products: CzPhaseProductBinding,
    *,
    control_slot_id: AcquisitionSlotId,
    target_slot_id: AcquisitionSlotId,
    declaration: q.Program,
    amplitudes: Sequence[Quantity],
    control_states: Sequence[int],
    analyzer_phases: Sequence[Quantity],
    shots: int = 128,
    target: FakeListTarget | None = None,
    compiler_id: TargetCompilerId = CZ_PHASE_COMPILER_ID,
    host_implementation: DomainHostTransformImplementation | None = None,
    invocation_id: str = "cz-conditional-phase",
) -> PreparedCzPhaseReference:
    """Close one conditional-phase scan batch before hardware effects."""

    if control_slot_id == target_slot_id:
        msg = "CZ phase acquisition slots must differ"
        raise ValueError(msg)
    if isinstance(shots, bool) or shots <= 0:
        msg = "CZ phase shots must be a positive integer"
        raise ValueError(msg)
    selected_target = default_fake_list_target() if target is None else target
    if not invocation_id:
        msg = "CZ phase invocation_id must be non-empty"
        raise ValueError(msg)

    points = preparation.context.points
    selected_amplitudes = _validated_values(
        points,
        amplitudes,
        normalizer=_normalized_amplitude,
        label="amplitudes",
    )
    selected_states = _validated_values(
        points,
        control_states,
        normalizer=_validated_control_state,
        label="control states",
    )
    selected_phases = _validated_values(
        points,
        analyzer_phases,
        normalizer=_normalized_phase,
        label="analyzer phases",
    )
    catalog = cz_phase_calibration_catalog()
    entries = tuple(
        prepare_cz_phase_entry(
            declaration,
            amplitude=amplitude,
            control_state=control_state,
            analyzer_phase=phase,
            entry_id=TargetCompileEntryId(f"cz-phase-entry-{point.ordinal}"),
            calibration_catalog=catalog,
        )
        for point, amplitude, control_state, phase in zip(
            points,
            selected_amplitudes,
            selected_states,
            selected_phases,
            strict=True,
        )
    )
    compiler = FakeListTargetCompiler(compiler_id, selected_target)
    batch = prepare_quantum_target_batch(
        entries,
        target_id=selected_target.id,
        compiler_id=compiler.id,
        capability_fingerprint=selected_target.capability_fingerprint,
        repetitions=shots,
    )
    entry_bindings = tuple(
        QuantumTargetEntryPointBinding(entry.id, point)
        for entry, point in zip(entries, points, strict=True)
    )
    acquisition_bindings = tuple(
        binding
        for entry in entries
        for binding in (
            *(
                QuantumTargetAcquisitionUseBinding(
                    _acquisition_address(entry, control_slot_id),
                    product_use,
                )
                for product_use in products.control_iq_shots
            ),
            *(
                QuantumTargetAcquisitionUseBinding(
                    _acquisition_address(entry, target_slot_id),
                    product_use,
                )
                for product_use in products.target_iq_shots
            ),
        )
    )
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        entry_bindings,
        acquisition_bindings,
    )
    compiled_target = bind_compiled_quantum_target(
        mapping,
        compile_target(compiler, batch.request),
    )
    response = CzPhaseAcquisitionResponse(
        points=tuple(
            CzPhaseResponsePoint(
                control_address=_acquisition_address(entry, control_slot_id),
                target_address=_acquisition_address(entry, target_slot_id),
                amplitude=amplitude,
                control_state=control_state,
                analyzer_phase=phase,
            )
            for entry, amplitude, control_state, phase in zip(
                entries,
                selected_amplitudes,
                selected_states,
                selected_phases,
                strict=True,
            )
        ),
        shots=shots,
    )
    if response.addresses != batch.acquisition_addresses:
        msg = "CZ phase response must exactly cover prepared acquisitions"
        raise ValueError(msg)
    runtime = FakeListDomainRuntime(
        FakeListRuntime(
            digitizer=FakeSegmentedDigitizer(response=response),
        )
    )
    realization = select_fake_measurement_realization(
        compiled_target,
        selected_target,
        tuple(
            integrated_iq_shots(result.result_address)
            for result in mapping.domain_mapping.results
        ),
    )
    invocation = fake_measurement_invocation_spec(
        realization,
        invocation_id=invocation_id,
        response_intent=response.intent,
    )
    implementation = (
        binary_iq_probability_host_implementation()
        if host_implementation is None
        else host_implementation
    )
    measurements = preparation.measurement_plan(
        mapping.domain_mapping,
        host_transforms=(
            DomainHostTransformBinding(products.control_transform, implementation),
            DomainHostTransformBinding(products.target_transform, implementation),
        ),
    )
    return PreparedCzPhaseReference(
        preparation=preparation,
        products=products,
        amplitudes=selected_amplitudes,
        control_states=selected_states,
        analyzer_phases=selected_phases,
        declaration=declaration,
        target=selected_target,
        compiler=compiler,
        calibration_catalog=catalog,
        entries=entries,
        compiled_target=compiled_target,
        response=response,
        runtime=runtime,
        realization=realization,
        invocation=invocation,
        measurements=measurements,
    )


def _drive_template(
    program_id: str,
    *,
    qubit: QubitId,
    amplitude: Quantity,
) -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(qubit),
            envelope=Constant(
                duration=_SINGLE_QUBIT_DURATION,
                amplitude=amplitude,
            ),
        ),
    )


def _validate_candidate_coverage(entry: PreparedQuantumTargetEntry) -> None:
    candidates = tuple(
        origin.provenance
        for origin in entry.event_origins
        if isinstance(origin.provenance, ImplementedGatePulseEventProvenance)
    )
    if (
        len(candidates) != 1
        or candidates[0].gate_id != GateId("cz")
        or candidates[0].candidate_id != CZ_CANDIDATE_ID
        or candidates[0].template_program_id.value != CZ_FLUX_PULSE_TEMPLATE.id
    ):
        msg = "CZ phase entries must contain exactly one authored CZ candidate"
        raise ValueError(msg)


def _acquisition_address(
    entry: PreparedQuantumTargetEntry,
    slot_id: AcquisitionSlotId,
) -> TargetAcquisitionAddress:
    selected = tuple(
        address for address in entry.acquisition_addresses if address.slot_id == slot_id
    )
    if len(selected) != 1:
        msg = (
            f"CZ phase entry {entry.id.value!r} requires exactly one acquisition "
            f"for result {slot_id.value!r}"
        )
        raise ValueError(msg)
    return selected[0]


def _validated_values[ValueT](
    points: Sequence[DomainPointRef],
    values: Sequence[object],
    *,
    normalizer: Callable[[object], ValueT],
    label: str,
) -> tuple[ValueT, ...]:
    selected_points = tuple(points)
    selected = tuple(values)
    if not selected_points or len(selected) != len(selected_points):
        msg = f"CZ phase {label} must exactly cover the logical point batch"
        raise ValueError(msg)
    return tuple(normalizer(value) for value in selected)


def _normalized_amplitude(value: object) -> Quantity:
    if not isinstance(value, Quantity):
        msg = "CZ amplitudes must be quantities"
        raise TypeError(msg)
    try:
        selected = float(value.to("arb").value)
    except ValueError as error:
        msg = "CZ amplitudes must use amplitude units"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "CZ amplitudes must be finite"
        raise ValueError(msg)
    return Quantity(selected, "arb")


def _normalized_phase(value: object) -> Quantity:
    if not isinstance(value, Quantity):
        msg = "CZ analyzer phases must be quantities"
        raise TypeError(msg)
    try:
        selected = float(value.to("rad").value)
    except ValueError as error:
        msg = "CZ analyzer phases must use phase units"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "CZ analyzer phases must be finite"
        raise ValueError(msg)
    return Quantity(selected, "rad")


def _validated_control_state(value: object) -> int:
    if type(value) is not int or value not in (0, 1):
        msg = "CZ control states must be 0 or 1"
        raise ValueError(msg)
    return value


__all__ = [
    "ANALYZER_PHASE_INPUT",
    "CONTROL_STATE_INPUT",
    "CZ_AMPLITUDE_INPUT",
    "CZ_CANDIDATE_ID",
    "CZ_FLUX_PULSE_TEMPLATE",
    "CZ_PHASE_COMPILER_ID",
    "CZ_READOUT_PULSE_TEMPLATE",
    "X90_TARGET_CALIBRATION_ID",
    "X_CONTROL_CALIBRATION_ID",
    "CzPhaseProductBinding",
    "PreparedCzPhaseReference",
    "cz_conditional_phase_program",
    "cz_phase_calibration_catalog",
    "prepare_cz_phase_entry",
    "prepare_cz_phase_reference",
]
