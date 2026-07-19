"""Canonical logical measurement values at the RunProgram boundary."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, cast

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.linking.linked import MaterializedLinkedPointSet
from scopecat.compiler.typed.point_domain import LogicalPointId, MaterializedPoint
from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.measurements.contracts import (
    measurement_value_contract_issues,
    validated_measurement_value_copy,
)
from scopecat.records.measurement import MeasurementValue


class MeasurementValueSelection(Protocol):
    """Logical value contract consumed by projection and canonical sealing."""

    @property
    def linked_points(self) -> MaterializedLinkedPointSet: ...

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]: ...

    @property
    def linked_contract_fingerprint(self) -> str: ...

    @property
    def contract_fingerprint(self) -> str: ...

    def product_use(self, product_use_id: ProductUseId) -> ProductUse: ...

    def product_for_use(self, product_use_id: ProductUseId) -> ProductDef: ...

    def point(self, logical_point_id: LogicalPointId) -> MaterializedPoint: ...


@dataclass(frozen=True, slots=True)
class SelectedMeasurementValues:
    """Canonical logical value inventory required from one RunProgram."""

    linked_points: MaterializedLinkedPointSet = field(repr=False)
    product_use_ids: tuple[ProductUseId, ...]
    linked_contract_fingerprint: str = field(init=False)
    contract_fingerprint: str = field(init=False)
    _use_by_id: Mapping[ProductUseId, ProductUse] = field(
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )
    _product_by_use_id: Mapping[ProductUseId, ProductDef] = field(
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )
    _point_by_id: Mapping[LogicalPointId, MaterializedPoint] = field(
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        all_uses, all_products = _measurement_product_inventory(self.linked_points)
        use_by_id = {use.id: use for use in all_uses}
        linked_fingerprint = measurement_value_contract_fingerprint(self.linked_points)
        object.__setattr__(self, "linked_contract_fingerprint", linked_fingerprint)
        object.__setattr__(
            self,
            "contract_fingerprint",
            stable_content_hash(
                {
                    "schema": "scopecat.selected_measurement_values.v1",
                    "linked_contract_fingerprint": linked_fingerprint,
                    "product_use_ids": [item.value for item in self.product_use_ids],
                }
            ),
        )
        object.__setattr__(
            self,
            "_use_by_id",
            MappingProxyType(
                {use_id: use_by_id[use_id] for use_id in self.product_use_ids}
            ),
        )
        object.__setattr__(
            self,
            "_product_by_use_id",
            MappingProxyType(
                {use_id: all_products[use_id] for use_id in self.product_use_ids}
            ),
        )
        object.__setattr__(
            self,
            "_point_by_id",
            MappingProxyType(
                {
                    point.logical_id: point
                    for point in self.linked_points.point_domain.points
                }
            ),
        )

    def product_use(self, product_use_id: ProductUseId) -> ProductUse:
        try:
            return self._use_by_id[product_use_id]
        except KeyError as error:
            msg = f"product use {product_use_id.value!r} is not selected"
            raise KeyError(msg) from error

    def product_for_use(self, product_use_id: ProductUseId) -> ProductDef:
        try:
            return self._product_by_use_id[product_use_id]
        except KeyError as error:
            msg = f"product use {product_use_id.value!r} is not selected"
            raise KeyError(msg) from error

    def point(self, logical_point_id: LogicalPointId) -> MaterializedPoint:
        try:
            return self._point_by_id[logical_point_id]
        except KeyError as error:
            msg = f"logical point {logical_point_id.value!r} is not selected"
            raise KeyError(msg) from error


@dataclass(frozen=True, slots=True)
class MeasurementValueCandidate:
    """Producer candidate keyed only by logical point and product-use identity."""

    logical_point_id: LogicalPointId
    product_use_id: ProductUseId
    value: MeasurementValue


@dataclass(frozen=True, slots=True, init=False)
class ClosedMeasurementProductValue:
    """One checked host value with producer-neutral logical identity."""

    point: MaterializedPoint = field(repr=False)
    product_use: ProductUse = field(repr=False)
    _product: ProductDef = field(repr=False)
    _value: MeasurementValue = field(repr=False)

    def __init__(
        self,
        point: MaterializedPoint,
        product_use: ProductUse,
        product: ProductDef,
        value: MeasurementValue,
    ) -> None:
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "product_use", product_use)
        object.__setattr__(self, "_product", product)
        object.__setattr__(self, "_value", validated_measurement_value_copy(value))

    @property
    def logical_point_id(self) -> LogicalPointId:
        return self.point.logical_id

    @property
    def product_use_id(self) -> ProductUseId:
        return self.product_use.id

    @property
    def product_id(self) -> ProductId:
        return self._product.id

    @property
    def product(self) -> ProductDef:
        return self._product

    @property
    def value(self) -> MeasurementValue:
        return validated_measurement_value_copy(self._value)


@dataclass(frozen=True, slots=True)
class ClosedMeasurementProductValues:
    """Canonical producer-neutral values for every required point/use pair."""

    selection: MeasurementValueSelection = field(repr=False)
    values: tuple[ClosedMeasurementProductValue, ...]
    _by_output: Mapping[
        tuple[LogicalPointId, ProductUseId],
        ClosedMeasurementProductValue,
    ] = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        by_output = {
            (value.logical_point_id, value.product_use_id): value
            for value in self.values
        }
        object.__setattr__(self, "_by_output", MappingProxyType(by_output))

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        return self.selection.product_use_ids

    def value_for_output(
        self,
        logical_point_id: LogicalPointId,
        product_use_id: ProductUseId,
    ) -> ClosedMeasurementProductValue:
        try:
            return self._by_output[(logical_point_id, product_use_id)]
        except KeyError as error:
            msg = (
                "assembled measurement values have no output for point "
                f"{logical_point_id.value!r}, use {product_use_id.value!r}"
            )
            raise KeyError(msg) from error


def select_measurement_values(
    linked_points: MaterializedLinkedPointSet,
    *,
    required_product_use_ids: Sequence[ProductUseId],
) -> SelectedMeasurementValues:
    """Select one canonical logical inventory of demanded product uses."""

    required = tuple(required_product_use_ids)
    all_uses, product_by_use_id = _measurement_product_inventory(linked_points)
    all_use_by_id = {use.id: use for use in all_uses}
    required_set = set(required)
    problems: list[Problem] = []
    for use_id, count in Counter(required).items():
        if count > 1:
            problems.append(
                _selection_problem(
                    "measurement_value_required_use_duplicate",
                    f"required product use {use_id.value!r} is repeated",
                    path=("required_product_use_ids",),
                    category=ProblemCategory.CONFLICT,
                )
            )
    for index, use_id in enumerate(required):
        if use_id not in all_use_by_id:
            problems.append(
                _selection_problem(
                    "measurement_value_required_use_unknown",
                    f"required product use {use_id.value!r} is not in the plan",
                    path=("required_product_use_ids", index),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
    for use_id in required_set & set(all_use_by_id):
        problems.extend(_carrier_selection_problems(use_id, product_by_use_id[use_id]))
    if problems:
        raise CheckFailed(problems)
    return SelectedMeasurementValues(
        linked_points,
        tuple(use.id for use in all_uses if use.id in required_set),
    )


def seal_measurement_values(
    selection: MeasurementValueSelection,
    candidates: Sequence[MeasurementValueCandidate],
) -> ClosedMeasurementProductValues:
    """Close the canonical logical value inventory once at the run boundary."""

    selected = selection
    supplied = tuple(candidates)
    points = selected.linked_points.point_domain.points
    expected_keys = {
        (point.logical_id, use_id)
        for point in points
        for use_id in selected.product_use_ids
    }
    point_ids = {point.logical_id for point in points}
    use_ids = set(selected.product_use_ids)
    by_key: dict[
        tuple[LogicalPointId, ProductUseId],
        MeasurementValueCandidate,
    ] = {}
    first_index: dict[tuple[LogicalPointId, ProductUseId], int] = {}
    problems: list[Problem] = []
    for candidate_index, candidate in enumerate(supplied):
        key = (candidate.logical_point_id, candidate.product_use_id)
        if key in by_key:
            problems.append(
                _value_problem(
                    "measurement_value_duplicate",
                    "logical measurement values repeat one point/use pair",
                    path=("candidates", candidate_index),
                    details={"first_candidate_index": first_index[key]},
                )
            )
            continue
        by_key[key] = candidate
        first_index[key] = candidate_index
        if candidate.logical_point_id not in point_ids:
            problems.append(
                _value_problem(
                    "measurement_value_point_unknown",
                    "logical measurement values reference a foreign point",
                    path=("candidates", candidate_index, "logical_point_id"),
                )
            )
        if candidate.product_use_id not in use_ids:
            problems.append(
                _value_problem(
                    "measurement_value_use_unknown",
                    "logical measurement values reference an unselected product use",
                    path=("candidates", candidate_index, "product_use_id"),
                )
            )
        if key not in expected_keys:
            continue
        product = selected.product_for_use(candidate.product_use_id)
        problems.extend(
            _measurement_contract_problems(
                candidate.value,
                product=product,
                candidate_index=candidate_index,
                logical_point_id=candidate.logical_point_id,
                product_use_id=candidate.product_use_id,
            )
        )

    for point in points:
        for use_id in selected.product_use_ids:
            if (point.logical_id, use_id) in by_key:
                continue
            problems.append(
                _value_problem(
                    "measurement_value_output_missing",
                    "logical measurement values are missing one point/use pair",
                    path=("outputs", point.logical_ordinal, use_id.value),
                    details={
                        "logical_point_id": point.logical_id.value,
                        "product_use_id": use_id.value,
                    },
                )
            )
    if problems:
        raise ProviderContractError(problems)

    return ClosedMeasurementProductValues(
        selected,
        tuple(
            ClosedMeasurementProductValue(
                point,
                selected.product_use(use_id),
                selected.product_for_use(use_id),
                by_key[(point.logical_id, use_id)].value,
            )
            for point in points
            for use_id in selected.product_use_ids
        ),
    )


def _measurement_product_inventory(
    linked_points: MaterializedLinkedPointSet,
) -> tuple[tuple[ProductUse, ...], dict[ProductUseId, ProductDef]]:
    linked_plan = linked_points.linked_plan
    uses = tuple(linked_plan.product_uses)
    products_by_id = {product.id: product for product in linked_plan.product_defs}
    products = {use.id: products_by_id[use.product_id] for use in uses}
    return uses, products


def measurement_value_contract_fingerprint(
    linked_points: MaterializedLinkedPointSet,
) -> str:
    """Identify one transient point/use/product contract independent of objects."""

    uses, products = _measurement_product_inventory(linked_points)
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.measurement_value_contract.v1",
                "points": [
                    {
                        "logical_point_id": point.logical_id.value,
                        "row": point.row,
                    }
                    for point in linked_points.point_domain.points
                ],
                "product_uses": [
                    {
                        "product_use_id": use.id.value,
                        "product_id": use.product_id.qualified_name,
                        "product": products[use.id],
                    }
                    for use in uses
                ],
            }
        )
    )


def _carrier_selection_problems(
    use_id: ProductUseId,
    product: ProductDef,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    details = {
        "product_use_id": use_id.value,
        "product_id": product.id.qualified_name,
    }
    if product.kind != "observable":
        problems.append(
            _selection_problem(
                "measurement_value_product_kind_unsupported",
                f"measurement values cannot carry {product.kind!r} products",
                path=("product_uses", use_id.value, "product", "kind"),
                details={**details, "actual": product.kind},
            )
        )
    if not product.axes and product.dtype in {"bool", "string"}:
        problems.append(
            _selection_problem(
                "measurement_value_scalar_dtype_unsupported",
                f"measurement values have no scalar {product.dtype!r} carrier",
                path=("product_uses", use_id.value, "product", "dtype"),
                details={**details, "actual": product.dtype},
            )
        )
    return tuple(problems)


def _measurement_contract_problems(
    value: MeasurementValue,
    *,
    product: ProductDef,
    candidate_index: int,
    logical_point_id: LogicalPointId,
    product_use_id: ProductUseId,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for issue in measurement_value_contract_issues(
        value,
        expected_dtype=product.dtype,
        expected_unit=product.unit,
        expected_shape=tuple(axis.size for axis in product.axes),
    ):
        problems.append(
            _value_problem(
                f"measurement_value_{issue.code.value}",
                "measurement value does not satisfy its logical product contract",
                path=("candidates", candidate_index, *issue.path),
                details={
                    "logical_point_id": logical_point_id.value,
                    "product_use_id": product_use_id.value,
                    "product_id": product.id.qualified_name,
                    "expected": _problem_detail(issue.expected),
                    "actual": _problem_detail(issue.actual),
                },
            )
        )
    return tuple(problems)


def _selection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return compiler_problem(
        code,
        message,
        model_location("measurement_values", *path),
        category=category,
        details=details,
    )


def _value_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object] | None = None,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.EXECUTION,
        location=model_location("measurement_values", *path),
        details=details,
    )


def _problem_detail(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, tuple):
        selected = cast("tuple[object, ...]", value)
        return [_problem_detail(item) for item in selected]
    return repr(value)
