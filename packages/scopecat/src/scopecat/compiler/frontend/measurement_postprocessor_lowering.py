"""Demand-close authored measurement postprocessors into bound product edges."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.compiler.bound_facts import (
    BoundMeasurementPostprocessor,
    BoundMeasurementPostprocessorOutput,
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
    """Live bound postprocessors plus the source uses they introduce."""

    postprocessors: tuple[BoundMeasurementPostprocessor, ...]
    input_product_uses: tuple[ProductUse, ...]


def lower_measurement_postprocessor_graph(
    program: VerifiedLogicalProgram,
    record_product_uses: Sequence[ProductUse],
) -> LoweredMeasurementPostprocessorGraph:
    """Retain only record-reachable postprocessors and mint exact input uses.

    The single input is a real product consumer. Input uses are minted only
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
        pending.append(producer.input)
    live = tuple(
        postprocessor for postprocessor in declarations if postprocessor.id in live_ids
    )
    input_uses = tuple(
        ProductUse(
            product_id=postprocessor.input,
            id=_postprocessor_input_use_id(postprocessor.id),
        )
        for postprocessor in live
    )
    all_uses = (*tuple(record_product_uses), *input_uses)
    uses_by_product: dict[ProductId, list[ProductUseId]] = {}
    for use in all_uses:
        uses_by_product.setdefault(use.product_id, []).append(use.id)

    bound: list[BoundMeasurementPostprocessor] = []
    for postprocessor, input_use in zip(live, input_uses, strict=True):
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
                input_product_id=postprocessor.input,
                input_product_use_id=input_use.id,
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
) -> ProductUseId:
    return ProductUseId(
        f"scopecat.measurement-postprocessor/{postprocessor_id.qualified_name}/input"
    )
