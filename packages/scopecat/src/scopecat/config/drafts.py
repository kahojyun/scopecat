"""Typed, side-effect-free editing of one config parameter snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Self

from scopecat.config.parameter_resolution import validate_parameter_snapshot
from scopecat.config.parameter_updates import (
    ParameterUpdate,
    delete_parameter_rows,
    insert_parameter_rows,
    materialize_parameter_updates,
    replace_scalar_parameter,
    replace_series_parameter,
    replace_table_parameter,
    update_parameter_rows,
)
from scopecat.config.validation import (
    ParameterValueValidationError,
    parameter_table_key_part,
)
from scopecat.kernel.frozen import FrozenMapping
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.kernel.value_types import Table
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.records.parameter import (
    ParameterAtomValue,
    StoredParameterValue,
    TableParameterValue,
)
from scopecat.records.parameter_change import ParameterValueDelta

type TableRowOperation = Literal["insert", "update", "delete"]


@dataclass(frozen=True, slots=True)
class TableCellDiff:
    """One changed cell, retaining presence separately because null is a value."""

    column_id: str
    before_present: bool
    before: ParameterAtomValue
    after_present: bool
    after: ParameterAtomValue


@dataclass(frozen=True, slots=True)
class TableRowDiff:
    """One keyed or positional table-row change."""

    operation: TableRowOperation
    key: Mapping[str, ParameterAtomValue] | None
    before_index: int | None
    after_index: int | None
    before: Mapping[str, ParameterAtomValue] | None
    after: Mapping[str, ParameterAtomValue] | None
    cells: tuple[TableCellDiff, ...]


@dataclass(frozen=True, slots=True)
class TableDiff:
    """Structured row and cell changes for one table parameter."""

    primary_key: tuple[str, ...]
    rows: tuple[TableRowDiff, ...]


@dataclass(frozen=True, slots=True)
class ParameterDiff:
    """Before and after values for one changed parameter."""

    parameter_id: str
    before: StoredParameterValue
    after: StoredParameterValue
    table: TableDiff | None = None


@dataclass(frozen=True, slots=True)
class ConfigDiff:
    """All parameter changes in the order they were first edited."""

    parameters: tuple[ParameterDiff, ...]

    def get(self, parameter_id: str) -> ParameterDiff | None:
        """Return one changed parameter by id."""

        return next(
            (
                parameter
                for parameter in self.parameters
                if parameter.parameter_id == parameter_id
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class ConfigDraftCheckResult:
    """Structured validation outcome for a config draft."""

    problems: tuple[Problem, ...]
    candidate: ConfigProfileSnapshot | None
    deltas: tuple[ParameterValueDelta, ...]
    diff: ConfigDiff | None

    def __post_init__(self) -> None:
        problems = tuple(self.problems)
        deltas = tuple(self.deltas)
        complete = self.candidate is not None and self.diff is not None
        if (self.candidate is None) != (self.diff is None):
            msg = "a config draft check must provide candidate and diff together"
            raise ValueError(msg)
        if complete != bool(deltas):
            msg = "a successful config draft check requires parameter deltas"
            raise ValueError(msg)
        if complete == has_blocking_problems(problems):
            msg = (
                "a successful config draft check requires candidate and diff; "
                "a failed check requires blocking problems"
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
        """Start an isolated draft from an accepted or registered snapshot."""

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

    def replace_series(
        self,
        parameter_id: str,
        items: Sequence[ParameterAtomValue],
    ) -> Self:
        return self.apply(replace_series_parameter(parameter_id, items))

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
        if has_blocking_problems(problems):
            return ConfigDraftCheckResult(
                problems=problems,
                candidate=None,
                deltas=(),
                diff=None,
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
            diff=_build_config_diff(self._base, deltas),
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
        diff=None,
    )


def _validation_problem(error: ParameterValueValidationError) -> Problem:
    path = error.path or ()
    if path and path[0] == "parameter_snapshot":
        path = path[1:]
    return blocking_problem(
        error.code,
        str(error),
        category=ProblemCategory.INVALID_INPUT,
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
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("config_draft", "updates"),
    )


def _build_config_diff(
    base: ConfigProfileSnapshot,
    deltas: tuple[ParameterValueDelta, ...],
) -> ConfigDiff:
    parameters: list[ParameterDiff] = []
    for delta in deltas:
        definition = base.parameter_catalog.get(delta.parameter_id)
        table_diff = None
        if (
            definition is not None
            and isinstance(definition.value_type, Table)
            and isinstance(delta.before, TableParameterValue)
            and isinstance(delta.after, TableParameterValue)
        ):
            table_diff = _build_table_diff(
                definition.value_type,
                before=delta.before,
                after=delta.after,
            )
        parameters.append(
            ParameterDiff(
                parameter_id=delta.parameter_id,
                before=delta.before,
                after=delta.after,
                table=table_diff,
            )
        )
    return ConfigDiff(parameters=tuple(parameters))


def _build_table_diff(
    table_type: Table,
    *,
    before: TableParameterValue,
    after: TableParameterValue,
) -> TableDiff:
    column_ids = tuple(column.id for column in table_type.columns)
    if table_type.primary_key:
        rows = _build_keyed_row_diffs(
            primary_key=table_type.primary_key,
            column_ids=column_ids,
            before=before.rows,
            after=after.rows,
        )
    else:
        rows = _build_positional_row_diffs(
            column_ids=column_ids,
            before=before.rows,
            after=after.rows,
        )
    return TableDiff(primary_key=table_type.primary_key, rows=rows)


def _build_keyed_row_diffs(
    *,
    primary_key: tuple[str, ...],
    column_ids: tuple[str, ...],
    before: Sequence[Mapping[str, ParameterAtomValue]],
    after: Sequence[Mapping[str, ParameterAtomValue]],
) -> tuple[TableRowDiff, ...]:
    before_by_key = {
        _row_identity(row, primary_key): (index, row)
        for index, row in enumerate(before)
    }
    after_by_key = {
        _row_identity(row, primary_key): (index, row) for index, row in enumerate(after)
    }
    changes: list[TableRowDiff] = []
    for identity, (before_index, before_row) in before_by_key.items():
        matched = after_by_key.get(identity)
        key = _row_key(before_row, primary_key)
        if matched is None:
            changes.append(
                _row_diff(
                    operation="delete",
                    key=key,
                    before_index=before_index,
                    after_index=None,
                    before=before_row,
                    after=None,
                    column_ids=column_ids,
                )
            )
            continue
        after_index, after_row = matched
        if before_row != after_row:
            changes.append(
                _row_diff(
                    operation="update",
                    key=key,
                    before_index=before_index,
                    after_index=after_index,
                    before=before_row,
                    after=after_row,
                    column_ids=column_ids,
                )
            )
    for identity, (after_index, after_row) in after_by_key.items():
        if identity not in before_by_key:
            changes.append(
                _row_diff(
                    operation="insert",
                    key=_row_key(after_row, primary_key),
                    before_index=None,
                    after_index=after_index,
                    before=None,
                    after=after_row,
                    column_ids=column_ids,
                )
            )
    return tuple(changes)


def _build_positional_row_diffs(
    *,
    column_ids: tuple[str, ...],
    before: Sequence[Mapping[str, ParameterAtomValue]],
    after: Sequence[Mapping[str, ParameterAtomValue]],
) -> tuple[TableRowDiff, ...]:
    changes: list[TableRowDiff] = []
    shared_length = min(len(before), len(after))
    for index in range(shared_length):
        if before[index] != after[index]:
            changes.append(
                _row_diff(
                    operation="update",
                    key=None,
                    before_index=index,
                    after_index=index,
                    before=before[index],
                    after=after[index],
                    column_ids=column_ids,
                )
            )
    for index in range(shared_length, len(before)):
        changes.append(
            _row_diff(
                operation="delete",
                key=None,
                before_index=index,
                after_index=None,
                before=before[index],
                after=None,
                column_ids=column_ids,
            )
        )
    for index in range(shared_length, len(after)):
        changes.append(
            _row_diff(
                operation="insert",
                key=None,
                before_index=None,
                after_index=index,
                before=None,
                after=after[index],
                column_ids=column_ids,
            )
        )
    return tuple(changes)


def _row_diff(
    *,
    operation: TableRowOperation,
    key: Mapping[str, ParameterAtomValue] | None,
    before_index: int | None,
    after_index: int | None,
    before: Mapping[str, ParameterAtomValue] | None,
    after: Mapping[str, ParameterAtomValue] | None,
    column_ids: tuple[str, ...],
) -> TableRowDiff:
    return TableRowDiff(
        operation=operation,
        key=key,
        before_index=before_index,
        after_index=after_index,
        before=None if before is None else FrozenMapping(before.items()),
        after=None if after is None else FrozenMapping(after.items()),
        cells=_cell_diffs(before=before, after=after, column_ids=column_ids),
    )


def _cell_diffs(
    *,
    before: Mapping[str, ParameterAtomValue] | None,
    after: Mapping[str, ParameterAtomValue] | None,
    column_ids: tuple[str, ...],
) -> tuple[TableCellDiff, ...]:
    before_row = before or {}
    after_row = after or {}
    known = set(column_ids)
    ordered_columns = (
        *column_ids,
        *sorted((before_row.keys() | after_row.keys()) - known),
    )
    return tuple(
        TableCellDiff(
            column_id=column_id,
            before_present=column_id in before_row,
            before=before_row.get(column_id),
            after_present=column_id in after_row,
            after=after_row.get(column_id),
        )
        for column_id in ordered_columns
        if (column_id in before_row) != (column_id in after_row)
        or before_row.get(column_id) != after_row.get(column_id)
    )


def _row_identity(
    row: Mapping[str, ParameterAtomValue],
    primary_key: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(parameter_table_key_part(row[column_id]) for column_id in primary_key)


def _row_key(
    row: Mapping[str, ParameterAtomValue],
    primary_key: tuple[str, ...],
) -> Mapping[str, ParameterAtomValue]:
    return FrozenMapping((column_id, row[column_id]) for column_id in primary_key)


__all__ = [
    "ConfigDiff",
    "ConfigDraft",
    "ConfigDraftCheckResult",
    "ConfigTableDraft",
    "ParameterDiff",
    "TableCellDiff",
    "TableDiff",
    "TableRowDiff",
    "TableRowOperation",
]
