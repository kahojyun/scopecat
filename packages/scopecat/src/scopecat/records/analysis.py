"""Persisted analysis record models."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Annotated, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    model_validator,
)

from scopecat.records._metadata import JsonMetadata

type _NonEmptyText = Annotated[str, Field(min_length=1)]

MAX_ANALYSIS_TABLE_SAFE_INTEGER = 2**53 - 1
MAX_ANALYSIS_TABLE_COLUMNS = 32
MAX_ANALYSIS_TABLE_ROWS = 500
MAX_ANALYSIS_FIGURE_SERIES = 16
MAX_ANALYSIS_FIGURE_POINTS = 4096
MAX_ANALYSIS_OUTPUTS = 32
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


class AnalysisParameterProposalReference(_AnalysisContentModel):
    """Persisted reference to the separately stored proposal record."""

    proposal_id: _NonEmptyText
    record_ref: _NonEmptyText


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


type AnalysisRecordOutput = Annotated[
    AnalysisTableRecordOutput
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
