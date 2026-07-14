"""Canonical execution placement slices for typed domain calls.

This module is the sole owner of the rule that a domain adapter lane may claim
one call and the measurement-transform closure fed exactly by that call's
product-use slots. SDK projection and backend preparation consume the frozen
result instead of reconstructing ownership from projected object identity.
"""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.semantic.model import DomainCallId
from scopecat.compiler.typed.program import TypedMeasurementTransform, TypedProgram
from scopecat.kernel.product_identity import ProductUseId
from scopecat.planning.coverage import (
    ExecutionCoverage,
    ExecutionTask,
    product_execution_coverage,
)


@dataclass(frozen=True, slots=True)
class DomainCallExecutionSlice:
    """One call and the exact transform/product tasks hosted on its lane."""

    call_id: DomainCallId
    transforms: tuple[TypedMeasurementTransform, ...]
    direct_product_use_ids: tuple[ProductUseId, ...]
    derived_product_use_ids: tuple[ProductUseId, ...]
    product_use_ids: tuple[ProductUseId, ...]
    coverage: ExecutionCoverage


def domain_call_execution_slices(
    program: TypedProgram,
) -> tuple[DomainCallExecutionSlice, ...]:
    """Derive every currently placeable domain lane exactly once."""

    ordered_use_ids = tuple(use.id for use in program.product_uses)
    return tuple(
        _domain_call_execution_slice(program, ordered_use_ids, call_index)
        for call_index in range(len(program.domain_calls))
    )


def _domain_call_execution_slice(
    program: TypedProgram,
    ordered_use_ids: tuple[ProductUseId, ...],
    call_index: int,
) -> DomainCallExecutionSlice:
    call = program.domain_calls[call_index]
    direct_ids = {
        use_id for result in call.results for use_id in result.product_use_ids
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
            ExecutionTask("domain_call", call.id.qualified_name),
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
    return DomainCallExecutionSlice(
        call_id=call.id,
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


__all__ = [
    "DomainCallExecutionSlice",
    "domain_call_execution_slices",
]
