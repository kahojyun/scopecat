"""Runtime collect command construction and readback binding."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat._runtime.graph import RuntimePoint
from scopecat._runtime.state import command_channel_bindings
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.instruments.sdk import (
    CollectAxisRequest,
    CollectCommand,
    CollectProductRequest,
    InstrumentReadback,
)
from scopecat.results import MeasurementValue


@dataclass(frozen=True)
class RuntimeCollectInstruction:
    command: CollectCommand
    record_bindings: dict[str, str]


def collect_instruction(
    *,
    point: RuntimePoint,
    instrument_id: str,
    point_count: int,
) -> RuntimeCollectInstruction | None:
    plans = [
        instruction
        for instruction in point.collect
        if instruction.instrument_id is None
        or instruction.instrument_id == instrument_id
    ]
    bindings = [binding for instruction in plans for binding in instruction.products]
    if not bindings:
        return None
    record_bindings = {binding.product_key: binding.record_id for binding in bindings}
    return RuntimeCollectInstruction(
        record_bindings=record_bindings,
        command=CollectCommand(
            instrument_id=instrument_id,
            point_index=point.point_index,
            point_count=point_count,
            requests=[
                CollectProductRequest(
                    id=binding.product_key,
                    capability_id=binding.capability,
                    unit=binding.unit,
                    dtype=binding.dtype,
                    dimensions=[
                        CollectAxisRequest(
                            id=axis.id,
                            kind=axis.kind,
                            size=axis.size,
                            unit=axis.unit,
                            metadata=axis.metadata,
                        )
                        for axis in binding.axes
                    ],
                    channel_bindings=command_channel_bindings(
                        resource_id=instrument_id,
                        capability_id=binding.capability,
                        route_bindings=list(point.route_bindings),
                    ),
                    metadata=binding.metadata,
                )
                for binding in bindings
            ],
        ),
    )


def merge_readback(
    *,
    point_index: int,
    command: CollectCommand,
    record_bindings: dict[str, str],
    readback: InstrumentReadback,
    observables: dict[str, MeasurementValue],
    instruments: list[str],
    diagnostics: list[Diagnostic],
) -> None:
    if readback.values:
        instruments.append(command.instrument_id)
    for product_id, value in readback.values.items():
        observable_id = record_bindings.get(product_id)
        if observable_id is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "instrument_unexpected_product",
                    f"instrument {command.instrument_id} returned unexpected "
                    f"collected product {product_id}",
                    f"points.{point_index}.collect_products.{product_id}",
                )
            )
            continue
        if observable_id in observables:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "instrument_duplicate_output",
                    f"point {point_index} received duplicate observable "
                    f"{observable_id}",
                    f"points.{point_index}.outputs.{observable_id}",
                )
            )
            continue
        observables[observable_id] = value


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "RuntimeCollectInstruction",
    "collect_instruction",
    "merge_readback",
]
