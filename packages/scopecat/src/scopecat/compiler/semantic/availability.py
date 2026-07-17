"""Orthogonal stage and rate semantics for transient typed values."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from scopecat.kernel.problems import ModelLocation


class ValueStage(StrEnum):
    """Earliest compiler/execution stage at which a value exists."""

    PLAN = "plan"
    EXECUTE = "execute"
    RESULT = "result"


class ValueRate(StrEnum):
    """Frequency at which a value may change within one run."""

    RUN = "run"
    POINT = "point"
    ROW = "row"


_STAGE_ORDER = {
    ValueStage.PLAN: 0,
    ValueStage.EXECUTE: 1,
    ValueStage.RESULT: 2,
}
_RATE_ORDER = {
    ValueRate.RUN: 0,
    ValueRate.POINT: 1,
    ValueRate.ROW: 2,
}


@dataclass(frozen=True, slots=True)
class ValueAvailability:
    """When a typed value exists and how often it may change."""

    stage: ValueStage
    rate: ValueRate

    @classmethod
    def combined(
        cls,
        *values: ValueAvailability,
    ) -> ValueAvailability:
        """Return the latest stage and fastest rate required by all values."""

        if not values:
            return cls(ValueStage.PLAN, ValueRate.RUN)
        return cls(
            stage=max(values, key=lambda value: _STAGE_ORDER[value.stage]).stage,
            rate=max(values, key=lambda value: _RATE_ORDER[value.rate]).rate,
        )


class ValueAvailabilityError(ValueError):
    """A value is unavailable in a consumer's declared stage or rate."""

    def __init__(
        self,
        code: str,
        message: str,
        location: ModelLocation,
    ) -> None:
        self.code = code
        self.location = location
        super().__init__(message)


def require_value_availability(
    actual: ValueAvailability,
    *,
    stages: Sequence[ValueStage],
    rates: Sequence[ValueRate] = (ValueRate.RUN, ValueRate.POINT),
    context: str,
    location: ModelLocation,
) -> None:
    """Require a value to belong to the consumer's accepted stage and rate."""

    accepted_stages = tuple(stages)
    if actual.stage not in accepted_stages:
        expected = _alternatives(accepted_stages)
        raise ValueAvailabilityError(
            "value_stage_unavailable",
            f"{context} requires {expected}-stage values, but the value is "
            f"{actual.stage.value}-stage",
            location,
        )
    accepted_rates = tuple(rates)
    if actual.rate not in accepted_rates:
        expected = _alternatives(accepted_rates)
        raise ValueAvailabilityError(
            "value_rate_unavailable",
            f"{context} requires {expected}-rate values, but the value is "
            f"{actual.rate.value}-rate",
            location,
        )


def _alternatives(values: Sequence[StrEnum]) -> str:
    return " or ".join(value.value for value in values)
