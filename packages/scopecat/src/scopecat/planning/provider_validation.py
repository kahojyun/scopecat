"""Validate provider descriptions and concrete provisioning results."""

from __future__ import annotations

import logging

from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.sdk.instruments.contracts import (
    DriverFault,
    InstrumentDescription,
    InstrumentDriver,
)

logger = logging.getLogger(__name__)


def validate_instruments(
    *,
    config: ConfigProfileSnapshot,
    instruments: list[InstrumentDriver],
) -> list[Problem]:
    """Validate the identity of concrete drivers returned by a provider."""

    problems: list[Problem] = []
    configured_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    seen: set[str] = set()
    for instrument_index, instrument in enumerate(instruments):
        instrument_id = instrument.instrument_id
        if not instrument_id:
            problems.append(
                _preflight_problem(
                    "instrument_missing_id",
                    "instrument_id must be non-empty",
                    "instruments",
                    instrument_index,
                    "instrument_id",
                )
            )
            continue
        if instrument_id in seen:
            problems.append(
                _preflight_problem(
                    "instrument_duplicate_id",
                    f"duplicate instrument id {instrument_id}",
                    "instruments",
                    instrument_index,
                    "instrument_id",
                )
            )
        seen.add(instrument_id)
        if instrument_id not in configured_ids:
            problems.append(
                _preflight_problem(
                    "instrument_not_in_config",
                    f"instrument {instrument_id} is not in config",
                    "instruments",
                    instrument_index,
                    "instrument_id",
                )
            )
        if not instrument.implementation_id:
            problems.append(
                _preflight_problem(
                    "instrument_missing_implementation_id",
                    "implementation_id must be non-empty",
                    "instruments",
                    instrument_index,
                    "implementation_id",
                )
            )
        if not instrument.implementation_version:
            problems.append(
                _preflight_problem(
                    "instrument_missing_implementation_version",
                    "implementation_version must be non-empty",
                    "instruments",
                    instrument_index,
                    "implementation_version",
                )
            )
    return problems


def describe_instruments(
    instruments: list[InstrumentDriver],
) -> tuple[list[InstrumentDescription], list[Problem]]:
    """Describe concrete drivers and validate their declared identities."""

    descriptions: list[InstrumentDescription] = []
    problems: list[Problem] = []
    for instrument in instruments:
        try:
            description = instrument.describe()
        except Exception as error:
            problems.append(
                preflight_problem_from_exception(
                    "instrument_describe_failed",
                    f"instrument describe failed for {instrument.instrument_id}",
                    ("instruments", instrument.instrument_id, "description"),
                    error,
                )
            )
            continue
        if description.instrument_id != instrument.instrument_id:
            problems.append(
                _preflight_problem(
                    "instrument_description_id_mismatch",
                    f"driver {instrument.instrument_id} described "
                    f"{description.instrument_id}",
                    "instruments",
                    instrument.instrument_id,
                    "description",
                    "instrument_id",
                )
            )
            continue
        if (
            description.implementation_id != instrument.implementation_id
            or description.implementation_version != instrument.implementation_version
        ):
            problems.append(
                _preflight_problem(
                    "instrument_description_implementation_mismatch",
                    f"instrument {instrument.instrument_id} description does not "
                    "match its implementation identity",
                    "instruments",
                    instrument.instrument_id,
                    "description",
                    "implementation",
                )
            )
            continue
        descriptions.append(description)
    return descriptions, problems


def preflight_problem_from_exception(
    code: str,
    message: str,
    path: tuple[LocationPathItem, ...],
    error: Exception,
) -> Problem:
    """Normalize provider and driver description errors as preflight problems."""

    if isinstance(error, DriverFault):
        source = error.problem
        related_locations = source.related_locations
        if source.location is not None:
            related_locations = (source.location, *related_locations)
        return source.model_copy(
            update={
                "phase": ProblemPhase.PROVIDER_PREFLIGHT,
                "location": model_location("instrument_provider", *path),
                "related_locations": related_locations,
            }
        )
    logger.error(
        "instrument provider preflight raised an exception",
        extra={"problem_code": code},
        exc_info=(type(error), error, error.__traceback__),
    )
    return problem(
        code,
        f"{message} ({type(error).__name__})",
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("instrument_provider", *path),
        details={
            "exception_type": f"{type(error).__module__}.{type(error).__qualname__}"
        },
    )


def _preflight_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("instrument_provider", *path),
    )


__all__ = [
    "describe_instruments",
    "preflight_problem_from_exception",
    "validate_instruments",
]
