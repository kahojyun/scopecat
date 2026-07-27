"""Terminal run outcome contracts shared across operation boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.problems import Problem

RunResult = Literal["succeeded", "failed", "cancelled"]
RunCertainty = Literal["known", "indeterminate"]
RunStatus = Literal[
    "planned",
    "completed",
    "failed",
    "interrupted",
    "unknown",
]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class RunOutcome(BaseModel):
    """Immutable durable outcome established when one run becomes terminal."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    run_id: str
    result: RunResult
    certainty: RunCertainty
    finished_at: datetime = Field(default_factory=utc_now)
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> RunOutcome:
        has_problems = bool(self.problems)
        if self.result == "succeeded":
            if self.certainty != "known":
                msg = "a succeeded run outcome must be known"
                raise ValueError(msg)
            if has_problems:
                msg = "a succeeded run outcome cannot contain problems"
                raise ValueError(msg)
            return self
        if not has_problems:
            msg = "a non-succeeded run outcome requires a problem"
            raise ValueError(msg)
        return self

    @property
    def status(self) -> RunStatus:
        """Return the presentation status derived from durable outcome facts."""

        if self.result == "succeeded":
            return "completed"
        if self.result == "cancelled":
            return "interrupted"
        if self.certainty == "indeterminate":
            return "unknown"
        return "failed"
