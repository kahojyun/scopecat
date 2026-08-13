"""Canonical logical measurement values at the RunProgram boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import ProviderContractError
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.points import AcceptedRunPoint, RunPointContract
from scopecat.measurements.products import ProductDef
from scopecat.measurements.records import measurement_axis_scalar
from scopecat.program.point_domain import (
    PointAxis,
    PointAxisRange,
    PointAxisValues,
)
from scopecat.records.measurement import (
    InstrumentAcquisitionEvidence,
    MeasurementValue,
)


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
                        "schema": "scopecat.measurement_value_contract.v7",
                        "experiment_id": self.point_contract.experiment_id,
                        "experiment_kind": self.point_contract.experiment_kind,
                        "point_count": self.point_contract.point_count,
                        "point_limit": self.point_contract.point_limit,
                        "coordinate_columns": self.point_contract.coordinate_columns,
                        "domain_layout": self.point_contract.domain_layout,
                        "domain_axes": [
                            _point_axis_contract(axis)
                            for axis in self.point_contract.domain_axes
                        ],
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


def _point_axis_contract(axis: PointAxis[Quantity]) -> dict[str, object]:
    source = axis.source
    if isinstance(source, PointAxisValues):
        source_contract: dict[str, object] = {
            "kind": "values",
            "values": tuple(measurement_axis_scalar(value) for value in source.values),
        }
    elif isinstance(source, PointAxisRange):
        source_contract = {
            "kind": "range",
            "start": measurement_axis_scalar(source.start),
            "stop": measurement_axis_scalar(source.stop),
            "count": source.count,
        }
    else:
        source_contract = {
            "kind": "linear",
            "center": measurement_axis_scalar(source.center),
            "span": measurement_axis_scalar(source.span),
            "count": source.count,
        }
    return {
        "id": axis.id,
        "value_type": axis.value_type,
        "source": source_contract,
    }


@dataclass(frozen=True, slots=True)
class MeasurementValueCandidate:
    """Producer candidate keyed only by logical point and product-use identity."""

    logical_point_id: LogicalPointId
    product_use_id: ProductUseId
    value: MeasurementValue
    evidence: InstrumentAcquisitionEvidence | None = None


@dataclass(frozen=True, slots=True, init=False)
class ClosedMeasurementProductValue:
    """One checked host value with producer-neutral logical identity."""

    point: AcceptedRunPoint = field(repr=False)
    product_use: ProductUse = field(repr=False)
    _product: ProductDef = field(repr=False)
    _value: MeasurementValue = field(repr=False)
    _evidence: InstrumentAcquisitionEvidence | None = field(repr=False)

    def __init__(
        self,
        point: AcceptedRunPoint,
        product_use: ProductUse,
        product: ProductDef,
        value: MeasurementValue,
        evidence: InstrumentAcquisitionEvidence | None,
    ) -> None:
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "product_use", product_use)
        object.__setattr__(self, "_product", product)
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_evidence", evidence)

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
        return self._value

    @property
    def evidence(self) -> InstrumentAcquisitionEvidence | None:
        return self._evidence


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
    points: Sequence[AcceptedRunPoint],
) -> ClosedMeasurementProductValues:
    """Close the canonical logical value inventory for one admitted coverage."""

    supplied = tuple(candidates)
    points = tuple(points)
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
                by_key[(point.logical_id, use_id)].evidence,
            )
            for point in points
            for use_id in catalog.product_use_ids
        ),
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
