"""Durable outcomes for proposed parameter changes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.models.config import ConfigContentHash
from scopecat.models.parameter import ParameterSnapshot, StoredParameterValue
from scopecat.models.run import utc_now


class ParameterValueDelta(BaseModel):
    """Review projection for one changed value in a candidate snapshot.

    Deltas describe the observed before/after state. They are deliberately not
    replayable update commands; the candidate snapshot is the durable authority.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    parameter_id: str
    before: StoredParameterValue
    after: StoredParameterValue

    @model_validator(mode="after")
    def validate_values(self) -> ParameterValueDelta:
        if not self.parameter_id:
            msg = "parameter delta id must be non-empty"
            raise ValueError(msg)
        if self.before.id != self.parameter_id or self.after.id != self.parameter_id:
            msg = "parameter delta before/after ids must match parameter_id"
            raise ValueError(msg)
        if self.before == self.after:
            msg = f"parameter delta {self.parameter_id!r} must change its value"
            raise ValueError(msg)
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy through validation so durable delta invariants cannot drift."""

        _ = deep
        data = self.model_dump(mode="python")
        if update is not None:
            data.update(update)
        return type(self).model_validate(data)


class ParameterChangeProposal(BaseModel):
    """Immutable candidate parameter snapshot proposed by analysis."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.parameter_change_proposal.v1"] = (
        "scopecat.parameter_change_proposal.v1"
    )
    id: str
    source_run_id: str
    base_config_id: str
    base_config_content_hash: ConfigContentHash
    reason: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    candidate_snapshot: ParameterSnapshot
    deltas: tuple[ParameterValueDelta, ...] = Field(min_length=1)
    proposed_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "id",
        "source_run_id",
        "base_config_id",
        "reason",
    )
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "parameter change proposal string fields must be non-empty"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_candidate_snapshot(self) -> ParameterChangeProposal:
        seen: set[str] = set()
        for delta in self.deltas:
            if delta.parameter_id in seen:
                msg = f"duplicate parameter delta: {delta.parameter_id}"
                raise ValueError(msg)
            seen.add(delta.parameter_id)
            candidate_value = self.candidate_snapshot.get(delta.parameter_id)
            if candidate_value != delta.after:
                msg = (
                    "parameter delta after value does not match candidate snapshot: "
                    f"{delta.parameter_id}"
                )
                raise ValueError(msg)
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy through validation so durable proposal invariants cannot drift."""

        _ = deep
        data = self.model_dump(mode="python")
        if update is not None:
            data.update(update)
        return type(self).model_validate(data)


__all__ = [
    "ParameterChangeProposal",
    "ParameterValueDelta",
]
