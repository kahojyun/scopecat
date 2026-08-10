from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import numpy as np
import pytest
from pydantic import ValidationError

from scopecat.kernel.quantity import Quantity
from scopecat.records.analysis import (
    MAX_ANALYSIS_FIGURE_POINTS,
    MAX_ANALYSIS_OUTPUTS,
    MAX_ANALYSIS_TABLE_COLUMNS,
    MAX_ANALYSIS_TABLE_ROWS,
    MAX_ANALYSIS_TABLE_SAFE_INTEGER,
    MAX_ANALYSIS_TOTAL_FIGURE_POINTS,
    MAX_ANALYSIS_TOTAL_TABLE_CELLS,
    AnalysisField,
    AnalysisFigure,
    AnalysisFigureAxis,
    AnalysisFigureRecordOutput,
    AnalysisFigureSeries,
    AnalysisParameterProposalRecordOutput,
    AnalysisParameterProposalReference,
    AnalysisRecord,
    AnalysisRecordInput,
    AnalysisTable,
    AnalysisTableColumn,
    AnalysisTableRecordOutput,
    AnalysisTableRow,
)


@dataclass(frozen=True)
class _Observation:
    bias: Annotated[
        Quantity,
        AnalysisField(id="bias_mv", label="Bias", unit="mV"),
    ]
    response: Annotated[float, AnalysisField(label="Response", unit="ratio")]
    group: Annotated[int, AnalysisField(label="Group")]


def test_analysis_projects_annotated_objects_into_tables_and_figures() -> None:
    table = AnalysisTable.from_objects(
        [
            _Observation(Quantity(0.1, "V"), 0.2, 1),
            _Observation(Quantity(0.2, "V"), 0.4, 1),
            _Observation(Quantity(0.3, "V"), 0.6, 2),
        ]
    )
    figure = AnalysisFigure.from_table(
        table,
        kind="scatter",
        x="bias_mv",
        y="response",
        series="group",
    )

    assert [column.id for column in table.columns] == [
        "bias_mv",
        "response",
        "group",
    ]
    assert [row.cells for row in table.rows] == [
        [100.0, 0.2, 1],
        [200.0, 0.4, 1],
        [300.0, 0.6, 2],
    ]
    assert [(series.id, series.x, series.y) for series in figure.series] == [
        ("1", [100.0, 200.0], [0.2, 0.4]),
        ("2", [300.0], [0.6]),
    ]


def test_analysis_record_outputs_round_trip_as_discriminated_display_contracts() -> (
    None
):
    record = AnalysisRecord(
        run_id="run-analysis",
        title="Fit review",
        outputs=[
            AnalysisTableRecordOutput(
                kind="table",
                title="Fit parameters",
                content=AnalysisTable.from_rows(
                    [{"frequency": 5.1, "converged": True}],
                    columns=[
                        AnalysisTableColumn(
                            id="frequency",
                            label="Frequency",
                            unit="GHz",
                        ),
                        AnalysisTableColumn(id="converged", label="Converged"),
                    ],
                ),
            ),
            AnalysisFigureRecordOutput(
                kind="figure",
                title="Fit curve",
                content=AnalysisFigure(
                    kind="line",
                    x_axis=AnalysisFigureAxis(label="Bias", unit="V"),
                    y_axis=AnalysisFigureAxis(label="Frequency", unit="GHz"),
                    series=[
                        AnalysisFigureSeries(
                            id="fit",
                            x=[-0.1, 0.0, 0.1],
                            y=[5.0, 5.1, 5.0],
                        )
                    ],
                ),
            ),
            AnalysisParameterProposalRecordOutput(
                kind="parameter_change_proposal",
                title="readout-fit",
                content=AnalysisParameterProposalReference(
                    proposal_id="readout-fit",
                    record_ref="records/parameter-change-proposal/readout-fit.json",
                ),
            ),
        ],
    )

    restored = AnalysisRecord.model_validate_json(record.model_dump_json())

    assert isinstance(restored.outputs[0], AnalysisTableRecordOutput)
    assert restored.outputs[0].content.rows[0].cells == [5.1, True]
    assert isinstance(restored.outputs[1], AnalysisFigureRecordOutput)
    assert restored.outputs[1].content.series[0].y == [5.0, 5.1, 5.0]
    assert isinstance(restored.outputs[2], AnalysisParameterProposalRecordOutput)
    assert restored.outputs[2].content.proposal_id == "readout-fit"


def test_analysis_embedded_outputs_have_gui_safe_size_limits() -> None:
    with pytest.raises(ValidationError, match="at most 500 items"):
        AnalysisTable(
            columns=[AnalysisTableColumn(id="value")],
            rows=[
                AnalysisTableRow(cells=[index])
                for index in range(MAX_ANALYSIS_TABLE_ROWS + 1)
            ],
        )

    points_per_series = MAX_ANALYSIS_FIGURE_POINTS // 2 + 1
    values = [float(index) for index in range(points_per_series)]
    with pytest.raises(ValidationError, match="total point count"):
        AnalysisFigure(
            kind="scatter",
            x_axis=AnalysisFigureAxis(label="x"),
            y_axis=AnalysisFigureAxis(label="y"),
            series=[
                AnalysisFigureSeries(id="first", x=values, y=values),
                AnalysisFigureSeries(id="second", x=values, y=values),
            ],
        )


def test_analysis_table_integer_rejects_values_outside_javascript_safe_range() -> None:
    row = AnalysisTableRow(
        cells=[
            -MAX_ANALYSIS_TABLE_SAFE_INTEGER,
            MAX_ANALYSIS_TABLE_SAFE_INTEGER,
        ]
    )

    assert row.cells == [
        -MAX_ANALYSIS_TABLE_SAFE_INTEGER,
        MAX_ANALYSIS_TABLE_SAFE_INTEGER,
    ]
    with pytest.raises(ValidationError, match="JavaScript safe range"):
        AnalysisTableRow(cells=[MAX_ANALYSIS_TABLE_SAFE_INTEGER + 2])
    with pytest.raises(ValidationError, match="JavaScript safe range"):
        AnalysisTableRow.model_validate_json('{"cells":[9007199254740993]}')


def test_analysis_helpers_normalize_numpy_arrays_and_scalars() -> None:
    table = AnalysisTable.from_rows([{"count": np.int64(7), "ratio": np.float64(0.25)}])
    series = AnalysisFigureSeries.from_arrays(
        id="numpy",
        x=np.asarray([1, 2], dtype=np.int64),
        y=np.asarray([0.25, 0.5], dtype=np.float64),
    )

    assert table.rows[0].cells == [7, 0.25]
    assert series.x == [1.0, 2.0]
    assert series.y == [0.25, 0.5]


def test_analysis_record_bounds_total_embedded_display_content() -> None:
    table = AnalysisTable(
        columns=[
            AnalysisTableColumn(id=f"column-{index}")
            for index in range(MAX_ANALYSIS_TABLE_COLUMNS)
        ],
        rows=[
            AnalysisTableRow(cells=[index] * MAX_ANALYSIS_TABLE_COLUMNS)
            for index in range(MAX_ANALYSIS_TABLE_ROWS)
        ],
    )
    table_output = AnalysisTableRecordOutput(
        kind="table",
        title="large table",
        content=table,
    )
    with pytest.raises(ValidationError, match="total table cell count"):
        AnalysisRecord(
            run_id="run-table-budget",
            title="large tables",
            outputs=[
                table_output
                for _ in range(
                    MAX_ANALYSIS_TOTAL_TABLE_CELLS
                    // (MAX_ANALYSIS_TABLE_COLUMNS * MAX_ANALYSIS_TABLE_ROWS)
                    + 1
                )
            ],
        )

    values = [float(index) for index in range(MAX_ANALYSIS_FIGURE_POINTS)]
    figure_output = AnalysisFigureRecordOutput(
        kind="figure",
        title="large figure",
        content=AnalysisFigure(
            kind="line",
            x_axis=AnalysisFigureAxis(label="x"),
            y_axis=AnalysisFigureAxis(label="y"),
            series=[AnalysisFigureSeries(id="large", x=values, y=values)],
        ),
    )
    with pytest.raises(ValidationError, match="total figure point count"):
        AnalysisRecord(
            run_id="run-figure-budget",
            title="large figures",
            outputs=[
                figure_output
                for _ in range(
                    MAX_ANALYSIS_TOTAL_FIGURE_POINTS // MAX_ANALYSIS_FIGURE_POINTS + 1
                )
            ],
        )

    with pytest.raises(ValidationError, match=f"at most {MAX_ANALYSIS_OUTPUTS} items"):
        AnalysisRecord(
            run_id="run-output-budget",
            title="too many outputs",
            outputs=[table_output] * (MAX_ANALYSIS_OUTPUTS + 1),
        )


def test_analysis_record_rejects_empty_required_text_like_the_wire_contract() -> None:
    with pytest.raises(ValidationError, match="at least 1 character"):
        AnalysisRecord(run_id="run-analysis", title="", outputs=[])
    with pytest.raises(ValidationError, match="at least 1 character"):
        AnalysisRecord(
            run_id="run-analysis",
            title="Analysis",
            step_id="",
            outputs=[],
        )
    with pytest.raises(ValidationError, match="at least 1 character"):
        AnalysisRecordInput(
            target="",
            kind="measurement_dataset",
            role="data",
        )
    with pytest.raises(ValidationError, match="at least 1 character"):
        AnalysisTableRecordOutput(
            kind="table",
            title="",
            content=AnalysisTable.from_rows([{"value": 1}]),
        )
