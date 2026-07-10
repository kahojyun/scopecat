from scopecat._compiler.program import (
    linked_program as experiment,
)
from scopecat._compiler.program import (
    observable,
    overlay_parameter_cell,
    record_axis,
    set_state,
)
from scopecat._relations import col, grid, table
from scopecat.models.parameter import Quantity
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar, String
from tests.support.experiment_preview import preview_result
from tests.support.parameter_fixtures import parameters


def test_preview_reports_record_output_shape_diagnostics() -> None:
    spec = experiment(
        id="bad-record-shape",
        kind="diagnostic",
        points=grid(index=[0]),
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

    preview, diagnostics = preview_result(spec, parameters())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_record_duplicate",
        "experiment_record_axis_duplicate",
    ]
    assert preview.dataset_dimensions == {}
    assert preview.primary_observables == ("signal", "signal")


def test_preview_rejects_duplicate_instrument_product_keys() -> None:
    spec = experiment(
        id="bad-record-products",
        kind="diagnostic",
        points=grid(index=[0]),
        records=[
            observable("raw_i", unit="ratio", product_key="i"),
            observable("demod_i", unit="ratio", product_key="i"),
        ],
    )

    preview, diagnostics = preview_result(spec, parameters())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_record_product_duplicate"
    ]
    assert preview.dataset_dimensions == {}
    assert preview.primary_observables == ("raw_i", "demod_i")


def test_preview_reports_points_evaluation_diagnostics() -> None:
    spec = experiment(
        id="missing-points",
        kind="diagnostic",
        points=table("missing_table"),
    )

    preview, diagnostics = preview_result(spec, parameters())

    assert preview.points == ()
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_points_evaluation_failed"
    ]


def test_preview_reports_parameter_overlay_diagnostics() -> None:
    spec = experiment(
        id="bad-overlay",
        kind="diagnostic",
        points=grid(device_id=["r0"]),
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
            set_state(
                "readout-a",
                "pulse.frequency",
                Quantity(value=5.9, unit="GHz"),
            )
        ],
    )

    preview, diagnostics = preview_result(spec, parameters())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_parameter_overlay_row_not_found"
    ]
    assert preview.state_changes == ()


def test_preview_reports_unknown_parameter_table_diagnostics() -> None:
    spec = experiment(
        id="missing-overlay-table",
        kind="diagnostic",
        points=grid(device_id=["r0"]),
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

    preview, diagnostics = preview_result(spec, parameters())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_parameter_overlay_table_missing"
    ]
    assert preview.state_changes == ()


def test_preview_reports_state_evaluation_and_conflict_diagnostics() -> None:
    state_failure = experiment(
        id="bad-state",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[set_state(1, "pulse.frequency", Quantity(value=5.9, unit="GHz"))],
    )
    conflict = experiment(
        id="conflict-state",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state("readout-a", "pulse.frequency", Quantity(value=5.9, unit="GHz")),
            set_state("readout-a", "pulse.frequency", Quantity(value=6.0, unit="GHz")),
        ],
    )

    failed_preview, failed_diagnostics = preview_result(state_failure, parameters())
    conflict_preview, conflict_diagnostics = preview_result(conflict, parameters())

    assert [diagnostic.code for diagnostic in failed_diagnostics] == [
        "experiment_state_evaluation_failed"
    ]
    assert failed_preview.state_changes == ()
    assert [diagnostic.code for diagnostic in conflict_diagnostics] == [
        "experiment_conflicting_desired_state"
    ]
    assert [change.after for change in conflict_preview.state_changes] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]
