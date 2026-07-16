"""Workspace execution adapter for conditional-phase Ramsey CZ calibration."""

from __future__ import annotations

import math

import scopecat as sc
from scopecat import Quantity
from scopecat.sdk.domain import (
    CorrelatedDomainFetch,
    DomainBatchContext,
    DomainBatchView,
    DomainExecutionOffer,
    DomainExecutionView,
    PreparedDomainExecution,
)
from scopecat_quantum import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_host_implementation,
    binary_iq_probability_transform,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.reference_experiments.cz_phase_calibration import (
    ANALYZER_PHASE_INPUT,
    CONTROL_STATE_INPUT,
    CZ_AMPLITUDE_INPUT,
    CzPhaseProductBinding,
    PreparedCzPhaseReference,
    cz_conditional_phase_program,
    prepare_cz_phase_reference,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListRun,
    FakeListTarget,
    default_fake_list_target,
    realize_fetched_fake_measurements,
)

CZ_PHASE_ADAPTER_ID = "quantum-lab-demo.cz-conditional-phase.v1"
CZ_PHASE_TEMPLATE_ID = "quantum_lab_demo.reference.cz_conditional_phase"
CZ_PHASE_EXPERIMENT_ID = "cz-conditional-phase"
CZ_PHASE_SHOTS = 128
DEFAULT_CZ_AMPLITUDES = tuple(Quantity(value, "arb") for value in (0.18, 0.24, 0.30))
DEFAULT_CONTROL_STATES = (0, 1)
DEFAULT_ANALYZER_PHASES = tuple(
    Quantity(value, "rad")
    for value in (0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0)
)

_AMPLITUDE_TYPE = sc.ScalarType(sc.QuantityType(unit="arb"))
_PHASE_TYPE = sc.ScalarType(sc.QuantityType(unit="rad"))
CZ_AMPLITUDE = sc.point("coupler_amplitude", _AMPLITUDE_TYPE)
CONTROL_STATE = sc.point(
    "control_state",
    sc.ScalarType(sc.IntType(minimum=0, maximum=1)),
)
ANALYZER_PHASE = sc.point("analyzer_phase", _PHASE_TYPE)

_CZ_PROGRAM = cz_conditional_phase_program()
[_CONTROL_RESULT, _TARGET_RESULT] = _CZ_PROGRAM.results
_CZ_DOMAIN_PROGRAM = quantum.domain_program(_CZ_PROGRAM)
_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)
_CONTROL_TRANSFORM = binary_iq_probability_transform(
    "control-binary-iq-probability",
    iq_shots="control_iq_shots",
    probability_0="control_probability_0",
    probability_1="control_probability_1",
    discriminator=_DISCRIMINATOR,
)
_TARGET_TRANSFORM = binary_iq_probability_transform(
    "target-binary-iq-probability",
    iq_shots="target_iq_shots",
    probability_0="target_probability_0",
    probability_1="target_probability_1",
    discriminator=_DISCRIMINATOR,
)

CZ_PHASE_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.reference.cz_phase.capture")
    .product(
        "control_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(CZ_PHASE_SHOTS),),
    )
    .product(
        "target_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(CZ_PHASE_SHOTS),),
    )
    .product(
        "control_probability_0",
        "control_probability_1",
        "target_probability_0",
        "target_probability_1",
        unit="ratio",
    )
    .measurement_transforms(_CONTROL_TRANSFORM, _TARGET_TRANSFORM)
    .build()
)

_TEMPLATE_CAPTURE = CZ_PHASE_CAPTURE_MODULE.instantiate("capture")
_CZ_EXECUTION = quantum.domain_execution(
    _CZ_DOMAIN_PROGRAM,
    inputs={
        CZ_AMPLITUDE_INPUT: CZ_AMPLITUDE,
        CONTROL_STATE_INPUT: CONTROL_STATE,
        ANALYZER_PHASE_INPUT: ANALYZER_PHASE,
    },
    results={
        _CONTROL_RESULT: _TEMPLATE_CAPTURE.products.control_iq_shots,
        _TARGET_RESULT: _TEMPLATE_CAPTURE.products.target_iq_shots,
    },
)
CZ_PHASE_TEMPLATE = (
    sc.module("quantum_lab_demo.reference.cz_phase.root")
    .use(_TEMPLATE_CAPTURE)
    .template(
        CZ_PHASE_TEMPLATE_ID,
        kind=CZ_PHASE_EXPERIMENT_ID,
    )
    .domain(_CZ_EXECUTION)
    .experiment_id(CZ_PHASE_EXPERIMENT_ID)
    .scan(
        sc.cartesian(
            sc.axis(CZ_AMPLITUDE, DEFAULT_CZ_AMPLITUDES),
            sc.axis(CONTROL_STATE, DEFAULT_CONTROL_STATES),
            sc.axis(ANALYZER_PHASE, DEFAULT_ANALYZER_PHASES),
        )
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.control_probability_1,
        record_id="control_probability_1",
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.target_probability_1,
        record_id="target_probability_1",
    )
    .label("CZ conditional-phase Ramsey")
    .description(
        "Resolve accepted single-qubit gates and one explicit coupler-flux CZ "
        "candidate inside the same typed Program."
    )
)


class CzPhaseDomainExecutionAdapter:
    """Bind authored two-qubit programs to the fake list-mode laboratory."""

    def __init__(self, *, target: FakeListTarget | None = None) -> None:
        selected = default_fake_list_target() if target is None else target
        self.target = selected
        self._preparations: list[PreparedCzPhaseReference] = []

    @property
    def adapter_id(self) -> str:
        return CZ_PHASE_ADAPTER_ID

    @property
    def preparations(self) -> tuple[PreparedCzPhaseReference, ...]:
        return tuple(self._preparations)

    @property
    def physical_execution_count(self) -> int:
        return sum(
            reference.runtime.physical_execution_count
            for reference in self._preparations
        )

    def select(self, view: DomainBatchView) -> DomainExecutionOffer | None:
        execution = _execution_or_none(view)
        if execution is None:
            return None
        return DomainExecutionOffer(
            max_points_per_batch=self.target.max_list_entries,
        )

    def prepare(self, context: DomainBatchContext) -> PreparedDomainExecution:
        execution = context.execution
        execution_points = tuple(execution.points)
        if tuple(point.ref for point in execution_points) != context.points:
            msg = "CZ phase execution points do not match the batch context"
            raise ValueError(msg)
        control_result, target_result = _validated_result_contracts(execution)
        preparation = context.new_preparation()
        reference = prepare_cz_phase_reference(
            preparation,
            _product_binding(execution),
            control_slot_id=control_result.acquisition_slot_id,
            target_slot_id=target_result.acquisition_slot_id,
            declaration=_program_body(execution),
            amplitudes=tuple(
                _decode_amplitude(point.input("coupler_amplitude"))
                for point in execution_points
            ),
            control_states=tuple(
                _decode_control_state(point.input("control_state"))
                for point in execution_points
            ),
            analyzer_phases=tuple(
                _decode_phase(point.input("analyzer_phase"))
                for point in execution_points
            ),
            shots=CZ_PHASE_SHOTS,
            target=self.target,
            invocation_id=f"cz-conditional-phase.batch-{context.batch_ordinal}",
        )
        self._preparations.append(reference)
        return preparation.build(
            measurements=reference.measurements,
            invocation=reference.invocation,
            runtime=reference.runtime,
            realize=lambda fetched: _realize(reference, fetched),
        )


def _execution_or_none(view: DomainBatchView) -> DomainExecutionView | None:
    selected = view.matching_execution(
        dialect_id=quantum.QUANTUM_PROGRAM_DIALECT_ID,
        dialect_version=quantum.QUANTUM_PROGRAM_DIALECT_VERSION,
    )
    if selected is None or not (
        isinstance(selected.program.body, quantum.Program)
        and selected.program.body.id == _CZ_PROGRAM.id
    ):
        return None
    _validated_result_contracts(selected)
    return selected


def _program_body(execution: DomainExecutionView) -> quantum.Program:
    body = execution.program.body
    if not isinstance(body, quantum.Program):
        msg = "CZ phase domain program body must be a Program"
        raise TypeError(msg)
    return body


def _product_binding(execution: DomainExecutionView) -> CzPhaseProductBinding:
    [control_transform, target_transform] = execution.measurement_transforms
    return CzPhaseProductBinding(
        control_iq_shots=execution.result("control_iq_shots").product_uses,
        target_iq_shots=execution.result("target_iq_shots").product_uses,
        control_transform=control_transform,
        target_transform=target_transform,
    )


def _validated_result_contracts(
    execution: DomainExecutionView,
) -> tuple[quantum.MeasurementResult, quantum.MeasurementResult]:
    body = _program_body(execution)
    control = execution.result("control_iq_shots").contract
    target = execution.result("target_iq_shots").contract
    if (
        not isinstance(control, quantum.MeasurementResult)
        or control.id != "control_iq_shots"
        or not any(result is control for result in body.results)
        or not isinstance(target, quantum.MeasurementResult)
        or target.id != "target_iq_shots"
        or not any(result is target for result in body.results)
    ):
        msg = "CZ phase IQ results must bind their authored result handles"
        raise ValueError(msg)
    if len(execution.measurement_transforms) != 2:
        msg = "CZ phase execution requires exactly two measurement transforms"
        raise ValueError(msg)
    implementation = binary_iq_probability_host_implementation()
    for transform in execution.measurement_transforms:
        implementation.validate_transform(transform)
    return control, target


def _decode_amplitude(value: object) -> Quantity:
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


def _decode_phase(value: object) -> Quantity:
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


def _decode_control_state(value: object) -> int:
    if type(value) is not int or value not in (0, 1):
        msg = "CZ control states must be 0 or 1"
        raise ValueError(msg)
    return value


def _realize(
    reference: PreparedCzPhaseReference,
    fetched: CorrelatedDomainFetch[FakeListRun],
):
    return realize_fetched_fake_measurements(
        reference.realization,
        fetched,
    ).result_values


__all__ = [
    "ANALYZER_PHASE",
    "CONTROL_STATE",
    "CZ_AMPLITUDE",
    "CZ_PHASE_ADAPTER_ID",
    "CZ_PHASE_CAPTURE_MODULE",
    "CZ_PHASE_EXPERIMENT_ID",
    "CZ_PHASE_SHOTS",
    "CZ_PHASE_TEMPLATE",
    "CZ_PHASE_TEMPLATE_ID",
    "DEFAULT_ANALYZER_PHASES",
    "DEFAULT_CONTROL_STATES",
    "DEFAULT_CZ_AMPLITUDES",
    "CzPhaseDomainExecutionAdapter",
]
