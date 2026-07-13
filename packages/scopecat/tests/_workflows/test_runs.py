from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from scopecat._workflows import runs as run_workflows
from scopecat._workflows.runs import (
    preview_experiment,
    run_experiment,
    start_run,
    validate_experiment,
)
from scopecat.authoring import QuantityType, ScalarType, parameter
from scopecat.authoring._invocation_plan import PreparedInvocation, prepare_invocation
from scopecat.authoring._resolution import (
    CompiledInvocation,
    compile_prepared_invocation,
)
from scopecat.errors import CheckFailed
from scopecat.execution_backend import ExecutionBackend
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from tests.support.authoring import (
    DRIVE_FREQUENCY_POINT,
    SIMPLE_MODULE,
    simple_template,
)
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_config, load_prepared_invocation


def test_preview_and_start_run_use_separate_paths(
    tmp_path: Path,
) -> None:
    config = load_config()
    experiment = load_prepared_invocation()

    preview = preview_experiment(
        config=config,
        execution_backend=ExecutionBackend(provider=TestSignalInstrumentProvider()),
        experiment=experiment,
        workspace=tmp_path / "preview",
    )
    provider_run = start_run(
        execution_backend=ExecutionBackend(provider=TestSignalInstrumentProvider()),
        config=config,
        experiment=experiment,
        workspace=tmp_path / "provider",
    )

    assert preview.points[0].point_index == 0
    assert preview.point_count == 3
    assert provider_run.status == "completed"
    assert {dataset.id for dataset in provider_run.datasets} == {"raw-measurements"}


def test_preview_and_start_run_accept_template_invocation(tmp_path: Path) -> None:
    config = load_config()
    experiment_template = (
        SIMPLE_MODULE.template("test.workflow_request_scan", kind="simple_scan")
        .experiment_id("authored-simple-scan")
        .scan(
            DRIVE_FREQUENCY_POINT,
            center=parameter(
                "drive_frequency",
                ScalarType(QuantityType()),
            ),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        )
        .build()
    )
    invocation = prepare_invocation(experiment_template.bind(subject="q0"))

    preview = preview_experiment(
        config=config,
        execution_backend=ExecutionBackend(provider=TestSignalInstrumentProvider()),
        experiment=invocation,
        workspace=tmp_path / "preview",
    )
    provider_run = start_run(
        execution_backend=ExecutionBackend(provider=TestSignalInstrumentProvider()),
        config=config,
        experiment=invocation,
        workspace=tmp_path / "provider",
    )

    assert preview.template_id == "test.workflow_request_scan"
    assert preview.inputs == {"subject": "q0"}
    assert preview.experiment_id == "authored-simple-scan"
    assert provider_run.status == "completed"


@pytest.mark.parametrize("workflow", ["run", "validate", "preview"])
def test_public_workflow_compiles_authoring_before_config_source_io(
    workflow: Literal["run", "validate", "preview"],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_reads = 0

    def unexpected_config_read(**_kwargs: object) -> object:
        nonlocal config_reads
        config_reads += 1
        raise AssertionError("config source must not be read for invalid authoring")

    resolver = (
        "_resolve_config_for_run" if workflow == "run" else "_resolve_config_read_only"
    )
    monkeypatch.setattr(run_workflows, resolver, unexpected_config_read)
    invalid = prepare_invocation(simple_template().bind())

    if workflow == "validate":
        result = validate_experiment(invalid, workspace=tmp_path)
        problem = result.problems[0]
    else:
        terminal = run_experiment if workflow == "run" else preview_experiment
        with pytest.raises(CheckFailed) as error:
            terminal(
                invalid,
                execution_backend=ExecutionBackend(
                    provider=TestSignalInstrumentProvider()
                ),
                workspace=tmp_path,
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
            workspace=tmp_path,
        )

    assert error.value.problems[0].code == "experiment_template_missing_input"
    assert config_validations == 0


@pytest.mark.parametrize("workflow", ["start", "run", "validate", "preview"])
def test_public_workflow_compiles_authoring_once(
    workflow: Literal["start", "run", "validate", "preview"],
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

    if workflow == "validate":
        result = validate_experiment(
            experiment,
            config=invalid_config,
            workspace=tmp_path,
        )
        assert (
            result.problems[0].code == "configuration.config_profile_workspace_mismatch"
        )
    else:
        terminal = {
            "start": lambda: start_run(
                config=invalid_config,
                experiment=experiment,
                workspace=tmp_path,
            ),
            "run": lambda: run_experiment(
                experiment,
                config=invalid_config,
                workspace=tmp_path,
            ),
            "preview": lambda: preview_experiment(
                experiment,
                config=invalid_config,
                execution_backend=ExecutionBackend(
                    provider=TestSignalInstrumentProvider()
                ),
                workspace=tmp_path,
            ),
        }[workflow]
        with pytest.raises(CheckFailed) as error:
            terminal()
        assert (
            error.value.problems[0].code
            == "configuration.config_profile_workspace_mismatch"
        )

    assert authoring_compiles == 1
