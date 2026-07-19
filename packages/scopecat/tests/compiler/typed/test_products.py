from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import link_verified_program
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    ProductAxisDef,
    ProductDef,
)
from scopecat.compiler.typed.program import CoreProgram
from scopecat.compiler.typed.records import RecordAxisPlan, RecordPlan, RecordUse
from scopecat.compiler.typed.verification import verify_core_program
from scopecat.execution.local.program import CollectStage
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.product_identity import (
    ProductUse,
    ProductUseId,
    product_id,
    product_use,
)
from scopecat.planning.local_materialization import materialize_local_execution
from tests.testkit.authoring import load_config
from tests.testkit.bound_plan import config_with_physical_resources
from tests.testkit.local_effect_program import make_test_local_effect_program
from tests.testkit.typed_program import instrument_product_producer, link_program


def _product(name: str = "signal") -> ProductDef:
    return ProductDef(
        id=product_id(name),
        unit="ratio",
        metadata={"definition": name},
    )


def _program(
    *,
    products: tuple[ProductDef, ...],
    producers: tuple[InstrumentProductProducer, ...] = (),
    uses: tuple[ProductUse, ...] = (),
    records: tuple[RecordUse, ...] = (),
) -> CoreProgram:
    return CoreProgram(
        id="product-ir",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=uses,
        record_uses=records,
    )


def _duplicate_use_program() -> CoreProgram:
    product = _product()
    use = product_use(product.id)
    return _program(products=(product,), uses=(use, use))


def test_compiler_product_and_record_metadata_is_recursively_immutable() -> None:
    metadata: dict[str, JsonValue] = {
        "labels": ["original"],
        "owner": {"name": "original"},
    }
    axis = ProductAxisDef(
        id="shot",
        kind="shot",
        size=2,
        metadata=metadata,
    )
    product = ProductDef(
        id=product_id("signal"),
        axes=(axis,),
        metadata=metadata,
    )
    producer = instrument_product_producer(product, metadata=metadata)
    use = product_use(product.id)
    record_use = RecordUse(id="signal", product_use_id=use.id, metadata=metadata)
    record_axis = RecordAxisPlan(
        id="shot",
        kind="shot",
        size=2,
        metadata=metadata,
    )
    record_plan = RecordPlan(
        id="signal",
        product_use_id=use.id,
        product_id=product.id,
        kind=product.kind,
        dtype=product.dtype,
        axes=(record_axis,),
        metadata=metadata,
    )
    program = CoreProgram(
        id="immutable-metadata",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        metadata=metadata,
    )

    cast("list[JsonValue]", metadata["labels"]).append("mutated")
    cast("dict[str, JsonValue]", metadata["owner"])["name"] = "mutated"

    for selected in (
        axis.metadata,
        product.metadata,
        producer.metadata,
        record_use.metadata,
        record_axis.metadata,
        record_plan.metadata,
        program.metadata,
    ):
        assert selected == {
            "labels": ("original",),
            "owner": {"name": "original"},
        }
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, JsonValue]", selected)["extra"] = True
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, JsonValue]", selected["owner"])["name"] = "mutated"


def _duplicate_producer_program() -> CoreProgram:
    product = _product()
    producer = instrument_product_producer(product)
    return _program(
        products=(product,),
        producers=(producer, producer),
    )


def _orphan_producer_program() -> CoreProgram:
    return _program(
        products=(_product("available"),),
        producers=(
            instrument_product_producer(
                product_id("missing"),
                id="orphan",
            ),
        ),
    )


def test_record_aliases_share_one_product_realization() -> None:
    product = _product()
    producer = instrument_product_producer(
        product,
        metadata={"producer": "signal"},
    )
    use = product_use(product.id)
    program = _program(
        products=(product,),
        producers=(producer,),
        uses=(use,),
        records=(
            RecordUse(
                id="primary",
                product_use_id=use.id,
                metadata={"record": "primary"},
            ),
            RecordUse(
                id="secondary",
                product_use_id=use.id,
                metadata={"record": "secondary"},
            ),
        ),
    )

    plan = materialize_local_execution(
        link_program(program, validate_config_environment(load_config()))
    )

    operation = plan.points[0].collect_operations[0]
    requests = operation.command.requests
    assert len(requests) == 1
    assert operation.result_bindings[0].product_use_id == use.id
    assert requests[0].metadata == {"producer": "signal"}

    execution = make_test_local_effect_program(plan, instrument_order=("source-0",))
    collect = execution.points[0].stages[-1]
    assert isinstance(collect, CollectStage)
    assert len(collect.operations[0].command.requests) == 1


def test_record_policy_does_not_change_collection_request() -> None:
    product = _product()
    producer = instrument_product_producer(product)
    use = product_use(product.id)
    first = _program(
        products=(product,),
        producers=(producer,),
        uses=(use,),
        records=(RecordUse(id="first", product_use_id=use.id),),
    )
    second = _program(
        products=(product,),
        producers=(producer,),
        uses=(use,),
        records=(
            RecordUse(
                id="renamed",
                product_use_id=use.id,
                metadata={"policy": "changed"},
            ),
        ),
    )
    environment = validate_config_environment(load_config())

    first_plan = materialize_local_execution(link_program(first, environment))
    second_plan = materialize_local_execution(link_program(second, environment))

    assert (
        first_plan.points[0].collect_operations
        == second_plan.points[0].collect_operations
    )


def test_unused_product_producer_is_linked_without_placement() -> None:
    product = _product()
    producer = instrument_product_producer(
        product,
        physical_resource_id="definitely-missing",
    )
    linked = link_program(
        _program(products=(product,), producers=(producer,)),
        validate_config_environment(load_config()),
    )

    assert linked.product_defs == (product,)
    assert linked.instrument_product_producers == (producer,)
    assert linked.product_uses == ()
    assert linked.record_uses == ()

    plan = materialize_local_execution(
        link_verified_program(linked.verified_program, linked.environment)
    )

    assert plan.points[0].collect_operations == ()


def test_unrecorded_product_use_is_still_realized_once() -> None:
    product = _product()
    producer = instrument_product_producer(product)
    use = product_use(product.id)

    plan = materialize_local_execution(
        link_program(
            _program(products=(product,), producers=(producer,), uses=(use,)),
            validate_config_environment(load_config()),
        )
    )

    assert [
        binding.product_use_id
        for operation in plan.points[0].collect_operations
        for binding in operation.result_bindings
    ] == [use.id]


def test_demanded_product_without_a_producer_fails_before_materialization() -> None:
    product = ProductDef(id=product_id("derived"))
    use = product_use(product.id)

    with pytest.raises(CheckFailed) as failure:
        materialize_local_execution(
            link_program(
                _program(products=(product,), uses=(use,)),
                validate_config_environment(load_config()),
            )
        )

    assert [problem.code for problem in failure.value.problems] == [
        "product_local_producer_missing"
    ]


def test_implicit_product_target_requires_one_matching_instrument() -> None:
    product = _product()
    producer = instrument_product_producer(product)
    use = product_use(product.id)
    config = config_with_physical_resources({"source-1": ()})

    with pytest.raises(CheckFailed) as failure:
        materialize_local_execution(
            link_program(
                _program(products=(product,), producers=(producer,), uses=(use,)),
                validate_config_environment(config),
            )
        )

    assert [problem.code for problem in failure.value.problems] == [
        "product_instrument_ambiguous"
    ]


@pytest.mark.parametrize(
    ("program", "expected_code"),
    (
        (
            lambda: _program(products=(_product(), _product())),
            "product_definition_duplicate",
        ),
        (
            _duplicate_use_program,
            "product_use_identity_duplicate",
        ),
        (
            _duplicate_producer_program,
            "product_producer_duplicate",
        ),
        (
            _orphan_producer_program,
            "product_producer_definition_missing",
        ),
        (
            lambda: _program(
                products=(_product("available"),),
                uses=(ProductUse(product_id=product_id("missing")),),
            ),
            "product_use_definition_missing",
        ),
        (
            lambda: _program(
                products=(_product(),),
                records=(
                    RecordUse(
                        id="dangling",
                        product_use_id=ProductUseId.fresh(),
                    ),
                ),
            ),
            "record_product_use_missing",
        ),
    ),
)
def test_sealing_rejects_malformed_product_graph(
    program: Callable[[], CoreProgram],
    expected_code: str,
) -> None:
    with pytest.raises(CheckFailed) as caught:
        verify_core_program(program())

    assert expected_code in {problem.code for problem in caught.value.problems}
