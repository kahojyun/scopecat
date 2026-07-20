from __future__ import annotations

import pytest

from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.semantic.model import (
    DomainProgramId,
    DomainResultPortDef,
    MeasurementTransformId,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    TypedDomainExecution,
    TypedDomainProgram,
    TypedDomainResultBinding,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.verification import verify_core_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
    product_id,
)
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from tests.testkit.typed_program import instrument_acquisition


def _use(product: ProductId, name: str) -> ProductUse:
    return ProductUse(product_id=product, id=ProductUseId(name))


def _domain(
    name: str,
    outputs: tuple[tuple[str, ProductId, tuple[ProductUse, ...]], ...],
) -> TypedDomainExecution:
    return TypedDomainExecution(
        id=name,
        program=TypedDomainProgram(
            id=DomainProgramId(SymbolId(local_id=f"{name}-program")),
            dialect_id="tests.product-ownership",
            dialect_version="1",
            body=(),
            result_ports=tuple(DomainResultPortDef(role) for role, _, _ in outputs),
        ),
        results=tuple(
            TypedDomainResultBinding(
                id=role,
                product_id=product,
                product_use_ids=tuple(use.id for use in uses),
            )
            for role, product, uses in outputs
        ),
    )


def _transform(
    name: str,
    *,
    inputs: tuple[tuple[str, ProductUse], ...] = (),
    outputs: tuple[tuple[str, ProductId, tuple[ProductUse, ...]], ...],
) -> TypedMeasurementTransform:
    return TypedMeasurementTransform(
        id=MeasurementTransformId(SymbolId(local_id=name)),
        semantic=MeasurementTransformSemanticContract(
            id=f"tests.{name}",
            version="1",
        ),
        inputs=tuple(
            TypedMeasurementTransformInput(
                id=role,
                product_id=use.product_id,
                product_use_id=use.id,
            )
            for role, use in inputs
        ),
        outputs=tuple(
            TypedMeasurementTransformOutput(
                id=role,
                product_id=product,
                product_use_ids=tuple(use.id for use in uses),
            )
            for role, product, uses in outputs
        ),
    )


def _problem_codes(program: CoreProgram) -> set[str]:
    with pytest.raises(CheckFailed) as caught:
        verify_core_program(program)
    return {problem.code for problem in caught.value.problems}


def test_direct_owners_support_mixed_real_experiment_dataflow() -> None:
    raw = product_id("raw")
    reference = product_id("reference")
    calibration = product_id("calibration")
    fitted = product_id("fitted")
    residual = product_id("residual")
    score = product_id("score")

    raw_fit_use = _use(raw, "fit/raw")
    reference_fit_use = _use(reference, "fit/reference")
    calibration_fit_use = _use(calibration, "fit/calibration")
    fitted_record_use = _use(fitted, "fitted/record")
    residual_score_use = _use(residual, "score/residual")
    score_primary_use = _use(score, "score/primary")
    score_monitor_use = _use(score, "score/monitor")

    fit = _transform(
        "fit",
        inputs=(
            ("raw", raw_fit_use),
            ("reference", reference_fit_use),
            ("calibration", calibration_fit_use),
        ),
        outputs=(
            ("fitted", fitted, (fitted_record_use,)),
            ("residual", residual, (residual_score_use,)),
        ),
    )
    score_transform = _transform(
        "score",
        inputs=(("residual", residual_score_use),),
        outputs=(("score", score, (score_primary_use, score_monitor_use)),),
    )
    program = CoreProgram(
        id="mixed-product-owners",
        kind="compiler_test",
        point_domain=PointDomain(POINT_UNIT),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("scalar_signal",),
            ),
        ),
        effects=(
            _domain("capture", (("raw", raw, (raw_fit_use,)),)),
            instrument_acquisition(
                reference,
                capability="scalar_signal",
            ),
            instrument_acquisition(
                calibration,
                capability="scalar_signal",
            ),
        ),
        measurement_transforms=(score_transform, fit),
        product_defs=tuple(
            ProductDef(id=product)
            for product in (raw, reference, calibration, fitted, residual, score)
        ),
        product_uses=(
            raw_fit_use,
            reference_fit_use,
            calibration_fit_use,
            fitted_record_use,
            residual_score_use,
            score_primary_use,
            score_monitor_use,
        ),
        record_uses=(
            RecordUse(id="fitted", product_use_id=fitted_record_use.id),
            RecordUse(id="score", product_use_id=score_primary_use.id),
            RecordUse(id="monitor", product_use_id=score_monitor_use.id),
        ),
    )

    verified = verify_core_program(program)

    assert tuple(
        transform.id.qualified_name for transform in verified.measurement_transforms
    ) == ("fit", "score")


def test_all_cross_kind_owner_collisions_are_reported_from_direct_outputs() -> None:
    source = product_id("source")
    collided = product_id("collided")
    source_use = _use(source, "derive/source")
    collided_use = _use(collided, "collided/record")
    transform = _transform(
        "derive",
        inputs=(("source", source_use),),
        outputs=(("result", collided, (collided_use,)),),
    )
    program = CoreProgram(
        id="cross-kind-owner-conflict",
        kind="compiler_test",
        point_domain=PointDomain(POINT_UNIT),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("scalar_signal",),
            ),
        ),
        effects=(
            _domain("capture", (("result", collided, (collided_use,)),)),
            instrument_acquisition(source, capability="scalar_signal"),
            instrument_acquisition(collided, capability="scalar_signal"),
        ),
        measurement_transforms=(transform,),
        product_defs=(ProductDef(id=source), ProductDef(id=collided)),
        product_uses=(source_use, collided_use),
        record_uses=(RecordUse(id="collided", product_use_id=collided_use.id),),
    )

    codes = _problem_codes(program)

    assert "product_owner_conflict" in codes
    assert "measurement_transform_product_domain_producer_conflict" in codes


def test_same_kind_duplicate_owners_are_detected_without_side_tables() -> None:
    shared = product_id("shared")
    shared_use = _use(shared, "shared/record")
    product_defs = (ProductDef(id=shared),)
    record_uses = (RecordUse(id="shared", product_use_id=shared_use.id),)
    duplicate_domains = CoreProgram(
        id="duplicate-domain-owners",
        kind="compiler_test",
        point_domain=PointDomain(POINT_UNIT),
        effects=(
            _domain("first", (("result", shared, (shared_use,)),)),
            _domain("second", (("result", shared, (shared_use,)),)),
        ),
        product_defs=product_defs,
        product_uses=(shared_use,),
        record_uses=record_uses,
    )
    duplicate_transforms = CoreProgram(
        id="duplicate-transform-owners",
        kind="compiler_test",
        point_domain=PointDomain(POINT_UNIT),
        measurement_transforms=(
            _transform(
                "first",
                outputs=(("result", shared, (shared_use,)),),
            ),
            _transform(
                "second",
                outputs=(("result", shared, (shared_use,)),),
            ),
        ),
        product_defs=product_defs,
        product_uses=(shared_use,),
        record_uses=record_uses,
    )

    assert "domain_product_producer_duplicate" in _problem_codes(duplicate_domains)
    assert "measurement_transform_output_product_duplicate" in _problem_codes(
        duplicate_transforms
    )
