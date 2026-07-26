from __future__ import annotations

from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    TypedDomainResultBinding,
)
from scopecat.domain.program import DomainProgramDef
from scopecat.graph.relations.point_domain import POINT_UNIT
from scopecat.kernel.product_identity import (
    ProductUse,
    ProductUseId,
    product_id,
)


def test_domain_result_closure_contains_only_exact_direct_product_uses() -> None:
    shared_product = product_id("shared")
    output_product = product_id("output")
    direct_use = ProductUse(shared_product, ProductUseId("shared/direct"))
    foreign_use = ProductUse(shared_product, ProductUseId("shared/foreign"))
    output_use = ProductUse(output_product, ProductUseId("output/use"))
    execution = TypedDomainExecution(
        id="domain",
        program=DomainProgramDef(
            id="program",
            dialect_id="test",
            dialect_version="1",
            body=object(),
        ),
        results=(
            TypedDomainResultBinding(
                id="shared",
                product_id=shared_product,
                product_use_ids=(direct_use.id,),
            ),
        ),
    )
    program = CoreProgram(
        id="test.domain-results",
        kind="test",
        point_domain=PointDomain(POINT_UNIT),
        effects=(execution,),
        product_uses=(direct_use, foreign_use, output_use),
    )

    result_closure = domain_result_closure(program, "domain")

    assert result_closure.product_use_ids == (direct_use.id,)
