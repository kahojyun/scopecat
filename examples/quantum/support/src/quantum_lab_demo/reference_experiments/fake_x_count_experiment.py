"""Public authoring and Workspace adapter for the fake X-count reference."""

from __future__ import annotations

from collections.abc import Sequence

import scopecat as sc
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
    GateParameterKind,
    IqCentroid,
    binary_iq_probability_host_implementation,
    binary_iq_probability_transform,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.reference_experiments.fake_x_count import (
    FakeXCountProductBinding,
    PreparedFakeXCountReference,
    prepare_fake_x_count_reference,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    FakeListTarget,
    default_fake_list_target,
    realize_fetched_fake_measurements,
)

FAKE_X_COUNT_ADAPTER_ID = "quantum-lab-demo.fake-x-count.v1"
FAKE_X_COUNT_TEMPLATE_ID = "quantum_lab_demo.reference.fake_x_count"
FAKE_X_COUNT_EXPERIMENT_ID = "fake-x-count"
FAKE_X_COUNT_SHOTS = 32
DEFAULT_X_COUNTS = (0, 1, 2, 4)


def _decode_x_count(value: object) -> int:
    if type(value) is not int or value < 0:
        msg = "fake X-count coordinates must be non-negative integers"
        raise ValueError(msg)
    return value


X_COUNT = sc.point(
    "x_count",
    sc.ScalarType(sc.IntType(minimum=0)),
)

_Q0 = quantum.qubit("q0")
_X_COUNT_INPUT = quantum.scalar_input("x_count", GateParameterKind.INTEGER)
_X_GATE = quantum.single_qubit_gate("x")
_READOUT = quantum.measure(_Q0, result="iq_shots")
_X_COUNT_PROGRAM = quantum.program(
    "fake-x-count",
    quantum.sequence(
        quantum.repeat(_X_GATE(_Q0), _X_COUNT_INPUT),
        _READOUT,
    ),
)
_X_COUNT_DOMAIN_PROGRAM = quantum.domain_program(_X_COUNT_PROGRAM)
_X_COUNT_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)
_X_COUNT_TRANSFORM = binary_iq_probability_transform(
    "binary-iq-probability",
    iq_shots="integrated_iq_shots",
    probability_0="probability_0",
    probability_1="probability_1",
    discriminator=_X_COUNT_DISCRIMINATOR,
)

FAKE_X_COUNT_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.reference.fake_x_count.capture")
    .product(
        "integrated_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(FAKE_X_COUNT_SHOTS),),
    )
    .product("probability_0", "probability_1", unit="ratio")
    .measurement_transforms(_X_COUNT_TRANSFORM)
    .build()
)

_TEMPLATE_CAPTURE = FAKE_X_COUNT_CAPTURE_MODULE.instantiate("capture")


def fake_x_count_domain_execution(iq_shots: sc.ProductRef) -> sc.DomainExecution:
    """Bind the reference quantum program to one composed capture product."""

    return quantum.domain_execution(
        _X_COUNT_DOMAIN_PROGRAM,
        inputs={_X_COUNT_INPUT: X_COUNT},
        results={_READOUT.result: iq_shots},
    )


_X_COUNT_EXECUTION = fake_x_count_domain_execution(
    _TEMPLATE_CAPTURE.products.integrated_iq_shots
)
FAKE_X_COUNT_TEMPLATE = (
    sc.module("quantum_lab_demo.reference.fake_x_count.root")
    .use(_TEMPLATE_CAPTURE)
    .template(
        FAKE_X_COUNT_TEMPLATE_ID,
        kind=FAKE_X_COUNT_EXPERIMENT_ID,
    )
    .domain(_X_COUNT_EXECUTION)
    .experiment_id(FAKE_X_COUNT_EXPERIMENT_ID)
    .scan(X_COUNT, DEFAULT_X_COUNTS)
    .record_product(
        _TEMPLATE_CAPTURE.products.probability_0,
        record_id="probability_0",
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.probability_1,
        record_id="probability_1",
    )
    .label("Fake AWG X-count scan")
    .description(
        "Compile calibrated q0 X repetitions into one fake AWG list and "
        "discriminate digitizer IQ."
    )
)


class FakeXCountDomainExecutionAdapter:
    """Lab-owned target selection for the fake list-mode AWG and digitizer."""

    def __init__(self, *, target: FakeListTarget | None = None) -> None:
        self.target = default_fake_list_target() if target is None else target
        self.runtime = FakeListDomainRuntime()

    @property
    def adapter_id(self) -> str:
        return FAKE_X_COUNT_ADAPTER_ID

    def select(
        self,
        view: DomainBatchView,
    ) -> DomainExecutionOffer | None:
        execution = _execution_or_none(view)
        if execution is None:
            return None
        return DomainExecutionOffer(
            max_points_per_batch=self.target.max_list_entries,
        )

    def prepare(self, context: DomainBatchContext) -> PreparedDomainExecution:
        execution = context.execution
        preparation = context.new_preparation()
        iq_result = _validated_result_contracts(execution)
        products = _product_binding(execution)
        x_counts = tuple(
            _decode_x_count(value) for value in execution.input_values("x_count")
        )
        body = execution.program.body
        if not isinstance(body, quantum.Program):
            msg = "fake X-count domain program body must be a quantum Program"
            raise TypeError(msg)
        reference = prepare_fake_x_count_reference(
            preparation,
            products,
            acquisition_slot_id=iq_result.acquisition_slot_id,
            programs=tuple(
                quantum.bind(body, {"x_count": x_count}).verified
                for x_count in x_counts
            ),
            x_counts=x_counts,
            shots=FAKE_X_COUNT_SHOTS,
            target=self.target,
            invocation_id=f"fake-x-count.batch-{context.batch_ordinal}",
        )
        return preparation.build(
            measurements=reference.measurements,
            invocation=reference.invocation,
            runtime=self.runtime,
            realize=lambda fetched: _realize(reference, fetched),
        )


def fake_x_count_scratch_experiment(
    lab: sc.Workspace,
    *,
    x_counts: Sequence[int] = DEFAULT_X_COUNTS,
) -> sc.Experiment:
    """Build the same reference semantics through the scratch Experiment UX."""

    capture = FAKE_X_COUNT_CAPTURE_MODULE.instantiate("capture")
    execution = fake_x_count_domain_execution(capture.products.integrated_iq_shots)
    return (
        lab.experiment("fake X-count scratch")
        .use(capture)
        .domain(execution)
        .scan(X_COUNT, tuple(x_counts))
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
        and selected.program.body.id == _X_COUNT_PROGRAM.id
    ):
        return None
    _validated_result_contracts(selected)
    return selected


def _product_binding(view: DomainExecutionView) -> FakeXCountProductBinding:
    [transform] = view.measurement_transforms
    return FakeXCountProductBinding(
        iq_shots=view.result("iq_shots").product_uses,
        transform=transform,
    )


def _validated_result_contracts(
    execution: DomainExecutionView,
) -> quantum.MeasurementResult:
    body = execution.program.body
    if not isinstance(body, quantum.Program):
        msg = "fake X-count domain program body must be a quantum Program"
        raise TypeError(msg)
    iq_result = execution.result("iq_shots").contract
    if (
        not isinstance(iq_result, quantum.MeasurementResult)
        or iq_result.id != "iq_shots"
        or not any(result is iq_result for result in body.results)
    ):
        msg = "fake X-count IQ result must bind its authored MeasurementResult handle"
        raise ValueError(msg)
    if len(execution.measurement_transforms) != 1:
        msg = "fake X-count execution requires one authored measurement transform"
        raise ValueError(msg)
    binary_iq_probability_host_implementation().validate_transform(
        execution.measurement_transforms[0]
    )
    return iq_result


def _realize(
    reference: PreparedFakeXCountReference,
    fetched: CorrelatedDomainFetch[FakeListRun],
):
    return realize_fetched_fake_measurements(
        reference.realization,
        fetched,
    ).result_values


__all__ = [
    "DEFAULT_X_COUNTS",
    "FAKE_X_COUNT_ADAPTER_ID",
    "FAKE_X_COUNT_CAPTURE_MODULE",
    "FAKE_X_COUNT_EXPERIMENT_ID",
    "FAKE_X_COUNT_SHOTS",
    "FAKE_X_COUNT_TEMPLATE",
    "FAKE_X_COUNT_TEMPLATE_ID",
    "X_COUNT",
    "FakeXCountDomainExecutionAdapter",
    "fake_x_count_domain_execution",
    "fake_x_count_scratch_experiment",
]
