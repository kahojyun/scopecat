"""Hardware-independent acquisition result contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable

from scopecat.kernel.value_types import Int, Scalar
from scopecat.program.measurement_types import MeasurementDType


class AcquisitionKind(StrEnum):
    """The hardware-independent value produced by an acquisition slot."""

    INTEGRATED_IQ = "integrated_iq"
    CLASSIFIED_STATE = "classified_state"
    RAW_TRACE = "raw_trace"


@runtime_checkable
class BoundedIntegerInput(Protocol):
    """Structural input accepted as a point-local result-dimension extent.

    The protocol keeps the hardware-independent acquisition model independent
    of the quantum authoring package.  ``authoring.ProgramInput`` satisfies it
    structurally.
    """

    @property
    def id(self) -> str: ...

    @property
    def value_type(self) -> Scalar: ...


type QuantumResultDimensionSize = int | BoundedIntegerInput


@dataclass(frozen=True, slots=True)
class QuantumResultDimension:
    """One bounded, acquisition-local dimension other than shot and entity.

    Entity-set results receive their identity-bearing ``entity`` dimension from
    the bound :class:`~scopecat_quantum.authoring.QubitSet`. Dimensions declared
    here describe the value returned by each physical acquisition slot, such as
    repeated captures, feedback rounds, cycles, or raw samples. A symbolic size
    must be a bounded integer input with a positive minimum and finite maximum;
    binding replaces it with the selected point's concrete positive integer.
    """

    id: str
    kind: str
    size: QuantumResultDimensionSize
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("quantum result dimension id must be non-empty")
        if not self.kind.strip():
            raise ValueError("quantum result dimension kind must be non-empty")
        if self.id in {"entity", "point", "shot"}:
            raise ValueError(f"quantum result dimension id {self.id!r} is reserved")
        if self.kind in {"entity", "point", "shot"}:
            raise ValueError(f"quantum result dimension kind {self.kind!r} is reserved")
        if isinstance(self.size, int) and not isinstance(self.size, bool):
            if self.size <= 0:
                raise ValueError("quantum result dimension size must be positive")
        elif isinstance(self.size, BoundedIntegerInput):
            atom = self.size.value_type.atom
            if not isinstance(atom, Int):
                raise TypeError(
                    "quantum result dimension inputs must have an integer type"
                )
            if atom.minimum is None or atom.minimum < 1:
                raise ValueError("quantum result dimension inputs require minimum >= 1")
            if atom.maximum is None:
                raise ValueError(
                    "quantum result dimension inputs require a finite maximum"
                )
        else:
            raise TypeError(
                "quantum result dimension size must be a positive integer or "
                "bounded integer input"
            )
        if self.unit is not None and not self.unit.strip():
            raise ValueError(
                "quantum result dimension unit must be non-empty when provided"
            )

    @property
    def maximum_size(self) -> int:
        """Return the statically visible maximum extent."""

        if isinstance(self.size, int):
            return self.size
        atom = self.size.value_type.atom
        if not isinstance(atom, Int):
            raise AssertionError("symbolic result dimension must have an Int type")
        maximum = atom.maximum
        if maximum is None:
            raise AssertionError("symbolic result dimensions were validated as bounded")
        return maximum

    @property
    def minimum_size(self) -> int:
        """Return the statically visible minimum extent."""

        if isinstance(self.size, int):
            return self.size
        atom = self.size.value_type.atom
        if not isinstance(atom, Int):
            raise AssertionError("symbolic result dimension must have an Int type")
        minimum = atom.minimum
        if minimum is None:
            raise AssertionError("symbolic result dimensions were validated as bounded")
        return minimum

    @property
    def size_input_id(self) -> str | None:
        """Return the source input id for a point-local extent, if any."""

        return None if isinstance(self.size, int) else self.size.id


def _validated_result_dimensions(
    acquisition_kind: AcquisitionKind,
    dimensions: tuple[QuantumResultDimension, ...],
) -> tuple[QuantumResultDimension, ...]:
    selected = tuple(dimensions)
    ids = tuple(dimension.id for dimension in selected)
    if len(set(ids)) != len(ids):
        raise ValueError("quantum result dimension ids must be unique")
    sample_dimensions = tuple(
        dimension for dimension in selected if dimension.kind == "sample"
    )
    if acquisition_kind is AcquisitionKind.RAW_TRACE:
        if len(sample_dimensions) != 1:
            raise ValueError("raw-trace results require exactly one sample dimension")
    elif sample_dimensions:
        raise ValueError("sample dimensions are reserved for raw-trace results")
    return selected


@dataclass(frozen=True, slots=True)
class QuantumResultContract:
    """Logical value and bounded local shape of one quantum acquisition."""

    acquisition_kind: AcquisitionKind
    dtype: MeasurementDType
    unit: str | None
    dimensions: tuple[QuantumResultDimension, ...] = ()

    def __post_init__(self) -> None:
        dimensions = _validated_result_dimensions(
            self.acquisition_kind,
            self.dimensions,
        )
        object.__setattr__(self, "dimensions", dimensions)
        if self.dtype in {"bool", "string"} and self.unit is not None:
            raise ValueError(f"{self.dtype} quantum results cannot have a unit")
        if (
            self.acquisition_kind is AcquisitionKind.INTEGRATED_IQ
            and self.dtype != "complex128"
        ):
            raise ValueError("integrated-IQ results require complex128 values")
        if self.acquisition_kind is AcquisitionKind.CLASSIFIED_STATE and (
            self.dtype != "int64" or self.unit is not None
        ):
            raise ValueError(
                "classified-state results require int64 values without a unit"
            )
        if self.acquisition_kind is AcquisitionKind.RAW_TRACE and self.dtype not in {
            "float64",
            "complex128",
        }:
            raise ValueError("raw-trace results require float64 or complex128 values")

    def with_dimensions(
        self,
        *dimensions: QuantumResultDimension,
    ) -> QuantumResultContract:
        """Return the same value contract with a new bounded local shape."""

        return replace(self, dimensions=dimensions)

    @property
    def is_concrete(self) -> bool:
        """Whether every local dimension has a point-bound integer extent."""

        return all(isinstance(dimension.size, int) for dimension in self.dimensions)


INTEGRATED_IQ_RESULT = QuantumResultContract(
    acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    dtype="complex128",
    unit="ratio",
)


CLASSIFIED_STATE_RESULT = QuantumResultContract(
    acquisition_kind=AcquisitionKind.CLASSIFIED_STATE,
    dtype="int64",
    unit=None,
)


def raw_trace_result(
    samples: QuantumResultDimensionSize,
    /,
    *,
    dimensions: tuple[QuantumResultDimension, ...] = (),
    dtype: MeasurementDType = "complex128",
    unit: str | None = "ratio",
) -> QuantumResultContract:
    """Construct a bounded raw trace with ``sample`` as its innermost axis."""

    return QuantumResultContract(
        acquisition_kind=AcquisitionKind.RAW_TRACE,
        dtype=dtype,
        unit=unit,
        dimensions=(
            *dimensions,
            QuantumResultDimension("sample", "sample", samples),
        ),
    )


__all__ = [
    "CLASSIFIED_STATE_RESULT",
    "INTEGRATED_IQ_RESULT",
    "AcquisitionKind",
    "BoundedIntegerInput",
    "QuantumResultContract",
    "QuantumResultDimension",
    "QuantumResultDimensionSize",
    "raw_trace_result",
]
