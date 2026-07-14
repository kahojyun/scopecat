"""Producer-neutral model for native measurement-transform graphs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.linking.linked import MaterializedLinkedPointSet
from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.product_identity import ProductUseId
from scopecat.measurements.semantics import (
    MeasurementTransformRate,
    MeasurementTransformSemanticContract,
)


@dataclass(frozen=True, slots=True)
class NativeMeasurementTransformId:
    """Nominal runtime identity lowered from an authored transform."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.value), str):
            msg = "measurement transform identity must be a string"
            raise TypeError(msg)
        if not self.value:
            msg = "measurement transform identity must be non-empty"
            raise ValueError(msg)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class MeasurementTransformInputPort:
    """Typed consumer edge from one semantic input role to one logical slot."""

    id: str
    product_use_id: ProductUseId
    product: ProductDef = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.id), str):
            msg = "measurement transform port id must be a string"
            raise TypeError(msg)
        if not self.id:
            msg = "measurement transform port id must be non-empty"
            raise ValueError(msg)
        if not isinstance(cast("object", self.product_use_id), ProductUseId):
            msg = "measurement transform ports require ProductUseId values"
            raise TypeError(msg)
        if not isinstance(cast("object", self.product), ProductDef):
            msg = "measurement transform ports require ProductDef contracts"
            raise TypeError(msg)
        object.__setattr__(self, "product", deepcopy(self.product))


@dataclass(frozen=True, slots=True)
class MeasurementTransformOutputPort:
    """Typed producer edge fanning one semantic output out to demanded slots."""

    id: str
    product_use_ids: tuple[ProductUseId, ...]
    product: ProductDef = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.id), str):
            msg = "measurement transform output port id must be a string"
            raise TypeError(msg)
        if not self.id:
            msg = "measurement transform output port id must be non-empty"
            raise ValueError(msg)
        selected_use_ids = tuple(self.product_use_ids)
        if any(
            not isinstance(cast("object", use_id), ProductUseId)
            for use_id in selected_use_ids
        ):
            msg = "measurement transform output ports require ProductUseId values"
            raise TypeError(msg)
        if len(selected_use_ids) != len(set(selected_use_ids)):
            msg = "measurement transform output product uses must be unique"
            raise ValueError(msg)
        if not isinstance(cast("object", self.product), ProductDef):
            msg = "measurement transform output ports require ProductDef contracts"
            raise TypeError(msg)
        object.__setattr__(self, "product_use_ids", selected_use_ids)
        object.__setattr__(self, "product", deepcopy(self.product))


@dataclass(frozen=True, slots=True)
class MeasurementTransformDef:
    """One multi-input, multi-output pure transform declaration."""

    id: NativeMeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    rate: MeasurementTransformRate
    inputs: tuple[MeasurementTransformInputPort, ...]
    outputs: tuple[MeasurementTransformOutputPort, ...]

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.id), NativeMeasurementTransformId):
            msg = "measurement transforms require NativeMeasurementTransformId"
            raise TypeError(msg)
        if not isinstance(
            cast("object", self.semantic), MeasurementTransformSemanticContract
        ):
            msg = "measurement transforms require a semantic contract"
            raise TypeError(msg)
        if self.rate != "point":
            msg = "measurement transform rate must be point"
            raise ValueError(msg)
        object.__setattr__(self, "semantic", self.semantic.model_copy(deep=True))
        selected_inputs = tuple(self.inputs)
        selected_outputs = tuple(self.outputs)
        if any(
            not isinstance(cast("object", port), MeasurementTransformInputPort)
            for port in selected_inputs
        ) or any(
            not isinstance(cast("object", port), MeasurementTransformOutputPort)
            for port in selected_outputs
        ):
            msg = "measurement transform inputs and outputs require typed ports"
            raise TypeError(msg)
        object.__setattr__(self, "inputs", selected_inputs)
        object.__setattr__(self, "outputs", selected_outputs)


@dataclass(frozen=True, slots=True, init=False)
class VerifiedMeasurementTransformGraph:
    """Closed typed DAG with canonical topological node order."""

    linked_points: MaterializedLinkedPointSet = field(repr=False)
    transforms: tuple[MeasurementTransformDef, ...]
    linked_contract_fingerprint: str
    contract_fingerprint: str

    def __init__(
        self,
        linked_points: MaterializedLinkedPointSet,
        transforms: tuple[MeasurementTransformDef, ...],
        linked_contract_fingerprint: str,
        contract_fingerprint: str,
    ) -> None:
        object.__setattr__(self, "linked_points", linked_points)
        object.__setattr__(self, "transforms", transforms)
        object.__setattr__(
            self,
            "linked_contract_fingerprint",
            linked_contract_fingerprint,
        )
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)


__all__ = [
    "MeasurementTransformDef",
    "MeasurementTransformInputPort",
    "MeasurementTransformOutputPort",
    "NativeMeasurementTransformId",
    "VerifiedMeasurementTransformGraph",
]
