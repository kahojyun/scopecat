"""Public 2-D DRAG-beta authoring and Workspace execution adapter.

The experiment keeps one unified :class:`Program` declaration across the
whole scan.  Every logical point binds both its pulse-level DRAG coefficient
and its gate-level amplification count before the batch is compiled into one
fake list-mode target artifact.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

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

from quantum_lab_demo.reference_experiments.drag_beta_calibration import (
    AMPLIFICATION_INPUT,
    BETA_INPUT,
    DEFAULT_BASELINE_BETA,
    DragBetaProductBinding,
    PreparedDragBetaReference,
    drag_beta_calibration_program,
    prepare_drag_beta_reference,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    FakeListTarget,
    default_fake_list_target,
    realize_fetched_fake_measurements,
)

DRAG_BETA_ADAPTER_ID = "quantum-lab-demo.drag-beta.v1"
DRAG_BETA_TEMPLATE_ID = "quantum_lab_demo.reference.drag_beta"
DRAG_BETA_EXPERIMENT_ID = "drag-beta-calibration"
DRAG_BETA_SHOTS = 64
DRAG_BETA_PARAMETER_ID = "qubits"
DRAG_BETA_PARAMETER_COLUMN = "drag_beta"
DRAG_BETA_SPAN = Quantity(1.0, "ns")
DRAG_BETA_POINTS = 5
DEFAULT_BETAS = tuple(Quantity(value, "ns") for value in (0.0, 0.25, 0.5, 0.75, 1.0))
DEFAULT_AMPLIFICATIONS = (1, 2, 3)


def _decode_beta(value: object) -> Quantity:
    if not isinstance(value, Quantity):
        msg = "DRAG-beta coordinates must be time quantities"
        raise TypeError(msg)
    try:
        beta_ns = float(value.to("ns").value)
    except ValueError as error:
        msg = "DRAG-beta coordinates must be time quantities"
        raise ValueError(msg) from error
    if not math.isfinite(beta_ns):
        msg = "DRAG-beta coordinates must be finite"
        raise ValueError(msg)
    return Quantity(beta_ns, "ns")


def _decode_amplification(value: object) -> int:
    if type(value) is not int or value <= 0:
        msg = "DRAG-beta amplification coordinates must be positive integers"
        raise ValueError(msg)
    return value


_BETA_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
BETA = sc.point("beta", _BETA_VALUE_TYPE)
AMPLIFICATION = sc.point(
    "amplification",
    sc.ScalarType(sc.IntType(minimum=1)),
)

_DRAG_BETA_PROGRAM = drag_beta_calibration_program()
[_IQ_SHOTS_RESULT] = _DRAG_BETA_PROGRAM.results
_DRAG_BETA_DOMAIN_PROGRAM = quantum.domain_program(_DRAG_BETA_PROGRAM)
_DRAG_BETA_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)
_DRAG_BETA_TRANSFORM = binary_iq_probability_transform(
    "binary-iq-probability",
    iq_shots="integrated_iq_shots",
    probability_0="probability_0",
    probability_1="probability_1",
    discriminator=_DRAG_BETA_DISCRIMINATOR,
)

DRAG_BETA_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.reference.drag_beta.capture")
    .product(
        "integrated_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(DRAG_BETA_SHOTS),),
    )
    .product("probability_0", "probability_1", unit="ratio")
    .measurement_transforms(_DRAG_BETA_TRANSFORM)
    .build()
)

_TEMPLATE_CAPTURE = DRAG_BETA_CAPTURE_MODULE.instantiate("capture")
_DRAG_BETA_EXECUTION = quantum.domain_execution(
    _DRAG_BETA_DOMAIN_PROGRAM,
    inputs={
        BETA_INPUT: BETA,
        AMPLIFICATION_INPUT: AMPLIFICATION,
    },
    results={
        _IQ_SHOTS_RESULT: _TEMPLATE_CAPTURE.products.integrated_iq_shots,
    },
)
DRAG_BETA_TEMPLATE = (
    sc.module("quantum_lab_demo.reference.drag_beta.root")
    .use(_TEMPLATE_CAPTURE)
    .template(
        DRAG_BETA_TEMPLATE_ID,
        kind=DRAG_BETA_EXPERIMENT_ID,
    )
    .domain(_DRAG_BETA_EXECUTION)
    .experiment_id(DRAG_BETA_EXPERIMENT_ID)
    .scan(
        sc.cartesian(
            sc.axis(
                BETA,
                center=sc.parameter_lookup(
                    DRAG_BETA_PARAMETER_ID,
                    key={"qubit": "q0"},
                    column=DRAG_BETA_PARAMETER_COLUMN,
                    value_type=_BETA_VALUE_TYPE,
                ),
                span=DRAG_BETA_SPAN,
                points=DRAG_BETA_POINTS,
            ),
            sc.axis(AMPLIFICATION, DEFAULT_AMPLIFICATIONS),
        )
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.probability_0,
        record_id="probability_0",
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.probability_1,
        record_id="probability_1",
    )
    .label("DRAG beta rough calibration")
    .description(
        "Scan a pulse-level DRAG coefficient against a gate-level amplification "
        "count in one mixed quantum program."
    )
)


class DragBetaDomainExecutionAdapter:
    """Bind the authored mixed program to the fake list-mode laboratory."""

    def __init__(
        self,
        *,
        target: FakeListTarget | None = None,
        baseline_beta: Quantity = DEFAULT_BASELINE_BETA,
    ) -> None:
        selected_target = default_fake_list_target() if target is None else target
        self.target = selected_target
        self.baseline_beta = _decode_beta(baseline_beta)
        self._runtimes: list[FakeListDomainRuntime] = []

    @property
    def runtime(self) -> FakeListDomainRuntime:
        """Return the batch-local runtime after preparation."""

        if not self._runtimes:
            msg = "DRAG-beta runtime is available after adapter preparation"
            raise RuntimeError(msg)
        return self._runtimes[-1]

    @property
    def physical_execution_count(self) -> int:
        """Return physical executions across every prepared target batch."""

        return sum(runtime.physical_execution_count for runtime in self._runtimes)

    @property
    def adapter_id(self) -> str:
        return DRAG_BETA_ADAPTER_ID

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
            msg = "DRAG-beta execution points do not match the batch context"
            raise ValueError(msg)
        preparation = context.new_preparation()
        iq_result = _validated_result_contracts(execution)
        reference = prepare_drag_beta_reference(
            preparation,
            _product_binding(execution),
            result_slot_id=iq_result.acquisition_slot_id,
            declaration=_program_body(execution),
            betas=tuple(
                _decode_beta(point.input("beta")) for point in execution_points
            ),
            amplifications=tuple(
                _decode_amplification(point.input("amplification"))
                for point in execution_points
            ),
            baseline_beta=self.baseline_beta,
            shots=DRAG_BETA_SHOTS,
            target=self.target,
            invocation_id=f"drag-beta.batch-{context.batch_ordinal}",
        )
        self._runtimes.append(reference.runtime)
        return preparation.build(
            measurements=reference.measurements,
            invocation=reference.invocation,
            runtime=reference.runtime,
            realize=lambda fetched: _realize(reference, fetched),
        )


def drag_beta_scratch_experiment(
    lab: sc.Workspace,
    *,
    betas: Sequence[Quantity] = DEFAULT_BETAS,
    amplifications: Sequence[int] = DEFAULT_AMPLIFICATIONS,
) -> sc.Experiment:
    """Build the same 2-D semantics through the scratch Experiment UX."""

    capture = DRAG_BETA_CAPTURE_MODULE.instantiate("capture")
    execution = quantum.domain_execution(
        _DRAG_BETA_DOMAIN_PROGRAM,
        inputs={
            BETA_INPUT: BETA,
            AMPLIFICATION_INPUT: AMPLIFICATION,
        },
        results={
            _IQ_SHOTS_RESULT: capture.products.integrated_iq_shots,
        },
    )
    return (
        lab.experiment("DRAG beta calibration scratch")
        .use(capture)
        .domain(execution)
        .scan(
            sc.cartesian(
                sc.axis(BETA, tuple(betas)),
                sc.axis(AMPLIFICATION, tuple(amplifications)),
            )
        )
        .record_product(
            capture.products.probability_0,
            record_id="probability_0",
        )
        .record_product(
            capture.products.probability_1,
            record_id="probability_1",
        )
    )


def _execution_or_none(view: DomainBatchView) -> DomainExecutionView | None:
    selected = view.matching_execution(
        dialect_id=quantum.QUANTUM_PROGRAM_DIALECT_ID,
        dialect_version=quantum.QUANTUM_PROGRAM_DIALECT_VERSION,
    )
    if selected is None or not (
        isinstance(selected.program.body, quantum.Program)
        and selected.program.body.id == _DRAG_BETA_PROGRAM.id
    ):
        return None
    _validated_result_contracts(selected)
    return selected


def _program_body(execution: DomainExecutionView) -> quantum.Program:
    body = execution.program.body
    if not isinstance(body, quantum.Program):
        msg = "DRAG-beta domain program body must be a Program"
        raise TypeError(msg)
    return body


def _product_binding(view: DomainExecutionView) -> DragBetaProductBinding:
    [transform] = view.measurement_transforms
    return DragBetaProductBinding(
        iq_shots=view.result("iq_shots").product_uses,
        transform=transform,
    )


def _validated_result_contracts(
    execution: DomainExecutionView,
) -> quantum.MeasurementResult:
    body = _program_body(execution)
    iq_result = execution.result("iq_shots").contract
    if (
        not isinstance(iq_result, quantum.MeasurementResult)
        or iq_result.id != "iq_shots"
        or not any(result is iq_result for result in body.results)
    ):
        msg = "DRAG-beta IQ result must bind its authored result handle"
        raise ValueError(msg)
    if len(execution.measurement_transforms) != 1:
        msg = "DRAG-beta execution requires one authored measurement transform"
        raise ValueError(msg)
    binary_iq_probability_host_implementation().validate_transform(
        execution.measurement_transforms[0]
    )
    return iq_result


def _realize(
    reference: PreparedDragBetaReference,
    fetched: CorrelatedDomainFetch[FakeListRun],
):
    return realize_fetched_fake_measurements(
        reference.realization,
        fetched,
    ).result_values


__all__ = [
    "AMPLIFICATION",
    "BETA",
    "DEFAULT_AMPLIFICATIONS",
    "DEFAULT_BETAS",
    "DRAG_BETA_ADAPTER_ID",
    "DRAG_BETA_CAPTURE_MODULE",
    "DRAG_BETA_EXPERIMENT_ID",
    "DRAG_BETA_PARAMETER_COLUMN",
    "DRAG_BETA_PARAMETER_ID",
    "DRAG_BETA_POINTS",
    "DRAG_BETA_SHOTS",
    "DRAG_BETA_SPAN",
    "DRAG_BETA_TEMPLATE",
    "DRAG_BETA_TEMPLATE_ID",
    "DragBetaDomainExecutionAdapter",
    "drag_beta_scratch_experiment",
]
