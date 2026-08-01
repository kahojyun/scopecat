"""Select product uses owned by one bound domain execution."""

from __future__ import annotations

from scopecat.compiler.bound_facts import BoundProgramFacts
from scopecat.kernel.product_identity import ProductUseId
from scopecat.program.logical import LogicalDomainExecution


def domain_result_product_use_ids(
    program: BoundProgramFacts,
    execution: LogicalDomainExecution,
) -> tuple[ProductUseId, ...]:
    """Select exact product-use edges from one domain execution's results."""

    direct_ids = {
        use_id
        for result_id, _product_id in execution.results
        for use_id in program.domain_result_use_ids[(execution.id, result_id)]
    }
    return tuple(use.id for use in program.product_uses if use.id in direct_ids)
