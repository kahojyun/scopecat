"""Production X90 execution with config-bound DRAG and a fixed Xm90 reference."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import cast

import scopecat as sc
from scopecat import Quantity
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.sdk.domain import (
    CorrelatedDomainFetch,
    DomainBatchContext,
    DomainCallView,
    DomainCompilation,
    DomainCompiledJob,
    DomainCompileRequest,
    DomainExecutionView,
    DomainHostTransformBinding,
    DomainHostTransformImplementation,
    DomainMeasurementTransform,
    DomainPreparationBuilder,
    DomainProductUseRef,
    DomainResultMapping,
    PreparedDomainExecution,
    compiled_jobs,
)
from scopecat_quantum import (
    AcquisitionSlotId,
    BinaryIqDiscriminator,
    CalibrationCatalog,
    CircuitPulseEventProvenance,
    CompiledQuantumTarget,
    DriveSignal,
    GateCalibrationCatalog,
    GateId,
    ImplementedGatePulseEventProvenance,
    IqCentroid,
    Play,
    PreparedQuantumTargetEntry,
    PulseEventId,
    PulseProgramId,
    QuantumTargetAcquisitionUseBinding,
    QuantumTargetEntryPointBinding,
    TargetAcquisitionAddress,
    TargetCompileEntryId,
    TargetCompilerId,
    binary_iq_probability_host_implementation,
    binary_iq_probability_transform,
    compile_target,
    lower_quantum_program_to_pulses,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
    seal_quantum_target_result_mapping,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.experiments.ids import QUBIT_PARAMETER_TABLE
from quantum_lab_demo.reference_experiments.drag_beta_calibration import (
    DEFAULT_BASELINE_BETA,
    DRAG_GATE_PULSE_TEMPLATE,
    DRAG_READOUT_PULSE_TEMPLATE,
    XM90_CALIBRATION_ID,
    baseline_calibration_catalog,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListArtifact,
    FakeListDomainRuntime,
    FakeListRun,
    FakeListTarget,
    FakeListTargetCompiler,
    FakeMeasurementInvocationSpec,
    SelectedFakeMeasurementRealization,
    default_fake_list_target,
    fake_measurement_invocation_spec,
    integrated_iq_shots,
    realize_fetched_fake_measurements,
    select_fake_measurement_realization,
)

PRODUCTION_DRAG_GATE_ADAPTER_ID = "quantum-lab-demo.production-drag-gate.v1"
PRODUCTION_DRAG_GATE_TEMPLATE_ID = "quantum_lab_demo.production.drag_x90"
PRODUCTION_DRAG_GATE_EXPERIMENT_ID = "production-drag-x90"
PRODUCTION_DRAG_GATE_SHOTS = 32
PRODUCTION_DRAG_GATE_COMPILER_ID = TargetCompilerId(
    "quantum-lab-demo.production-drag-gate.v1"
)
DRAG_BETA_PARAMETER_COLUMN = "drag_beta"
TRUSTED_REFERENCE_BETA = DEFAULT_BASELINE_BETA

_BETA_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
PRODUCTION_DRAG_BETA_INPUT = quantum.input("drag_beta", _BETA_VALUE_TYPE)
ACTIVE_DRAG_BETA = sc.parameter_lookup(
    QUBIT_PARAMETER_TABLE,
    key={"qubit": "q0"},
    column=DRAG_BETA_PARAMETER_COLUMN,
    value_type=_BETA_VALUE_TYPE,
)

_Q0 = quantum.qubit("q0")
_X90 = quantum.single_qubit_gate("x90")
_XM90 = quantum.single_qubit_gate("xm90")


def production_drag_gate_program() -> quantum.Program:
    """Declare a production X90 followed by one fixed trusted Xm90."""

    production_x90 = quantum.implements(
        _X90(_Q0),
        DRAG_GATE_PULSE_TEMPLATE(
            _Q0,
            template_beta=PRODUCTION_DRAG_BETA_INPUT,
            template_phase=Quantity(0, "rad"),
        ),
    )
    capture = quantum.acquire(
        _Q0,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    return quantum.program(
        "production-drag-x90",
        quantum.sequence(
            production_x90,
            _XM90(_Q0),
            quantum.parallel(DRAG_READOUT_PULSE_TEMPLATE(_Q0), capture),
        ),
    )


def trusted_xm90_calibration_catalog() -> CalibrationCatalog:
    """Return only the Xm90 reference calibration at its fixed lab value."""

    source = baseline_calibration_catalog(TRUSTED_REFERENCE_BETA)
    selected = tuple(
        entry for entry in source.gates.entries if entry.id == XM90_CALIBRATION_ID
    )
    if len(selected) != 1:
        msg = "trusted reference catalog must contain exactly one Xm90 calibration"
        raise AssertionError(msg)
    return CalibrationCatalog(gates=GateCalibrationCatalog(selected))


_PRODUCTION_DRAG_PROGRAM = production_drag_gate_program()
[_IQ_SHOTS_RESULT] = _PRODUCTION_DRAG_PROGRAM.results
_PRODUCTION_DRAG_DOMAIN_PROGRAM = quantum.domain_program(_PRODUCTION_DRAG_PROGRAM)
_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)
_PROBABILITY_TRANSFORM = binary_iq_probability_transform(
    "binary-iq-probability",
    iq_shots="integrated_iq_shots",
    probability_0="probability_0",
    probability_1="probability_1",
    discriminator=_DISCRIMINATOR,
)

PRODUCTION_DRAG_GATE_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.production.drag_x90.capture")
    .product(
        "integrated_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(PRODUCTION_DRAG_GATE_SHOTS),),
    )
    .product("probability_0", "probability_1", unit="ratio")
    .measurement_transforms(_PROBABILITY_TRANSFORM)
    .build()
)

_TEMPLATE_CAPTURE = PRODUCTION_DRAG_GATE_CAPTURE_MODULE.instantiate("capture")
_PRODUCTION_DRAG_EXECUTION = quantum.domain_execution(
    _PRODUCTION_DRAG_DOMAIN_PROGRAM,
    inputs={PRODUCTION_DRAG_BETA_INPUT: ACTIVE_DRAG_BETA},
    results={
        _IQ_SHOTS_RESULT: _TEMPLATE_CAPTURE.products.integrated_iq_shots,
    },
)
PRODUCTION_DRAG_GATE_TEMPLATE = (
    sc.module("quantum_lab_demo.production.drag_x90.root")
    .use(_TEMPLATE_CAPTURE)
    .template(
        PRODUCTION_DRAG_GATE_TEMPLATE_ID,
        kind=PRODUCTION_DRAG_GATE_EXPERIMENT_ID,
    )
    .domain(_PRODUCTION_DRAG_EXECUTION)
    .experiment_id(PRODUCTION_DRAG_GATE_EXPERIMENT_ID)
    .record_product(_TEMPLATE_CAPTURE.products.probability_0, record_id="probability_0")
    .record_product(_TEMPLATE_CAPTURE.products.probability_1, record_id="probability_1")
    .label("Production DRAG X90")
    .description(
        "Compile the active q0 DRAG beta into a production X90 while keeping "
        "the trusted Xm90 reference calibration fixed."
    )
)


@dataclass(frozen=True, slots=True)
class ProductionDragProductBinding:
    """Context-owned IQ uses and their probability transform."""

    iq_shots: tuple[DomainProductUseRef, ...]
    transform: DomainMeasurementTransform

    def __post_init__(self) -> None:
        selected = tuple(self.iq_shots)
        if not selected:
            msg = "production DRAG bindings require IQ product uses"
            raise ValueError(msg)
        if len(set(selected)) != len(selected):
            msg = "production DRAG IQ product uses must be distinct"
            raise ValueError(msg)
        object.__setattr__(self, "iq_shots", selected)


@dataclass(frozen=True, slots=True)
class PreparedProductionDragGate:
    """Pure compilation and execution evidence for one production gate point."""

    preparation: DomainPreparationBuilder = field(repr=False)
    products: ProductionDragProductBinding
    resolved_drag_beta: Quantity
    declaration: quantum.Program
    target: FakeListTarget
    compiler: FakeListTargetCompiler
    calibration_catalog: CalibrationCatalog
    entry: PreparedQuantumTargetEntry
    compiled_target: CompiledQuantumTarget[FakeListArtifact]
    runtime: FakeListDomainRuntime = field(repr=False)
    realization: SelectedFakeMeasurementRealization = field(repr=False)
    invocation: FakeMeasurementInvocationSpec = field(repr=False)
    measurement_mapping: DomainResultMapping[TargetAcquisitionAddress] = field(
        repr=False
    )
    host_transforms: tuple[DomainHostTransformBinding, ...] = field(repr=False)

    @property
    def trusted_reference_beta(self) -> Quantity:
        return TRUSTED_REFERENCE_BETA

    @property
    def artifact(self) -> FakeListArtifact:
        return self.compiled_target.compiled.artifact

    @property
    def artifact_fingerprint(self) -> str:
        return self.compiled_target.compiled.artifact_fingerprint

    @property
    def production_samples(self) -> tuple[complex, ...]:
        origin = _production_origin(self.entry)
        return _compiled_event_samples(self, origin.address.event_id)

    @property
    def trusted_reference_samples(self) -> tuple[complex, ...]:
        origin = _trusted_reference_origin(self.entry)
        return _compiled_event_samples(self, origin.address.event_id)


def prepare_production_drag_gate(
    preparation: DomainPreparationBuilder,
    products: ProductionDragProductBinding,
    *,
    result_slot_id: AcquisitionSlotId,
    declaration: quantum.Program,
    drag_beta: Quantity,
    shots: int = PRODUCTION_DRAG_GATE_SHOTS,
    target: FakeListTarget | None = None,
    compiler_id: TargetCompilerId = PRODUCTION_DRAG_GATE_COMPILER_ID,
    host_implementation: DomainHostTransformImplementation | None = None,
    invocation_id: str = "production-drag-gate",
) -> PreparedProductionDragGate:
    """Bind active beta, compile the mixed program, and close its result mapping."""

    if isinstance(shots, bool) or shots <= 0:
        msg = "production DRAG shots must be a positive integer"
        raise ValueError(msg)
    selected_target = default_fake_list_target() if target is None else target
    if not invocation_id:
        msg = "production DRAG invocation_id must be non-empty"
        raise ValueError(msg)
    [point] = preparation.context.points
    selected_beta = _decode_beta(drag_beta)
    catalog = trusted_xm90_calibration_catalog()
    bound = quantum.bind(
        declaration,
        {PRODUCTION_DRAG_BETA_INPUT.id: selected_beta},
    )
    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        catalog,
        output_id=PulseProgramId(f"production-drag-{point.ordinal}.pulses"),
    )
    entry = prepare_quantum_target_entry(
        TargetCompileEntryId(f"production-drag-entry-{point.ordinal}"),
        lowered,
    )
    _production_origin(entry)
    _trusted_reference_origin(entry)
    compiler = FakeListTargetCompiler(compiler_id, selected_target)
    batch = prepare_quantum_target_batch(
        (entry,),
        target_id=selected_target.id,
        compiler_id=compiler.id,
        capability_fingerprint=selected_target.capability_fingerprint,
        repetitions=shots,
    )
    address = _acquisition_address(entry, result_slot_id)
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        (QuantumTargetEntryPointBinding(entry.id, point),),
        tuple(
            QuantumTargetAcquisitionUseBinding(address, product_use)
            for product_use in products.iq_shots
        ),
    )
    compiled_target = CompiledQuantumTarget(
        mapping,
        compile_target(compiler, batch.request),
    )
    runtime = FakeListDomainRuntime()
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
    )
    implementation = (
        binary_iq_probability_host_implementation()
        if host_implementation is None
        else host_implementation
    )
    host_transforms = (DomainHostTransformBinding(products.transform, implementation),)
    return PreparedProductionDragGate(
        preparation=preparation,
        products=products,
        resolved_drag_beta=selected_beta,
        declaration=declaration,
        target=selected_target,
        compiler=compiler,
        calibration_catalog=catalog,
        entry=entry,
        compiled_target=compiled_target,
        runtime=runtime,
        realization=realization,
        invocation=invocation,
        measurement_mapping=mapping.domain_mapping,
        host_transforms=host_transforms,
    )


@dataclass(frozen=True, slots=True)
class _ProductionDragArtifact:
    drag_beta: Quantity


class ProductionDragGateCompiler:
    """Execute config-bound production X90 programs on the fake target."""

    def __init__(self, *, target: FakeListTarget | None = None) -> None:
        selected = default_fake_list_target() if target is None else target
        self.target = selected
        self._preparations: list[PreparedProductionDragGate] = []

    @property
    def compiler_id(self) -> str:
        return PRODUCTION_DRAG_GATE_ADAPTER_ID

    @property
    def target_id(self) -> str:
        return self.target.id.value

    @property
    def preparations(self) -> tuple[PreparedProductionDragGate, ...]:
        """Return immutable preparation evidence in execution order."""

        return tuple(self._preparations)

    @property
    def physical_execution_count(self) -> int:
        return sum(item.runtime.physical_execution_count for item in self._preparations)

    def claim_resources(
        self,
        call: DomainCallView,
    ) -> tuple[ResourceClaim, ...] | None:
        if not _accepts_execution(call):
            return None
        return (ResourceClaim(self.target.id.value, "target"),)

    def compile(self, request: DomainCompileRequest) -> DomainCompilation | None:
        if not _accepts_execution(request.call):
            return None
        drag_beta = request.input("drag_beta")
        if not drag_beta.is_literal:
            return None
        artifact = _ProductionDragArtifact(_decode_beta(drag_beta.literal_value()))
        return compiled_jobs(
            request,
            max_points=1,
            absorbed_input_ids=("drag_beta",),
            compile_artifact=lambda _inputs: artifact,
        )

    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        execution = context.execution
        artifact = cast("_ProductionDragArtifact", job.take_artifact())
        if len(execution.points) != 1:
            msg = "production DRAG execution requires exactly one logical point"
            raise ValueError(msg)
        preparation = context.new_preparation()
        iq_result = _validated_result_contracts(execution)
        reference = prepare_production_drag_gate(
            preparation,
            _product_binding(execution),
            result_slot_id=iq_result.acquisition_slot_id,
            declaration=_program_body(execution),
            drag_beta=artifact.drag_beta,
            target=self.target,
            invocation_id=f"production-drag-gate.batch-{context.batch_ordinal}",
        )
        prepared = preparation.build(
            mapping=reference.measurement_mapping,
            host_transforms=reference.host_transforms,
            invocation=reference.invocation,
            runtime=reference.runtime,
            realize=lambda fetched: _realize(reference, fetched),
        )
        self._preparations.append(reference)
        return prepared


def _decode_beta(value: object) -> Quantity:
    if not isinstance(value, Quantity):
        msg = "production DRAG beta must be a time Quantity"
        raise TypeError(msg)
    try:
        selected = float(value.to("ns").value)
    except ValueError as error:
        msg = "production DRAG beta must be a time Quantity"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "production DRAG beta must be finite"
        raise ValueError(msg)
    return Quantity(selected, "ns")


def _accepts_execution(execution: DomainCallView) -> bool:
    if not (
        execution.program.dialect_id == quantum.QUANTUM_PROGRAM_DIALECT_ID
        and execution.program.dialect_version == quantum.QUANTUM_PROGRAM_DIALECT_VERSION
        and isinstance(execution.program.body, quantum.Program)
        and execution.program.body.id == _PRODUCTION_DRAG_PROGRAM.id
    ):
        return False
    _validated_result_contracts(execution)
    return True


def _program_body(
    execution: DomainCallView | DomainExecutionView,
) -> quantum.Program:
    body = execution.program.body
    if not isinstance(body, quantum.Program):
        msg = "production DRAG domain body must be a Program"
        raise TypeError(msg)
    return body


def _product_binding(execution: DomainExecutionView) -> ProductionDragProductBinding:
    [transform] = execution.measurement_transforms
    return ProductionDragProductBinding(
        iq_shots=execution.result("iq_shots").product_uses,
        transform=transform,
    )


def _validated_result_contracts(
    execution: DomainCallView | DomainExecutionView,
) -> quantum.MeasurementResult:
    body = _program_body(execution)
    iq_result = execution.result("iq_shots").contract
    if (
        not isinstance(iq_result, quantum.MeasurementResult)
        or iq_result.id != "iq_shots"
        or not any(result is iq_result for result in body.results)
    ):
        msg = "production DRAG IQ result must bind its authored result handle"
        raise ValueError(msg)
    if len(execution.measurement_transforms) != 1:
        msg = "production DRAG execution requires one measurement transform"
        raise ValueError(msg)
    binary_iq_probability_host_implementation().validate_transform(
        execution.measurement_transforms[0]
    )
    return iq_result


def _production_origin(entry: PreparedQuantumTargetEntry):
    selected = tuple(
        origin
        for origin in entry.event_origins
        if isinstance(origin.provenance, ImplementedGatePulseEventProvenance)
        and origin.provenance.gate_id == GateId("x90")
        and origin.provenance.candidate_id is None
        and origin.provenance.template_program_id.value == DRAG_GATE_PULSE_TEMPLATE.id
    )
    if len(selected) != 1:
        msg = "production gate must lower one non-candidate X90 implementation"
        raise ValueError(msg)
    return selected[0]


def _trusted_reference_origin(entry: PreparedQuantumTargetEntry):
    selected = tuple(
        origin
        for origin in entry.event_origins
        if isinstance(origin.provenance, CircuitPulseEventProvenance)
        and origin.provenance.calibration_id == XM90_CALIBRATION_ID
    )
    if len(selected) != 1:
        msg = "production gate must lower one trusted Xm90 calibration"
        raise ValueError(msg)
    return selected[0]


def _compiled_event_samples(
    prepared: PreparedProductionDragGate,
    event_id: PulseEventId,
) -> tuple[complex, ...]:
    [event] = tuple(
        item for item in prepared.entry.scheduled.events if item.id == event_id
    )
    if not isinstance(event.instruction, Play) or not isinstance(
        event.instruction.signal, DriveSignal
    ):
        msg = "production gate evidence requires a drive Play event"
        raise ValueError(msg)
    channel = prepared.target.output_channel(event.instruction.signal)
    if channel is None:
        msg = "production gate drive signal is not bound to an output channel"
        raise ValueError(msg)
    [artifact_entry] = tuple(
        item for item in prepared.artifact.entries if item.entry_id == prepared.entry.id
    )
    [waveform] = tuple(
        item for item in artifact_entry.waveforms if item.channel_id == channel
    )
    rate = Decimal(prepared.artifact.sample_rate_hz)
    start = event.start_seconds * rate
    count = event.duration_seconds * rate
    if start != start.to_integral_value() or count != count.to_integral_value():
        msg = "compiled gate event is not aligned to the target sample grid"
        raise ValueError(msg)
    first = int(start)
    return waveform.samples[first : first + int(count)]


def _acquisition_address(
    entry: PreparedQuantumTargetEntry,
    slot_id: AcquisitionSlotId,
) -> TargetAcquisitionAddress:
    selected = tuple(
        address for address in entry.acquisition_addresses if address.slot_id == slot_id
    )
    if len(selected) != 1:
        msg = "production gate entry requires exactly one authored acquisition"
        raise ValueError(msg)
    return selected[0]


def _realize(
    reference: PreparedProductionDragGate,
    fetched: CorrelatedDomainFetch[FakeListRun],
):
    return realize_fetched_fake_measurements(
        reference.realization,
        fetched,
    ).result_values


__all__ = [
    "ACTIVE_DRAG_BETA",
    "DRAG_BETA_PARAMETER_COLUMN",
    "PRODUCTION_DRAG_BETA_INPUT",
    "PRODUCTION_DRAG_GATE_ADAPTER_ID",
    "PRODUCTION_DRAG_GATE_CAPTURE_MODULE",
    "PRODUCTION_DRAG_GATE_COMPILER_ID",
    "PRODUCTION_DRAG_GATE_EXPERIMENT_ID",
    "PRODUCTION_DRAG_GATE_SHOTS",
    "PRODUCTION_DRAG_GATE_TEMPLATE",
    "PRODUCTION_DRAG_GATE_TEMPLATE_ID",
    "TRUSTED_REFERENCE_BETA",
    "PreparedProductionDragGate",
    "ProductionDragGateCompiler",
    "ProductionDragProductBinding",
    "prepare_production_drag_gate",
    "production_drag_gate_program",
    "trusted_xm90_calibration_catalog",
]
