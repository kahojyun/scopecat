"""Runtime instrument lifecycle helpers."""

from __future__ import annotations

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.instruments.sdk import (
    InstrumentDescription,
    InstrumentDriver,
    InstrumentStateSnapshot,
)
from scopecat.models.config import ConfigProfileSnapshot


def validate_instruments(
    *, config: ConfigProfileSnapshot, instruments: list[InstrumentDriver]
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()
    config_instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    for instrument in instruments:
        if not instrument.instrument_id:
            diagnostics.append(
                diagnostic(
                    "error",
                    "instrument_missing_id",
                    "instrument_id must be non-empty",
                    "instrument.instrument_id",
                )
            )
            continue
        if instrument.instrument_id in seen:
            diagnostics.append(
                diagnostic(
                    "error",
                    "instrument_duplicate_id",
                    f"duplicate instrument id {instrument.instrument_id}",
                    "instrument.instrument_id",
                )
            )
        seen.add(instrument.instrument_id)
        if instrument.instrument_id not in config_instrument_ids:
            diagnostics.append(
                diagnostic(
                    "error",
                    "instrument_not_in_config",
                    f"instrument {instrument.instrument_id} is not in config",
                    "instrument.instrument_id",
                )
            )
        if not instrument.implementation_id:
            diagnostics.append(
                diagnostic(
                    "error",
                    "instrument_missing_implementation_id",
                    "implementation_id must be non-empty",
                    "instrument.implementation_id",
                )
            )
        if not instrument.implementation_version:
            diagnostics.append(
                diagnostic(
                    "error",
                    "instrument_missing_implementation_version",
                    "implementation_version must be non-empty",
                    "instrument.implementation_version",
                )
            )
    return diagnostics


def describe_instruments(
    instruments: list[InstrumentDriver],
) -> tuple[list[InstrumentDescription], list[Diagnostic]]:
    descriptions: list[InstrumentDescription] = []
    diagnostics: list[Diagnostic] = []
    for instrument in instruments:
        try:
            descriptions.append(instrument.describe())
        except Exception as error:
            diagnostics.append(
                diagnostic_from_exception(
                    "error",
                    "instrument_describe_failed",
                    "instrument describe failed for "
                    f"{instrument.instrument_id}: {type(error).__name__}: {error}",
                    instrument.instrument_id,
                    error,
                )
            )
    return descriptions, diagnostics


def readback_all(
    instruments: list[InstrumentDriver], diagnostics: list[Diagnostic]
) -> list[InstrumentStateSnapshot]:
    states: list[InstrumentStateSnapshot] = []
    for instrument in instruments:
        try:
            states.append(instrument.read_state().model_copy(deep=True))
        except Exception as error:
            diagnostics.append(
                diagnostic_from_exception(
                    "error",
                    "instrument_readback_failed",
                    "instrument readback failed for "
                    f"{instrument.instrument_id}: {type(error).__name__}: {error}",
                    instrument.instrument_id,
                    error,
                )
            )
    return states


def abort_all(
    instruments: list[InstrumentDriver], diagnostics: list[Diagnostic]
) -> None:
    for instrument in instruments:
        try:
            instrument.abort()
        except Exception as error:
            diagnostics.append(
                diagnostic_from_exception(
                    "error",
                    "instrument_abort_failed",
                    "instrument abort failed for "
                    f"{instrument.instrument_id}: {type(error).__name__}: {error}",
                    instrument.instrument_id,
                    error,
                )
            )


def cleanup_all(
    instruments: list[InstrumentDriver], diagnostics: list[Diagnostic]
) -> None:
    for instrument in instruments:
        try:
            instrument.cleanup()
        except Exception as error:
            diagnostics.append(
                diagnostic_from_exception(
                    "error",
                    "instrument_cleanup_failed",
                    "instrument cleanup failed for "
                    f"{instrument.instrument_id}: {type(error).__name__}: {error}",
                    instrument.instrument_id,
                    error,
                )
            )


def diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


def diagnostic_from_exception(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None,
    error: Exception,
) -> Diagnostic:
    to_diagnostic = getattr(error, "to_diagnostic", None)
    if callable(to_diagnostic):
        converted = to_diagnostic()
        if isinstance(converted, Diagnostic):
            return converted
    return diagnostic(severity, code, message, path)


__all__ = [
    "abort_all",
    "cleanup_all",
    "describe_instruments",
    "diagnostic",
    "diagnostic_from_exception",
    "readback_all",
    "validate_instruments",
]
