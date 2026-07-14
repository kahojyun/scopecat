from __future__ import annotations

from scopecat.compiler.semantic.model import DomainCallId, DomainProgramId
from scopecat.compiler.typed.program import (
    TypedDomainCall,
    TypedDomainResultBinding,
    TypedProgram,
)
from scopecat.kernel.product_identity import (
    ProductProducerId,
    ProductUse,
    ProductUseId,
    product_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.planning.backend import _domain_call_affinity_problems
from scopecat.planning.coverage import ExecutionCoverage, ExecutionTask


def _program_with_demanded_domain_result() -> TypedProgram:
    selected_product_id = product_id("counts")
    selected_use = ProductUse(selected_product_id, ProductUseId("counts-use"))
    call = TypedDomainCall(
        id=DomainCallId(SymbolId(local_id="execute")),
        program_id=DomainProgramId(SymbolId(local_id="program")),
        results=(
            TypedDomainResultBinding(
                id="counts",
                product_id=selected_product_id,
                producer_id=ProductProducerId(selected_product_id.symbol),
                product_use_ids=(selected_use.id,),
            ),
        ),
    )
    return TypedProgram.model_construct(
        id="test.domain-affinity",
        kind="test",
        domain_calls=(call,),
        product_uses=(selected_use,),
    )


def test_domain_call_and_demanded_results_require_one_owner() -> None:
    program = _program_with_demanded_domain_result()
    problems = _domain_call_affinity_problems(
        program,
        (
            (
                "compiler-a",
                ExecutionCoverage((ExecutionTask("domain_call", "execute"),)),
            ),
            (
                "collector-b",
                ExecutionCoverage((ExecutionTask("product", "counts-use"),)),
            ),
        ),
    )

    assert [problem.code for problem in problems] == [
        "domain_call_result_affinity_split"
    ]


def test_domain_call_and_demanded_results_accept_one_owner() -> None:
    program = _program_with_demanded_domain_result()
    problems = _domain_call_affinity_problems(
        program,
        (
            (
                "compiler-a",
                ExecutionCoverage(
                    (
                        ExecutionTask("domain_call", "execute"),
                        ExecutionTask("product", "counts-use"),
                    )
                ),
            ),
        ),
    )

    assert problems == ()
