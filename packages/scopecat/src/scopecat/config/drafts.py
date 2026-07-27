"""Typed, side-effect-free editing of one config parameter snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Self

from scopecat.config.parameter_resolution import validate_parameter_snapshot
from scopecat.config.parameter_updates import (
    ParameterUpdate,
    delete_parameter_rows,
    insert_parameter_rows,
    materialize_parameter_updates,
    replace_scalar_parameter,
    replace_table_parameter,
    update_parameter_rows,
)
from scopecat.config.validation import ParameterValueValidationError
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.records.parameter import ParameterAtomValue
from scopecat.records.parameter_change import ParameterValueDelta


@dataclass(frozen=True, slots=True)
class ConfigDraftCheckResult:
    """Structured validation outcome for a config draft."""

    problems: tuple[Problem, ...]
    candidate: ConfigProfileSnapshot | None
    deltas: tuple[ParameterValueDelta, ...]

    def __post_init__(self) -> None:
        problems = tuple(self.problems)
        deltas = tuple(self.deltas)
        complete = self.candidate is not None
        if complete != bool(deltas):
            msg = "a successful config draft check requires parameter deltas"
            raise ValueError(msg)
        if complete == bool(problems):
            msg = (
                "a successful config draft check requires a candidate; "
                "a failed check requires problems"
            )
            raise ValueError(msg)
        object.__setattr__(self, "problems", problems)
        object.__setattr__(self, "deltas", deltas)

    @property
    def ok(self) -> bool:
        return self.candidate is not None


class ConfigDraft:
    """Accumulate typed parameter edits against one immutable config snapshot."""

    __slots__ = ("_base", "_updates")

    def __init__(self, base: ConfigProfileSnapshot) -> None:
        self._base = base.model_copy(deep=True)
        self._updates: list[ParameterUpdate] = []

    @classmethod
    def from_snapshot(cls, snapshot: ConfigProfileSnapshot) -> Self:
        """Start an isolated draft from an immutable snapshot."""

        return cls(snapshot)

    @property
    def updates(self) -> tuple[ParameterUpdate, ...]:
        """Return the canonical transient intents accumulated by this draft."""

        return tuple(self._updates)

    @property
    def base_content_hash(self) -> ConfigContentHash:
        """Identify the immutable snapshot against which these edits were authored."""

        return config_content_hash(self._base)

    def apply(self, *updates: ParameterUpdate) -> Self:
        """Append canonical parameter intents, including analysis-produced edits."""

        self._updates.extend(updates)
        return self

    def replace_scalar(
        self,
        parameter_id: str,
        value: ParameterAtomValue,
    ) -> Self:
        return self.apply(replace_scalar_parameter(parameter_id, value))

    def table(self, parameter_id: str) -> ConfigTableDraft:
        """Select one table parameter for replacement or keyed row edits."""

        return ConfigTableDraft(self, parameter_id)

    def check(self, *, candidate_id: str | None = None) -> ConfigDraftCheckResult:
        """Validate all edits and build a complete candidate config snapshot."""

        selected_id = f"{self._base.id}.draft" if candidate_id is None else candidate_id
        try:
            parameter_snapshot, deltas = materialize_parameter_updates(
                catalog=self._base.parameter_catalog,
                base=self._base.parameter_snapshot,
                updates=self._updates,
                candidate_id=f"{selected_id}.parameters",
            )
        except ParameterValueValidationError as error:
            return _failed_check(_validation_problem(error))
        except ValueError as error:
            return _failed_check(_update_problem(error))

        problems = validate_parameter_snapshot(
            self._base.parameter_catalog,
            parameter_snapshot,
        )
        if bool(problems):
            return ConfigDraftCheckResult(
                problems=problems,
                candidate=None,
                deltas=(),
            )
        candidate = self._base.model_copy(
            update={
                "id": selected_id,
                "parameter_snapshot": parameter_snapshot,
            },
            deep=True,
        )
        return ConfigDraftCheckResult(
            problems=problems,
            candidate=candidate,
            deltas=deltas,
        )


class ConfigTableDraft:
    """Fluent edits scoped to one table-shaped parameter."""

    __slots__ = ("_draft", "parameter_id")

    def __init__(self, draft: ConfigDraft, parameter_id: str) -> None:
        self._draft = draft
        self.parameter_id = parameter_id

    def replace(
        self,
        rows: Sequence[Mapping[str, ParameterAtomValue]],
    ) -> Self:
        self._draft.apply(replace_table_parameter(self.parameter_id, rows))
        return self

    def update(
        self,
        *,
        key: Mapping[str, ParameterAtomValue],
        values: Mapping[str, ParameterAtomValue],
    ) -> Self:
        self._draft.apply(
            update_parameter_rows(self.parameter_id, key=key, values=values)
        )
        return self

    def insert(
        self,
        rows: Sequence[Mapping[str, ParameterAtomValue]],
    ) -> Self:
        self._draft.apply(insert_parameter_rows(self.parameter_id, rows))
        return self

    def delete(
        self,
        *,
        key: Mapping[str, ParameterAtomValue],
    ) -> Self:
        self._draft.apply(delete_parameter_rows(self.parameter_id, key=key))
        return self


def _failed_check(problem: Problem) -> ConfigDraftCheckResult:
    return ConfigDraftCheckResult(
        problems=(problem,),
        candidate=None,
        deltas=(),
    )


def _validation_problem(error: ParameterValueValidationError) -> Problem:
    path = error.path or ()
    if path and path[0] == "parameter_snapshot":
        path = path[1:]
    return problem(
        error.code,
        str(error),
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("parameter_snapshot", *path),
    )


def _update_problem(error: ValueError) -> Problem:
    message = str(error)
    if message == "parameter change proposal requires at least one update":
        code = "config_draft_empty"
        message = "config draft requires at least one edit"
    elif message == "parameter change proposal does not change the base snapshot":
        code = "config_draft_no_changes"
        message = "config draft does not change the base snapshot"
    else:
        code = "config_draft_invalid_update"
    return problem(
        code,
        message,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("config_draft", "updates"),
    )


__all__ = [
    "ConfigDraft",
    "ConfigDraftCheckResult",
    "ConfigTableDraft",
]
