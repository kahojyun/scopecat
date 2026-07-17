"""Canonical execution placement for the optional typed domain execution.

This module is the sole owner of the rule that a domain adapter lane may claim
the execution and measurement-transform closure fed exactly by its
product-use slots. SDK projection and backend preparation consume the frozen
result instead of reconstructing ownership from projected object identity.
"""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.typed.program import TypedMeasurementTransform, TypedProgram
from scopecat.kernel.product_identity import ProductUseId
from scopecat.planning.coverage import (
    ExecutionCoverage,
    ExecutionTask,
    product_execution_coverage,
)


@dataclass(frozen=True, slots=True)
class DomainExecutionSlice:
    """The exact transform and product tasks hosted with domain execution."""

    transforms: tuple[TypedMeasurementTransform, ...]
    direct_product_use_ids: tuple[ProductUseId, ...]
    derived_product_use_ids: tuple[ProductUseId, ...]
    product_use_ids: tuple[ProductUseId, ...]
    coverage: ExecutionCoverage


def domain_execution_slice(
    program: TypedProgram,
) -> DomainExecutionSlice | None:
    """Derive the optional domain lane's exact execution slice."""

    execution = program.domain_execution
    if execution is None:
        return None
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
    products = product_execution_coverage(product_use_ids)
    coverage = ExecutionCoverage(
        (
            ExecutionTask("domain_execution", "domain"),
            *(
                ExecutionTask(
                    "measurement_transform",
                    transform.id.qualified_name,
                )
                for transform in transforms
            ),
            *products.tasks,
        )
    )
    return DomainExecutionSlice(
        transforms=transforms,
        direct_product_use_ids=direct_product_use_ids,
        derived_product_use_ids=derived_product_use_ids,
        product_use_ids=product_use_ids,
        coverage=coverage,
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
