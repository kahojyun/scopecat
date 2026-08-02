"""Point-local measurement postprocessor contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.postprocessor_contract import (
    MeasurementPostprocessorKernel,
)
from scopecat.program.products import ProductRef


@dataclass(frozen=True, slots=True)
class MeasurementPostprocessor:
    """One direct Python calculation from one measured product."""

    id: str
    input_binding: ProductId
    output_bindings: tuple[tuple[str, ProductId], ...]
    kernel: MeasurementPostprocessorKernel = field(repr=False, compare=False)
    scope: tuple[str, ...] = ()
    # Origins are authoring-only; compiler bindings remain plain ProductIds.
    input_product_origin: tuple[object, ...] | None = field(
        default=None,
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
            raise ValueError("measurement postprocessor ids must be non-empty")
        if any(not role for role, _product in self.output_bindings):
            raise ValueError("measurement postprocessor output roles must be non-empty")
        if not self.output_bindings:
            raise ValueError("measurement postprocessors require at least one output")
        if any(not segment for segment in self.scope):
            raise ValueError(
                "measurement postprocessor scope must contain non-empty strings"
            )
        if self.input_binding in {
            product_id for _role, product_id in self.output_bindings
        }:
            raise ValueError(
                "measurement postprocessor input and outputs must be distinct"
            )
        _require_unique(
            "measurement postprocessor output",
            tuple(role for role, _product in self.output_bindings),
        )

    @property
    def symbol_id(self) -> SymbolId:
        return SymbolId(scope=self.scope, local_id=self.id)


def create_measurement_postprocessor_internal(
    id: str,
    *,
    input: ProductRef,
    outputs: Mapping[str, ProductRef],
    kernel: MeasurementPostprocessorKernel,
) -> MeasurementPostprocessor:
    """Build the program IR recorded by a typed measurement producer."""

    return MeasurementPostprocessor(
        id=id,
        input_binding=input.product_id,
        output_bindings=tuple(
            (role, product.product_id) for role, product in outputs.items()
        ),
        kernel=kernel,
        input_product_origin=input.origin,
        output_product_origins=tuple(
            (role, product.origin) for role, product in outputs.items()
        ),
    )


def _require_unique(label: str, values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} roles must be unique")
