"""Test helpers for executing an already-typed experiment program."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import specialize_linked_program
from scopecat.compiler.typed.program import CoreProgram
from scopecat.composition.local import local_execution_services
from scopecat.execution.interpreter import interpret_run_program
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.execution.ports.resources import ResourceLeaseManager
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource, RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments.contracts import (
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from tests.testkit.typed_program import link_program


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
    experiment: CoreProgram,
    instruments: Sequence[InstrumentDriver],
    workspace: str | Path,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
    resource_leases: ResourceLeaseManager | None = None,
) -> RunManifest:
    """Bind a typed test program, then exercise the production executor boundary."""

    provider = _ExplicitDriverProvider(tuple(instruments))
    return execute_program_run(
        config=config,
        experiment=experiment,
        instrument_provider=provider,
        workspace=workspace,
        event_sink=event_sink,
        payload_observer=payload_observer,
        resource_leases=resource_leases,
    )


def execute_program_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: CoreProgram,
    instrument_provider: InstrumentProvider,
    workspace: str | Path,
    request: RunRequest | None = None,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
    resource_leases: ResourceLeaseManager | None = None,
) -> RunManifest:
    """Execute a typed test program through the unified production boundary."""

    environment = validate_config_environment(config)
    linked = specialize_linked_program(link_program(experiment, environment))
    program = ExperimentSystem(provider=instrument_provider).compile(
        linked,
        config=config,
    )
    services = local_execution_services(workspace)
    if resource_leases is not None:
        services = replace(services, resources=resource_leases)
    manifest = interpret_run_program(
        config=config,
        program=program,
        request=request,
        services=services,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    return manifest


__all__ = ["execute_bound_run", "execute_program_run"]
