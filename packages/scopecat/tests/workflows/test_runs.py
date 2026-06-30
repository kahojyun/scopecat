from __future__ import annotations

from pathlib import Path

import scopecat.experiments as experiments
import scopecat.relations as relations
from scopecat.experiments import (
    DryRunSnapshot,
    PlanSnapshot,
)
from scopecat.runs import load_plan_snapshot, open_run_store
from scopecat.workflows import load_run
from scopecat.workflows.runs import start_dry_run, start_run
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.records import read_measurement_records, read_model
from tests.support.workflow_fixtures import load_config, load_experiment


def test_start_run_supports_dry_and_native_simulate(
    tmp_path: Path,
) -> None:
    config = load_config()
    experiment = load_experiment()

    dry = start_run(
        mode="dry",
        config=config,
        experiment=experiment,
        workspace=tmp_path / "dry",
    )
    native = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=config,
        experiment=experiment,
        workspace=tmp_path / "native",
    )

    assert dry.manifest.runner_id == "scopecat.planner"
    assert dry.data_ref is None
    assert native.manifest.runner_id == "scopecat.native"
    assert native.data_ref == "artifacts/raw-measurements.jsonl"
    data_ref = native.data_ref
    assert data_ref is not None
    raw_path = tmp_path / "native" / "runs" / native.manifest.run_id / data_ref
    records = read_measurement_records(raw_path)
    assert [record.observables["signal"].value for record in records] == [
        0.5,
        1.0,
        0.5,
    ]


def test_start_run_supports_dry_run(
    tmp_path: Path,
) -> None:
    config = load_config()
    spec = load_experiment()

    result = start_run(
        mode="dry",
        config=config,
        experiment=spec,
        workspace=tmp_path,
    )

    assert result.snapshot.schema_version == "scopecat.dry_run_snapshot.v1"
    assert result.snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert result.manifest.runner_id == "scopecat.planner"
    assert isinstance(result.snapshot, DryRunSnapshot)
    assert result.snapshot.point_count == 3
    assert result.snapshot.plan.acquisition.estimated_records == 3
    assert result.snapshot.plan.acquisition.channels == ["source-0"]
    assert [intent.id for intent in result.snapshot.plan.result_intents] == ["signal"]
    assert result.snapshot.plan.expected_dataset_schema is not None
    assert result.snapshot.plan.point_coordinate_ids == ["drive_frequency"]
    assert result.snapshot.plan.expected_dataset_schema.primary_coordinates == [
        "drive_frequency"
    ]
    assert result.snapshot.plan.expected_dataset_schema.primary_observables == [
        "signal"
    ]
    assert result.snapshot.diagnostics == result.snapshot.plan.diagnostics
    assert _is_sha256(result.snapshot.plan.content_hash)
    assert _is_sha256(result.snapshot.plan.experiment_hash)
    assert config.parameter_build is not None
    assert (
        result.snapshot.plan.parameter_build_hash == config.parameter_build.content_hash
    )
    details = load_run(run_id=result.manifest.run_id, workspace=tmp_path)
    stored_plan = load_plan_snapshot(
        storage=open_run_store(tmp_path),
        run_id=result.manifest.run_id,
    )
    assert isinstance(details.plan, PlanSnapshot)
    assert details.plan == result.snapshot.plan
    assert isinstance(stored_plan, PlanSnapshot)
    assert stored_plan == result.snapshot.plan

    run_dir = tmp_path / "runs" / result.manifest.run_id
    persisted_plan = read_model(
        run_dir / result.manifest.plan_snapshot_ref,
        PlanSnapshot,
    )
    persisted_snapshot = read_model(
        run_dir / "artifacts" / "dry-run.snapshot.json",
        DryRunSnapshot,
    )
    assert persisted_plan.schema_version == "scopecat.plan_snapshot.v1"
    assert persisted_plan.experiment_hash == result.snapshot.plan.experiment_hash
    assert (
        persisted_plan.point_coordinate_ids == result.snapshot.plan.point_coordinate_ids
    )
    assert persisted_snapshot.schema_version == "scopecat.dry_run_snapshot.v1"
    summary = (run_dir / "artifacts" / "dry-run.summary.md").read_text()

    assert [record.value for record in persisted_plan.desired_state] == [
        point.row["drive_frequency"] for point in result.snapshot.plan.points
    ]
    assert persisted_snapshot.plan == persisted_plan
    assert persisted_plan.expected_dataset_schema is not None
    assert (
        persisted_plan.expected_dataset_schema.dataset_id
        == "simulated-frequency-scan.results"
    )
    assert "Scopecat Dry-Run Summary" in summary
    assert "- Parameter patches: 3" in summary
    assert (
        "- Acquisition: 3 records "
        "(scalar, record=point, shots=1, repetitions=1, "
        "dimensions=none, channels=source-0)"
    ) in summary
    assert "- Result intents: 1" in summary
    assert "- Dataset coordinates: drive_frequency" in summary
    assert "- Dataset observables: signal" in summary
    assert "## Points" in summary
    assert "- point 0: drive_frequency=4.9 GHz" in summary
    assert "## Parameter Patches" in summary
    assert (
        "- point 0: set_scalar drive_frequency key={} values=value=4.9 GHz "
        "affected_rows=0"
    ) in summary
    assert "## Desired State" in summary
    assert "- point 0: source-0.set_frequency.frequency = 4.9 GHz" in summary
    assert "## Result Intents" in summary
    assert "- signal: observable, record=point, estimated_records=3" in summary
    assert "## Diagnostics" in summary
    assert "- none" in summary


def test_start_dry_run_accepts_experiment_spec(tmp_path: Path) -> None:
    result = start_dry_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )

    assert result.manifest.runner_id == "scopecat.planner"
    assert isinstance(result.snapshot, DryRunSnapshot)
    assert result.snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert result.resolved_experiment is None


def test_dry_run_summary_exposes_planning_diagnostics(
    tmp_path: Path,
) -> None:
    config = load_config()
    spec = experiments.experiment(
        id="kernel-diagnostic-scan",
        kind="diagnostic",
        points=relations.grid(index=[0]),
        params=[
            experiments.set_param(
                "drive_frequency",
                relations.col("missing_frequency"),
            )
        ],
        acquire=experiments.acquire("iq"),
    )

    result = start_run(
        mode="dry",
        config=config,
        experiment=spec,
        workspace=tmp_path,
    )

    assert isinstance(result.snapshot, DryRunSnapshot)
    assert [item["code"] for item in result.snapshot.diagnostics] == [
        "experiment_parameter_patch_failed"
    ]

    run_dir = tmp_path / "runs" / result.manifest.run_id
    summary = (run_dir / "artifacts" / "dry-run.summary.md").read_text()

    assert "- Diagnostics: 1" in summary
    assert (
        "- error: experiment_parameter_patch_failed (params.0) - "
        "experiment parameter patch failed for point 0"
    ) in summary


def _is_sha256(value: str) -> bool:
    prefix = "sha256:"
    return value.startswith(prefix) and len(value.removeprefix(prefix)) == 64
