"""Derive the typed result-transform closure of a domain call."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedMeasurementTransform,
    core_domain_executions,
)
from scopecat.kernel.product_identity import ProductUseId


@dataclass(frozen=True, slots=True)
class DomainExecutionSlice:
    """The exact transform and product dataflow rooted at a domain call."""

    transforms: tuple[TypedMeasurementTransform, ...]
    direct_product_use_ids: tuple[ProductUseId, ...]
    derived_product_use_ids: tuple[ProductUseId, ...]
    product_use_ids: tuple[ProductUseId, ...]


def domain_execution_slice(
    program: CoreProgram,
    execution_id: str,
) -> DomainExecutionSlice:
    """Derive one domain effect's exact result-transform closure."""

    execution = next(
        item for item in core_domain_executions(program) if item.id == execution_id
    )
    ordered_use_ids = tuple(use.id for use in program.product_uses)
    direct_ids = {
        use_id for result in execution.results for use_id in result.product_use_ids
    }
    transforms = _typed_transform_closure(
        program.measurement_transforms,
        frozenset(direct_ids),
    )
    derived_ids = {
        use_id
        for transform in transforms
        for output in transform.outputs
        for use_id in output.product_use_ids
    }
    owned_ids = direct_ids | derived_ids
    direct_product_use_ids = tuple(
        use_id for use_id in ordered_use_ids if use_id in direct_ids
    )
    derived_product_use_ids = tuple(
        use_id for use_id in ordered_use_ids if use_id in derived_ids
    )
    product_use_ids = tuple(use_id for use_id in ordered_use_ids if use_id in owned_ids)
    return DomainExecutionSlice(
        transforms=transforms,
        direct_product_use_ids=direct_product_use_ids,
        derived_product_use_ids=derived_product_use_ids,
        product_use_ids=product_use_ids,
    )


def _typed_transform_closure(
    transforms: tuple[TypedMeasurementTransform, ...],
    source_product_use_ids: frozenset[ProductUseId],
) -> tuple[TypedMeasurementTransform, ...]:
    """Return the canonical closure fed by exact product-use occurrences."""

    available = set(source_product_use_ids)
    selected: list[TypedMeasurementTransform] = []
    remaining = list(transforms)
    while remaining:
        progressed = False
        next_remaining: list[TypedMeasurementTransform] = []
        for transform in remaining:
            if transform.inputs and all(
                port.product_use_id in available for port in transform.inputs
            ):
                selected.append(transform)
                available.update(
                    use_id
                    for output in transform.outputs
                    for use_id in output.product_use_ids
                )
                progressed = True
            else:
                next_remaining.append(transform)
        if not progressed:
            break
        remaining = next_remaining
    return tuple(selected)
