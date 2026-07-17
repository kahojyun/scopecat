from __future__ import annotations

import pytest

from scopecat.compiler.linking.product_realizations import (
    SelectedLocalProductRealization,
    SelectedLocalProductRealizations,
    select_local_product_realizations,
)
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    ProductDef,
    ProductKind,
)
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
)
from scopecat.kernel.product_identity import ProductUse, product_id, product_use
from scopecat.kernel.resource_identity import physical_resource_id
from scopecat.planning.routing import RoutingView
from scopecat.records.config import RoutingResource
from tests.testkit.typed_program import instrument_product_producer


def _product(
    name: str,
    *,
    kind: ProductKind = "observable",
) -> ProductDef:
    return ProductDef(
        id=product_id(name),
        kind=kind,
    )


def _routing() -> RoutingView:
    return RoutingView(resources=(RoutingResource(id="source-0"),))


def _select(
    products: tuple[ProductDef, ...],
    uses: tuple[ProductUse, ...],
    *,
    producers: tuple[InstrumentProductProducer, ...] | None = None,
) -> tuple[SelectedLocalProductRealizations | None, tuple[Problem, ...]]:
    selected_producers = (
        tuple(instrument_product_producer(product) for product in products)
        if producers is None
        else producers
    )
    selected, problems = select_local_product_realizations(
        products,
        selected_producers,
        uses,
        routing=_routing(),
    )
    return selected, problems


def test_local_product_selection_seals_exact_use_order_and_coverage() -> None:
    first = _product("first")
    second = _product("second")
    first_producer = instrument_product_producer(first)
    second_producer = instrument_product_producer(second)
    second_use = product_use(second.id)
    first_use = product_use(first.id)

    selected, problems = select_local_product_realizations(
        (first, second),
        (first_producer, second_producer),
        (second_use, first_use),
        routing=_routing(),
    )

    assert problems == ()
    assert selected is not None
    assert selected.entries == (
        SelectedLocalProductRealization(
            product_use_id=second_use.id,
            product_id=second.id,
            product=second,
            producer_id=second_producer.id,
            producer=second_producer,
            implicit_resource_id=physical_resource_id("source-0"),
        ),
        SelectedLocalProductRealization(
            product_use_id=first_use.id,
            product_id=first.id,
            product=first,
            producer_id=first_producer.id,
            producer=first_producer,
            implicit_resource_id=physical_resource_id("source-0"),
        ),
    )
    assert selected.selected_for(second_use.id) is selected.entries[0]
    assert selected.selected_for(first_use.id) is selected.entries[1]


def test_missing_producer_is_a_structured_target_failure() -> None:
    product = _product("derived")
    use = product_use(product.id)

    selected, problems = _select((product,), (use,), producers=())

    assert selected is None
    assert [problem.code for problem in problems] == ["product_local_producer_missing"]
    problem = problems[0]
    assert problem.impact is ProblemImpact.BLOCKING
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.category is ProblemCategory.NOT_FOUND
    assert isinstance(problem.location, ModelLocation)
    assert problem.location.root == "product_uses"
    assert problem.location.path == (use.id.value, "realization")


def test_non_observable_use_is_a_structured_target_failure() -> None:
    product = _product("artifact", kind="artifact")
    use = product_use(product.id)

    selected, problems = _select((product,), (use,))

    assert selected is None
    assert [problem.code for problem in problems] == [
        "product_local_target_kind_unsupported"
    ]
    assert problems[0].category is ProblemCategory.UNAVAILABLE


def test_multiple_producers_for_one_demand_are_rejected_as_ambiguous() -> None:
    product = _product("signal")
    use = product_use(product.id)
    producers = (
        instrument_product_producer(product, id="primary"),
        instrument_product_producer(product, id="secondary"),
    )

    selected, problems = _select((product,), (use,), producers=producers)

    assert selected is None
    assert [problem.code for problem in problems] == [
        "product_local_producer_ambiguous"
    ]
    assert problems[0].category is ProblemCategory.CONFLICT


def test_selected_realization_seals_an_exact_producer_snapshot() -> None:
    product = _product("signal")
    producer = instrument_product_producer(
        product,
        id="local-signal",
        metadata={"owner": {"name": "original"}},
    )
    use = product_use(product.id)

    selected, problems = _select(
        (product,),
        (use,),
        producers=(producer,),
    )

    assert problems == ()
    assert selected is not None
    proof = selected.selected_for(use.id)
    assert proof.producer_id == producer.id
    assert proof.producer == producer
    assert proof.producer is not producer

    producer.metadata["owner"] = {"name": "mutated"}

    assert proof.producer.metadata == {"owner": {"name": "original"}}


@pytest.mark.parametrize(
    ("products", "producers", "uses", "expected_code"),
    (
        (
            (_product("duplicate"), _product("duplicate")),
            (),
            (),
            "product_definition_duplicate",
        ),
        (
            (_product("duplicate-use"),),
            (),
            (use := product_use(product_id("duplicate-use")), use),
            "product_use_identity_duplicate",
        ),
        (
            (_product("available"),),
            (),
            (ProductUse(product_id=product_id("missing")),),
            "product_use_definition_missing",
        ),
    ),
)
def test_malformed_product_graph_returns_problems(
    products: tuple[ProductDef, ...],
    producers: tuple[InstrumentProductProducer, ...],
    uses: tuple[ProductUse, ...],
    expected_code: str,
) -> None:
    selected, problems = _select(products, uses, producers=producers)

    assert selected is None
    assert [problem.code for problem in problems] == [expected_code]
