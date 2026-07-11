"""Test helpers for executing an already-typed experiment program."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from scopecat._compiler.binding import bind_program
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.program import TypedProgram
from scopecat._execution.executor import execute_run
from scopecat.instruments import RuntimeEventSink, RuntimePayloadObserver
from scopecat.instruments.sdk import (
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionSummary
from scopecat.models.run import RunManifest


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

    environment = validate_config_environment(config)
    plan = bind_program(experiment, environment)
    manifest, summary = execute_run(
        config=config,
        plan=plan,
        request=None,
        instrument_provider=_ExplicitDriverProvider(tuple(instruments)),
        workspace=workspace,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    return manifest, cast("ExecutionSummary", summary)


__all__ = ["execute_bound_run"]
