from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

import scopecat as sc
import scopecat.config.resolution as config_resolution
import scopecat.runs.service as run_workflows
from scopecat import ExperimentCheckResult
from scopecat.authoring import InputDescription
from scopecat.compiler.frontend.invocation import PreparedInvocation
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_prepared_invocation,
)
from scopecat.config.candidates import CandidateConfig
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
)
from scopecat.records.config import ConfigProfileSnapshot
from tests.testkit.authoring import SIMPLE_MODULE, simple_template
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_invocation


def _workspace(
    tmp_path: Path,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> sc.Workspace:
    return sc.open(
        tmp_path,
        config=load_config() if config is None else config,
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )


def test_template_builder_returns_definition_problems() -> None:
    builder = SIMPLE_MODULE.template("test.check.duplicate", kind="check").inputs(
        InputDescription("subject"),
        InputDescription("subject"),
    )

    with pytest.raises(CheckFailed) as error:
        builder.build()

    assert error.value.problems[0].phase is ProblemPhase.DEFINITION
    assert error.value.problems[0].code == "experiment_template_input_duplicate"


def test_prepared_check_returns_authoring_problems(tmp_path: Path) -> None:
    report = _workspace(tmp_path).prepare(simple_template()).check()

    assert not report.ok
    assert report.problems[0].code == "experiment_template_missing_input"
    assert report.problems[0].phase is ProblemPhase.AUTHORING


def test_prepared_check_returns_preview_when_successful(tmp_path: Path) -> None:
    lab = _workspace(tmp_path)

    report = lab.prepare(load_invocation()).check()

    assert report.ok
    assert report.problems == ()
    assert report.preview is not None
    assert report.preview.point_count == 3


def test_prepared_check_returns_configuration_problems_without_preview(
    tmp_path: Path,
) -> None:
    config = load_config()
    invalid_config = config.model_copy(
        update={
            "environment": config.environment.model_copy(
                update={"workspace_id": "different-workspace"}
            )
        }
    )
    lab = _workspace(tmp_path, config=invalid_config)

    report = lab.prepare(load_invocation()).check()

    assert not report.ok
    assert {problem.phase for problem in report.problems} == {
        ProblemPhase.CONFIGURATION
    }
    assert report.preview is None


def test_prepared_check_compiles_authoring_once(
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
    lab = _workspace(tmp_path)

    report = lab.prepare(load_invocation()).check()

    assert report.ok
    assert authoring_compiles == 1


def test_check_problem_results_are_frozen(tmp_path: Path) -> None:
    prepared = _workspace(tmp_path).prepare(load_invocation())
    report = prepared.check()

    assert isinstance(report.problems, tuple)


def test_check_report_rejects_preview_with_blocking_problems(tmp_path: Path) -> None:
    blocking = Problem(
        code="test_error",
        impact=ProblemImpact.BLOCKING,
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.AUTHORING,
        message="test error",
    )

    successful = _workspace(tmp_path).prepare(load_invocation()).check()
    assert successful.preview is not None
    with pytest.raises(ValueError, match="successful experiment check"):
        ExperimentCheckResult(
            problems=(blocking,),
            preview=successful.preview,
        )


def test_check_result_rejects_success_without_preview() -> None:
    with pytest.raises(ValueError, match="successful experiment check"):
        ExperimentCheckResult(problems=(), preview=None)


def test_check_does_not_hide_internal_programming_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_validation(_config: object) -> None:
        raise AssertionError("internal bug")

    monkeypatch.setattr(
        run_workflows,
        "validate_config_environment",
        fail_validation,
    )
    prepared = _workspace(tmp_path).prepare(load_invocation())

    with pytest.raises(AssertionError, match="internal bug"):
        prepared.check()


@pytest.mark.parametrize(
    "terminal",
    ["check", "preview", "run"],
)
def test_session_candidate_config_is_not_read_before_authoring(
    terminal: Literal["check", "preview", "run"],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_reads = 0

    def unexpected_candidate_read(*_args: object, **_kwargs: object) -> object:
        nonlocal candidate_reads
        candidate_reads += 1
        raise AssertionError("candidate config must not be read for invalid authoring")

    monkeypatch.setattr(
        config_resolution,
        "resolve_candidate_config_snapshot",
        unexpected_candidate_read,
    )
    candidate = CandidateConfig(
        parameter_proposals=(),
    )
    lab = _workspace(tmp_path)
    prepared = lab.prepare(simple_template().bind(), config=candidate)

    if terminal == "check":
        assert prepared.check().problems[0].code == (
            "experiment_template_missing_input"
        )
    else:
        method = prepared.preview if terminal == "preview" else prepared.run
        with pytest.raises(CheckFailed) as error:
            method()
        assert error.value.problems[0].code == ("experiment_template_missing_input")

    assert candidate_reads == 0
