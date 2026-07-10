from pathlib import Path

from scopecat._compiler.program import (
    LinkedProgram,
    linked_program,
    observable,
    set_state,
)
from scopecat._parameter_resolution import resolve_config_parameters
from scopecat._relations import col, grid, range_values, table
from scopecat._workflows.preview import build_experiment_preview
from scopecat.config_profiles import load_config_profile
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from tests.support.workflow_fixtures import load_experiment

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def _preview_spec(spec: LinkedProgram, config: ConfigProfileSnapshot):
    return build_experiment_preview(
        spec,
        resolve_config_parameters(config).data,
        config=config,
    )


def test_preview_experiment_builds_expected_plan() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = load_experiment()

    preview, diagnostics = _preview_spec(spec, config)

    assert preview.experiment_id == spec.id
    assert preview.experiment_kind == spec.kind
    assert preview.point_count == 3
    assert preview.state_changes[0].resource == "source"
    assert preview.state_changes[0].field == "set_frequency.frequency"
    assert preview.state_changes[0].after == Quantity(value=4.9, unit="GHz")
    assert preview.state_fields[0].resource_id == "source-0"
    assert preview.state_fields[0].capability_id == "set_frequency"
    assert preview.state_fields[0].field_path == "frequency"
    assert preview.state_fields[0].value == Quantity(value=4.9, unit="GHz")
    assert preview.records[0].shape == (3,)
    assert diagnostics == ()


def test_preview_experiment_includes_float_step_stop_point() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = linked_program(
        id="float-range-scan",
        kind="simple_scan",
        points=grid(
            drive_frequency=range_values(
                5.9,
                6.0,
                0.025,
                unit="GHz",
                include_stop=True,
            )
        ),
        state=[
            set_state(
                "source-0",
                "set_frequency.frequency",
                col("drive_frequency"),
            )
        ],
        records=[observable("signal", unit="ratio", resource="source-0")],
    )

    preview, diagnostics = _preview_spec(spec, config)

    values = [record.coordinates["drive_frequency"] for record in preview.points]

    assert diagnostics == ()
    assert all(isinstance(value, Quantity) for value in values)
    assert [value.value for value in values if isinstance(value, Quantity)] == [
        5.9,
        5.925,
        5.95,
        5.975,
        6.0,
    ]


def test_duplicate_coordinate_rows_have_distinct_point_uids() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    value = Quantity(value=5.0, unit="GHz")
    spec = linked_program(
        id="duplicate-coordinate-scan",
        kind="simple_scan",
        points=grid(drive_frequency=[value, value]),
    )

    preview, diagnostics = _preview_spec(spec, config)

    assert diagnostics == ()
    assert len({point.point_uid for point in preview.points}) == 2


def test_validate_experiment_does_not_duplicate_preview_diagnostics() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = linked_program(
        id="bad-preview-points",
        kind="diagnostic",
        points=table("missing_table"),
    )

    _preview, diagnostics = _preview_spec(spec, config)

    assert [
        diagnostic.code
        for diagnostic in diagnostics
        if diagnostic.code == "experiment_points_evaluation_failed"
    ] == ["experiment_points_evaluation_failed"]
