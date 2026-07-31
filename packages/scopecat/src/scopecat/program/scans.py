"""Point-domain scan intents shared by authoring and compilation."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Scalar
from scopecat.program.expressions import ParameterLookupUse
from scopecat.program.parameters import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.program.value_refs import (
    ScalarOperand,
    ValueRef,
    internal_value_ref_parameter_contracts,
    internal_value_ref_parameter_lookup,
)

type ScanValue = Quantity | EntityRef | str | int | float | bool | None
type ScanCenter = ValueRef | Quantity


class Scan:
    """Opaque public handle for one scan axis."""

    __slots__ = ()

    def __init__(self) -> None:
        msg = "Scan is an opaque handle; create scans with scopecat scan factories"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class ValuesScanSource:
    values: tuple[ScanValue, ...]


@dataclass(frozen=True, slots=True)
class AroundScanSource:
    """A fixed-count linear axis around one explicit center."""

    center: ScanCenter
    span: Quantity
    points: int


type ScanSource = ValuesScanSource | AroundScanSource


@dataclass(frozen=True, slots=True, repr=False)
class AxisSpec(Scan):
    id: str
    value_type: Scalar
    source: ScanSource
    parameter_lookup: ValueRef | None = None


def parameter_cell_lookup(
    axis: AxisSpec,
) -> tuple[
    ParameterLookupUse,
    tuple[tuple[str, ScalarOperand], ...],
]:
    if axis.parameter_lookup is None:
        raise TypeError("scan axis does not overlay a parameter cell")
    lookup = internal_value_ref_parameter_lookup(axis.parameter_lookup)
    assert lookup is not None
    return lookup


def scan_parameter_contracts(scan: AxisSpec) -> tuple[ParameterContract, ...]:
    return merge_parameter_contracts(
        _value_parameter_contracts(scan.parameter_lookup),
        _source_parameter_contracts(scan),
    )


def _source_parameter_contracts(axis: AxisSpec) -> tuple[ParameterContract, ...]:
    source = axis.source
    if not isinstance(source, AroundScanSource):
        return ()
    return _value_parameter_contracts(source.center)


def _value_parameter_contracts(value: object) -> tuple[ParameterContract, ...]:
    return (
        internal_value_ref_parameter_contracts(value)
        if isinstance(value, ValueRef)
        else ()
    )
