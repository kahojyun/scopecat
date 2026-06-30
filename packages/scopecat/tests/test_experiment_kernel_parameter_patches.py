from scopecat.experiments import (
    acquire,
    bind_each,
    delete_param_rows,
    experiment,
    insert_param_rows,
    plan_experiment,
    set_param,
    set_state,
)
from scopecat.models.parameter import Quantity
from scopecat.relations import col, grid, linspace, outer, param, table
from tests.support.experiment_kernel import (
    derived_parameter_build as _derived_parameter_build,
)
from tests.support.experiment_kernel import (
    diagnostic_codes as _codes,
)
from tests.support.experiment_kernel import (
    drive_derivations as _drive_derivations,
)
from tests.support.experiment_kernel import (
    parameter_build as _parameter_build,
)


def test_kernel_insert_and_delete_row_patches_update_point_table_view() -> None:
    spec = experiment(
        id="patched-drive-table",
        kind="drive.table_patch",
        points=grid(
            inserted_if=linspace(140, 140, 1, unit="MHz"),
            carrier=linspace(5.0, 5.0, 1, unit="GHz"),
        ),
        params=[
            delete_param_rows(
                "drive_channels",
                key={"resource_id": "xy1"},
            ),
            insert_param_rows(
                "drive_channels",
                rows=[
                    {
                        "resource_id": "xy2",
                        "fixed_if": col("inserted_if"),
                    }
                ],
            ),
        ],
        state=[
            bind_each(
                table("drive_channels"),
                set_state(
                    col("resource_id"),
                    "carrier_frequency",
                    outer("carrier") + col("fixed_if"),
                ),
            )
        ],
        acquire=acquire("iq"),
    )

    plan = plan_experiment(
        spec,
        _parameter_build(),
        allow_table_row_changes=True,
    )

    assert [record.patch.kind for record in plan.parameter_patches] == [
        "delete_rows",
        "insert_rows",
    ]
    assert plan.parameter_patches[0].patch.key == {"resource_id": "xy1"}
    assert plan.parameter_patches[1].patch.rows == [
        {"resource_id": "xy2", "fixed_if": Quantity(value=140, unit="MHz")}
    ]
    assert plan.parameter_patches[0].affected_rows == [
        {"resource_id": "xy1", "fixed_if": Quantity(value=120, unit="MHz")}
    ]
    assert plan.parameter_patches[1].affected_rows == [
        {"resource_id": "xy2", "fixed_if": Quantity(value=140, unit="MHz")}
    ]
    assert [(record.resource, record.value) for record in plan.desired_state] == [
        ("xy0", Quantity(value=5.1, unit="GHz")),
        ("xy2", Quantity(value=5.14, unit="GHz")),
    ]


def test_kernel_rejects_structural_parameter_patches_without_opt_in() -> None:
    spec = experiment(
        id="structural-patch-without-opt-in",
        kind="diagnostic",
        points=grid(index=[0]),
        params=[
            delete_param_rows(
                "drive_channels",
                key={"resource_id": "xy1"},
            )
        ],
        state=[
            bind_each(
                table("drive_channels"),
                set_state(
                    col("resource_id"),
                    "carrier_frequency",
                    Quantity(value=5.0, unit="GHz"),
                ),
            )
        ],
        acquire=acquire("iq"),
    )

    plan = plan_experiment(spec, _parameter_build())

    assert _codes(plan.diagnostics) == [
        "experiment_parameter_patch_row_change_not_allowed"
    ]
    assert plan.parameter_patches == []
    assert plan.desired_state == []


def test_kernel_recomputes_derivations_after_point_parameter_patches() -> None:
    derivations = _drive_derivations()
    spec = experiment(
        id="derived-drive-plan",
        kind="drive.derived_frequency_scan",
        points=grid(lo_frequency=linspace(5.0, 5.1, 2, unit="GHz")),
        params=[set_param("drive.lo_frequency", col("lo_frequency"))],
        state=[
            set_state(
                "drive-center",
                "carrier_frequency",
                param("drive.center_frequency"),
            ),
            bind_each(
                table("drive_plan"),
                set_state(
                    col("resource_id"),
                    "carrier_frequency",
                    col("carrier_frequency"),
                ),
            ),
        ],
        acquire=acquire("iq"),
    )

    plan = plan_experiment(
        spec,
        _derived_parameter_build(),
        derivations=derivations,
    )

    assert _codes(plan.diagnostics) == []
    assert [record.patch.value for record in plan.parameter_patches] == [
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    assert [record.affected_rows for record in plan.parameter_patches] == [[], []]
    assert [
        (record.point_id, record.resource, record.value)
        for record in plan.desired_state
    ] == [
        (0, "drive-center", Quantity(value=5.1, unit="GHz")),
        (0, "drive-a", Quantity(value=5.1, unit="GHz")),
        (0, "drive-b", Quantity(value=5.12, unit="GHz")),
        (1, "drive-center", Quantity(value=5.2, unit="GHz")),
        (1, "drive-a", Quantity(value=5.2, unit="GHz")),
        (1, "drive-b", Quantity(value=5.22, unit="GHz")),
    ]
