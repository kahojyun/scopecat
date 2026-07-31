"""Derive the typed result closure rooted at one domain execution."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.typed.program import (
    BoundProgramFacts,
    bound_domain_executions,
)
from scopecat.kernel.product_identity import ProductUseId


@dataclass(frozen=True, slots=True)
class DomainResultClosure:
    """Exact logical product occurrences produced by one execution."""

    product_use_ids: tuple[ProductUseId, ...]


def domain_result_closure(
    program: BoundProgramFacts,
    execution_id: str,
) -> DomainResultClosure:
    """Select exact product-use edges from one domain execution's results."""

    execution = next(
        item for item in bound_domain_executions(program) if item.id == execution_id
    )
    direct_ids = {
        use_id for result in execution.results for use_id in result.product_use_ids
    }
    return DomainResultClosure(
        product_use_ids=tuple(
            use.id for use in program.product_uses if use.id in direct_ids
        ),
    )
