"""Host implementation selection for authored domain measurement transforms.

Core projects authored product edges into a :class:`DomainBatchContext`.
Laboratory adapters may inspect those immutable capabilities and bind host
implementations, but they cannot create or rewire transform declarations.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from scopecat.measurements.contracts import validated_measurement_value_copy
from scopecat.measurements.semantics import MeasurementTransformSemanticContract
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.domain.view import (
    DomainMeasurementTransform,
    DomainPointRef,
    DomainTransformInputPort,
    DomainTransformOutputPort,
)

type DomainTransformRate = Literal["point"]
type DomainHostTransformValidator = Callable[["DomainMeasurementTransform"], None]
type DomainHostTransformKernel = Callable[
    ["DomainHostTransformCall"],
    Mapping[str, MeasurementValue],
]


@dataclass(frozen=True, slots=True)
class DomainHostTransformCall:
    """One point-local SDK call delivered to a laboratory host kernel."""

    transform: DomainMeasurementTransform
    point: DomainPointRef
    inputs: Mapping[str, MeasurementValue] = field(repr=False)

    def __post_init__(self) -> None:
        candidates = dict(self.inputs)
        expected = {port.id for port in self.transform.inputs}
        if set(candidates) != expected:
            msg = "domain host transform call inputs must exactly match input roles"
            raise ValueError(msg)
        try:
            selected = {
                port_id: validated_measurement_value_copy(value)
                for port_id, value in candidates.items()
            }
        except (AttributeError, TypeError, ValueError) as error:
            msg = "domain host transform call inputs must be measurement values"
            raise TypeError(msg) from error
        object.__setattr__(self, "inputs", MappingProxyType(selected))

    @property
    def transform_id(self) -> str:
        return self.transform.id

    @property
    def semantic(self) -> MeasurementTransformSemanticContract:
        return self.transform.semantic

    @property
    def input_ports(self) -> tuple[DomainTransformInputPort, ...]:
        return self.transform.inputs

    @property
    def output_ports(self) -> tuple[DomainTransformOutputPort, ...]:
        return self.transform.outputs

    @property
    def point_index(self) -> int:
        return self.point.ordinal


@dataclass(frozen=True, slots=True)
class DomainHostTransformImplementation:
    """Transient SDK host callable for one semantic transform family."""

    id: str
    semantic_id: str
    semantic_version: str
    implementation_fingerprint: str
    validate_transform: DomainHostTransformValidator = field(
        repr=False,
        compare=False,
    )
    kernel: DomainHostTransformKernel = field(repr=False, compare=False)
    rate: DomainTransformRate = "point"

    def __post_init__(self) -> None:
        text_fields = (
            self.id,
            self.semantic_id,
            self.semantic_version,
            self.implementation_fingerprint,
        )
        if not all(text_fields):
            msg = "domain host transform implementation fields must be non-empty"
            raise ValueError(msg)
        if self.rate != "point":
            msg = "domain host transform implementations support point rate only"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainHostTransformBinding:
    """Explicit host implementation selection for one SDK transform."""

    transform: DomainMeasurementTransform
    implementation: DomainHostTransformImplementation

    def __post_init__(self) -> None:
        semantic = self.transform.semantic
        implementation = self.implementation
        if (
            implementation.semantic_id != semantic.id
            or implementation.semantic_version != semantic.version
            or implementation.rate != self.transform.rate
        ):
            msg = "domain host transform implementation is semantically incompatible"
            raise ValueError(msg)


__all__ = [
    "DomainHostTransformBinding",
    "DomainHostTransformCall",
    "DomainHostTransformImplementation",
    "DomainMeasurementTransform",
    "DomainTransformInputPort",
    "DomainTransformOutputPort",
    "DomainTransformRate",
    "MeasurementTransformSemanticContract",
]
