from scopecat.experiments import (
    configure,
    experiment,
    local_overrides,
    local_scan,
    observable,
    param_row,
    rows,
    scan_parameter,
    set_state,
)
from scopecat.models.parameter import Quantity
from scopecat.relations import col, grid, linspace, param, range_values
from tests.support.experiment_preview import preview_contract
from tests.support.parameter_fixtures import parameter_view


def test_rows_helper_selects_parameter_table_rows() -> None:
    spec = experiment(
        id="selected-readout-rows-helper",
        kind="diagnostic",
        points=rows("readout_devices", enabled=True),
        state=[
            set_state(
                col("resource_id"),
                "readout.frequency",
                param(
                    "readout_devices",
                    key={"device_id": col("device_id")},
                    column="frequency",
                ),
            )
        ],
    )

    preview = preview_contract(spec, parameter_view())

    assert [point.coordinates["device_id"] for point in preview.points] == ["r0"]
    assert preview.coordinate_ids == (
        "device_id",
        "enabled",
        "resource_id",
        "frequency",
    )
    assert [(change.resource, change.after) for change in preview.state_changes] == [
        ("readout-a", Quantity(value=5.95, unit="GHz"))
    ]


def test_scan_parameter_helper_builds_points_and_patch() -> None:
    scan = scan_parameter(
        param_row("readout_devices", device_id="r0"),
        "frequency",
        linspace(5.9, 6.0, 2, unit="GHz"),
        axis="readout_frequency",
    )
    spec = experiment(
        id="parameter-scan-helper",
        kind="readout.frequency_scan",
        points=scan.points,
        params=scan.params(),
        state=[
            set_state(
                "readout-a",
                "pulse.frequency",
                param(
                    "readout_devices",
                    key={"device_id": "r0"},
                    column="frequency",
                ),
            )
        ],
        records=[observable("signal", unit="ratio")],
    )

    preview = preview_contract(spec, parameter_view())

    assert preview.coordinate_ids == ("readout_frequency",)
    assert [point.coordinates["readout_frequency"] for point in preview.points] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]
    assert [change.after for change in preview.state_changes] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]


def test_configure_helper_groups_parameter_patches() -> None:
    spec = experiment(
        id="configure-helper",
        kind="readout.configure",
        points=grid(index=[0]),
        params=configure(
            param_row("readout_devices", device_id="r0").patch(
                frequency=Quantity(value=6.0, unit="GHz")
            )
        ),
        state=[
            set_state(
                "readout-a",
                "pulse.frequency",
                param(
                    "readout_devices",
                    key={"device_id": "r0"},
                    column="frequency",
                ),
            )
        ],
    )

    preview = preview_contract(spec, parameter_view())

    assert [change.after for change in preview.state_changes] == [
        Quantity(value=6.0, unit="GHz")
    ]


def test_local_scan_helper_records_center_offset_and_actual_value() -> None:
    readout = param_row("readout_devices", device_id="r0")
    spec = experiment(
        id="local-scan-helper",
        kind="readout.local_frequency_scan",
        points=local_scan(
            "frequency",
            center=readout.value("frequency"),
            offsets=linspace(-50, 50, 3, unit="MHz"),
        ),
        state=[
            set_state(
                "readout-a",
                "pulse.frequency",
                col("frequency"),
            )
        ],
    )

    preview = preview_contract(spec, parameter_view())

    assert preview.coordinate_ids == (
        "frequency_center",
        "frequency_offset",
        "frequency",
    )
    assert [point.coordinates["frequency_center"] for point in preview.points] == [
        Quantity(value=5.95, unit="GHz")
    ] * 3
    assert [point.coordinates["frequency_offset"] for point in preview.points] == [
        Quantity(value=-50, unit="MHz"),
        Quantity(value=0, unit="MHz"),
        Quantity(value=50, unit="MHz"),
    ]
    assert [point.coordinates["frequency"] for point in preview.points] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=5.95, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]
    assert [change.after for change in preview.state_changes] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=5.95, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    ]


def test_local_overrides_helper_builds_axes_and_state() -> None:
    overrides = local_overrides(
        "z_pulse.amplitude",
        {
            "G2": range_values(0, 0.2, 0.1, unit="V", include_stop=True),
            "C12": Quantity(value=0.5, unit="V"),
        },
        axis_prefix="bias",
    )
    spec = experiment(
        id="local-overrides-helper",
        kind="debug.local_overrides",
        points=grid(delay=linspace(1, 2, 2, unit="us")).cross(overrides.points),
        state=overrides.state,
    )

    preview = preview_contract(spec, parameter_view())

    assert preview.point_count == 6
    assert preview.points[0].coordinates == {
        "delay": Quantity(value=1, unit="us"),
        "bias_G2": Quantity(value=0, unit="V"),
        "bias_C12": Quantity(value=0.5, unit="V"),
    }
    assert [
        change.after
        for change in preview.state_changes
        if change.resource == "C12" and change.field == "z_pulse.amplitude"
    ] == [Quantity(value=0.5, unit="V")]
