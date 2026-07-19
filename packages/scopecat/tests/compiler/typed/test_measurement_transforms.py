from __future__ import annotations

from dataclasses import replace
from typing import Literal

import pytest

from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.semantic.model import MeasurementTransformId
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    MeasurementTransformProductProducer,
    ProductDef,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.verification import verify_core_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.product_identity import (
    ProductId,
    ProductProducerId,
    ProductUse,
    ProductUseId,
    product_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from tests.testkit.typed_program import instrument_product_producer


def _transform_id(name: str) -> MeasurementTransformId:
    return MeasurementTransformId(SymbolId(local_id=name))


def _use(product: ProductId, name: str) -> ProductUse:
    return ProductUse(product_id=product, id=ProductUseId(name))


def _producer(
    transform_id: MeasurementTransformId,
    role: str,
    product: ProductId,
) -> MeasurementTransformProductProducer:
    return MeasurementTransformProductProducer(
        id=ProductProducerId(product.symbol),
        product_id=product,
        transform_id=transform_id,
        output_id=role,
    )


def _transform(
    name: str,
    *,
    source: ProductId,
    source_use: ProductUse,
    output: ProductId,
    output_uses: tuple[ProductUse, ...],
    rate: Literal["point"] = "point",
) -> TypedMeasurementTransform:
    transform_id = _transform_id(name)
    return TypedMeasurementTransform(
        id=transform_id,
        semantic=MeasurementTransformSemanticContract(
            id=f"test.{name}",
            version="1",
        ),
        rate=rate,
        inputs=(
            TypedMeasurementTransformInput(
                id="source",
                product_id=source,
                product_use_id=source_use.id,
            ),
        ),
        outputs=(
            TypedMeasurementTransformOutput(
                id="result",
                product_id=output,
                producer_id=ProductProducerId(output.symbol),
                product_use_ids=tuple(use.id for use in output_uses),
            ),
        ),
    )


def _chain_program() -> CoreProgram:
    raw = product_id("raw")
    middle = product_id("middle")
    derived = product_id("derived")
    raw_use = _use(raw, "first/source")
    middle_use = _use(middle, "second/source")
    derived_first = _use(derived, "derived/first")
    derived_second = _use(derived, "derived/second")
    first = _transform(
        "first",
        source=raw,
        source_use=raw_use,
        output=middle,
        output_uses=(middle_use,),
    )
    second = _transform(
        "second",
        source=middle,
        source_use=middle_use,
        output=derived,
        output_uses=(derived_first, derived_second),
    )
    return CoreProgram(
        id="typed-transforms",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        measurement_transforms=(second, first),
        product_defs=(
            ProductDef(id=raw),
            ProductDef(id=middle),
            ProductDef(id=derived),
        ),
        instrument_product_producers=(
            instrument_product_producer(raw, provider_key="raw"),
        ),
        measurement_transform_product_producers=(
            _producer(first.id, "result", middle),
            _producer(second.id, "result", derived),
        ),
        product_uses=(
            derived_first,
            derived_second,
            raw_use,
            middle_use,
        ),
        record_uses=(
            RecordUse(id="first", product_use_id=derived_first.id),
            RecordUse(id="second", product_use_id=derived_second.id),
        ),
    )


def _problem_codes(program: CoreProgram) -> set[str]:
    with pytest.raises(CheckFailed) as caught:
        verify_core_program(program)
    return {problem.code for problem in caught.value.problems}


def test_typed_measurement_transforms_are_canonical_and_demand_closed() -> None:
    program = _chain_program()

    verified = verify_core_program(program)

    assert tuple(
        transform.id.qualified_name for transform in verified.measurement_transforms
    ) == ("first", "second")


def test_typed_transform_output_requires_exact_use_inventory() -> None:
    program = _chain_program()
    second, first = program.measurement_transforms
    incomplete_output = replace(
        second.outputs[0],
        product_use_ids=second.outputs[0].product_use_ids[:1],
    )
    incomplete = replace(
        program,
        measurement_transforms=(
            replace(second, outputs=(incomplete_output,)),
            first,
        ),
    )

    assert "measurement_transform_output_product_use_coverage_mismatch" in (
        _problem_codes(incomplete)
    )


def test_typed_product_use_allows_multiple_record_alias_consumers() -> None:
    program = _chain_program()
    first_record = program.record_uses[0]
    aliased = replace(
        program,
        record_uses=(
            *program.record_uses,
            RecordUse(
                id="first-alias",
                product_use_id=first_record.product_use_id,
            ),
        ),
    )

    verify_core_program(aliased)


def test_typed_product_use_cannot_be_record_and_transform_input() -> None:
    program = _chain_program()
    _second, first = program.measurement_transforms
    conflicted = replace(
        program,
        record_uses=(
            *program.record_uses,
            RecordUse(
                id="raw-conflict",
                product_use_id=first.inputs[0].product_use_id,
            ),
        ),
    )

    assert "measurement_transform_input_product_use_conflict" in _problem_codes(
        conflicted
    )


def test_typed_product_use_has_at_most_one_transform_input_consumer() -> None:
    program = _chain_program()
    second, first = program.measurement_transforms
    duplicate_input = replace(first.inputs[0], id="duplicate-source")
    conflicted = replace(
        program,
        measurement_transforms=(
            second,
            replace(first, inputs=(*first.inputs, duplicate_input)),
        ),
    )

    assert "measurement_transform_input_product_use_duplicate" in _problem_codes(
        conflicted
    )


def test_typed_transform_input_requires_matching_use_and_producer() -> None:
    program = _chain_program()
    second, first = program.measurement_transforms
    foreign_input = replace(
        first.inputs[0],
        product_use_id=ProductUseId("missing"),
    )
    invalid = replace(
        program,
        measurement_transforms=(
            second,
            replace(first, inputs=(foreign_input,)),
        ),
        instrument_product_producers=(),
    )

    codes = _problem_codes(invalid)
    assert "measurement_transform_input_product_use_mismatch" in codes
    assert "measurement_transform_input_producer_missing" in codes


def test_typed_transform_rejects_point_set_rate_and_cross_kind_producer() -> None:
    program = _chain_program()
    second, first = program.measurement_transforms
    invalid = replace(
        program,
        measurement_transforms=(
            second,
            replace(first, rate="point_set"),
        ),
        instrument_product_producers=(
            *program.instrument_product_producers,
            instrument_product_producer(
                first.outputs[0].product_id,
                id="middle-instrument",
                provider_key="middle",
            ),
        ),
    )

    codes = _problem_codes(invalid)
    assert "measurement_transform_rate_unsupported" in codes
    assert "measurement_transform_product_instrument_producer_conflict" in codes


def test_typed_transform_cycle_is_rejected() -> None:
    left = product_id("left")
    right = product_id("right")
    left_use = _use(left, "right/source")
    right_use = _use(right, "left/source")
    left_transform = _transform(
        "left",
        source=right,
        source_use=right_use,
        output=left,
        output_uses=(left_use,),
    )
    right_transform = _transform(
        "right",
        source=left,
        source_use=left_use,
        output=right,
        output_uses=(right_use,),
    )
    program = CoreProgram(
        id="typed-transform-cycle",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        measurement_transforms=(left_transform, right_transform),
        product_defs=(ProductDef(id=left), ProductDef(id=right)),
        measurement_transform_product_producers=(
            _producer(left_transform.id, "result", left),
            _producer(right_transform.id, "result", right),
        ),
        product_uses=(left_use, right_use),
    )

    assert "measurement_transform_cycle" in _problem_codes(program)
