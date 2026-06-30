"""Public runner adapter authoring API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic
from scopecat.experiments import (
    ExperimentSpec,
    PlanSnapshot,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionProfile
from scopecat.models.run import RunEvent
from scopecat.results import MeasurementSink
from scopecat.runner.artifact_store import RunnerArtifactWriter


@dataclass(frozen=True)
class RunnerContext:
    """Typed execution context provided to user-authored runner adapters."""

    run_id: str
    config: ConfigProfileSnapshot
    experiment: ExperimentSpec
    execution: ExecutionProfile
    plan: PlanSnapshot
    artifacts: RunnerArtifactWriter


class RunnerAdapterResult(BaseModel):
    """Optional adapter-owned execution metadata and diagnostics."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)


class RunnerAdapter(Protocol):
    """Protocol implemented by private or lab-specific runner adapters."""

    adapter_id: str
    adapter_version: str

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult: ...
