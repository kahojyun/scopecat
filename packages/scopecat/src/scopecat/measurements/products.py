"""Logical measurement product declarations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.product_identity import ProductId
from scopecat.measurements.results import MeasurementDType


def _empty_metadata() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class ProductAxisDef:
    """One axis in a logical product's output schema."""

    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.id or not self.kind or self.size <= 0:
            msg = "product axes require non-empty ids and kinds and positive sizes"
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
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(self.metadata, path=f"product {self.id!s} metadata"),
        )
