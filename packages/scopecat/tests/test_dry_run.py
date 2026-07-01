from pathlib import Path

from scopecat.execution.dry_run import execute_dry_run
from scopecat.experiments import (
    DryRunSnapshot,
    ExperimentSpec,
    PlanSnapshot,
    acquire,
    experiment,
    point,
    set_param,
    set_state,
)
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunManifest
from scopecat.relations import col, grid, param, range_values
from tests.support.records import read_model

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simulated_scan"


def test_execute_dry_run_persists_expected_files(tmp_path: Path) -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)

    manifest, dry_run = execute_dry_run(
        config=config,
        experiment=spec,
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    persisted_manifest = read_model(run_dir / "manifest.json", RunManifest)
    persisted_config = read_model(
        run_dir / "config-profile.snapshot.json",
        ConfigProfileSnapshot,
    )
    assert (run_dir / "plan.snapshot.json").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "artifacts" / "dry-run.snapshot.json").is_file()
    assert persisted_manifest == manifest
    assert persisted_config == config
    assert manifest.runner_id == "scopecat.planner"
    assert dry_run.point_count == 3
    assert dry_run.plan.desired_state[0].resource == "source-0"
    assert dry_run.plan.desired_state[0].field == "set_frequency.frequency"
    assert dry_run.plan.state_patches[0].after == Quantity(value=4.9, unit="GHz")
    assert dry_run.plan.acquisition.estimated_records == 3

    persisted_plan = read_model(run_dir / "plan.snapshot.json", PlanSnapshot)
    persisted_snapshot = read_model(
        run_dir / "artifacts" / "dry-run.snapshot.json",
        DryRunSnapshot,
    )
    assert persisted_plan == dry_run.plan
    assert persisted_snapshot == dry_run


def test_execute_dry_run_includes_float_step_stop_point(
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

    _, dry_run = execute_dry_run(
        config=config,
        experiment=spec,
        workspace=tmp_path,
    )

    values = [record.row["drive_frequency"] for record in dry_run.plan.points]

    assert all(isinstance(value, Quantity) for value in values)
    assert [value.value for value in values if isinstance(value, Quantity)] == [
        5.9,
        5.925,
        5.95,
        5.975,
        6.0,
    ]
