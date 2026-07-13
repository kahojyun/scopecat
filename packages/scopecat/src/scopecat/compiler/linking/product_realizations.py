"""Select and seal local realizations for logical product uses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.typed.products import InstrumentProductProducer, ProductDef
from scopecat.compiler.typed.records import validate_product_graph
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.product_identity import (
    ProductId,
    ProductProducerId,
    ProductUse,
    ProductUseId,
)
from scopecat.kernel.resource_identity import PhysicalResourceId
from scopecat.planning.routing import RoutingError, RoutingView


@dataclass(frozen=True, slots=True)
class SelectedLocalProductRealization:
    """One logical product-use occurrence assigned to local collection."""

    product_use_id: ProductUseId
    product_id: ProductId
    product: ProductDef = field(repr=False)
    producer_id: ProductProducerId
    producer: InstrumentProductProducer = field(repr=False)
    implicit_resource_id: PhysicalResourceId | None = None
    kind: Literal["instrument_collection"] = "instrument_collection"

    def __post_init__(self) -> None:
        if self.product.id != self.product_id:
            msg = "selected product realization must retain its product contract"
            raise ValueError(msg)
        if self.producer.id != self.producer_id:
            msg = "selected product realization must retain its producer contract"
            raise ValueError(msg)
        if self.producer.product_id != self.product_id:
            msg = "selected producer must close over the selected logical product"
            raise ValueError(msg)
        if self.product.kind != "observable":
            msg = "local instrument collection requires an observable product"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True, init=False)
class SelectedLocalProductRealizations:
    """Complete, unique local realization coverage for selected product uses."""

    entries: tuple[SelectedLocalProductRealization, ...]
    _by_use: Mapping[ProductUseId, SelectedLocalProductRealization] = field(
        repr=False,
        compare=False,
        hash=False,
    )

    def __init__(
        self,
        entries: tuple[SelectedLocalProductRealization, ...],
    ) -> None:
        by_use = {entry.product_use_id: entry for entry in entries}
        if len(by_use) != len(entries):
            msg = "selected local product realizations require unique product uses"
            raise ValueError(msg)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "_by_use", MappingProxyType(by_use))

    def __copy__(self) -> SelectedLocalProductRealizations:
        return self

    def __deepcopy__(
        self,
        _memo: dict[int, object],
    ) -> SelectedLocalProductRealizations:
        return self

    def selected_for(
        self,
        product_use_id: ProductUseId,
    ) -> SelectedLocalProductRealization:
        try:
            return self._by_use[product_use_id]
        except KeyError as error:
            msg = (
                "no local product realization was selected for use "
                f"{product_use_id.value!r}"
            )
            raise ValueError(msg) from error


def select_local_product_realizations(
    product_defs: Sequence[ProductDef],
    producers: Sequence[InstrumentProductProducer],
    product_uses: Sequence[ProductUse],
    *,
    routing: RoutingView,
    phase: ProblemPhase = ProblemPhase.PLANNING,
) -> tuple[SelectedLocalProductRealizations | None, tuple[Problem, ...]]:
    """Select exact local collection coverage without realizing any product."""

    graph_problems = validate_product_graph(
        product_defs,
        producers,
        product_uses,
        (),
        phase=phase,
    )
    if graph_problems:
        return None, graph_problems

    products_by_id = {product.id: product for product in product_defs}
    producers_by_product: dict[ProductId, list[InstrumentProductProducer]] = {}
    for producer in producers:
        producers_by_product.setdefault(producer.product_id, []).append(producer)
    selected: list[SelectedLocalProductRealization] = []
    problems: list[Problem] = []
    for use in product_uses:
        product = products_by_id.get(use.product_id)
        if product is None:
            # Product-graph validation above owns this expected failure. Keep
            # selection total if that validation is ever independently changed.
            problems.append(
                compiler_problem(
                    "product_use_definition_missing",
                    f"product use {use.id.value!r} references unknown product "
                    f"{use.product_id.qualified_name!r}",
                    _realization_location(use),
                    phase=phase,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        supported = True
        if product.kind != "observable":
            supported = False
            problems.append(
                compiler_problem(
                    "product_local_target_kind_unsupported",
                    "local execution cannot realize product use "
                    f"{use.id.value!r} with kind {product.kind!r}",
                    _realization_location(use),
                    phase=phase,
                    category=ProblemCategory.UNAVAILABLE,
                )
            )
        candidates = producers_by_product.get(product.id, [])
        if not candidates:
            problems.append(
                compiler_problem(
                    "product_local_producer_missing",
                    f"no instrument producer can realize product use {use.id.value!r}",
                    _realization_location(use),
                    phase=phase,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        if len(candidates) > 1:
            problems.append(
                compiler_problem(
                    "product_local_producer_ambiguous",
                    "product use matches multiple instrument producers: "
                    + ", ".join(producer.id.qualified_name for producer in candidates),
                    _realization_location(use),
                    phase=phase,
                    category=ProblemCategory.CONFLICT,
                )
            )
            continue
        producer = candidates[0]
        if supported:
            implicit_resource_id: PhysicalResourceId | None = None
            if isinstance(producer.resource_target, PhysicalResourceId):
                try:
                    binding = routing.bind_physical(
                        resource_id=producer.resource_target,
                        capabilities=(
                            ()
                            if producer.capability is None
                            else (producer.capability,)
                        ),
                    )
                except RoutingError as error:
                    problems.append(
                        compiler_problem(
                            error.code,
                            str(error),
                            _producer_location(producer, "physical_resource_id"),
                            phase=phase,
                            category=(
                                ProblemCategory.NOT_FOUND
                                if error.code.endswith("not_found")
                                else ProblemCategory.UNAVAILABLE
                            ),
                        )
                    )
                    continue
                if binding.resource_kind != "instrument":
                    problems.append(
                        compiler_problem(
                            "physical_resource_kind_unsupported",
                            "physical resource "
                            f"{producer.resource_target.value!r} has kind "
                            f"{binding.resource_kind!r}; local collection "
                            "requires an instrument",
                            _producer_location(producer, "physical_resource_id"),
                            phase=phase,
                            category=ProblemCategory.UNAVAILABLE,
                        )
                    )
                    continue
            elif producer.resource_target is None:
                candidates = tuple(
                    resource
                    for resource in routing.resources
                    if resource.kind == "instrument"
                    and (
                        producer.capability is None
                        or producer.capability in resource.capabilities
                    )
                )
                if not candidates:
                    problems.append(
                        compiler_problem(
                            "product_instrument_not_found",
                            "no configured instrument can realize product use "
                            f"{use.id.value!r}",
                            _realization_location(use),
                            phase=phase,
                            category=ProblemCategory.NOT_FOUND,
                        )
                    )
                    continue
                if len(candidates) > 1:
                    problems.append(
                        compiler_problem(
                            "product_instrument_ambiguous",
                            "product use without an explicit resource matches "
                            "multiple instruments: "
                            + ", ".join(item.id for item in candidates),
                            _realization_location(use),
                            phase=phase,
                            category=ProblemCategory.UNAVAILABLE,
                        )
                    )
                    continue
                implicit_resource_id = PhysicalResourceId(next(iter(candidates)).id)
            selected.append(
                SelectedLocalProductRealization(
                    product_use_id=use.id,
                    product_id=product.id,
                    product=product.model_copy(deep=True),
                    producer_id=producer.id,
                    producer=producer.model_copy(deep=True),
                    implicit_resource_id=implicit_resource_id,
                )
            )

    if problems:
        return None, tuple(problems)
    if len(selected) != len(product_uses):
        raise AssertionError("successful local product selection lost use coverage")
    return (
        SelectedLocalProductRealizations(
            tuple(selected),
        ),
        (),
    )


def _realization_location(use: ProductUse) -> ModelLocation:
    return model_location("product_uses", use.id.value, "realization")


def _producer_location(
    producer: InstrumentProductProducer,
    field_name: str,
) -> ModelLocation:
    return model_location(
        "instrument_product_producers",
        producer.id.qualified_name,
        field_name,
    )


__all__ = [
    "SelectedLocalProductRealization",
    "SelectedLocalProductRealizations",
    "select_local_product_realizations",
]
