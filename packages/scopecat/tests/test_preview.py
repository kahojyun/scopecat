from pathlib import Path

from scopecat.experiments import (
    ExperimentSpec,
    acquire,
    experiment,
    point,
    set_param,
    set_state,
)
from scopecat.models.config import load_config_profile
from scopecat.models.parameter import Quantity
from scopecat.relations import col, grid, param, range_values
from scopecat.workflows.runs import preview_experiment, validate_experiment
from tests.support.records import read_model

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def test_preview_experiment_builds_expected_plan(tmp_path: Path) -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)

    preview = preview_experiment(
        config=config,
        experiment=spec,
        workspace=tmp_path,
    )

    assert preview.config == config
    assert len(preview.plan.points) == 3
    assert preview.plan.desired_state[0].resource == "source-0"
    assert preview.plan.desired_state[0].field == "set_frequency.frequency"
    assert preview.plan.state_patches[0].after == Quantity(value=4.9, unit="GHz")
    assert preview.plan.acquisition.estimated_records == 3
    assert validate_experiment(
        config=config,
        experiment=spec,
        workspace=tmp_path,
    ).ok


def test_preview_experiment_includes_float_step_stop_point(
    tmp_path: Path,
) -> None:
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
        acquire=acquire(
            "scalar",
            observations=[point("signal", unit="ratio")],
        ),
    )

    preview = preview_experiment(
        config=config,
        experiment=spec,
        workspace=tmp_path,
    )

    values = [record.row["drive_frequency"] for record in preview.plan.points]

    assert all(isinstance(value, Quantity) for value in values)
    assert [value.value for value in values if isinstance(value, Quantity)] == [
        5.9,
        5.925,
        5.95,
        5.975,
        6.0,
    ]
