"""Producer-neutral model for native measurement-transform graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import override

from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.product_identity import ProductUseId
from scopecat.measurements.semantics import (
    MeasurementTransformSemanticContract,
)


@dataclass(frozen=True, slots=True)
class NativeMeasurementTransformId:
    """Nominal runtime identity lowered from an authored transform."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            msg = "measurement transform identity must be non-empty"
            raise ValueError(msg)

    @override
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class MeasurementTransformInputPort:
    """Typed consumer edge from one semantic input role to one logical slot."""

    id: str
    product_use_id: ProductUseId
    product: ProductDef = field(repr=False)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "measurement transform port id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class MeasurementTransformOutputPort:
    """Typed producer edge fanning one semantic output out to demanded slots."""

    id: str
    product_use_ids: tuple[ProductUseId, ...]
    product: ProductDef = field(repr=False)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "measurement transform output port id must be non-empty"
            raise ValueError(msg)
        if len(self.product_use_ids) != len(set(self.product_use_ids)):
            msg = "measurement transform output product uses must be unique"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class MeasurementTransformDef:
    """One multi-input, multi-output pure transform declaration."""

    id: NativeMeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    inputs: tuple[MeasurementTransformInputPort, ...]
    outputs: tuple[MeasurementTransformOutputPort, ...]
