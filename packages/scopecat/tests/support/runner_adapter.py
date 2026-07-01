from __future__ import annotations

from pathlib import Path
from typing import Any

from scopecat.experiments import PlanSnapshot
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementDatasetSchema
from scopecat.runner import (
    MeasurementSink,
    RunnerAdapterResult,
    RunnerContext,
)

SIMULATED_EXAMPLE_DIR = (
    Path(__file__).parents[4] / "fixtures" / "core" / "simulated_scan"
)


class FakeRunnerAdapter:
    adapter_id = "test.runner_adapter"
    adapter_version = "v0"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        assert isinstance(context.plan, PlanSnapshot)
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
                metadata={"source": "fake_runner_adapter"},
            )
        return RunnerAdapterResult(metadata={"source": "fake_runner_adapter"})


class MismatchedObservableRunnerAdapter(FakeRunnerAdapter):
    adapter_id = "test.mismatched_observable_runner_adapter"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        assert isinstance(context.plan, PlanSnapshot)
        for point in context.plan.points:
            sink.record(
                point_index=point.point_id,
                coordinates={
                    name: value
                    for name, value in point.row.items()
                    if isinstance(value, Quantity)
                },
                observables={
                    "adapter_signal": Quantity(
                        value=round(0.25 + point.point_id * 0.125, 12),
                        unit="ratio",
                    )
                },
                metadata={"source": "mismatched_observable_runner_adapter"},
            )
        return RunnerAdapterResult(
            metadata={"source": "mismatched_observable_runner_adapter"}
        )


class FailingRunnerAdapter:
    adapter_id = "test.failing_runner_adapter"
    adapter_version = "v0"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        del context, sink
        raise RuntimeError("boom")


class ArtifactRunnerAdapter(FakeRunnerAdapter):
    adapter_id = "test.artifact_runner_adapter"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        result = super().run(context, sink)
        context.artifacts.write_text(
            id="adapter-extra",
            kind="adapter_artifact",
            filename="adapter-extra.txt",
            content="adapter-owned artifact\n",
            media_type="text/plain",
        )
        return result


class UnsafeArtifactRunnerAdapter(FakeRunnerAdapter):
    adapter_id = "test.unsafe_artifact_runner_adapter"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        result = super().run(context, sink)
        context.artifacts.write_text(
            id="unsafe-extra",
            kind="adapter_artifact",
            filename="../escape.txt",
            content="unsafe\n",
        )
        return result


class FailingAfterArtifactRunnerAdapter(FakeRunnerAdapter):
    adapter_id = "test.failing_after_artifact_runner_adapter"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        context.artifacts.write_text(
            id="pre-failure-extra",
            kind="adapter_artifact",
            filename="pre-failure-extra.txt",
            content="written before failure\n",
        )
        super().run(context, sink)
        raise RuntimeError("boom after artifact")


class KernelRunnerAdapter:
    adapter_id = "test.kernel_runner_adapter"
    adapter_version = "v0"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        assert isinstance(context.plan, PlanSnapshot)
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
                metadata={"source": "kernel_runner_adapter"},
            )
        return RunnerAdapterResult(metadata={"source": "kernel_runner_adapter"})


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(SIMULATED_EXAMPLE_DIR / "config-profile.json")


def load_simulated_config() -> ConfigProfileSnapshot:
    return load_config_profile(SIMULATED_EXAMPLE_DIR / "config-profile.json")


def assert_measurement_dataset_schema(
    metadata: dict[str, Any],
    *,
    dataset_id: str,
    dataset_role: str,
    coordinates: dict[str, str],
    observables: dict[str, str],
    dimension_label: str | None = None,
) -> None:
    assert metadata["dataset_role"] == dataset_role
    assert metadata["record_schema"] == "scopecat.measurement_record.v0"
    schema = MeasurementDatasetSchema.model_validate(metadata["dataset_schema"])
    assert schema.schema_version == "scopecat.measurement_dataset_schema.v0"
    assert schema.dataset_id == dataset_id
    assert schema.dataset_role == dataset_role
    assert schema.record_schema == "scopecat.measurement_record.v0"
    assert len(schema.dimensions) == 1
    dimension = schema.dimensions[0]
    assert dimension.id == "point"
    assert dimension.kind == "point"
    assert dimension.label == dimension_label
    assert dimension.size == 3
    assert dimension.unit is None
    assert dimension.metadata == {}
    assert schema.primary_coordinates == list(coordinates)
    assert schema.primary_observables == list(observables)
    variables = {variable.id: variable for variable in schema.variables}
    for variable_id, unit in coordinates.items():
        assert variables[variable_id].role == "coordinate"
        assert variables[variable_id].unit == unit
        assert variables[variable_id].dims == ["point"]
        assert variables[variable_id].shape == [3]
    for variable_id, unit in observables.items():
        assert variables[variable_id].role == "observable"
        assert variables[variable_id].unit == unit
        assert variables[variable_id].dims == ["point"]
        assert variables[variable_id].shape == [3]
