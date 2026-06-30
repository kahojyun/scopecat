from __future__ import annotations

from pathlib import Path

from scopecat.experiments import PlanSnapshot
from scopecat.models.parameter import Quantity
from scopecat.runner import (
    MeasurementSink,
    RunnerAdapterResult,
    RunnerAdapterRunSnapshot,
    RunnerContext,
)
from scopecat.workflows import load_run, read_run_measurement_dataset
from scopecat.workflows.runs import start_runner_adapter_run
from tests.support.workflow_fixtures import load_config, load_experiment


class WorkflowSignalRunnerAdapter:
    adapter_id = "tests.workflow_signal_runner_adapter"
    adapter_version = "v0"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        if isinstance(context.plan, PlanSnapshot):
            for point in context.plan.points:
                sink.record(
                    point_index=point.point_id,
                    coordinates={
                        name: value
                        for name, value in point.row.items()
                        if isinstance(value, Quantity)
                    },
                    observables={
                        "signal": Quantity(
                            value=round(0.25 + point.point_id * 0.125, 12),
                            unit="ratio",
                        )
                    },
                )
            return RunnerAdapterResult(metadata={"plan_schema": "experiment"})

        raise AssertionError("workflow runner adapter requires an experiment plan")


def test_start_runner_adapter_run_supports_experiment_spec(
    tmp_path: Path,
) -> None:
    result = start_runner_adapter_run(
        config=load_config(),
        experiment=load_experiment(),
        adapter=WorkflowSignalRunnerAdapter(),
        workspace=tmp_path,
    )

    assert result.manifest.runner_id == "tests.workflow_signal_runner_adapter"
    assert result.data_ref == "artifacts/raw-measurements.jsonl"
    assert isinstance(result.snapshot, RunnerAdapterRunSnapshot)
    assert isinstance(result.snapshot.plan, PlanSnapshot)
    assert result.snapshot.measurement_count == 3
    assert result.snapshot.metadata == {"plan_schema": "experiment"}
    assert result.resolved_experiment is None

    details = load_run(run_id=result.manifest.run_id, workspace=tmp_path)
    raw_dataset = read_run_measurement_dataset(
        run_id=result.manifest.run_id,
        workspace=tmp_path,
    )

    assert isinstance(details.plan, PlanSnapshot)
    assert raw_dataset.dataset.dataset_schema.dataset_id == "raw-measurements"
    assert [
        record.observables["signal"].value for record in raw_dataset.dataset.records
    ] == [0.25, 0.375, 0.5]
