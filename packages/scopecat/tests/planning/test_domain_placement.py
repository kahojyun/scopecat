from __future__ import annotations

from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.semantic.model import (
    DomainProgramId,
    MeasurementTransformId,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    TypedDomainProgram,
    TypedDomainResultBinding,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
    TypedProgram,
)
from scopecat.kernel.product_identity import (
    ProductProducerId,
    ProductUse,
    ProductUseId,
    product_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.planning.coverage import ExecutionTask
from scopecat.planning.domain_placement import domain_execution_slice


def test_domain_slice_follows_exact_product_use_edges() -> None:
    shared_product = product_id("shared")
    output_product = product_id("output")
    direct_use = ProductUse(shared_product, ProductUseId("shared/direct"))
    foreign_use = ProductUse(shared_product, ProductUseId("shared/foreign"))
    output_use = ProductUse(output_product, ProductUseId("output/use"))
    execution = TypedDomainExecution(
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
        rate="point",
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
    program = TypedProgram(
        id="test.domain-placement",
        kind="test",
        point_domain=PointDomain(POINT_UNIT),
        domain_execution=execution,
        measurement_transforms=(transform,),
        product_uses=(direct_use, foreign_use, output_use),
    )

    execution_slice = domain_execution_slice(program)
    assert execution_slice is not None

    assert execution_slice.transforms == ()
    assert execution_slice.direct_product_use_ids == (direct_use.id,)
    assert execution_slice.derived_product_use_ids == ()
    assert execution_slice.product_use_ids == (direct_use.id,)
    assert execution_slice.coverage.tasks == (
        ExecutionTask("domain_execution", "domain"),
        ExecutionTask("product", direct_use.id.value),
    )
