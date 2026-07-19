from __future__ import annotations

from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.semantic.model import (
    DomainProgramId,
    MeasurementTransformId,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    TypedDomainProgram,
    TypedDomainResultBinding,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
)
from scopecat.kernel.product_identity import (
    ProductProducerId,
    ProductUse,
    ProductUseId,
    product_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.semantics import MeasurementTransformSemanticContract


def test_domain_result_closure_follows_exact_product_use_edges() -> None:
    shared_product = product_id("shared")
    output_product = product_id("output")
    direct_use = ProductUse(shared_product, ProductUseId("shared/direct"))
    foreign_use = ProductUse(shared_product, ProductUseId("shared/foreign"))
    output_use = ProductUse(output_product, ProductUseId("output/use"))
    execution = TypedDomainExecution(
        id="domain",
        program=TypedDomainProgram(
            id=DomainProgramId(SymbolId(local_id="program")),
            dialect_id="test",
            dialect_version="1",
            body=object(),
        ),
        results=(
            TypedDomainResultBinding(
                id="shared",
                product_id=shared_product,
                producer_id=ProductProducerId(shared_product.symbol),
                product_use_ids=(direct_use.id,),
            ),
        ),
    )
    transform = TypedMeasurementTransform(
        id=MeasurementTransformId(SymbolId(local_id="derive")),
        semantic=MeasurementTransformSemanticContract(id="test.derive", version="1"),
        inputs=(
            TypedMeasurementTransformInput(
                id="source",
                product_id=shared_product,
                product_use_id=foreign_use.id,
            ),
        ),
        outputs=(
            TypedMeasurementTransformOutput(
                id="output",
                product_id=output_product,
                producer_id=ProductProducerId(output_product.symbol),
                product_use_ids=(output_use.id,),
            ),
        ),
    )
    program = CoreProgram(
        id="test.domain-results",
        kind="test",
        point_domain=PointDomain(POINT_UNIT),
        effects=(execution,),
        measurement_transforms=(transform,),
        product_uses=(direct_use, foreign_use, output_use),
    )

    result_closure = domain_result_closure(program, "domain")

    assert result_closure.transforms == ()
    assert result_closure.direct_product_use_ids == (direct_use.id,)
    assert result_closure.derived_product_use_ids == ()
    assert result_closure.product_use_ids == (direct_use.id,)
