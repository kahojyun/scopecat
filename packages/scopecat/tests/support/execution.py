"""Test helpers for executing an already-typed experiment program."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import link_program
from scopecat._compiler.program import TypedProgram
from scopecat._execution.execution_plan_executor import execute_execution_plan
from scopecat.execution_backend import ExecutionBackend
from scopecat.instruments.sdk import (
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionSummary
from scopecat.models.run import RunConfigSource, RunManifest
from scopecat.models.run_request import RunRequest
from scopecat.runtime import RuntimeEventSink, RuntimePayloadObserver


@dataclass(frozen=True, slots=True)
class _ExplicitDriverProvider:
    drivers: tuple[InstrumentDriver, ...]

    @property
    def provider_id(self) -> str:
        return "tests.explicit_driver_provider"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(driver.describe() for driver in self.drivers),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        return InstrumentProviderResult(drivers=self.drivers)


def execute_bound_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: TypedProgram,
    instruments: Sequence[InstrumentDriver],
    workspace: str | Path,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> tuple[RunManifest, ExecutionSummary]:
    """Bind a typed test program, then exercise the production executor boundary."""

    provider = _ExplicitDriverProvider(tuple(instruments))
    return execute_program_run(
        config=config,
        experiment=experiment,
        instrument_provider=provider,
        workspace=workspace,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def execute_program_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: TypedProgram,
    instrument_provider: InstrumentProvider,
    workspace: str | Path,
    request: RunRequest | None = None,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> tuple[RunManifest, ExecutionSummary]:
    """Execute a typed test program through the unified production boundary."""

    environment = validate_config_environment(config)
    linked = link_program(experiment, environment)
    prepared = ExecutionBackend(provider=instrument_provider).prepare(
        linked,
        config=config,
    )
    manifest, summary = execute_execution_plan(
        config=config,
        prepared=prepared,
        request=request,
        workspace=workspace,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    return manifest, cast("ExecutionSummary", summary)


__all__ = ["execute_bound_run", "execute_program_run"]
