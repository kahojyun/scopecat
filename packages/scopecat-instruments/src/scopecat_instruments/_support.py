"""Shared parsing and receipt helpers for concrete drivers."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverInvokeRequest,
    InstrumentPropertyState,
    InstrumentStateSnapshot,
    InvokeReceipt,
    PropertyRef,
)
from scopecat.sdk.problems import Problem, ProblemPhase, model_location, problem


@dataclass(frozen=True)
class NetworkTrace:
    frequencies_hz: tuple[float, ...]
    values: tuple[complex, ...]

    def __post_init__(self) -> None:
        if len(self.frequencies_hz) != len(self.values):
            raise ValueError("network trace frequency and value lengths differ")


@dataclass(frozen=True)
class LinearSweepSettings:
    start_frequency_hz: float
    stop_frequency_hz: float
    points: int
    if_bandwidth_hz: float
    source_power_dbm: float
    s_parameter: str


@dataclass(frozen=True)
class ScpiIdentity:
    manufacturer: str
    model: str
    serial_number: str
    firmware: str
    raw: str


def parse_identity(response: str) -> ScpiIdentity:
    raw = response.strip()
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("instrument returned malformed *IDN? response")
    return ScpiIdentity(
        manufacturer=parts[0],
        model=parts[1],
        serial_number=parts[2] if len(parts) > 2 else "",
        firmware=",".join(parts[3:]) if len(parts) > 3 else "",
        raw=raw,
    )


def format_number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("SCPI numeric values must be finite")
    return format(value, ".15g")


def parse_float(response: str) -> float:
    value = float(response.strip())
    if not math.isfinite(value):
        raise ValueError("instrument returned a non-finite number")
    return value


def parse_int(response: str) -> int:
    return int(response.strip())


def parse_bool(response: str) -> bool:
    selected = response.strip().upper()
    if selected in {"1", "ON"}:
        return True
    if selected in {"0", "OFF"}:
        return False
    raise ValueError(f"instrument returned invalid boolean {response!r}")


def parse_csv_floats(response: str) -> tuple[float, ...]:
    return tuple(parse_float(value) for value in response.strip().split(",") if value)


def strip_scpi_string(response: str) -> str:
    selected = response.strip()
    if len(selected) >= 2 and selected[0] == selected[-1] and selected[0] in {"'", '"'}:
        return selected[1:-1]
    return selected


def quantity_value(value: StateValue, unit: str) -> float:
    literal = value.root
    if not isinstance(literal, Quantity):
        raise TypeError("validated state property is not a quantity")
    if literal.unit == unit:
        return literal.value
    return literal.to(unit).value


def bool_value(value: StateValue) -> bool:
    literal = value.root
    if not isinstance(literal, bool):
        raise TypeError("validated state property is not a boolean")
    return literal


def int_value(value: StateValue) -> int:
    literal = value.root
    if not isinstance(literal, int) or isinstance(literal, bool):
        raise TypeError("validated state property is not an integer")
    return literal


def string_value(value: StateValue) -> str:
    literal = value.root
    if not isinstance(literal, str):
        raise TypeError("validated state property is not a string")
    return literal


def state_property(
    target: PropertyRef,
    value: bool | float | str | Quantity,
) -> InstrumentPropertyState:
    return InstrumentPropertyState(
        interface_id=target.interface_id,
        component_path=list(target.component_path),
        property_id=target.property_id,
        value=StateValue(value),
    )


def state_properties_by_target(
    snapshot: InstrumentStateSnapshot,
) -> dict[PropertyRef, InstrumentPropertyState]:
    return {
        PropertyRef(
            property_state.interface_id,
            tuple(property_state.component_path),
            property_state.property_id,
        ): property_state
        for property_state in snapshot.properties
    }


def not_applied(problems: Iterable[Problem]) -> ApplyReceipt:
    return ApplyReceipt(status="not_applied", problems=tuple(problems))


def unsupported_invoke(
    request: DriverInvokeRequest,
    instrument_id: str,
) -> InvokeReceipt:
    return InvokeReceipt(
        status="not_invoked",
        problems=(
            execution_problem(
                "instrument_operation_not_implemented",
                f"{instrument_id} does not implement {request.target.operation_id}",
                "driver_invoke_request",
                "operation_id",
            ),
        ),
    )


def state_sync_failed(instrument_id: str, error: Exception) -> ApplyReceipt:
    return not_applied(
        [
            execution_problem(
                "instrument_state_sync_failed",
                f"could not synchronize state from {instrument_id}",
                "driver_apply_request",
                details={"exception_type": _exception_type(error)},
            )
        ]
    )


def apply_unknown(instrument_id: str, error: Exception) -> ApplyReceipt:
    return ApplyReceipt(
        status="unknown",
        problems=(
            execution_problem(
                "instrument_apply_outcome_unknown",
                f"lost confirmation while applying state to {instrument_id} "
                f"({type(error).__name__})",
                "driver_apply_request",
                details={"exception_type": _exception_type(error)},
            ),
        ),
    )


def not_collected(problems: Iterable[Problem]) -> CollectReceipt:
    return CollectReceipt(status="not_collected", problems=tuple(problems))


def collect_unknown(instrument_id: str, error: Exception) -> CollectReceipt:
    return CollectReceipt(
        status="unknown",
        problems=(
            execution_problem(
                "instrument_collect_outcome_unknown",
                f"lost readback while collecting from {instrument_id} "
                f"({type(error).__name__})",
                "driver_collect_request",
                details={"exception_type": _exception_type(error)},
            ),
        ),
    )


def execution_problem(
    code: str,
    message: str,
    root: str,
    *path: str | int,
    details: dict[str, str] | None = None,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location(root, *path),
        details=details,
    )


def provider_problem(
    code: str,
    message: str,
    *path: str | int,
    details: dict[str, str] | None = None,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("instrument_provider", *path),
        details=details,
    )


def _exception_type(error: Exception) -> str:
    return f"{type(error).__module__}.{type(error).__qualname__}"
