"""Demand-close authored measurement computes into bound product edges."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.compiler.bound_facts import (
    BoundMeasurementPostprocessor,
    BoundMeasurementPostprocessorInput,
    BoundMeasurementPostprocessorOutput,
    BoundMeasurementPostprocessorValueInput,
)
from scopecat.compiler.frontend.logical_verification import VerifiedLogicalProgram
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
)
from scopecat.program.logical import (
    MeasurementPostprocessorId,
)


@dataclass(frozen=True, slots=True)
class LoweredMeasurementPostprocessorGraph:
    """Live bound measurement computes plus the source uses they introduce."""

    postprocessors: tuple[BoundMeasurementPostprocessor, ...]
    input_product_uses: tuple[ProductUse, ...]


def lower_measurement_postprocessor_graph(
    program: VerifiedLogicalProgram,
    record_product_uses: Sequence[ProductUse],
) -> LoweredMeasurementPostprocessorGraph:
    """Retain only record-reachable postprocessors and mint exact input uses.

    Inputs are real product consumers. Input uses are minted only
    after liveness so an unused declaration cannot cause an acquisition.
    """

    declarations = tuple(program.program.measurement_postprocessors)
    demanded_product_ids = {use.product_id for use in record_product_uses}
    producer_by_output = {
        product_id: postprocessor
        for postprocessor in declarations
        for _role, product_id in postprocessor.outputs
    }
    live_ids: set[MeasurementPostprocessorId] = set()
    pending = list(demanded_product_ids)
    while pending:
        product_id = pending.pop()
        producer = producer_by_output.get(product_id)
        if producer is None or producer.id in live_ids:
            continue
        live_ids.add(producer.id)
        pending.extend(product_id for _name, product_id in producer.inputs)
    live = tuple(
        postprocessor for postprocessor in declarations if postprocessor.id in live_ids
    )
    named_input_uses = tuple(
        (
            postprocessor,
            tuple(
                (
                    name,
                    ProductUse(
                        product_id=product_id,
                        id=_postprocessor_input_use_id(postprocessor.id, name),
                    ),
                )
                for name, product_id in postprocessor.inputs
            ),
        )
        for postprocessor in live
    )
    input_uses = tuple(
        use for _postprocessor, inputs in named_input_uses for _name, use in inputs
    )
    all_uses = (*tuple(record_product_uses), *input_uses)
    uses_by_product: dict[ProductId, list[ProductUseId]] = {}
    for use in all_uses:
        uses_by_product.setdefault(use.product_id, []).append(use.id)

    bound: list[BoundMeasurementPostprocessor] = []
    for postprocessor, inputs in named_input_uses:
        outputs: list[BoundMeasurementPostprocessorOutput] = []
        for role, product_id in postprocessor.outputs:
            outputs.append(
                BoundMeasurementPostprocessorOutput(
                    id=role,
                    product_id=product_id,
                    product_use_ids=tuple(uses_by_product.get(product_id, ())),
                )
            )
        bound.append(
            BoundMeasurementPostprocessor(
                id=postprocessor.id,
                inputs=tuple(
                    BoundMeasurementPostprocessorInput(
                        id=name,
                        product_id=use.product_id,
                        product_use_id=use.id,
                    )
                    for name, use in inputs
                ),
                value_inputs=tuple(
                    BoundMeasurementPostprocessorValueInput(
                        id=name,
                        value_id=value_id,
                    )
                    for name, value_id in postprocessor.value_inputs
                ),
                outputs=tuple(outputs),
                kernel=postprocessor.kernel,
            )
        )
    return LoweredMeasurementPostprocessorGraph(
        postprocessors=tuple(bound),
        input_product_uses=input_uses,
    )


def _postprocessor_input_use_id(
    postprocessor_id: MeasurementPostprocessorId,
    input_id: str,
) -> ProductUseId:
    return ProductUseId(
        "scopecat.measurement-compute/"
        f"{postprocessor_id.qualified_name}/inputs/{input_id}"
    )
