"""Canonical logical measurement values at the RunProgram boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.typed.products import ProductDef
from scopecat.execution.points import RunPoint, RunPointContract
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.measurements.contracts import (
    measurement_value_contract_issues,
    validated_measurement_value_copy,
)
from scopecat.records.measurement import MeasurementValue


@dataclass(frozen=True, slots=True)
class MeasurementValueCatalog:
    """Point-independent measurement product contract for one experiment."""

    point_contract: RunPointContract
    product_uses: tuple[ProductUse, ...]
    product_defs: tuple[ProductDef, ...]
    product_use_ids: tuple[ProductUseId, ...] = field(init=False)
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

    def __post_init__(self) -> None:
        products_by_id = {product.id: product for product in self.product_defs}
        use_by_id = {use.id: use for use in self.product_uses}
        product_by_use_id = {
            use.id: products_by_id[use.product_id] for use in self.product_uses
        }
        problems = tuple(
            problem
            for use in self.product_uses
            for problem in _catalog_carrier_problems(
                use.id,
                product_by_use_id[use.id],
            )
        )
        if problems:
            raise CheckFailed(problems)
        object.__setattr__(
            self,
            "product_use_ids",
            tuple(use.id for use in self.product_uses),
        )
        object.__setattr__(self, "_use_by_id", MappingProxyType(use_by_id))
        object.__setattr__(
            self,
            "_product_by_use_id",
            MappingProxyType(product_by_use_id),
        )
        object.__setattr__(
            self,
            "contract_fingerprint",
            stable_content_hash(
                content_fingerprint(
                    {
                        "schema": "scopecat.measurement_value_contract.v1",
                        "experiment_id": self.point_contract.experiment_id,
                        "experiment_kind": self.point_contract.experiment_kind,
                        "coordinate_ids": self.point_contract.coordinate_ids,
                        "product_uses": [
                            {
                                "product_use_id": use.id.value,
                                "product_id": use.product_id.qualified_name,
                                "product": products_by_id[use.product_id],
                            }
                            for use in self.product_uses
                        ],
                    }
                )
            ),
        )

    def product_use(self, product_use_id: ProductUseId) -> ProductUse:
        try:
            return self._use_by_id[product_use_id]
        except KeyError as error:
            msg = f"product use {product_use_id.value!r} is not in the catalog"
            raise KeyError(msg) from error

    def product_for_use(self, product_use_id: ProductUseId) -> ProductDef:
        try:
            return self._product_by_use_id[product_use_id]
        except KeyError as error:
            msg = f"product use {product_use_id.value!r} is not in the catalog"
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

    point: RunPoint = field(repr=False)
    product_use: ProductUse = field(repr=False)
    _product: ProductDef = field(repr=False)
    _value: MeasurementValue = field(repr=False)

    def __init__(
        self,
        point: RunPoint,
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

    catalog: MeasurementValueCatalog = field(repr=False)
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
        return self.catalog.product_use_ids

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


def seal_measurement_values(
    catalog: MeasurementValueCatalog,
    candidates: Sequence[MeasurementValueCandidate],
    *,
    points: Sequence[RunPoint],
) -> ClosedMeasurementProductValues:
    """Close the canonical logical value inventory for one admitted coverage."""

    supplied = tuple(candidates)
    points = tuple(points)
    expected_keys = {
        (point.logical_id, use_id)
        for point in points
        for use_id in catalog.product_use_ids
    }
    point_ids = {point.logical_id for point in points}
    use_ids = set(catalog.product_use_ids)
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
                    "logical measurement values reference a foreign product use",
                    path=("candidates", candidate_index, "product_use_id"),
                )
            )
        if key not in expected_keys:
            continue
        product = catalog.product_for_use(candidate.product_use_id)
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
        for use_id in catalog.product_use_ids:
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
        catalog,
        tuple(
            ClosedMeasurementProductValue(
                point,
                catalog.product_use(use_id),
                catalog.product_for_use(use_id),
                by_key[(point.logical_id, use_id)].value,
            )
            for point in points
            for use_id in catalog.product_use_ids
        ),
    )


def _catalog_carrier_problems(
    use_id: ProductUseId,
    product: ProductDef,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    details = {
        "product_use_id": use_id.value,
        "product_id": product.id.qualified_name,
    }
    if not product.axes and product.dtype in {"bool", "string"}:
        problems.append(
            _catalog_problem(
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


def _catalog_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object] | None = None,
) -> Problem:
    return compiler_problem(
        code,
        message,
        model_location("measurement_values", *path),
        details=details,
    )


def _value_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object] | None = None,
) -> Problem:
    return problem(
        code,
        message,
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
