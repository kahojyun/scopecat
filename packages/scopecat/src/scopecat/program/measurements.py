"""Point-local measurement postprocessor contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.symbols import SymbolId
from scopecat.program.measurement_contracts import (
    MeasurementPostprocessorKernel,
    SingleMeasurementPostprocessorKernel,
)
from scopecat.program.products import ProductRef
from scopecat.program.values import ComputeInput, capture_compute_input_internal

if TYPE_CHECKING:
    from scopecat.records.measurement import MeasurementValue


@dataclass(frozen=True, slots=True)
class MeasurementPostprocessor:
    """One direct Python calculation from measured products."""

    id: str
    input_bindings: tuple[tuple[str, ProductId], ...]
    output_bindings: tuple[tuple[str, ProductId], ...]
    kernel: MeasurementPostprocessorKernel = field(repr=False, compare=False)
    value_input_bindings: tuple[tuple[str, ComputeInput], ...] = ()
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
            raise ValueError("measurement postprocessor ids must be non-empty")
        if not self.input_bindings:
            raise ValueError("measurement postprocessors require a measured input")
        if any(not name for name, _product in self.input_bindings):
            raise ValueError("measurement postprocessor input names must be non-empty")
        if any(not name for name, _value in self.value_input_bindings):
            raise ValueError("measurement postprocessor value names must be non-empty")
        if any(not role for role, _product in self.output_bindings):
            raise ValueError("measurement postprocessor output roles must be non-empty")
        if not self.output_bindings:
            raise ValueError("measurement postprocessors require at least one output")
        if any(not segment for segment in self.scope):
            raise ValueError(
                "measurement postprocessor scope must contain non-empty strings"
            )
        input_ids = {product_id for _name, product_id in self.input_bindings}
        output_ids = {product_id for _role, product_id in self.output_bindings}
        if input_ids & output_ids:
            raise ValueError(
                "measurement postprocessor inputs and outputs must be distinct"
            )
        _require_unique(
            "measurement postprocessor input",
            (
                *(name for name, _product in self.input_bindings),
                *(name for name, _value in self.value_input_bindings),
            ),
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
    kernel: SingleMeasurementPostprocessorKernel,
) -> MeasurementPostprocessor:
    """Build the program IR recorded by a typed measurement producer."""

    def mapped_kernel(
        values: Mapping[str, object],
    ) -> Mapping[
        str,
        MeasurementValue,
    ]:
        return kernel(cast("MeasurementValue", values["input"]))

    return create_measurement_compute_internal(
        id,
        inputs={"input": input},
        outputs=outputs,
        kernel=mapped_kernel,
    )


def create_measurement_compute_internal(
    id: str,
    *,
    inputs: Mapping[str, ProductRef],
    value_inputs: Mapping[str, ComputeInput] | None = None,
    outputs: Mapping[str, ProductRef],
    kernel: MeasurementPostprocessorKernel,
) -> MeasurementPostprocessor:
    """Build a multi-input point-local measurement computation."""

    return MeasurementPostprocessor(
        id=id,
        input_bindings=tuple(
            (name, product.product_id) for name, product in inputs.items()
        ),
        value_input_bindings=tuple(
            (name, capture_compute_input_internal(value))
            for name, value in (value_inputs or {}).items()
        ),
        output_bindings=tuple(
            (role, product.product_id) for role, product in outputs.items()
        ),
        kernel=kernel,
        input_product_origins=tuple(
            (name, product.origin) for name, product in inputs.items()
        ),
        output_product_origins=tuple(
            (role, product.origin) for role, product in outputs.items()
        ),
    )


def _require_unique(label: str, values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} roles must be unique")
