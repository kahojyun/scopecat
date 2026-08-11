"""Demand-close authored measurement computes into bound product edges."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.compiler.bound_facts import (
    BoundMeasurementCompute,
    BoundMeasurementComputeInput,
    BoundMeasurementComputeOutput,
    BoundMeasurementComputeValueInput,
)
from scopecat.compiler.frontend.logical_verification import VerifiedLogicalProgram
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
)
from scopecat.program.logical import (
    MeasurementComputeId,
)


@dataclass(frozen=True, slots=True)
class LoweredMeasurementComputeGraph:
    """Live bound measurement computes plus the source uses they introduce."""

    computes: tuple[BoundMeasurementCompute, ...]
    input_product_uses: tuple[ProductUse, ...]


def lower_measurement_compute_graph(
    program: VerifiedLogicalProgram,
    record_product_uses: Sequence[ProductUse],
) -> LoweredMeasurementComputeGraph:
    """Retain only record-reachable computes and mint exact input uses.

    Inputs are real product consumers. Input uses are minted only
    after liveness so an unused declaration cannot cause an acquisition.
    """

    declarations = tuple(program.program.measurement_computes)
    demanded_product_ids = {use.product_id for use in record_product_uses}
    producer_by_output = {
        product_id: compute
        for compute in declarations
        for _role, product_id in compute.outputs
    }
    live_ids: set[MeasurementComputeId] = set()
    pending = list(demanded_product_ids)
    while pending:
        product_id = pending.pop()
        producer = producer_by_output.get(product_id)
        if producer is None or producer.id in live_ids:
            continue
        live_ids.add(producer.id)
        pending.extend(product_id for _name, product_id in producer.inputs)
    live = tuple(compute for compute in declarations if compute.id in live_ids)
    named_input_uses = tuple(
        (
            compute,
            tuple(
                (
                    name,
                    ProductUse(
                        product_id=product_id,
                        id=_compute_input_use_id(compute.id, name),
                    ),
                )
                for name, product_id in compute.inputs
            ),
        )
        for compute in live
    )
    input_uses = tuple(
        use for _compute, inputs in named_input_uses for _name, use in inputs
    )
    all_uses = (*tuple(record_product_uses), *input_uses)
    uses_by_product: dict[ProductId, list[ProductUseId]] = {}
    for use in all_uses:
        uses_by_product.setdefault(use.product_id, []).append(use.id)

    bound: list[BoundMeasurementCompute] = []
    for compute, inputs in named_input_uses:
        outputs: list[BoundMeasurementComputeOutput] = []
        for role, product_id in compute.outputs:
            outputs.append(
                BoundMeasurementComputeOutput(
                    id=role,
                    product_id=product_id,
                    product_use_ids=tuple(uses_by_product.get(product_id, ())),
                )
            )
        bound.append(
            BoundMeasurementCompute(
                id=compute.id,
                inputs=tuple(
                    BoundMeasurementComputeInput(
                        id=name,
                        product_id=use.product_id,
                        product_use_id=use.id,
                    )
                    for name, use in inputs
                ),
                value_inputs=tuple(
                    BoundMeasurementComputeValueInput(
                        id=name,
                        value_id=value_id,
                    )
                    for name, value_id in compute.value_inputs
                ),
                outputs=tuple(outputs),
                kernel=compute.kernel,
                implementation=compute.implementation,
                deterministic=compute.deterministic,
                captures=compute.captures,
            )
        )
    return LoweredMeasurementComputeGraph(
        computes=tuple(bound),
        input_product_uses=input_uses,
    )


def _compute_input_use_id(
    compute_id: MeasurementComputeId,
    input_id: str,
) -> ProductUseId:
    return ProductUseId(
        f"scopecat.measurement-compute/{compute_id.qualified_name}/inputs/{input_id}"
    )
