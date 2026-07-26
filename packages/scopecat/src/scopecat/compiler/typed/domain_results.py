"""Derive the typed result closure rooted at one domain execution."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedMeasurementTransform,
    core_domain_executions,
)
from scopecat.kernel.product_identity import ProductUseId


@dataclass(frozen=True, slots=True)
class DomainResultClosure:
    """Stable direct and host-derived result ownership for one execution."""

    transforms: tuple[TypedMeasurementTransform, ...]
    product_use_ids: tuple[ProductUseId, ...]


def domain_result_closure(
    program: CoreProgram,
    execution_id: str,
) -> DomainResultClosure:
    """Follow exact product-use edges from one domain execution's results."""

    execution = next(
        item for item in core_domain_executions(program) if item.id == execution_id
    )
    ordered_use_ids = tuple(use.id for use in program.product_uses)
    direct_ids = {
        use_id for result in execution.results for use_id in result.product_use_ids
    }
    available = set(direct_ids)
    selected: list[TypedMeasurementTransform] = []
    # Semantic verification topologically orders transforms before typed lowering.
    for transform in program.measurement_transforms:
        if transform.inputs and all(
            port.product_use_id in available for port in transform.inputs
        ):
            selected.append(transform)
            available.update(
                use_id
                for output in transform.outputs
                for use_id in output.product_use_ids
            )
    return DomainResultClosure(
        transforms=tuple(selected),
        product_use_ids=tuple(
            use_id for use_id in ordered_use_ids if use_id in available
        ),
    )
