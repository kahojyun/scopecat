from scopecat.experiments import (
    experiment,
    observable,
    record_axis,
    set_state,
    update_param_rows,
)
from scopecat.models.parameter import Quantity
from scopecat.parameters import ParameterDerivationSet, ScalarParameterDerivation
from scopecat.relations import col, grid, param, table
from tests.support.experiment_preview import preview_result
from tests.support.parameter_fixtures import (
    derived_parameter_view,
    parameter_view,
)


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

    preview, diagnostics = preview_result(spec, parameter_view())

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

    preview, diagnostics = preview_result(spec, parameter_view())

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

    preview, diagnostics = preview_result(spec, parameter_view())

    assert preview.points == ()
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_points_evaluation_failed"
    ]


def test_preview_reports_parameter_patch_diagnostics() -> None:
    spec = experiment(
        id="bad-patch",
        kind="diagnostic",
        points=grid(device_id=["r0"]),
        params=[
            update_param_rows(
                "readout_devices",
                key={"device_id": col("device_id")},
                values={"frequency": Quantity(value=5.9, unit="GHz")},
            ),
            update_param_rows(
                "readout_devices",
                key={"device_id": "missing"},
                values={"frequency": Quantity(value=5.9, unit="GHz")},
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

    preview, diagnostics = preview_result(spec, parameter_view())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_parameter_patch_row_not_found"
    ]
    assert preview.state_changes == ()


def test_preview_reports_unknown_parameter_table_diagnostics() -> None:
    spec = experiment(
        id="missing-patch-table",
        kind="diagnostic",
        points=grid(device_id=["r0"]),
        params=[
            update_param_rows(
                "missing_table",
                key={"device_id": col("device_id")},
                values={"frequency": Quantity(value=5.9, unit="GHz")},
            )
        ],
    )

    preview, diagnostics = preview_result(spec, parameter_view())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_parameter_patch_table_missing"
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

    failed_preview, failed_diagnostics = preview_result(state_failure, parameter_view())
    conflict_preview, conflict_diagnostics = preview_result(conflict, parameter_view())

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


def test_preview_reports_parameter_derivation_diagnostics() -> None:
    spec = experiment(
        id="failed-derivation",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[set_state("drive-a", "carrier_frequency", param("derived.bad"))],
    )
    derivations = ParameterDerivationSet(
        id="bad-derivations",
        scalars=[
            ScalarParameterDerivation(
                id="derived.bad",
                expression=param("missing.scalar"),
            )
        ],
    )

    preview, diagnostics = preview_result(
        spec,
        derived_parameter_view(),
        derivations=derivations,
    )

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_parameter_derivation_failed"
    ]
    assert preview.state_changes == ()
