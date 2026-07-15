"""Pure compilation and analysis slice for rough DRAG-beta calibration.

The authored program deliberately mixes logical gates with pulse-level candidate
implementations.  Only the baseline X90 and Xm90 operations consult the
calibration catalog; explicit X90/Xm90 implementations keep their logical
identity while carrying one reusable, bindable DRAG PulseTemplate. Calibration
candidates and an accepted production implementation therefore share the same
physical template without sharing lifecycle state. Readout stimulus and
acquisition are explicit physical statements in the same program.

No device effect occurs here.  A point is closed through binding, mixed-program
lowering, scheduling, and target-entry preparation.  A complete batch can then
close result correlation, compilation, response intent, and host measurement
planning before the Workspace adapter performs the effect.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
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
    DRAG,
    AcquisitionSlotId,
    CalibrationCatalog,
    CalibrationId,
    CompiledQuantumTarget,
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

from quantum_lab_demo.reference_experiments.drag_beta_response import (
    DEFAULT_BASELINE,
    DEFAULT_CURVATURE,
    DEFAULT_OPTIMUM_BETA,
    DragBetaAcquisitionResponse,
    DragBetaResponsePoint,
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

POSITIVE_CANDIDATE_ID = "x90.drag.plus"
NEGATIVE_CANDIDATE_ID = "x90.drag.minus"
BETA_INPUT = q.input("beta", ScalarType(QuantityType(unit="ns")))
AMPLIFICATION_INPUT = q.input(
    "amplification",
    ScalarType(IntType(minimum=1)),
)

_Q0 = q.qubit("q0")
_Q0_ID = QubitId("q0")
_X90 = q.single_qubit_gate("x90")
_XM90 = q.single_qubit_gate("xm90")
_TEMPLATE_QUBIT = q.qubit("template")
_TEMPLATE_BETA = q.input("template_beta", ScalarType(QuantityType(unit="ns")))
_TEMPLATE_PHASE = q.input(
    "template_phase",
    ScalarType(QuantityType(unit="rad")),
)

_PULSE_DURATION = Quantity(16, "ns")
_PULSE_AMPLITUDE = Quantity(0.2, "arb")
_PULSE_SIGMA = Quantity(4, "ns")
_READOUT_DURATION = Quantity(8, "ns")

DEFAULT_BASELINE_BETA = Quantity(0.5, "ns")

X90_CALIBRATION_ID = CalibrationId("drag-beta.baseline.x90.q0")
XM90_CALIBRATION_ID = CalibrationId("drag-beta.baseline.xm90.q0")
DEFAULT_COMPILER_ID = TargetCompilerId("quantum-lab-demo.drag-beta.v1")

DRAG_GATE_PULSE_TEMPLATE = q.pulse_template(
    "drag-beta.gate-pulse",
    q.play(
        q.drive(_TEMPLATE_QUBIT),
        q.drag(
            duration=_PULSE_DURATION,
            amplitude=_PULSE_AMPLITUDE,
            sigma=_PULSE_SIGMA,
            beta=_TEMPLATE_BETA,
            phase=_TEMPLATE_PHASE,
        ),
    ),
    elements=(_TEMPLATE_QUBIT,),
)

DRAG_READOUT_PULSE_TEMPLATE = q.pulse_template(
    "drag-beta.readout-stimulus",
    q.play(
        q.readout(_TEMPLATE_QUBIT),
        q.constant(
            duration=_READOUT_DURATION,
            amplitude=Quantity(0.25, "arb"),
        ),
    ),
    elements=(_TEMPLATE_QUBIT,),
)


def drag_beta_calibration_program() -> q.Program:
    """Declare one bindable rough-calibration program for the complete scan.

    Both the physical DRAG coefficient and the logical amplification count are
    first-class inputs.  One declaration can therefore be bound at every point
    of a two-dimensional beta-by-amplification scan without generating a
    different program identity for each repetition count. The trusted X90 and
    Xm90 reference gates prepare and invert the same state around the repeated
    candidate identity pair. At the optimum the sequence returns near the
    ground state; a coherently accumulated small error therefore contributes a
    population term proportional to ``N^2 * (beta - beta_opt)^2``.
    """

    candidate_pair = q.sequence(
        _candidate_x90(),
        _candidate_xm90(),
    )
    capture = q.acquire(
        _Q0,
        duration=_READOUT_DURATION,
        result="iq_shots",
    )
    return q.program(
        "drag-beta-rough-calibration",
        q.sequence(
            _X90(_Q0),
            q.repeat(candidate_pair, AMPLIFICATION_INPUT),
            _XM90(_Q0),
            q.parallel(
                DRAG_READOUT_PULSE_TEMPLATE(_Q0),
                capture,
            ),
        ),
    )


def baseline_calibration_catalog(
    beta: Quantity = DEFAULT_BASELINE_BETA,
) -> CalibrationCatalog:
    """Return the calibrated baseline gates; readout is authored physically."""

    selected_beta = _normalized_beta(beta)

    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=X90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (_Q0_ID,)),
                    pulse_template=_baseline_drag_template(
                        "x90-baseline-template",
                        beta=selected_beta,
                        phase=Quantity(0, "rad"),
                    ),
                ),
                GateCalibration(
                    id=XM90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("xm90"), (_Q0_ID,)),
                    pulse_template=_baseline_drag_template(
                        "xm90-baseline-template",
                        beta=selected_beta,
                        phase=Quantity(math.pi, "rad"),
                    ),
                ),
            )
        ),
    )


def prepare_drag_beta_point(
    declaration: q.Program,
    beta: Quantity,
    amplification: int,
    *,
    baseline_beta: Quantity = DEFAULT_BASELINE_BETA,
    entry_id: TargetCompileEntryId,
) -> PreparedQuantumTargetEntry:
    """Bind one beta point, refine baseline operations, and prepare target IR."""

    return _prepare_drag_beta_point(
        declaration,
        beta,
        amplification,
        calibration_catalog=baseline_calibration_catalog(baseline_beta),
        entry_id=entry_id,
    )


def _prepare_drag_beta_point(
    declaration: q.Program,
    beta: Quantity,
    amplification: int,
    *,
    calibration_catalog: CalibrationCatalog,
    entry_id: TargetCompileEntryId,
) -> PreparedQuantumTargetEntry:
    """Prepare one point against an already-bound baseline catalog."""

    bound = q.bind(
        declaration,
        {
            BETA_INPUT.id: beta,
            AMPLIFICATION_INPUT.id: _require_positive_amplification(amplification),
        },
    )
    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        calibration_catalog,
        output_id=PulseProgramId(f"{entry_id.value}.pulses"),
    )
    return prepare_quantum_target_entry(entry_id, lowered)


@dataclass(frozen=True, slots=True)
class DragBetaProductBinding:
    """Context-owned direct IQ uses and their authored host transform."""

    iq_shots: tuple[DomainProductUseRef, ...]
    transform: DomainMeasurementTransform

    def __post_init__(self) -> None:
        selected = tuple(self.iq_shots)
        if not selected:
            msg = "DRAG-beta product bindings require at least one IQ use"
            raise ValueError(msg)
        if any(not isinstance(value, DomainProductUseRef) for value in selected):
            msg = "DRAG-beta IQ bindings require SDK product-use references"
            raise TypeError(msg)
        if len(set(selected)) != len(selected):
            msg = "DRAG-beta IQ product uses must be distinct"
            raise ValueError(msg)
        if not isinstance(self.transform, DomainMeasurementTransform):
            msg = "DRAG-beta product bindings require an authored transform"
            raise TypeError(msg)
        object.__setattr__(self, "iq_shots", selected)


@dataclass(frozen=True, slots=True)
class PreparedDragBetaReference:
    """Pure, fully correlated mixed-program target and measurement plan."""

    preparation: DomainPreparationBuilder = field(repr=False)
    products: DragBetaProductBinding
    betas: tuple[Quantity, ...]
    amplifications: tuple[int, ...]
    declaration: q.Program
    target: FakeListTarget
    compiler: FakeListTargetCompiler
    calibration_catalog: CalibrationCatalog
    entries: tuple[PreparedQuantumTargetEntry, ...]
    compiled_target: CompiledQuantumTarget[FakeListArtifact]
    response: DragBetaAcquisitionResponse = field(repr=False)
    runtime: FakeListDomainRuntime = field(repr=False)
    realization: SelectedFakeMeasurementRealization = field(repr=False)
    invocation: FakeMeasurementInvocationSpec = field(repr=False)
    measurements: DomainMeasurementPlan[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ] = field(repr=False)

    @property
    def shots(self) -> int:
        """Return hardware repetitions for every beta-amplification point."""

        return self.compiled_target.compiled.repetitions


def prepare_drag_beta_reference(
    preparation: DomainPreparationBuilder,
    products: DragBetaProductBinding,
    *,
    result_slot_id: AcquisitionSlotId,
    declaration: q.Program,
    betas: Sequence[Quantity],
    amplifications: Sequence[int],
    baseline_beta: Quantity = DEFAULT_BASELINE_BETA,
    shots: int = 64,
    target: FakeListTarget | None = None,
    compiler_id: TargetCompilerId = DEFAULT_COMPILER_ID,
    host_implementation: DomainHostTransformImplementation | None = None,
    invocation_id: str = "drag-beta",
) -> PreparedDragBetaReference:
    """Close one 2-D mixed program batch before any target effect occurs."""

    if not isinstance(preparation, DomainPreparationBuilder):
        msg = "DRAG-beta preparation requires a domain preparation builder"
        raise TypeError(msg)
    if not isinstance(products, DragBetaProductBinding):
        msg = "DRAG-beta preparation requires a product binding"
        raise TypeError(msg)
    if not isinstance(result_slot_id, AcquisitionSlotId):
        msg = "DRAG-beta preparation requires a typed acquisition slot"
        raise TypeError(msg)
    if not isinstance(declaration, q.Program):
        msg = "DRAG-beta preparation requires a Program declaration"
        raise TypeError(msg)
    if type(shots) is not int or shots <= 0:
        msg = "DRAG-beta shots must be a positive integer"
        raise ValueError(msg)
    selected_target = default_fake_list_target() if target is None else target
    if not isinstance(selected_target, FakeListTarget):
        msg = "DRAG-beta target must be a FakeListTarget"
        raise TypeError(msg)
    if not isinstance(compiler_id, TargetCompilerId):
        msg = "DRAG-beta compiler_id must be a TargetCompilerId"
        raise TypeError(msg)
    if not invocation_id:
        msg = "DRAG-beta invocation_id must be non-empty"
        raise ValueError(msg)

    points = preparation.context.points
    selected_betas = _validated_betas(points, betas)
    selected_amplifications = _validated_amplifications(points, amplifications)
    catalog = baseline_calibration_catalog(baseline_beta)
    entries = tuple(
        _prepare_drag_beta_point(
            declaration,
            beta,
            amplification,
            calibration_catalog=catalog,
            entry_id=TargetCompileEntryId(f"drag-beta-entry-{point.ordinal}"),
        )
        for point, beta, amplification in zip(
            points,
            selected_betas,
            selected_amplifications,
            strict=True,
        )
    )
    for entry, amplification in zip(
        entries,
        selected_amplifications,
        strict=True,
    ):
        _validate_candidate_coverage(entry, amplification)
    compiler = FakeListTargetCompiler(compiler_id, selected_target)
    batch = prepare_quantum_target_batch(
        entries,
        target_id=selected_target.id,
        compiler_id=compiler.id,
        capability_fingerprint=selected_target.capability_fingerprint,
        repetitions=shots,
    )
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        tuple(
            QuantumTargetEntryPointBinding(entry.id, point)
            for entry, point in zip(entries, points, strict=True)
        ),
        tuple(
            QuantumTargetAcquisitionUseBinding(
                _acquisition_address(entry, result_slot_id),
                product_use,
            )
            for entry in entries
            for product_use in products.iq_shots
        ),
    )
    compiled_target = bind_compiled_quantum_target(
        mapping,
        compile_target(compiler, batch.request),
    )
    response = DragBetaAcquisitionResponse(
        points=tuple(
            DragBetaResponsePoint(
                address=_acquisition_address(entry, result_slot_id),
                beta=beta,
                amplification=amplification,
            )
            for entry, beta, amplification in zip(
                entries,
                selected_betas,
                selected_amplifications,
                strict=True,
            )
        ),
        shots=shots,
    )
    if response.addresses != batch.acquisition_addresses:
        msg = "DRAG-beta response plan must exactly cover the prepared acquisitions"
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
            DomainHostTransformBinding(products.transform, implementation),
        ),
    )
    return PreparedDragBetaReference(
        preparation=preparation,
        products=products,
        betas=selected_betas,
        amplifications=selected_amplifications,
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


@dataclass(frozen=True, slots=True)
class DragBetaObservation:
    """One probability observation at a beta value and amplification count."""

    beta: Quantity
    amplification: int
    p1: float

    def __post_init__(self) -> None:
        _beta_ns(self.beta)
        _require_positive_amplification(self.amplification)
        if not isinstance(self.p1, int | float) or isinstance(self.p1, bool):
            msg = "DRAG-beta p1 observations must be finite numbers"
            raise TypeError(msg)
        selected = float(self.p1)
        if not math.isfinite(selected):
            msg = "DRAG-beta p1 observations must be finite numbers"
            raise ValueError(msg)
        if not 0.0 <= selected <= 1.0:
            msg = "DRAG-beta p1 observations must lie in [0, 1]"
            raise ValueError(msg)
        object.__setattr__(self, "p1", selected)


@dataclass(frozen=True, slots=True)
class DragBetaFit:
    """Shared fit of ``p1 = baseline + N^2 (a beta^2 + b beta + c)``."""

    beta_hat: Quantity
    baseline: float
    quadratic: float
    linear: float
    scaled_offset: float
    rmse: float


def synthetic_drag_beta_response(beta: Quantity, *, amplification: int) -> float:
    """Return a deterministic rough-calibration response for offline examples."""

    selected_beta = _beta_ns(beta)
    selected_amplification = _require_positive_amplification(amplification)
    response = (
        DEFAULT_BASELINE
        + DEFAULT_CURVATURE
        * selected_amplification**2
        * (selected_beta - _beta_ns(DEFAULT_OPTIMUM_BETA)) ** 2
    )
    if response > 1.0:
        msg = "synthetic DRAG-beta response exceeds 1; narrow the beta scan"
        raise ValueError(msg)
    return response


def fit_drag_beta(observations: Sequence[DragBetaObservation]) -> DragBetaFit:
    """Jointly fit beta scans from multiple amplification counts.

    The linear least-squares basis is ``1, N^2 beta^2, N^2 beta, N^2``.
    A full-rank fit therefore requires enough beta coverage and more than one
    amplification count; the optimum is the shared vertex ``-b / (2a)``.
    """

    selected = tuple(observations)
    if len(selected) < 4 or any(
        not isinstance(observation, DragBetaObservation) for observation in selected
    ):
        msg = "DRAG-beta fitting requires at least four typed observations"
        raise ValueError(msg)
    rows: list[tuple[float, float, float, float]] = []
    values: list[float] = []
    for observation in selected:
        beta_ns = _beta_ns(observation.beta)
        amplification = _require_positive_amplification(observation.amplification)
        scale = float(amplification**2)
        rows.append((1.0, scale * beta_ns**2, scale * beta_ns, scale))
        values.append(observation.p1)

    design = np.asarray(rows, dtype=float)
    response = np.asarray(values, dtype=float)
    coefficients, _residuals, rank, _singular_values = np.linalg.lstsq(
        design,
        response,
        rcond=None,
    )
    if int(rank) != 4:
        msg = "DRAG-beta observations do not identify a joint quadratic"
        raise ValueError(msg)
    baseline, quadratic, linear, scaled_offset = (
        float(value) for value in coefficients
    )
    if not math.isfinite(quadratic) or quadratic <= 0:
        msg = "DRAG-beta joint quadratic must have positive curvature"
        raise ValueError(msg)
    beta_hat = -linear / (2.0 * quadratic)
    scanned_betas = tuple(_beta_ns(observation.beta) for observation in selected)
    if not min(scanned_betas) <= beta_hat <= max(scanned_betas):
        msg = "fitted DRAG beta lies outside the scanned beta range"
        raise ValueError(msg)
    residual = design @ coefficients - response
    rmse = float(np.sqrt(np.mean(residual**2)))
    return DragBetaFit(
        beta_hat=Quantity(beta_hat, "ns"),
        baseline=baseline,
        quadratic=quadratic,
        linear=linear,
        scaled_offset=scaled_offset,
        rmse=rmse,
    )


def _candidate_x90() -> q.QuantumFragment:
    return q.implements(
        _X90(_Q0),
        DRAG_GATE_PULSE_TEMPLATE(
            _Q0,
            template_beta=BETA_INPUT,
            template_phase=Quantity(0, "rad"),
        ),
        candidate=POSITIVE_CANDIDATE_ID,
    )


def _candidate_xm90() -> q.QuantumFragment:
    return q.implements(
        _XM90(_Q0),
        DRAG_GATE_PULSE_TEMPLATE(
            _Q0,
            template_beta=BETA_INPUT,
            template_phase=Quantity(math.pi, "rad"),
        ),
        candidate=NEGATIVE_CANDIDATE_ID,
    )


def _baseline_drag_template(
    program_id: str,
    *,
    beta: Quantity,
    phase: Quantity,
) -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(_Q0_ID),
            envelope=DRAG(
                duration=_PULSE_DURATION,
                amplitude=_PULSE_AMPLITUDE,
                sigma=_PULSE_SIGMA,
                beta=beta,
                phase=phase,
            ),
        ),
    )


def _acquisition_address(
    entry: PreparedQuantumTargetEntry,
    slot_id: AcquisitionSlotId,
) -> TargetAcquisitionAddress:
    selected = tuple(
        address for address in entry.acquisition_addresses if address.slot_id == slot_id
    )
    if len(selected) != 1:
        msg = (
            f"DRAG-beta entry {entry.id.value!r} requires exactly one "
            f"acquisition for result {slot_id.value!r}"
        )
        raise ValueError(msg)
    return selected[0]


def _validate_candidate_coverage(
    entry: PreparedQuantumTargetEntry,
    amplification: int,
) -> None:
    candidate_ids = tuple(
        origin.provenance.candidate_id
        for origin in entry.event_origins
        if isinstance(
            origin.provenance,
            ImplementedGatePulseEventProvenance,
        )
    )
    expected = (POSITIVE_CANDIDATE_ID, NEGATIVE_CANDIDATE_ID) * amplification
    if candidate_ids != expected:
        msg = (
            f"DRAG-beta entry {entry.id.value!r} does not exactly implement "
            "its authored amplification sequence"
        )
        raise ValueError(msg)


def _validated_betas(
    points: Sequence[DomainPointRef],
    values: Sequence[Quantity],
) -> tuple[Quantity, ...]:
    selected_points = tuple(points)
    selected = tuple(values)
    if not selected_points:
        msg = "DRAG-beta experiments require at least one logical point"
        raise ValueError(msg)
    if len(selected) != len(selected_points):
        msg = "DRAG-beta values must exactly cover the logical point batch"
        raise ValueError(msg)
    for point, value in zip(selected_points, selected, strict=True):
        try:
            _beta_ns(value)
        except (TypeError, ValueError) as error:
            msg = f"DRAG-beta point {point.ordinal} requires a finite time Quantity"
            raise ValueError(msg) from error
    return selected


def _validated_amplifications(
    points: Sequence[DomainPointRef],
    values: Sequence[int],
) -> tuple[int, ...]:
    selected_points = tuple(points)
    selected = tuple(values)
    if len(selected) != len(selected_points):
        msg = "DRAG-beta amplification values must exactly cover the point batch"
        raise ValueError(msg)
    for point, value in zip(selected_points, selected, strict=True):
        try:
            _require_positive_amplification(value)
        except ValueError as error:
            msg = (
                f"DRAG-beta point {point.ordinal} requires a positive "
                "integer amplification"
            )
            raise ValueError(msg) from error
    return selected


def _require_positive_amplification(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        msg = "DRAG-beta amplification must be a positive integer"
        raise ValueError(msg)
    return value


def _beta_ns(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "DRAG beta must be a time Quantity"
        raise TypeError(msg)
    try:
        selected = float(value.to("ns").value)
    except ValueError as error:
        msg = "DRAG beta must be a time Quantity"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "DRAG beta must be finite"
        raise ValueError(msg)
    return selected


def _normalized_beta(value: object) -> Quantity:
    return Quantity(_beta_ns(value), "ns")


__all__ = [
    "AMPLIFICATION_INPUT",
    "BETA_INPUT",
    "DEFAULT_BASELINE_BETA",
    "DEFAULT_COMPILER_ID",
    "DRAG_GATE_PULSE_TEMPLATE",
    "DRAG_READOUT_PULSE_TEMPLATE",
    "NEGATIVE_CANDIDATE_ID",
    "POSITIVE_CANDIDATE_ID",
    "X90_CALIBRATION_ID",
    "XM90_CALIBRATION_ID",
    "DragBetaFit",
    "DragBetaObservation",
    "DragBetaProductBinding",
    "PreparedDragBetaReference",
    "baseline_calibration_catalog",
    "drag_beta_calibration_program",
    "fit_drag_beta",
    "prepare_drag_beta_point",
    "prepare_drag_beta_reference",
    "synthetic_drag_beta_response",
]
