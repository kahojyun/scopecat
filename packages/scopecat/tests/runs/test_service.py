from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import tests.testkit.planning as run_workflows
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_invocation,
)
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.kernel.errors import CheckFailed
from scopecat.planning.service import plan_scratch_experiment
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
    instrument_bindings,
)
from scopecat.runs.service import load_run_request
from scopecat.sdk.instruments.contracts import InstrumentProviderContext
from tests.testkit.authoring import simple_template
from tests.testkit.execution import execute_invocation_run
from tests.testkit.instrument_host import (
    compose_test_instruments,
    provision_test_instrument_host,
)
from tests.testkit.runtime import (
    admit_test_run,
    check_experiment,
    list_test_runs,
    plan_experiment,
    sqlite_execution_session,
    sqlite_project_services,
)
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_invocation


def test_plan_admit_and_execute_are_separate_run_stages(tmp_path: Path) -> None:
    services = sqlite_project_services(tmp_path)
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    planned = plan_experiment(
        load_invocation(),
        config=config,
        services=services,
        system=composition.system,
    )

    assert list_test_runs(services.runs) == []

    accepted = admit_test_run(
        config=planned.config,
        request=planned.request,
        repository=services.runs,
        config_source=planned.config_source,
    )

    assert accepted.outcome is None
    assert services.runs.read_manifest(accepted.run_id) == accepted
    assert services.runs.read_config_profile_snapshot(accepted.run_id) == planned.config
    assert (
        load_run_request(run_id=accepted.run_id, services=services) == planned.request
    )

    completed = execute_admitted_run(
        program=planned.program,
        session=sqlite_execution_session(
            tmp_path,
            accepted.run_id,
            instruments=provision_test_instrument_host(
                composition.backend.provider,
                context=InstrumentProviderContext(
                    bindings=instrument_bindings(planned.config)
                ),
                instrument_ids=planned.program.resource_order,
            ),
        ),
    )

    assert completed.run_id == accepted.run_id
    assert completed.status == "completed"
    assert completed.config_content_hash == config_content_hash(planned.config)


def test_admitted_execution_rejects_a_program_for_another_config(
    tmp_path: Path,
) -> None:
    services = sqlite_project_services(tmp_path)
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    planned = plan_experiment(
        load_invocation(),
        config=config,
        services=services,
        system=composition.system,
    )
    accepted = admit_test_run(
        config=planned.config,
        request=planned.request,
        repository=services.runs,
    )

    with pytest.raises(ValueError, match="does not match"):
        execute_admitted_run(
            program=replace(
                planned.program,
                config_content_hash=f"sha256:{'0' * 64}",
            ),
            session=sqlite_execution_session(tmp_path, accepted.run_id),
        )

    assert services.runs.read_manifest(accepted.run_id).outcome is None


def test_check_and_test_execution_use_separate_paths(
    tmp_path: Path,
) -> None:
    config = load_config()
    experiment = load_invocation()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )

    result = check_experiment(
        config=config,
        system=composition.system,
        experiment=experiment,
        services=sqlite_project_services(tmp_path / "preview"),
    )
    provider_run = execute_invocation_run(
        system=composition.system,
        instrument_backend=composition.backend,
        config=config,
        experiment=experiment,
        project_root=tmp_path / "provider",
    )

    assert result.preview is not None
    assert result.preview.points[0].point_index == 0
    assert result.preview.point_count == 3
    assert result.preview.experiment_id == "test.workflow_scan"
    assert provider_run.status == "completed"
    assert {dataset.id for dataset in provider_run.datasets} == {"raw-measurements"}


def test_check_compiles_authoring_before_config_source_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_reads = 0

    def unexpected_config_read(**_kwargs: object) -> object:
        nonlocal config_reads
        config_reads += 1
        raise AssertionError("config source must not be read for invalid authoring")

    monkeypatch.setattr(
        run_workflows,
        "resolve_test_config",
        unexpected_config_read,
    )
    invalid = simple_template().bind()

    result = check_experiment(invalid, services=sqlite_project_services(tmp_path))
    problem = result.problems[0]

    assert problem.code == "experiment_missing_input"
    assert config_reads == 0


def test_scratch_planning_compiles_authoring_before_config_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_validations = 0

    def unexpected_config_validation(_config: ConfigProfileSnapshot) -> object:
        nonlocal config_validations
        config_validations += 1
        raise AssertionError("config must not be validated for invalid authoring")

    monkeypatch.setattr(
        run_workflows,
        "build_config_environment",
        unexpected_config_validation,
    )
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )

    with pytest.raises(CheckFailed) as error:
        plan_scratch_experiment(
            config=config,
            experiment=simple_template().bind(),
            system=composition.system,
        )

    assert error.value.problems[0].code == "experiment_missing_input"
    assert config_validations == 0


def test_check_compiles_authoring_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authoring_compiles = 0

    def counted_compile(
        experiment: ExperimentInvocation,
        **_kwargs: object,
    ) -> CompiledInvocation:
        nonlocal authoring_compiles
        authoring_compiles += 1
        return compile_invocation(experiment)

    monkeypatch.setattr(
        run_workflows,
        "compile_invocation",
        counted_compile,
    )
    config = load_config()
    invalid_config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={"primary_entity_id": "missing-entity"}
            )
        }
    )
    experiment = load_invocation()

    result = check_experiment(
        experiment,
        config=invalid_config,
        services=sqlite_project_services(tmp_path),
    )
    assert result.problems[0].code == "configuration.unknown_primary_entity"

    assert authoring_compiles == 1
