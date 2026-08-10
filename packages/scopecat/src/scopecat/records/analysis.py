"""Persisted analysis record models."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import (
    Annotated,
    Literal,
    Self,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.kernel.content_identity import canonical_json
from scopecat.kernel.quantity import Quantity
from scopecat.records._metadata import JsonMetadata

type _NonEmptyText = Annotated[str, Field(min_length=1)]

MAX_ANALYSIS_TABLE_SAFE_INTEGER = 2**53 - 1
MAX_ANALYSIS_TABLE_COLUMNS = 32
MAX_ANALYSIS_TABLE_ROWS = 500
MAX_ANALYSIS_FIGURE_SERIES = 16
MAX_ANALYSIS_FIGURE_POINTS = 4096
MAX_ANALYSIS_OUTPUTS = 32
MAX_ANALYSIS_DATA_BYTES = 1_000_000
MAX_ANALYSIS_TOTAL_TABLE_CELLS = 64_000
MAX_ANALYSIS_TOTAL_FIGURE_POINTS = 16_384


def _reject_unsafe_table_integer(value: object) -> object:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and abs(value) > MAX_ANALYSIS_TABLE_SAFE_INTEGER
    ):
        raise ValueError(
            "analysis table integers must be within the JavaScript safe range"
        )
    return value


type _AnalysisTableInteger = Annotated[
    int,
    Field(
        ge=-MAX_ANALYSIS_TABLE_SAFE_INTEGER,
        le=MAX_ANALYSIS_TABLE_SAFE_INTEGER,
    ),
]
type AnalysisTableCell = Annotated[
    bool | _AnalysisTableInteger | FiniteFloat | str | None,
    BeforeValidator(_reject_unsafe_table_integer),
]


@dataclass(frozen=True, slots=True)
class AnalysisField:
    """Presentation policy declared once beside a typed derived-data field."""

    id: str | None = None
    label: str | None = None
    unit: str | None = None


def _normalized_external_scalar(value: object) -> bool | int | float | str | None:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    item = getattr(value, "item", None)
    if item is None:
        raise TypeError("analysis values must be scalar JSON values")
    try:
        normalized = cast("Callable[[], object]", item)()
    except (TypeError, ValueError) as error:
        raise TypeError("analysis values must be scalar JSON values") from error
    if normalized is None or isinstance(normalized, bool | int | float | str):
        return normalized
    raise TypeError("analysis values must be scalar JSON values")


def _normalized_figure_value(value: object) -> float:
    normalized = _normalized_external_scalar(value)
    if isinstance(normalized, bool) or not isinstance(normalized, int | float):
        raise TypeError("analysis figure values must be real numbers")
    return float(normalized)


class _AnalysisContentModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )


class AnalysisTableColumn(_AnalysisContentModel):
    """One stable scalar column in an analysis-authored table."""

    id: _NonEmptyText
    label: _NonEmptyText | None = None
    unit: _NonEmptyText | None = None


class AnalysisTableRow(_AnalysisContentModel):
    """Cells aligned positionally with an :class:`AnalysisTable` schema."""

    cells: list[AnalysisTableCell]


class AnalysisTable(_AnalysisContentModel):
    """A bounded, display-ready scalar table with an explicit column schema."""

    columns: list[AnalysisTableColumn] = Field(
        min_length=1,
        max_length=MAX_ANALYSIS_TABLE_COLUMNS,
    )
    rows: list[AnalysisTableRow] = Field(
        default_factory=list,
        max_length=MAX_ANALYSIS_TABLE_ROWS,
    )

    @model_validator(mode="after")
    def validate_layout(self) -> AnalysisTable:
        column_ids = tuple(column.id for column in self.columns)
        if len(column_ids) != len(set(column_ids)):
            raise ValueError("analysis table column ids must be unique")
        if any(len(row.cells) != len(self.columns) for row in self.rows):
            raise ValueError("analysis table rows must match the column count")
        return self

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Mapping[str, object]],
        *,
        columns: Sequence[AnalysisTableColumn] | None = None,
    ) -> Self:
        """Build the canonical table layout, normalizing array-library scalars."""

        selected_rows = tuple(rows)
        if columns is None:
            if not selected_rows:
                raise ValueError(
                    "analysis table columns are required for an empty table"
                )
            selected_columns = tuple(
                AnalysisTableColumn(id=column_id) for column_id in selected_rows[0]
            )
        else:
            selected_columns = tuple(columns)
        expected_ids = tuple(column.id for column in selected_columns)
        expected_id_set = set(expected_ids)
        for row in selected_rows:
            if set(row) != expected_id_set:
                raise ValueError(
                    "analysis table rows must define exactly the declared columns"
                )
        return cls(
            columns=list(selected_columns),
            rows=[
                AnalysisTableRow(
                    cells=[
                        _normalized_external_scalar(row[column_id])
                        for column_id in expected_ids
                    ]
                )
                for row in selected_rows
            ],
        )

    @classmethod
    def from_objects(cls, rows: Sequence[object]) -> Self:
        """Project annotated dataclass fields into one scalar table."""

        selected_rows = tuple(rows)
        if not selected_rows:
            raise ValueError("analysis object rows must not be empty")
        row_type = type(selected_rows[0])
        if not is_dataclass(row_type) or any(
            type(row) is not row_type for row in selected_rows
        ):
            raise TypeError("analysis object rows must share one dataclass type")
        hints = _dataclass_type_hints(row_type)
        selected_fields = tuple(
            (member.name, policy)
            for member in fields(row_type)
            if (policy := _analysis_field(hints.get(member.name))) is not None
        )
        if not selected_fields:
            raise TypeError(
                "analysis object rows require Annotated AnalysisField fields"
            )
        columns = tuple(
            AnalysisTableColumn(
                id=policy.id or name,
                label=policy.label,
                unit=policy.unit,
            )
            for name, policy in selected_fields
        )
        return cls.from_rows(
            [
                {
                    column.id: _analysis_field_value(
                        cast("object", getattr(row, name)),
                        policy,
                    )
                    for (name, policy), column in zip(
                        selected_fields,
                        columns,
                        strict=True,
                    )
                }
                for row in selected_rows
            ],
            columns=columns,
        )


def _dataclass_type_hints(row_type: type[object]) -> Mapping[str, object]:
    """Resolve postponed fields even after a project module is unloaded."""

    initializer = getattr(row_type, "__init__", None)
    retained_globals = getattr(initializer, "__globals__", None)
    globalns = cast(
        "dict[str, object] | None",
        retained_globals if isinstance(retained_globals, dict) else None,
    )
    return get_type_hints(
        row_type,
        globalns=globalns,
        include_extras=True,
    )


class AnalysisFigureAxis(_AnalysisContentModel):
    """One labeled numeric figure axis."""

    label: _NonEmptyText
    unit: _NonEmptyText | None = None


class AnalysisFigureSeries(_AnalysisContentModel):
    """One embedded numeric series; x and y values are point-aligned."""

    id: _NonEmptyText
    label: _NonEmptyText | None = None
    x: list[FiniteFloat] = Field(
        min_length=1,
        max_length=MAX_ANALYSIS_FIGURE_POINTS,
    )
    y: list[FiniteFloat] = Field(
        min_length=1,
        max_length=MAX_ANALYSIS_FIGURE_POINTS,
    )

    @model_validator(mode="after")
    def validate_points(self) -> AnalysisFigureSeries:
        if len(self.x) != len(self.y):
            raise ValueError(
                "analysis figure series x and y values must have equal length"
            )
        return self

    @classmethod
    def from_arrays(
        cls,
        *,
        id: str,
        x: Iterable[object],
        y: Iterable[object],
        label: str | None = None,
    ) -> Self:
        """Build a series from Python or array-library numeric iterables."""

        return cls(
            id=id,
            label=label,
            x=[_normalized_figure_value(value) for value in x],
            y=[_normalized_figure_value(value) for value in y],
        )


class AnalysisFigure(_AnalysisContentModel):
    """A finite embedded line or scatter figure ready for local rendering."""

    kind: Literal["line", "scatter"]
    x_axis: AnalysisFigureAxis
    y_axis: AnalysisFigureAxis
    series: list[AnalysisFigureSeries] = Field(
        min_length=1,
        max_length=MAX_ANALYSIS_FIGURE_SERIES,
    )

    @model_validator(mode="after")
    def validate_series(self) -> AnalysisFigure:
        series_ids = tuple(series.id for series in self.series)
        if len(series_ids) != len(set(series_ids)):
            raise ValueError("analysis figure series ids must be unique")
        if sum(len(series.x) for series in self.series) > MAX_ANALYSIS_FIGURE_POINTS:
            raise ValueError(
                "analysis figure total point count must not exceed "
                f"{MAX_ANALYSIS_FIGURE_POINTS}"
            )
        return self

    @classmethod
    def from_table(
        cls,
        table: AnalysisTable,
        *,
        kind: Literal["line", "scatter"],
        x: str,
        y: str,
        series: str | None = None,
        label: str | None = None,
    ) -> Self:
        """Project aligned numeric columns without rebuilding x/y lists."""

        columns = {
            column.id: (index, column) for index, column in enumerate(table.columns)
        }
        try:
            x_index, x_column = columns[x]
            y_index, y_column = columns[y]
            series_index = None if series is None else columns[series][0]
        except KeyError as error:
            raise KeyError(
                f"analysis figure column is missing: {error.args[0]}"
            ) from None
        grouped: dict[object, list[AnalysisTableRow]] = {}
        for row in table.rows:
            group = label or y if series_index is None else row.cells[series_index]
            grouped.setdefault(group, []).append(row)
        return cls(
            kind=kind,
            x_axis=AnalysisFigureAxis(
                label=x_column.label or x_column.id, unit=x_column.unit
            ),
            y_axis=AnalysisFigureAxis(
                label=y_column.label or y_column.id, unit=y_column.unit
            ),
            series=[
                AnalysisFigureSeries(
                    id=str(group),
                    label=str(group),
                    x=[_figure_cell(row.cells[x_index], column=x) for row in rows],
                    y=[_figure_cell(row.cells[y_index], column=y) for row in rows],
                )
                for group, rows in grouped.items()
            ],
        )


def _analysis_field(annotation: object) -> AnalysisField | None:
    if get_origin(annotation) is not Annotated:
        return None
    metadata_items = cast("tuple[object, ...]", get_args(annotation)[1:])
    return next(
        (
            metadata
            for metadata in metadata_items
            if isinstance(metadata, AnalysisField)
        ),
        None,
    )


def _analysis_field_value(value: object, policy: AnalysisField) -> object:
    if isinstance(value, Quantity):
        if policy.unit is None:
            raise TypeError("Quantity analysis fields require a presentation unit")
        return value.to(policy.unit).value
    return value


def _figure_cell(value: AnalysisTableCell, *, column: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"analysis figure column {column!r} must contain numbers")
    return float(value)


class AnalysisParameterProposalReference(_AnalysisContentModel):
    """Persisted reference to the separately stored proposal record."""

    proposal_id: _NonEmptyText
    record_ref: _NonEmptyText


class AnalysisComputeInput(_AnalysisContentModel):
    """One named, content-identified input consumed by dataset compute."""

    name: _NonEmptyText
    kind: Literal["measurement_dataset", "derived_dataset", "value"]
    target: _NonEmptyText
    content_hash: _NonEmptyText
    codec: _NonEmptyText
    value: JsonValue | None = None


class AnalysisComputeExecution(_AnalysisContentModel):
    """Content-addressed provenance for one successful dataset compute."""

    id: _NonEmptyText
    implementation: _NonEmptyText
    placement: Literal["dataset"] = "dataset"
    deterministic: bool
    inputs: Sequence[_NonEmptyText]
    outputs: Sequence[_NonEmptyText]
    input_bindings: Sequence[AnalysisComputeInput]
    captures: Sequence[_NonEmptyText] = ()
    access: Literal["full", "batches"] = "full"
    output_content_hash: _NonEmptyText

    @field_validator("inputs", "outputs", "input_bindings", "captures")
    @classmethod
    def freeze_edges[T](cls, value: Sequence[T]) -> Sequence[T]:
        return tuple(value)

    @model_validator(mode="after")
    def validate_input_bindings(self) -> AnalysisComputeExecution:
        if tuple(self.inputs) != tuple(binding.name for binding in self.input_bindings):
            raise ValueError("analysis compute inputs must match its input bindings")
        return self


class AnalysisDerivedData(_AnalysisContentModel):
    """JSON-safe compute output retained as an analysis fact."""

    codec: _NonEmptyText
    value: JsonValue
    execution: AnalysisComputeExecution

    @model_validator(mode="after")
    def validate_budget(self) -> AnalysisDerivedData:
        size = len(canonical_json(self.value).encode("utf-8"))
        if size > MAX_ANALYSIS_DATA_BYTES:
            raise ValueError(
                f"analysis derived data must not exceed {MAX_ANALYSIS_DATA_BYTES} bytes"
            )
        return self


class AnalysisDatasetReference(_AnalysisContentModel):
    """Reference to one separately stored, content-addressed derived dataset."""

    output_id: _NonEmptyText
    dataset_id: _NonEmptyText
    content_hash: _NonEmptyText
    codec: _NonEmptyText
    execution: AnalysisComputeExecution | None = None


class AnalysisRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: _NonEmptyText
    kind: Literal["measurement_dataset"]
    role: _NonEmptyText
    title: str | None = None
    metadata: JsonMetadata | None = None


class _AnalysisRecordOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: _NonEmptyText
    metadata: JsonMetadata = Field(default_factory=dict)


class AnalysisTableRecordOutput(_AnalysisRecordOutput):
    kind: Literal["table"]
    content: AnalysisTable


class AnalysisFigureRecordOutput(_AnalysisRecordOutput):
    kind: Literal["figure"]
    content: AnalysisFigure


class AnalysisParameterProposalRecordOutput(_AnalysisRecordOutput):
    kind: Literal["parameter_change_proposal"]
    content: AnalysisParameterProposalReference


class AnalysisDataRecordOutput(_AnalysisRecordOutput):
    kind: Literal["data"]
    content: AnalysisDerivedData


class AnalysisDatasetRecordOutput(_AnalysisRecordOutput):
    kind: Literal["dataset"]
    content: AnalysisDatasetReference


type AnalysisRecordOutput = Annotated[
    AnalysisDataRecordOutput
    | AnalysisDatasetRecordOutput
    | AnalysisTableRecordOutput
    | AnalysisFigureRecordOutput
    | AnalysisParameterProposalRecordOutput,
    Field(discriminator="kind"),
]


def validate_analysis_output_content_budget(
    contents: Iterable[AnalysisTable | AnalysisFigure],
) -> None:
    """Reject a group of embedded outputs too large for one analysis view."""

    table_cells = 0
    figure_points = 0
    for content in contents:
        if isinstance(content, AnalysisTable):
            table_cells += len(content.columns) * len(content.rows)
        else:
            figure_points += sum(len(series.x) for series in content.series)
    if table_cells > MAX_ANALYSIS_TOTAL_TABLE_CELLS:
        raise ValueError(
            "analysis total table cell count must not exceed "
            f"{MAX_ANALYSIS_TOTAL_TABLE_CELLS}"
        )
    if figure_points > MAX_ANALYSIS_TOTAL_FIGURE_POINTS:
        raise ValueError(
            "analysis total figure point count must not exceed "
            f"{MAX_ANALYSIS_TOTAL_FIGURE_POINTS}"
        )


class AnalysisRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: _NonEmptyText
    title: _NonEmptyText
    key: _NonEmptyText | None = None
    step_id: _NonEmptyText | None = None
    inputs: list[AnalysisRecordInput] = Field(default_factory=list)
    outputs: list[AnalysisRecordOutput] = Field(max_length=MAX_ANALYSIS_OUTPUTS)

    @model_validator(mode="after")
    def validate_output_budget(self) -> AnalysisRecord:
        validate_analysis_output_content_budget(
            output.content
            for output in self.outputs
            if isinstance(
                output, AnalysisTableRecordOutput | AnalysisFigureRecordOutput
            )
        )
        return self
