"""Public authoring and Workspace adapter for the fake X-count reference."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import scopecat as sc
from scopecat.domain_execution import (
    PreparedDomainExecution,
    erase_prepared_domain_execution,
)
from scopecat.domain_invocation import (
    LinkedPlan,
    ProductId,
    ProductUseId,
    materialize_linked_points,
)
from scopecat.domain_runtime import CorrelatedDomainFetch

from quantum_lab_demo.reference_experiments.fake_x_count import (
    FakeXCountProductBinding,
    PreparedFakeXCountReference,
    prepare_fake_x_count_reference,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    realize_fetched_fake_measurements,
)

FAKE_X_COUNT_ADAPTER_ID = "quantum-lab-demo.fake-x-count.v1"
FAKE_X_COUNT_TEMPLATE_ID = "quantum_lab_demo.reference.fake_x_count"
FAKE_X_COUNT_EXPERIMENT_ID = "fake-x-count"
FAKE_X_COUNT_SHOTS = 32
DEFAULT_X_COUNTS = (0, 1, 2, 4)

X_COUNT = sc.point(
    "x_count",
    sc.ScalarType(sc.IntType(minimum=0)),
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
    .build()
)

_TEMPLATE_CAPTURE = FAKE_X_COUNT_CAPTURE_MODULE.instantiate("capture")
_IQ_SHOTS_PRODUCT_ID = _TEMPLATE_CAPTURE.products.integrated_iq_shots.product_id
_PROBABILITY_0_PRODUCT_ID = _TEMPLATE_CAPTURE.products.probability_0.product_id
_PROBABILITY_1_PRODUCT_ID = _TEMPLATE_CAPTURE.products.probability_1.product_id
FAKE_X_COUNT_TEMPLATE = (
    sc.module("quantum_lab_demo.reference.fake_x_count.root")
    .use(_TEMPLATE_CAPTURE)
    .template(
        FAKE_X_COUNT_TEMPLATE_ID,
        kind=FAKE_X_COUNT_EXPERIMENT_ID,
    )
    .experiment_id(FAKE_X_COUNT_EXPERIMENT_ID)
    .scan(X_COUNT, DEFAULT_X_COUNTS)
    .record_product(
        _TEMPLATE_CAPTURE.products.integrated_iq_shots,
        record_id="integrated_iq_shots",
    )
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

    def __init__(self) -> None:
        self.runtime = FakeListDomainRuntime()

    @property
    def adapter_id(self) -> str:
        return FAKE_X_COUNT_ADAPTER_ID

    def prepare(self, linked: LinkedPlan) -> PreparedDomainExecution:
        linked_points = materialize_linked_points(linked)
        products = _product_binding(linked)
        reference = prepare_fake_x_count_reference(
            linked_points,
            products,
            x_count_column="x_count",
            shots=FAKE_X_COUNT_SHOTS,
        )
        return erase_prepared_domain_execution(
            adapter_id=self.adapter_id,
            semantic_operation_id=FAKE_X_COUNT_EXPERIMENT_ID,
            linked_points=linked_points,
            invocation=reference.invocation,
            runtime=self.runtime,
            realize=lambda fetched: _realize(reference, fetched),
            source_fragment=reference.domain_fragment,
            projection=reference.projection,
            transforms=reference.transform_plan,
        )


def fake_x_count_scratch_experiment(
    lab: sc.Workspace,
    *,
    x_counts: Sequence[int] = DEFAULT_X_COUNTS,
) -> sc.Experiment:
    """Build the same reference semantics through the scratch Experiment UX."""

    capture = FAKE_X_COUNT_CAPTURE_MODULE.instantiate("capture")
    return (
        lab.experiment("fake X-count scratch")
        .use(capture)
        .scan(X_COUNT, tuple(x_counts))
        .record_product(
            capture.products.integrated_iq_shots,
            record_id="integrated_iq_shots",
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


def _product_binding(linked: LinkedPlan) -> FakeXCountProductBinding:
    uses: dict[ProductId, list[ProductUseId]] = {}
    for use in linked.product_uses:
        uses.setdefault(use.product_id, []).append(use.id)

    def require_one(product_id: ProductId) -> ProductUseId:
        selected = uses.get(product_id, [])
        if len(selected) != 1:
            msg = (
                "fake X-count requires exactly one use of module-owned product "
                f"{product_id.qualified_name!r}, "
                f"got {len(selected)}"
            )
            raise ValueError(msg)
        return selected[0]

    return FakeXCountProductBinding(
        iq_shots=require_one(_IQ_SHOTS_PRODUCT_ID),
        probability_0=require_one(_PROBABILITY_0_PRODUCT_ID),
        probability_1=require_one(_PROBABILITY_1_PRODUCT_ID),
    )


def _realize(
    reference: PreparedFakeXCountReference,
    fetched: CorrelatedDomainFetch[object],
):
    typed = cast("CorrelatedDomainFetch[FakeListRun]", fetched)
    return realize_fetched_fake_measurements(reference.invocation, typed).output_values


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
    "fake_x_count_scratch_experiment",
]
