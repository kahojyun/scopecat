"""Domain-owned product-use selection."""

from __future__ import annotations

from scopecat.compiler.bound_facts import BoundProgramFacts
from scopecat.compiler.point_domain import PointDomain
from scopecat.domain.program import DomainProgramDef
from scopecat.kernel.product_identity import (
    ProductUse,
    ProductUseId,
    product_id,
)
from scopecat.planning.domain_results import domain_result_product_use_ids
from scopecat.program.logical import LogicalDomainExecution


def test_domain_result_selection_contains_only_exact_direct_product_uses() -> None:
    shared_product = product_id("shared")
    output_product = product_id("output")
    direct_use = ProductUse(shared_product, ProductUseId("shared/direct"))
    foreign_use = ProductUse(shared_product, ProductUseId("shared/foreign"))
    output_use = ProductUse(output_product, ProductUseId("output/use"))
    execution = LogicalDomainExecution(
        id="domain",
        program=DomainProgramDef(
            id="program",
            dialect_id="test",
            dialect_version="1",
            body=object(),
        ),
        results=(("shared", shared_product),),
    )
    program = BoundProgramFacts(
        point_domain=PointDomain(axes=()),
        domain_result_use_ids={(execution.id, "shared"): (direct_use.id,)},
        product_uses=(direct_use, foreign_use, output_use),
    )

    assert domain_result_product_use_ids(program, execution) == (direct_use.id,)
