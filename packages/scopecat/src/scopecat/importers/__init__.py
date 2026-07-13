"""Untrusted parameter drafts and their explicit acceptance boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scopecat._parameter_resolution import validate_parameter_snapshot
from scopecat.errors import CheckFailed
from scopecat.models.artifact import RunArtifactEntry
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterSnapshot,
    ScalarParameterValue,
    SeriesParameterValue,
    StoredParameterValue,
    TableParameterValue,
)
from scopecat.parameter_validation import coerce_stored_parameter_value
from scopecat.problems import (
    ExternalLocation,
    LocationPathItem,
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    has_blocking_problems,
)

ImportSourceKind = Literal["csv", "xlsx", "json", "registry", "legacy", "manual"]


class ScalarParameterDraftValue(BaseModel):
    """An untyped scalar value parsed by an importer."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["scalar"] = "scalar"
    id: str
    value: Any
    location: ExternalLocation
    metadata: dict[str, Any] = Field(default_factory=dict)


class SeriesParameterDraftValue(BaseModel):
    """An untyped ordered series parsed by an importer."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["series"] = "series"
    id: str
    items: list[Any] = Field(default_factory=list)
    location: ExternalLocation
    item_locations: list[ExternalLocation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_item_locations(self) -> SeriesParameterDraftValue:
        if self.item_locations and len(self.item_locations) != len(self.items):
            msg = "item_locations must be empty or match items length"
            raise ValueError(msg)
        return self


class TableParameterDraftValue(BaseModel):
    """An untyped table parsed by an importer."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["table"] = "table"
    id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    location: ExternalLocation
    row_locations: list[ExternalLocation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_row_locations(self) -> TableParameterDraftValue:
        if self.row_locations and len(self.row_locations) != len(self.rows):
            msg = "row_locations must be empty or match rows length"
            raise ValueError(msg)
        return self


type DraftParameterValue = Annotated[
    ScalarParameterDraftValue | SeriesParameterDraftValue | TableParameterDraftValue,
    Field(discriminator="shape"),
]


class ParameterDraft(BaseModel):
    """Raw importer output that has not been accepted as a parameter snapshot."""

    model_config = ConfigDict(extra="forbid")

    id: str
    values: list[DraftParameterValue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParameterImportResult(BaseModel):
    """An importer result containing a draft, provenance, and findings."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.parameter_import_result.v1"] = (
        "scopecat.parameter_import_result.v1"
    )
    id: str
    source_kind: ImportSourceKind
    source_uri: str
    draft: ParameterDraft
    artifacts: list[RunArtifactEntry] = Field(default_factory=list)
    problems: tuple[Problem, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_blocking_problems(self) -> bool:
        return has_blocking_problems(self.problems)


def parameter_import_result(
    *,
    id: str,  # noqa: A002
    source_kind: ImportSourceKind,
    source_uri: str,
    values: Sequence[DraftParameterValue] = (),
    artifacts: Sequence[RunArtifactEntry] = (),
    problems: Sequence[Problem] = (),
    draft_metadata: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ParameterImportResult:
    """Build a raw draft without implying that its values are accepted."""

    return ParameterImportResult(
        id=id,
        source_kind=source_kind,
        source_uri=source_uri,
        draft=ParameterDraft(
            id=f"{id}.draft",
            values=list(values),
            metadata=dict(draft_metadata or {}),
        ),
        artifacts=list(artifacts),
        problems=tuple(problems),
        metadata=dict(metadata or {}),
    )


def accept_parameter_import(
    result: ParameterImportResult,
    catalog: ParameterCatalog,
    *,
    snapshot_id: str | None = None,
) -> ParameterSnapshot:
    """Validate and freeze an imported draft into an accepted parameter snapshot.

    Importer problems are checked first. The raw values are then represented
    as stored values and cross-validated against the catalog. No snapshot is
    returned if either stage reports an error or blocker.
    """

    if result.has_blocking_problems:
        raise CheckFailed(_blocking_problems(result.problems))

    stored_values: list[StoredParameterValue] = []
    for draft_value in result.draft.values:
        try:
            stored_values.append(_to_stored_parameter_value(draft_value))
        except (TypeError, ValueError) as error:
            raise CheckFailed(
                [
                    import_problem(
                        code="invalid_imported_parameter_value",
                        message=(
                            "imported parameter value cannot be represented in "
                            "the durable parameter model"
                        ),
                        location=_draft_validation_error_location(
                            draft_value,
                            error,
                        ),
                        details={
                            "parameter_id": draft_value.id,
                            "shape": draft_value.shape,
                        },
                    )
                ]
            ) from error

    duplicate_problems = _duplicate_value_problems(result.draft.values)
    if duplicate_problems:
        raise CheckFailed(duplicate_problems)

    try:
        candidate = ParameterSnapshot(
            id=snapshot_id or f"{result.id}.snapshot",
            values=stored_values,
            metadata={
                **result.draft.metadata,
                "import_id": result.id,
                "import_source_kind": result.source_kind,
                "import_source_uri": result.source_uri,
            },
        )
    except (TypeError, ValueError) as error:
        raise CheckFailed(
            [
                import_problem(
                    code="invalid_parameter_draft_metadata",
                    message="parameter draft metadata is not persistable",
                    location=ExternalLocation(uri=result.source_uri),
                )
            ]
        ) from error
    draft_values = {draft_value.id: draft_value for draft_value in result.draft.values}
    catalog_problems = tuple(
        _import_problem_from_catalog(
            problem,
            drafts=draft_values,
            fallback=ExternalLocation(uri=result.source_uri),
        )
        for problem in validate_parameter_snapshot(catalog, candidate)
    )
    if has_blocking_problems(catalog_problems):
        raise CheckFailed(_blocking_problems(catalog_problems))

    normalized: list[StoredParameterValue] = []
    for stored in candidate.values:
        definition = catalog.get(stored.id)
        if definition is None:
            # An unknown definition is a blocking catalog problem above.
            continue
        normalized.append(
            coerce_stored_parameter_value(
                definition,
                stored,
                path=("parameter_snapshot", "values", stored.id),
            )
        )
    return ParameterSnapshot(
        id=candidate.id,
        values=normalized,
        metadata=candidate.metadata,
    )


def import_problem(
    *,
    code: str,
    message: str,
    impact: ProblemImpact = ProblemImpact.BLOCKING,
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    location: ExternalLocation | None = None,
    details: Mapping[str, object] | None = None,
) -> Problem:
    """Build an importer Problem without introducing another finding type."""

    return Problem(
        code=code,
        impact=impact,
        category=category,
        phase=ProblemPhase.IMPORTING,
        message=message,
        location=location,
        details={} if details is None else details,
    )


def _to_stored_parameter_value(
    draft: DraftParameterValue,
) -> StoredParameterValue:
    metadata: dict[str, Any] = {
        **draft.metadata,
        "import_location": _location_metadata(draft.location),
    }
    if isinstance(draft, ScalarParameterDraftValue):
        return ScalarParameterValue(
            id=draft.id,
            value=draft.value,
            metadata=metadata,
        )
    if isinstance(draft, SeriesParameterDraftValue):
        if draft.item_locations:
            metadata["import_item_locations"] = [
                _location_metadata(location) for location in draft.item_locations
            ]
        return SeriesParameterValue(
            id=draft.id,
            items=draft.items,
            metadata=metadata,
        )
    if draft.row_locations:
        metadata["import_row_locations"] = [
            _location_metadata(location) for location in draft.row_locations
        ]
    return TableParameterValue(
        id=draft.id,
        rows=draft.rows,
        metadata=metadata,
    )


def _duplicate_value_problems(
    values: Sequence[DraftParameterValue],
) -> tuple[Problem, ...]:
    seen: set[str] = set()
    problems: list[Problem] = []
    for value in values:
        if value.id in seen:
            problems.append(
                import_problem(
                    code="duplicate_imported_parameter_id",
                    message=f"parameter draft contains duplicate id {value.id!r}",
                    location=value.location,
                    details={"parameter_id": value.id},
                )
            )
        seen.add(value.id)
    return tuple(problems)


def _import_problem_from_catalog(
    problem: Problem,
    *,
    drafts: Mapping[str, DraftParameterValue],
    fallback: ExternalLocation,
) -> Problem:
    location = fallback
    original_location = problem.location
    if (
        isinstance(original_location, ModelLocation)
        and original_location.root == "parameter_snapshot"
        and len(original_location.path) >= 2
        and original_location.path[0] == "values"
    ):
        parameter_id = original_location.path[1]
        if isinstance(parameter_id, str) and parameter_id in drafts:
            location = (
                _draft_parts_location(
                    drafts[parameter_id],
                    original_location.path[2:],
                )
                or drafts[parameter_id].location
            )
    related_locations = problem.related_locations
    if original_location is not None:
        related_locations = (original_location, *related_locations)
    return problem.model_copy(
        update={
            "phase": ProblemPhase.IMPORTING,
            "location": location,
            "related_locations": related_locations,
        }
    )


def _draft_validation_error_location(
    draft: DraftParameterValue,
    error: TypeError | ValueError,
) -> ExternalLocation:
    if not isinstance(error, ValidationError):
        return draft.location
    for finding in error.errors():
        parts = tuple(finding["loc"])
        location = _draft_parts_location(draft, parts)
        if location is not None:
            return location
    return draft.location


def _draft_parts_location(
    draft: DraftParameterValue,
    parts: tuple[LocationPathItem, ...],
) -> ExternalLocation | None:
    if isinstance(draft, SeriesParameterDraftValue) and draft.item_locations:
        index = _collection_index(parts, "items")
        if index is not None and index < len(draft.item_locations):
            return draft.item_locations[index]
    if isinstance(draft, TableParameterDraftValue) and draft.row_locations:
        index = _collection_index(parts, "rows")
        if index is not None and index < len(draft.row_locations):
            return draft.row_locations[index]
    return None


def _collection_index(
    parts: tuple[LocationPathItem, ...], collection: str
) -> int | None:
    try:
        selected = parts.index(collection) + 1
    except ValueError:
        return None
    if selected >= len(parts):
        return None
    value = parts[selected]
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except ValueError:
        return None


def _blocking_problems(problems: Sequence[Problem]) -> tuple[Problem, ...]:
    return tuple(
        problem for problem in problems if problem.impact is ProblemImpact.BLOCKING
    )


def _location_metadata(location: ExternalLocation) -> dict[str, Any]:
    return location.model_dump(mode="json", exclude_none=True)


__all__ = [
    "DraftParameterValue",
    "ImportSourceKind",
    "ParameterDraft",
    "ParameterImportResult",
    "ScalarParameterDraftValue",
    "SeriesParameterDraftValue",
    "TableParameterDraftValue",
    "accept_parameter_import",
    "import_problem",
    "parameter_import_result",
]
