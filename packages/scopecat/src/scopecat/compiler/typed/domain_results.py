"""Derive the typed result closure rooted at one domain execution."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.typed.program import BoundProgramFacts
from scopecat.kernel.product_identity import ProductUseId
from scopecat.program.logical import LogicalDomainExecution


@dataclass(frozen=True, slots=True)
class DomainResultClosure:
    """Exact logical product occurrences produced by one execution."""

    product_use_ids: tuple[ProductUseId, ...]


def domain_result_closure(
    program: BoundProgramFacts,
    execution: LogicalDomainExecution,
) -> DomainResultClosure:
    """Select exact product-use edges from one domain execution's results."""

    direct_ids = {
        use_id
        for result_id, _product_id in execution.results
        for use_id in program.domain_result_use_ids[(execution.id, result_id)]
    }
    return DomainResultClosure(
        product_use_ids=tuple(
            use.id for use in program.product_uses if use.id in direct_ids
        ),
    )
