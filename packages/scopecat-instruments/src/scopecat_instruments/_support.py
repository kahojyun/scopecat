"""Shared value and receipt helpers for concrete drivers."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import (
    DriverOperation,
    DriverRejected,
    DriverScalar,
    DriverUnknown,
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


def quantity_value(value: DriverScalar, unit: str) -> float:
    if not isinstance(value, Quantity):
        raise TypeError("validated state property is not a quantity")
    if value.unit == unit:
        return value.value
    return value.to(unit).value


def bool_value(value: DriverScalar) -> bool:
    if not isinstance(value, bool):
        raise TypeError("validated state property is not a boolean")
    return value


def int_value(value: DriverScalar) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("validated state property is not an integer")
    return value


def string_value(value: DriverScalar) -> str:
    if not isinstance(value, str):
        raise TypeError("validated state property is not a string")
    return value


def unsupported_invoke(
    request: DriverOperation,
    instrument_id: str,
) -> DriverRejected:
    return DriverRejected(
        problems=(
            execution_problem(
                "instrument_operation_not_implemented",
                f"{instrument_id} does not implement {request.target.operation_id}",
                "driver_operation",
                "operation_id",
            ),
        ),
    )


def state_sync_failed(instrument_id: str, error: Exception) -> DriverRejected:
    return DriverRejected(
        problems=(
            execution_problem(
                "instrument_state_sync_failed",
                f"could not synchronize state from {instrument_id}",
                "driver_state_patch",
                details={"exception_type": _exception_type(error)},
            ),
        )
    )


def apply_unknown(instrument_id: str, error: Exception) -> DriverUnknown:
    return DriverUnknown(
        problems=(
            execution_problem(
                "instrument_apply_outcome_unknown",
                f"lost confirmation while applying state to {instrument_id} "
                f"({type(error).__name__})",
                "driver_state_patch",
                details={"exception_type": _exception_type(error)},
            ),
        ),
    )


def collect_unknown(instrument_id: str, error: Exception) -> DriverUnknown:
    return DriverUnknown(
        problems=(
            execution_problem(
                "instrument_collect_outcome_unknown",
                f"lost readback while collecting from {instrument_id} "
                f"({type(error).__name__})",
                "driver_acquisition",
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


def state_property_problem(
    code: str,
    message: str,
    target: PropertyRef,
) -> Problem:
    return execution_problem(
        code,
        message,
        "instrument_state",
        target.interface_id,
        *target.component_path,
        target.property_id,
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
