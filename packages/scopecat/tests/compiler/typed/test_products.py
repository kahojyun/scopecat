from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import InstrumentProductProducer, ProductDef
from scopecat.compiler.typed.program import (
    TypedProgram,
    instrument_product_producer,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.verification import verify_typed_program
from scopecat.execution.local.lowering import build_execution_program
from scopecat.execution.local.program import CollectStage
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.product_identity import (
    ProductUse,
    ProductUseId,
    product_id,
    product_use,
)
from tests.testkit.authoring import load_config
from tests.testkit.experiment_preview import config_with_physical_resources


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
) -> TypedProgram:
    return TypedProgram(
        id="product-ir",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=uses,
        record_uses=records,
    )


def _duplicate_use_program() -> TypedProgram:
    product = _product()
    use = product_use(product.id)
    return _program(products=(product,), uses=(use, use))


def _duplicate_producer_program() -> TypedProgram:
    product = _product()
    producer = instrument_product_producer(product)
    return _program(
        products=(product,),
        producers=(producer, producer),
    )


def _orphan_producer_program() -> TypedProgram:
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

    plan = materialize_local_plan(
        link_program(program, validate_config_environment(load_config()))
    )

    assert plan.valid, plan.problems
    assert [record.id for record in plan.records] == ["primary", "secondary"]
    assert plan.records[0].metadata == {
        "definition": "signal",
        "record": "primary",
    }
    assert plan.records[1].metadata == {
        "definition": "signal",
        "record": "secondary",
    }
    requests = plan.points[0].collect[0].requests
    assert len(requests) == 1
    assert requests[0].product_use_id == use.id
    assert requests[0].metadata == {"producer": "signal"}

    execution = build_execution_program(plan, instrument_order=("source-0",))
    collect = execution.points[0].stages[-1]
    assert isinstance(collect, CollectStage)
    assert len(collect.operations[0].command.requests) == 1
    assert [item.record_id for item in execution.record_projections] == [
        "primary",
        "secondary",
    ]


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

    first_plan = materialize_local_plan(link_program(first, environment))
    second_plan = materialize_local_plan(link_program(second, environment))

    assert first_plan.valid, first_plan.problems
    assert second_plan.valid, second_plan.problems
    assert first_plan.points[0].collect == second_plan.points[0].collect
    assert first_plan.records != second_plan.records


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

    plan = materialize_local_plan(link_program(linked.program, linked.environment))

    assert plan.valid, plan.problems
    assert plan.points[0].collect == ()


def test_unrecorded_product_use_is_still_realized_once() -> None:
    product = _product()
    producer = instrument_product_producer(product)
    use = product_use(product.id)

    plan = materialize_local_plan(
        link_program(
            _program(products=(product,), producers=(producer,), uses=(use,)),
            validate_config_environment(load_config()),
        )
    )

    assert plan.valid, plan.problems
    assert plan.records == ()
    assert [
        request.product_use_id
        for collect in plan.points[0].collect
        for request in collect.requests
    ] == [use.id]


def test_demanded_product_without_a_producer_fails_before_materialization() -> None:
    product = ProductDef(id=product_id("derived"))
    use = product_use(product.id)

    plan = materialize_local_plan(
        link_program(
            _program(products=(product,), uses=(use,)),
            validate_config_environment(load_config()),
        )
    )

    assert not plan.valid
    assert plan.points == ()
    assert [problem.code for problem in plan.problems] == [
        "product_local_producer_missing"
    ]


def test_implicit_product_target_requires_one_matching_instrument() -> None:
    product = _product()
    producer = instrument_product_producer(product)
    use = product_use(product.id)
    config = config_with_physical_resources({"source-1": ()})

    plan = materialize_local_plan(
        link_program(
            _program(products=(product,), producers=(producer,), uses=(use,)),
            validate_config_environment(config),
        )
    )

    assert not plan.valid
    assert [problem.code for problem in plan.problems] == [
        "product_instrument_ambiguous"
    ]


def test_bound_plan_rejects_lossy_or_mutated_product_projection() -> None:
    product = _product()
    producer = instrument_product_producer(product)
    use = product_use(product.id)
    plan = materialize_local_plan(
        link_program(
            _program(
                products=(product,),
                producers=(producer,),
                uses=(use,),
                records=(RecordUse(id="signal", product_use_id=use.id),),
            ),
            validate_config_environment(load_config()),
        )
    )
    assert plan.valid, plan.problems

    with pytest.raises(ValueError, match="record-use inventory"):
        replace(plan, records=())

    with pytest.raises(ValueError, match="record-use identities must be unique"):
        replace(
            plan,
            record_uses=(plan.record_uses[0], plan.record_uses[0]),
            records=(plan.records[0], plan.records[0]),
        )

    changed_contract = product.model_copy(update={"unit": "Hz"})
    with pytest.raises(ValueError, match="selected product"):
        replace(plan, product_defs=(changed_contract,))

    competing_producer = instrument_product_producer(product, id="competing")
    with pytest.raises(ValueError, match="exactly one retained"):
        replace(
            plan,
            instrument_product_producers=(producer, competing_producer),
        )

    point = plan.points[0]
    collect = point.collect[0]
    request = replace(collect.requests[0], provider_key="wrong")
    mutated_collect = replace(collect, requests=(request,))
    with pytest.raises(ValueError, match="selected producer contract"):
        replace(plan, points=(replace(point, collect=(mutated_collect,)),))

    invented_target = replace(
        collect.requests[0],
        entity_ids=("invented-entity",),
    )
    with pytest.raises(ValueError, match="invalid routed target"):
        replace(
            plan,
            points=(
                replace(
                    point,
                    collect=(replace(collect, requests=(invented_target,)),),
                ),
            ),
        )


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
    program: Callable[[], TypedProgram],
    expected_code: str,
) -> None:
    with pytest.raises(CheckFailed) as caught:
        verify_typed_program(program())

    assert expected_code in {problem.code for problem in caught.value.problems}
