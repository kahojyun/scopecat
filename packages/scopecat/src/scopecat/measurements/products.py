"""Logical measurement product declarations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.measurement_values import MeasurementDType
from scopecat.kernel.product_identity import ProductId


def _empty_metadata() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class ProductAxisDef:
    """One axis in a logical product's output schema."""

    id: str
    dimension_id: str
    kind: str
    size: int | None
    dimension_label: str | None = None
    unit: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if (
            not self.id
            or not self.dimension_id
            or not self.kind
            or (self.size is not None and self.size <= 0)
        ):
            msg = (
                "product axes require non-empty ids, dimension ids, and kinds "
                "and positive sizes when fixed"
            )
            raise ValueError(msg)
        if self.dimension_id == "point":
            msg = "product axis dimension id point is reserved"
            raise ValueError(msg)
        if self.dimension_label is not None and not self.dimension_label:
            msg = "product axis dimension label must be non-empty when provided"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata, path=f"product axis {self.id!r} metadata"
            ),
        )


@dataclass(frozen=True, slots=True)
class ProductDef:
    """Available logical product independent of recording and target realization."""

    id: ProductId
    unit: str | None = None
    dtype: MeasurementDType = "float64"
    axes: tuple[ProductAxisDef, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if self.dtype in {"bool", "string"} and self.unit is not None:
            msg = f"{self.dtype} measurement products cannot have a unit"
            raise ValueError(msg)
        object.__setattr__(self, "axes", tuple(self.axes))
        axis_ids = [axis.id for axis in self.axes]
        if len(axis_ids) != len(set(axis_ids)):
            msg = "product axes must use distinct acquisition-local ids"
            raise ValueError(msg)
        dimension_ids = [axis.dimension_id for axis in self.axes]
        if len(dimension_ids) != len(set(dimension_ids)):
            msg = "product axes must use distinct dataset dimensions"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(self.metadata, path=f"product {self.id!s} metadata"),
        )
