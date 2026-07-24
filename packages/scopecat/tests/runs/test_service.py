from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

import scopecat.runs.service as run_workflows
from scopecat.compiler.frontend.invocation import PreparedInvocation, prepare_invocation
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_prepared_invocation,
)
from scopecat.composition.embedded import embedded_workspace_services
from scopecat.execution.interpreter import admit_run, execute_admitted_run
from scopecat.kernel.errors import CheckFailed
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.runs.service import (
    check_experiment,
    load_run_config,
    load_run_request,
    plan_experiment,
    run_experiment,
    start_run,
)
from tests.testkit.authoring import simple_template
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_prepared_invocation


def test_plan_admit_and_execute_are_separate_run_stages(tmp_path: Path) -> None:
    services = embedded_workspace_services(tmp_path)
    system = ExperimentSystem(provider=TestSignalInstrumentProvider())
    planned = plan_experiment(
        load_prepared_invocation(),
        config=load_config(),
        services=services,
        system=system,
    )

    assert services.runs.list_runs() == []

    accepted = admit_run(
        config=planned.config,
        request=planned.request,
        repository=services.runs,
        config_source=planned.config_source,
    )

    assert accepted.lifecycle == "accepted"
    assert services.runs.read_manifest(accepted.run_id) == accepted
    assert load_run_config(run_id=accepted.run_id, services=services) == planned.config
    assert (
        load_run_request(run_id=accepted.run_id, services=services) == planned.request
    )

    completed = execute_admitted_run(
        run_id=accepted.run_id,
        program=planned.program,
        services=services.execution,
        instrument_provider=system.provider,
    )

    assert completed.run_id == accepted.run_id
    assert completed.status == "completed"
    assert completed.config_content_hash == config_content_hash(planned.config)


def test_admitted_execution_rejects_a_program_for_another_config(
    tmp_path: Path,
) -> None:
    services = embedded_workspace_services(tmp_path)
    system = ExperimentSystem(provider=TestSignalInstrumentProvider())
    planned = plan_experiment(
        load_prepared_invocation(),
        config=load_config(),
        services=services,
        system=system,
    )
    accepted = admit_run(
        config=planned.config,
        request=planned.request,
        repository=services.runs,
    )

    with pytest.raises(ValueError, match="does not match"):
        execute_admitted_run(
            run_id=accepted.run_id,
            program=replace(
                planned.program,
                config_content_hash=f"sha256:{'0' * 64}",
            ),
            services=services.execution,
            instrument_provider=system.provider,
        )

    assert services.runs.read_manifest(accepted.run_id).lifecycle == "accepted"


def test_check_and_start_run_use_separate_paths(
    tmp_path: Path,
) -> None:
    config = load_config()
    experiment = load_prepared_invocation()

    result = check_experiment(
        config=config,
        system=ExperimentSystem(provider=TestSignalInstrumentProvider()),
        experiment=experiment,
        services=embedded_workspace_services(tmp_path / "preview"),
    )
    provider_run = start_run(
        system=ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=config,
        experiment=experiment,
        services=embedded_workspace_services(tmp_path / "provider"),
    )

    assert result.preview is not None
    assert result.preview.points[0].point_index == 0
    assert result.preview.point_count == 3
    assert result.preview.experiment_id == "test.workflow_scan"
    assert provider_run.status == "completed"
    assert {dataset.id for dataset in provider_run.datasets} == {"raw-measurements"}


@pytest.mark.parametrize("workflow", ["run", "check"])
def test_workflow_compiles_authoring_before_config_source_io(
    workflow: Literal["run", "check"],
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
        "resolve_experiment_config",
        unexpected_config_read,
    )
    invalid = prepare_invocation(simple_template().bind())

    if workflow == "check":
        result = check_experiment(
            invalid, services=embedded_workspace_services(tmp_path)
        )
        problem = result.problems[0]
    else:
        with pytest.raises(CheckFailed) as error:
            run_experiment(
                invalid,
                system=ExperimentSystem(provider=TestSignalInstrumentProvider()),
                services=embedded_workspace_services(tmp_path),
            )
        problem = error.value.problems[0]

    assert problem.code == "experiment_template_missing_input"
    assert config_reads == 0


def test_start_run_compiles_authoring_before_config_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_validations = 0

    def unexpected_config_validation(_config: ConfigProfileSnapshot) -> object:
        nonlocal config_validations
        config_validations += 1
        raise AssertionError("config must not be validated for invalid authoring")

    monkeypatch.setattr(
        run_workflows,
        "validate_config_environment",
        unexpected_config_validation,
    )

    with pytest.raises(CheckFailed) as error:
        start_run(
            config=load_config(),
            experiment=prepare_invocation(simple_template().bind()),
            services=embedded_workspace_services(tmp_path),
        )

    assert error.value.problems[0].code == "experiment_template_missing_input"
    assert config_validations == 0


@pytest.mark.parametrize("workflow", ["start", "run", "check"])
def test_workflow_compiles_authoring_once(
    workflow: Literal["start", "run", "check"],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authoring_compiles = 0

    def counted_compile(experiment: PreparedInvocation) -> CompiledInvocation:
        nonlocal authoring_compiles
        authoring_compiles += 1
        return compile_prepared_invocation(experiment)

    monkeypatch.setattr(
        run_workflows,
        "compile_prepared_invocation",
        counted_compile,
    )
    config = load_config()
    invalid_config = config.model_copy(
        update={
            "environment": config.environment.model_copy(
                update={"workspace_id": "different-workspace"}
            )
        }
    )
    experiment = load_prepared_invocation()

    if workflow == "check":
        result = check_experiment(
            experiment,
            config=invalid_config,
            services=embedded_workspace_services(tmp_path),
        )
        assert (
            result.problems[0].code == "configuration.config_profile_workspace_mismatch"
        )
    else:
        terminal = {
            "start": lambda: start_run(
                config=invalid_config,
                experiment=experiment,
                services=embedded_workspace_services(tmp_path),
            ),
            "run": lambda: run_experiment(
                experiment,
                config=invalid_config,
                services=embedded_workspace_services(tmp_path),
            ),
        }[workflow]
        with pytest.raises(CheckFailed) as error:
            terminal()
        assert (
            error.value.problems[0].code
            == "configuration.config_profile_workspace_mismatch"
        )

    assert authoring_compiles == 1
