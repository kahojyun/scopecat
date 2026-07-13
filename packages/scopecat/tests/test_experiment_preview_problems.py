import pytest

from scopecat._compiler.program import (
    TypedPointSource,
    observable,
    overlay_parameter_cell,
    record_axis,
    set_state_field,
    typed_program,
)
from scopecat._compiler.records import RecordAxisSpec
from scopecat._relations import RelationExpr, col, grid, table
from scopecat.models.parameter import Quantity
from scopecat.problems import ProblemCategory, model_location
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar, String
from scopecat.value_types import Table as TableType
from tests.support.experiment_preview import preview_result
from tests.support.parameter_fixtures import parameters


def _point_source(expr: RelationExpr) -> TypedPointSource:
    return TypedPointSource(
        expr=expr,
        value_type=TableType(columns=(), allow_extra_columns=True),
    )


def test_preview_reports_record_output_shape_problems() -> None:
    spec = typed_program(
        id="bad-record-shape",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        records=[
            observable(
                "signal",
                unit="ratio",
                axes=[
                    record_axis("shot", size=3),
                    record_axis("shot", size=3),
                ],
            ),
            observable("signal", unit="ratio"),
        ],
    )

    preview, problems = preview_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_record_duplicate",
        "experiment_record_axis_duplicate",
    ]
    assert preview.dataset_dimensions == {}
    assert preview.primary_observables == ("signal", "signal")


def test_preview_reports_record_schema_problems_without_model_errors() -> None:
    spec = typed_program(
        id="invalid-record-schema",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        records=[
            observable("bad-unit", unit="not-a-unit"),
            observable(
                "bad-axis-unit",
                axes=[record_axis("sample", size=2, unit="not-a-unit")],
            ),
            observable(
                "reserved-axis",
                axes=[record_axis("point", size=2)],
            ),
        ],
    )

    preview, problems = preview_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_record_unit_unsupported",
        "experiment_record_axis_unit_unsupported",
        "experiment_record_axis_reserved",
    ]
    assert preview.schema is None


def test_preview_reports_coordinate_and_record_id_collision() -> None:
    spec = typed_program(
        id="coordinate-record-collision",
        kind="problem",
        point_source=_point_source(grid(signal=[1.0])),
        records=[observable("signal", unit="ratio")],
    )

    preview, problems = preview_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_record_coordinate_collision"
    ]
    assert preview.schema is None


def test_preview_rejects_duplicate_instrument_product_keys() -> None:
    spec = typed_program(
        id="bad-record-products",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        records=[
            observable("raw_i", unit="ratio", product_key="i"),
            observable("demod_i", unit="ratio", product_key="i"),
        ],
    )

    preview, problems = preview_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_record_product_duplicate"
    ]
    assert preview.dataset_dimensions == {}
    assert preview.primary_observables == ("raw_i", "demod_i")


def test_preview_rejects_unimplemented_observable_sources() -> None:
    spec = typed_program(
        id="unsupported-record-source",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        records=[observable("signal", source="point", unit="ratio")],
    )

    preview, problems = preview_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_record_source_unsupported"
    ]
    assert preview.schema is None


@pytest.mark.parametrize(
    "second_axis",
    [
        record_axis(
            "shot",
            size=3,
            kind="shot",
            unit="count",
            metadata={"mode": "raw"},
        ),
        record_axis(
            "shot",
            size=2,
            kind="sample",
            unit="count",
            metadata={"mode": "raw"},
        ),
        record_axis(
            "shot",
            size=2,
            kind="shot",
            unit=None,
            metadata={"mode": "raw"},
        ),
        record_axis(
            "shot",
            size=2,
            kind="shot",
            unit="count",
            metadata={"mode": "averaged"},
        ),
    ],
)
def test_preview_rejects_conflicting_shared_record_axes(
    second_axis: RecordAxisSpec,
) -> None:
    first_axis = record_axis(
        "shot",
        size=2,
        kind="shot",
        unit="count",
        metadata={"mode": "raw"},
    )
    spec = typed_program(
        id="conflicting-record-axis",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        records=[
            observable("i", axes=[first_axis]),
            observable("q", axes=[second_axis]),
        ],
    )

    preview, problems = preview_result(spec, parameters())

    assert [problem.code for problem in problems] == ["experiment_record_axis_conflict"]
    assert problems[0].category is ProblemCategory.CONFLICT
    assert problems[0].related_locations == (
        model_location("records", "i", "axes", "shot"),
    )
    assert preview.schema is None


def test_preview_reports_points_evaluation_problems() -> None:
    spec = typed_program(
        id="missing-points",
        kind="problem",
        point_source=_point_source(table("missing_table")),
    )

    preview, problems = preview_result(spec, parameters())

    assert preview.points == ()
    assert [problem.code for problem in problems] == [
        "experiment_points_evaluation_failed"
    ]


def test_preview_reports_parameter_overlay_problems() -> None:
    spec = typed_program(
        id="bad-overlay",
        kind="problem",
        point_source=_point_source(grid(device_id=["r0"])),
        parameter_overlays=[
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": col("device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
            ),
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": "missing"},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
            ),
        ],
        state=[
            set_state_field(
                "readout-a",
                capability_id="pulse",
                field_path="frequency",
                value=Quantity(value=5.9, unit="GHz"),
            )
        ],
    )

    preview, problems = preview_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_parameter_overlay_row_not_found"
    ]
    assert preview.state_changes == ()


def test_preview_reports_unknown_parameter_table_problems() -> None:
    spec = typed_program(
        id="missing-overlay-table",
        kind="problem",
        point_source=_point_source(grid(device_id=["r0"])),
        parameter_overlays=[
            overlay_parameter_cell(
                "missing_table",
                key={"device_id": col("device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
            )
        ],
    )

    preview, problems = preview_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_parameter_overlay_table_missing"
    ]
    assert preview.state_changes == ()


def test_preview_reports_state_evaluation_and_conflict_problems() -> None:
    state_failure = typed_program(
        id="bad-state",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        state=[
            set_state_field(
                1,
                capability_id="pulse",
                field_path="frequency",
                value=Quantity(value=5.9, unit="GHz"),
            )
        ],
    )
    conflict = typed_program(
        id="conflict-state",
        kind="problem",
        point_source=_point_source(grid(index=[0])),
        state=[
            set_state_field(
                "readout-a",
                capability_id="pulse",
                field_path="frequency",
                value=Quantity(value=5.9, unit="GHz"),
            ),
            set_state_field(
                "readout-a",
                capability_id="pulse",
                field_path="frequency",
                value=Quantity(value=6.0, unit="GHz"),
            ),
        ],
    )

    failed_preview, failed_problems = preview_result(state_failure, parameters())
    conflict_preview, conflict_problems = preview_result(conflict, parameters())

    assert [problem.code for problem in failed_problems] == [
        "experiment_state_evaluation_failed"
    ]
    assert failed_preview.state_changes == ()
    assert [problem.code for problem in conflict_problems] == [
        "experiment_conflicting_desired_state"
    ]
    assert [change.after for change in conflict_preview.state_changes] == [
        Quantity(value=5.9, unit="GHz"),
    ]
