"""Test helpers for executing an already-typed experiment program."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.typed.program import CoreProgram
from scopecat.config.environment import build_config_environment
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.planning.service import plan_scratch_experiment
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
from tests.testkit.runtime import (
    admit_test_run,
    sqlite_execution_session,
    sqlite_run_repository,
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
    project_root: str | Path,
) -> RunManifest:
    """Bind a typed test program, then exercise the production executor boundary."""

    provider = _ExplicitDriverProvider(tuple(instruments))
    return execute_program_run(
        config=config,
        experiment=experiment,
        instrument_provider=provider,
        project_root=project_root,
    )


def execute_invocation_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentInvocation,
    system: ExperimentSystem,
    project_root: str | Path,
    config_source: RunConfigSource | None = None,
    metadata: Mapping[str, object] | None = None,
    operator: str | None = None,
) -> RunManifest:
    """Execute an authored invocation through test-local SQLite ports."""

    planned = plan_scratch_experiment(
        experiment,
        config=config,
        system=system,
        config_source=config_source,
        metadata=metadata,
        operator=operator,
    )
    repository = sqlite_run_repository(project_root)
    accepted = admit_test_run(
        config=planned.config,
        request=planned.request,
        repository=repository,
        config_source=planned.config_source,
    )
    return execute_admitted_run(
        program=planned.program,
        session=sqlite_execution_session(
            project_root,
            accepted.run_id,
            runs=repository,
        ),
        instrument_provider=(
            planned.system.provider if planned.system is not None else None
        ),
    )


def execute_program_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: CoreProgram,
    instrument_provider: InstrumentProvider,
    project_root: str | Path,
    request: RunRequest | None = None,
    config_source: RunConfigSource | None = None,
) -> RunManifest:
    """Execute a typed test program through the unified production boundary."""

    environment = build_config_environment(config)
    linked = link_program(experiment, environment)
    program = ExperimentSystem(provider=instrument_provider).compile(linked)
    repository = sqlite_run_repository(project_root)
    accepted = admit_test_run(
        config=config,
        request=request or RunRequest(experiment_id=program.experiment_id),
        repository=repository,
        config_source=config_source,
    )
    manifest = execute_admitted_run(
        program=program,
        session=sqlite_execution_session(
            project_root,
            accepted.run_id,
            runs=repository,
        ),
        instrument_provider=instrument_provider,
    )
    return manifest


__all__ = ["execute_bound_run", "execute_invocation_run", "execute_program_run"]
