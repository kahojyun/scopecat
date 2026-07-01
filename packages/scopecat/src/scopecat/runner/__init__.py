"""Runner adapter authoring and execution APIs."""

from scopecat.results import MeasurementSink
from scopecat.runner.artifact_store import RunnerArtifactHandle, RunnerArtifactWriter
from scopecat.runner.executor import execute_runner_adapter
from scopecat.runner.sdk import RunnerAdapter, RunnerAdapterResult, RunnerContext
from scopecat.runner.snapshots import (
    RUNNER_ADAPTER_BOUNDARY_MANIFEST_SCHEMA_VERSION,
    RUNNER_ADAPTER_RUN_SNAPSHOT_SCHEMA_VERSION,
    RunnerAdapterBoundaryManifest,
    RunnerAdapterRunSnapshot,
    build_runner_adapter_boundary_manifest,
)

__all__ = [
    "RUNNER_ADAPTER_BOUNDARY_MANIFEST_SCHEMA_VERSION",
    "RUNNER_ADAPTER_RUN_SNAPSHOT_SCHEMA_VERSION",
    "MeasurementSink",
    "RunnerAdapter",
    "RunnerAdapterBoundaryManifest",
    "RunnerAdapterResult",
    "RunnerAdapterRunSnapshot",
    "RunnerArtifactHandle",
    "RunnerArtifactWriter",
    "RunnerContext",
    "build_runner_adapter_boundary_manifest",
    "execute_runner_adapter",
]
