from __future__ import annotations

from scopecat.experiments import (
    acquire,
    bind_each,
    experiment,
    plan_experiment,
    set_state,
    update_param_rows,
)
from scopecat.models.parameter import Quantity
from scopecat.relations import (
    col,
    grid,
    linspace,
    literal_rows,
    outer,
    param,
    table,
)
from tests.support.experiment_kernel import parameter_build as _parameter_build


def test_kernel_state_patches_record_adjacent_desired_state_diffs() -> None:
    unchanged = experiment(
        id="unchanged-state-patches",
        kind="diagnostic",
        points=grid(index=[0, 1]),
        state=[
            set_state(
                "drive-a",
                "carrier_frequency",
                Quantity(value=5.0, unit="GHz"),
            )
        ],
        acquire=acquire("iq"),
    )
    swept = experiment(
        id="swept-state-patches",
        kind="diagnostic",
        points=grid(frequency=linspace(5.0, 5.1, 2, unit="GHz")),
        state=[
            set_state(
                "drive-a",
                "carrier_frequency",
                col("frequency"),
            )
        ],
        acquire=acquire("iq"),
    )

    unchanged_plan = plan_experiment(unchanged, _parameter_build())
    swept_plan = plan_experiment(swept, _parameter_build())
    unchanged_patches = [
        patch.model_dump(mode="json") for patch in unchanged_plan.state_patches
    ]
    swept_patches = [
        patch.model_dump(mode="json") for patch in swept_plan.state_patches
    ]

    assert unchanged_patches == [
        {
            "point_id": 0,
            "resource": "drive-a",
            "field": "carrier_frequency",
            "before": None,
            "after": {"value": 5.0, "unit": "GHz"},
        }
    ]
    assert swept_patches == [
        {
            "point_id": 0,
            "resource": "drive-a",
            "field": "carrier_frequency",
            "before": None,
            "after": {"value": 5.0, "unit": "GHz"},
        },
        {
            "point_id": 1,
            "resource": "drive-a",
            "field": "carrier_frequency",
            "before": {"value": 5.0, "unit": "GHz"},
            "after": {"value": 5.1, "unit": "GHz"},
        },
    ]
    assert unchanged_plan.content_hash != swept_plan.content_hash


def test_kernel_repeated_state_uses_outer_point_row() -> None:
    spec = experiment(
        id="shared-lo-fixed-if-scan",
        kind="drive.shared_lo_scan",
        points=grid(lo_frequency=linspace(4.9, 5.0, 2, unit="GHz")),
        state=[
            bind_each(
                table("drive_channels"),
                set_state(
                    col("resource_id"),
                    "carrier_frequency",
                    outer("lo_frequency") + col("fixed_if"),
                ),
            )
        ],
        acquire=acquire("iq"),
    )

    plan = plan_experiment(spec, _parameter_build())

    assert [point.row["lo_frequency"] for point in plan.points] == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
    ]
    assert [
        (record.point_id, record.resource, record.field, record.value)
        for record in plan.desired_state
    ] == [
        (0, "xy0", "carrier_frequency", Quantity(value=5.0, unit="GHz")),
        (0, "xy1", "carrier_frequency", Quantity(value=5.02, unit="GHz")),
        (1, "xy0", "carrier_frequency", Quantity(value=5.1, unit="GHz")),
        (1, "xy1", "carrier_frequency", Quantity(value=5.12, unit="GHz")),
    ]


def test_kernel_selected_target_table_plans_simultaneous_resources() -> None:
    spec = experiment(
        id="selected-readouts-with-shared-drives",
        kind="readout.selected_parallel_scan",
        points=(
            table("readout_devices")
            .join(
                literal_rows([{"device_id": "r1"}, {"device_id": "r0"}]),
                on={"device_id": "device_id"},
            )
            .sort("device_id")
        ),
        params=[
            update_param_rows(
                "readout_devices",
                key={"device_id": col("device_id")},
                values={"frequency": col("frequency") + Quantity(value=50, unit="MHz")},
            )
        ],
        state=[
            set_state(
                col("resource_id"),
                "readout.frequency",
                param(
                    "readout_devices",
                    key={"device_id": col("device_id")},
                    column="frequency",
                ),
            ),
            bind_each(
                table("drive_channels"),
                set_state(
                    col("resource_id"),
                    "drive.carrier_frequency",
                    outer("frequency") + col("fixed_if"),
                ),
            ),
        ],
        acquire=acquire("iq", record="trace", dimensions=["time"]),
    )

    plan = plan_experiment(spec, _parameter_build())

    assert [point.row["device_id"] for point in plan.points] == ["r0", "r1"]
    assert [
        (record.patch.values or {})["frequency"] for record in plan.parameter_patches
    ] == [
        Quantity(value=6.0, unit="GHz"),
        Quantity(value=6.15, unit="GHz"),
    ]
    assert [
        (record.point_id, record.resource, record.field, record.value)
        for record in plan.desired_state
    ] == [
        (0, "readout-a", "readout.frequency", Quantity(value=6.0, unit="GHz")),
        (0, "xy0", "drive.carrier_frequency", Quantity(value=6.05, unit="GHz")),
        (0, "xy1", "drive.carrier_frequency", Quantity(value=6.07, unit="GHz")),
        (1, "readout-b", "readout.frequency", Quantity(value=6.15, unit="GHz")),
        (1, "xy0", "drive.carrier_frequency", Quantity(value=6.2, unit="GHz")),
        (1, "xy1", "drive.carrier_frequency", Quantity(value=6.22, unit="GHz")),
    ]
    assert plan.acquisition.record == "trace"
    assert plan.acquisition.dimensions == ["time"]
