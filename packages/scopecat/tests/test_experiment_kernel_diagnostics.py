from scopecat.experiments import (
    acquire,
    experiment,
    plan_experiment,
    point,
    set_state,
    update_param_rows,
)
from scopecat.models.parameter import Quantity
from scopecat.parameters import ParameterDerivationSet, ScalarParameterDerivation
from scopecat.relations import col, grid, param, table
from tests.support.experiment_kernel import (
    derived_parameter_build,
    diagnostic_codes,
    is_sha256,
    parameter_build,
)


def test_kernel_records_acquisition_shape_diagnostics() -> None:
    spec = experiment(
        id="bad-acquisition-shape",
        kind="diagnostic",
        points=grid(index=[0]),
        acquire=acquire(
            "iq",
            record="trace",
            dimensions=["time", "time"],
            channels=["readout-a", "readout-a"],
            observations=[
                point("signal", unit="ratio"),
                point("signal", unit="ratio"),
            ],
        ),
    )

    plan = plan_experiment(spec, parameter_build())

    assert diagnostic_codes(plan.diagnostics) == [
        "experiment_acquisition_duplicate_dimension",
        "experiment_acquisition_duplicate_channel",
        "experiment_acquisition_duplicate_observation",
    ]
    assert plan.expected_dataset_schema is None


def test_kernel_plan_records_points_evaluation_diagnostics() -> None:
    spec = experiment(
        id="missing-points",
        kind="diagnostic",
        points=table("missing_table"),
        acquire=acquire("iq"),
    )

    plan = plan_experiment(spec, parameter_build())

    assert plan.points == []
    assert diagnostic_codes(plan.diagnostics) == ["experiment_points_evaluation_failed"]
    assert is_sha256(plan.content_hash)


def test_kernel_plan_records_parameter_patch_diagnostics() -> None:
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
        acquire=acquire("iq"),
    )

    plan = plan_experiment(spec, parameter_build())

    assert diagnostic_codes(plan.diagnostics) == [
        "experiment_parameter_patch_row_not_found"
    ]
    assert plan.parameter_patches[0].patch.table_id == "readout_devices"
    assert plan.desired_state == []


def test_kernel_plan_records_unknown_parameter_table_diagnostics() -> None:
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
        acquire=acquire("iq"),
    )

    plan = plan_experiment(spec, parameter_build())

    assert diagnostic_codes(plan.diagnostics) == [
        "experiment_parameter_patch_table_missing"
    ]
    assert plan.parameter_patches == []
    assert plan.desired_state == []


def test_kernel_plan_records_state_evaluation_and_conflict_diagnostics() -> None:
    state_failure = experiment(
        id="bad-state",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[set_state(1, "pulse.frequency", Quantity(value=5.9, unit="GHz"))],
        acquire=acquire("iq"),
    )
    conflict = experiment(
        id="conflict-state",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state("readout-a", "pulse.frequency", Quantity(value=5.9, unit="GHz")),
            set_state("readout-a", "pulse.frequency", Quantity(value=6.0, unit="GHz")),
        ],
        acquire=acquire("iq"),
    )

    failed_plan = plan_experiment(state_failure, parameter_build())
    conflict_plan = plan_experiment(conflict, parameter_build())

    assert diagnostic_codes(failed_plan.diagnostics) == [
        "experiment_state_evaluation_failed"
    ]
    assert failed_plan.desired_state == []
    assert diagnostic_codes(conflict_plan.diagnostics) == [
        "experiment_conflicting_desired_state"
    ]
    assert [record.value for record in conflict_plan.desired_state] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]


def test_kernel_records_parameter_derivation_diagnostics() -> None:
    spec = experiment(
        id="failed-derivation",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[set_state("drive-a", "carrier_frequency", param("derived.bad"))],
        acquire=acquire("iq"),
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

    plan = plan_experiment(
        spec,
        derived_parameter_build(),
        derivations=derivations,
    )

    assert diagnostic_codes(plan.diagnostics) == [
        "experiment_parameter_derivation_failed"
    ]
    assert plan.desired_state == []
