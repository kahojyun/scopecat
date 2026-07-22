"""Authored pure measurement transforms over module-local products."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.authoring._products import ProductRef
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
    scope: tuple[str, ...] = ()
    # Origins are authoring-only; compiler bindings remain plain ProductIds.
    input_product_origins: tuple[tuple[str, tuple[object, ...]], ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    output_product_origins: tuple[tuple[str, tuple[object, ...]], ...] = field(
        default=(),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("measurement transform ids must be non-empty")
        if any(not role for role, _product in self.input_bindings):
            raise ValueError("measurement transform input roles must be non-empty")
        if any(not role for role, _product in self.output_bindings):
            raise ValueError("measurement transform output roles must be non-empty")
        if not self.output_bindings:
            raise ValueError("measurement transforms require at least one output")
        if any(not segment for segment in self.scope):
            raise ValueError(
                "measurement transform scope must contain non-empty strings"
            )
        _require_unique(
            "measurement transform input",
            tuple(role for role, _product in self.input_bindings),
        )
        _require_unique(
            "measurement transform output",
            tuple(role for role, _product in self.output_bindings),
        )

    @property
    def symbol_id(self) -> SymbolId:
        return SymbolId(scope=self.scope, local_id=self.id)


def measurement_transform(
    id: str,  # noqa: A002
    *,
    semantic: MeasurementTransformSemanticContract,
    inputs: Mapping[str, str | ProductRef] | None = None,
    outputs: Mapping[str, str | ProductRef],
) -> MeasurementTransform:
    """Declare one ordered pure transform over products visible to a module."""

    selected_inputs = inputs or {}
    for label, bindings in (("inputs", selected_inputs), ("outputs", outputs)):
        if any(
            not role or (isinstance(product, str) and not product)
            for role, product in bindings.items()
        ):
            msg = (
                f"measurement transform {label} require non-empty role and product ids"
            )
            raise ValueError(msg)
    return MeasurementTransform(
        id=id,
        semantic=semantic,
        input_bindings=tuple(
            (role, _binding_product_id(product))
            for role, product in selected_inputs.items()
        ),
        output_bindings=tuple(
            (role, _binding_product_id(product)) for role, product in outputs.items()
        ),
        input_product_origins=tuple(
            (role, product.origin)
            for role, product in selected_inputs.items()
            if isinstance(product, ProductRef)
        ),
        output_product_origins=tuple(
            (role, product.origin)
            for role, product in outputs.items()
            if isinstance(product, ProductRef)
        ),
    )


def _require_unique(label: str, values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} roles must be unique")


def _binding_product_id(product: str | ProductRef) -> ProductId:
    return (
        product.product_id if isinstance(product, ProductRef) else product_id(product)
    )
