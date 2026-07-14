"""Demand-close authored measurement transforms into typed product edges."""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import quote

from scopecat.compiler.semantic.model import (
    MeasurementTransformId,
    SemanticMeasurementTransform,
)
from scopecat.compiler.semantic.verification import VerifiedSemanticGraph
from scopecat.compiler.typed.products import MeasurementTransformProductProducer
from scopecat.compiler.typed.program import (
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
)
from scopecat.kernel.product_identity import (
    ProductId,
    ProductProducerId,
    ProductUse,
    ProductUseId,
)


@dataclass(frozen=True, slots=True)
class LoweredMeasurementTransformGraph:
    """Live typed transforms plus the consumer uses they introduce."""

    transforms: tuple[TypedMeasurementTransform, ...]
    producers: tuple[MeasurementTransformProductProducer, ...]
    input_product_uses: tuple[ProductUse, ...]


def lower_semantic_measurement_transform_graph(
    graph: VerifiedSemanticGraph,
    record_product_uses: Sequence[ProductUse],
) -> LoweredMeasurementTransformGraph:
    """Retain only record-reachable transforms and mint exact input uses.

    A transform input is a real product consumer even when its intermediate is
    not itself recorded.  Input uses are minted only after reverse liveness so
    an unused authored transform cannot cause a target acquisition.
    """

    declarations = tuple(graph.graph.measurement_transforms)
    output_owner = {
        product_id: transform
        for transform in declarations
        for _role, product_id in transform.outputs
    }
    live_ids = _live_transform_ids(
        tuple(record_product_uses),
        output_owner=output_owner,
    )
    live = _canonical_live_transforms(declarations, live_ids, output_owner)
    input_uses = tuple(
        ProductUse(
            product_id=product_id,
            id=_transform_input_use_id(transform.id, role),
        )
        for transform in live
        for role, product_id in transform.inputs
    )
    all_uses = (*tuple(record_product_uses), *input_uses)
    uses_by_product: dict[ProductId, list[ProductUseId]] = {}
    for use in all_uses:
        uses_by_product.setdefault(use.product_id, []).append(use.id)

    typed: list[TypedMeasurementTransform] = []
    producers: list[MeasurementTransformProductProducer] = []
    input_use_index = 0
    for transform in live:
        inputs: list[TypedMeasurementTransformInput] = []
        for role, product_id in transform.inputs:
            use = input_uses[input_use_index]
            input_use_index += 1
            inputs.append(
                TypedMeasurementTransformInput(
                    id=role,
                    product_id=product_id,
                    product_use_id=use.id,
                )
            )
        outputs: list[TypedMeasurementTransformOutput] = []
        for role, product_id in transform.outputs:
            producer_id = ProductProducerId(product_id.symbol)
            outputs.append(
                TypedMeasurementTransformOutput(
                    id=role,
                    product_id=product_id,
                    producer_id=producer_id,
                    product_use_ids=tuple(uses_by_product.get(product_id, ())),
                )
            )
            producers.append(
                MeasurementTransformProductProducer(
                    id=producer_id,
                    product_id=product_id,
                    transform_id=transform.id,
                    output_id=role,
                )
            )
        typed.append(
            TypedMeasurementTransform(
                id=transform.id,
                semantic=transform.semantic,
                rate=transform.rate,
                inputs=tuple(inputs),
                outputs=tuple(outputs),
            )
        )
    return LoweredMeasurementTransformGraph(
        transforms=tuple(typed),
        producers=tuple(producers),
        input_product_uses=input_uses,
    )


def authored_measurement_transform_output_product_ids(
    graph: VerifiedSemanticGraph,
) -> frozenset[ProductId]:
    """Return every authored transform output, including dead declarations."""

    return frozenset(
        product_id
        for transform in graph.graph.measurement_transforms
        for _role, product_id in transform.outputs
    )


def _live_transform_ids(
    record_uses: tuple[ProductUse, ...],
    *,
    output_owner: dict[ProductId, SemanticMeasurementTransform],
) -> frozenset[MeasurementTransformId]:
    pending = [use.product_id for use in reversed(record_uses)]
    live: set[MeasurementTransformId] = set()
    while pending:
        demanded_product = pending.pop()
        transform = output_owner.get(demanded_product)
        if transform is None or transform.id in live:
            continue
        live.add(transform.id)
        pending.extend(product_id for _role, product_id in reversed(transform.inputs))
    return frozenset(live)


def _canonical_live_transforms(
    declarations: tuple[SemanticMeasurementTransform, ...],
    live_ids: frozenset[MeasurementTransformId],
    output_owner: dict[ProductId, SemanticMeasurementTransform],
) -> tuple[SemanticMeasurementTransform, ...]:
    by_id = {
        transform.id: transform
        for transform in declarations
        if transform.id in live_ids
    }
    dependencies: dict[MeasurementTransformId, set[MeasurementTransformId]] = {
        transform_id: set() for transform_id in by_id
    }
    consumers: dict[MeasurementTransformId, set[MeasurementTransformId]] = {
        transform_id: set() for transform_id in by_id
    }
    for transform in by_id.values():
        for _role, product_id in transform.inputs:
            owner = output_owner.get(product_id)
            if owner is None or owner.id not in by_id:
                continue
            dependencies[transform.id].add(owner.id)
            consumers[owner.id].add(transform.id)

    ready = [
        (transform_id.qualified_name, transform_id)
        for transform_id, required in dependencies.items()
        if not required
    ]
    heapq.heapify(ready)
    ordered: list[SemanticMeasurementTransform] = []
    while ready:
        _name, transform_id = heapq.heappop(ready)
        ordered.append(by_id[transform_id])
        for consumer_id in consumers[transform_id]:
            dependencies[consumer_id].discard(transform_id)
            if not dependencies[consumer_id]:
                heapq.heappush(
                    ready,
                    (consumer_id.qualified_name, consumer_id),
                )
    if len(ordered) != len(by_id):
        raise AssertionError("verified semantic measurement transform graph is cyclic")
    return tuple(ordered)


def _transform_input_use_id(
    transform_id: MeasurementTransformId,
    role: str,
) -> ProductUseId:
    encoded_role = quote(role, safe="-._~[]")
    return ProductUseId(
        "scopecat.measurement-transform/"
        f"{transform_id.qualified_name}/inputs/{encoded_role}"
    )


__all__ = [
    "LoweredMeasurementTransformGraph",
    "authored_measurement_transform_output_product_ids",
    "lower_semantic_measurement_transform_graph",
]
