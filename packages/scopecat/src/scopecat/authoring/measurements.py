"""Authored pure measurement transforms over module-local products."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from scopecat.kernel.product_identity import ProductId, product_id
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.semantics import MeasurementTransformSemanticContract


@dataclass(frozen=True, slots=True)
class MeasurementTransform:
    """One pure point-local product transform in an authored module."""

    id: str
    semantic: MeasurementTransformSemanticContract
    input_bindings: tuple[tuple[str, ProductId], ...] = ()
    output_bindings: tuple[tuple[str, ProductId], ...] = ()
    rate: Literal["point"] = "point"
    scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _is_non_empty_string(cast("object", self.id)):
            raise ValueError("measurement transform ids must be non-empty")
        if not isinstance(
            cast("object", self.semantic),
            MeasurementTransformSemanticContract,
        ):
            msg = "measurement transforms require a semantic contract"
            raise TypeError(msg)
        if not _valid_bindings(cast("object", self.input_bindings)):
            msg = "measurement transform inputs require named local ProductId values"
            raise TypeError(msg)
        if not _valid_bindings(cast("object", self.output_bindings)):
            msg = "measurement transform outputs require named local ProductId values"
            raise TypeError(msg)
        if not self.output_bindings:
            raise ValueError("measurement transforms require at least one output")
        if self.rate != "point":
            raise ValueError("authored measurement transforms support point rate only")
        if not _is_string_tuple(cast("object", self.scope)):
            msg = "measurement transform scope must contain non-empty strings"
            raise TypeError(msg)
        _require_unique(
            "measurement transform input",
            tuple(role for role, _product in self.input_bindings),
        )
        _require_unique(
            "measurement transform output",
            tuple(role for role, _product in self.output_bindings),
        )
        object.__setattr__(self, "semantic", self.semantic.model_copy(deep=True))

    @property
    def symbol_id(self) -> SymbolId:
        return SymbolId(scope=self.scope, local_id=self.id)


def measurement_transform(
    id: str,  # noqa: A002
    *,
    semantic: MeasurementTransformSemanticContract,
    inputs: Mapping[str, str] | None = None,
    outputs: Mapping[str, str],
    rate: Literal["point"] = "point",
) -> MeasurementTransform:
    """Declare one ordered pure transform over module-local product names."""

    if inputs is not None and not isinstance(cast("object", inputs), Mapping):
        raise TypeError("measurement transform inputs must be a mapping")
    if not isinstance(cast("object", outputs), Mapping):
        raise TypeError("measurement transform outputs must be a mapping")
    selected_inputs = inputs or {}
    for label, bindings in (("inputs", selected_inputs), ("outputs", outputs)):
        if any(
            not _is_non_empty_string(cast("object", role))
            or not _is_non_empty_string(cast("object", product_name))
            for role, product_name in bindings.items()
        ):
            msg = (
                f"measurement transform {label} require non-empty role and "
                "local product ids"
            )
            raise TypeError(msg)
    return MeasurementTransform(
        id=id,
        semantic=semantic,
        input_bindings=tuple(
            (role, product_id(product_name))
            for role, product_name in selected_inputs.items()
        ),
        output_bindings=tuple(
            (role, product_id(product_name)) for role, product_name in outputs.items()
        ),
        rate=rate,
    )


def _require_unique(label: str, values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} roles must be unique")


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_string_tuple(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    return all(_is_non_empty_string(item) for item in cast("tuple[object, ...]", value))


def _valid_bindings(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    for binding in cast("tuple[object, ...]", value):
        if not isinstance(binding, tuple):
            return False
        selected = cast("tuple[object, ...]", binding)
        if len(selected) != 2:
            return False
        role, product = selected
        if not _is_non_empty_string(role) or not isinstance(product, ProductId):
            return False
    return True


__all__ = ["MeasurementTransform", "measurement_transform"]
