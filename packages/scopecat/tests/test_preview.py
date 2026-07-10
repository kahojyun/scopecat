from pathlib import Path

from scopecat._workflows.preview import build_experiment_preview
from scopecat.config_profiles import load_config_profile
from scopecat.experiments import (
    ExperimentSpec,
    experiment,
    observable,
    set_param,
    set_state,
)
from scopecat.models.config import ConfigProfileSnapshot, build_config_parameters
from scopecat.models.parameter import Quantity
from scopecat.relations import col, grid, param, range_values, table
from tests.support.records import read_model

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def _preview_spec(spec: ExperimentSpec, config: ConfigProfileSnapshot):
    return build_experiment_preview(
        spec,
        build_config_parameters(config),
        config=config,
    )


def test_preview_experiment_builds_expected_plan() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)

    preview, diagnostics = _preview_spec(spec, config)

    assert preview.experiment_id == spec.id
    assert preview.experiment_kind == spec.kind
    assert preview.point_count == 3
    assert preview.state_changes[0].resource == "source-0"
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
    spec = experiment(
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
        params=[set_param("drive_frequency", col("drive_frequency"))],
        state=[
            set_state(
                "source-0",
                "set_frequency.frequency",
                param("drive_frequency"),
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


def test_validate_experiment_does_not_duplicate_preview_diagnostics() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = experiment(
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
