from __future__ import annotations

from pathlib import Path
from typing import Literal, Never

import pytest

import scopecat as sc
import scopecat.config.resolution as config_resolution
import scopecat.planning.system as planning_system
from scopecat.config.candidates import CandidateConfig
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    problem,
)
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.records.config import ConfigProfileSnapshot, DomainTargetBinding
from scopecat.sdk.domain.compiler import (
    DomainCompilation,
    DomainCompiledJob,
    DomainCompileRequest,
    compiled_jobs,
)
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.execution import PreparedDomainExecution
from tests.testkit.authoring import simple_template, template_fixture
from tests.testkit.in_process_lab import (
    InProcessLab,
    InProcessPreparedExperiment,
    in_process_lab,
)
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_invocation


def _lab(
    tmp_path: Path,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> InProcessLab:
    return in_process_lab(
        tmp_path,
        config=load_config() if config is None else config,
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )


def _planning_failure(code: str) -> CheckFailed:
    return CheckFailed(
        (
            problem(
                code,
                "injected planning failure",
                phase=ProblemPhase.PLANNING,
            ),
        )
    )


def _assert_terminal_problem(
    prepared: InProcessPreparedExperiment,
    *,
    terminal: Literal["check", "preview"],
    code: str,
) -> None:
    if terminal == "check":
        report = prepared.check()
        assert not report.ok
        assert report.preview is None
        assert [problem.code for problem in report.problems] == [code]
        return

    with pytest.raises(CheckFailed) as captured:
        prepared.preview()
    assert [problem.code for problem in captured.value.problems] == [code]


class _RejectingDomainCompiler:
    def __init__(self, stage: Literal["compile", "prepare"]) -> None:
        self.stage = stage
        self.compile_calls = 0
        self.prepare_calls = 0

    @property
    def target_id(self) -> str:
        return "tests.domain.target"

    @property
    def target_kind(self) -> str:
        return "tests.domain"

    def compile(self, request: DomainCompileRequest) -> DomainCompilation:
        self.compile_calls += 1
        if self.stage == "compile":
            raise _planning_failure("injected_domain_compile_failure")
        return compiled_jobs(request, max_points=100)

    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        del job, context
        self.prepare_calls += 1
        raise _planning_failure("injected_domain_prepare_failure")


def _domain_invocation() -> sc.ExperimentInvocation:
    program = sc.domain_program(
        "check-program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
    )
    module = (
        sc.module_body(id="test.check-domain")
        .domain(sc.domain_execution(program))
        .build()
    )
    return template_fixture(
        module,
        id="test.check-domain",
        kind="check-domain",
    ).bind()


def test_prepared_check_returns_preview_when_successful(tmp_path: Path) -> None:
    lab = _lab(tmp_path)

    report = lab.prepare(load_invocation()).check()

    assert report.ok
    assert report.problems == ()
    assert report.preview is not None
    assert report.preview.point_count == 3


@pytest.mark.parametrize("terminal", ["check", "preview"])
def test_check_and_preview_surface_local_materialization_errors(
    terminal: Literal["check", "preview"],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_local_materialization(
        *_args: object,
        **_kwargs: object,
    ) -> Never:
        raise _planning_failure("injected_local_materialization_failure")

    monkeypatch.setattr(
        planning_system,
        "materialize_local_execution",
        reject_local_materialization,
    )

    _assert_terminal_problem(
        _lab(tmp_path).prepare(load_invocation()),
        terminal=terminal,
        code="injected_local_materialization_failure",
    )


@pytest.mark.parametrize("terminal", ["check", "preview"])
@pytest.mark.parametrize("stage", ["compile", "prepare"])
def test_check_and_preview_surface_domain_compilation_errors(
    terminal: Literal["check", "preview"],
    stage: Literal["compile", "prepare"],
    tmp_path: Path,
) -> None:
    compiler = _RejectingDomainCompiler(stage)
    config = load_config()
    config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "domain_target": DomainTargetBinding(
                        id=compiler.target_id,
                        kind=compiler.target_kind,
                    )
                }
            )
        }
    )
    prepared = _lab(tmp_path, config=config).prepare(
        _domain_invocation(),
        system=sc.ExperimentSystem(domain_compiler=compiler),
    )
    code = f"injected_domain_{stage}_failure"

    _assert_terminal_problem(prepared, terminal=terminal, code=code)
    assert compiler.compile_calls == 1
    assert compiler.prepare_calls == (stage == "prepare")


def test_prepared_check_returns_configuration_problems_without_preview(
    tmp_path: Path,
) -> None:
    config = load_config()
    invalid_config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={"primary_entity_id": "missing-entity"}
            )
        }
    )
    lab = _lab(tmp_path, config=invalid_config)

    report = lab.prepare(load_invocation()).check()

    assert not report.ok
    assert {problem.phase for problem in report.problems} == {
        ProblemPhase.CONFIGURATION
    }
    assert report.preview is None


def test_check_report_rejects_preview_with_problems(tmp_path: Path) -> None:
    blocking = Problem(
        code="test_error",
        phase=ProblemPhase.AUTHORING,
        message="test error",
    )

    successful = _lab(tmp_path).prepare(load_invocation()).check()
    assert successful.preview is not None
    with pytest.raises(ValueError, match="successful experiment check"):
        ExperimentCheckResult(
            problems=(blocking,),
            preview=successful.preview,
        )


def test_check_result_rejects_success_without_preview() -> None:
    with pytest.raises(ValueError, match="successful experiment check"):
        ExperimentCheckResult(problems=(), preview=None)


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
    lab = _lab(tmp_path)
    prepared = lab.prepare(simple_template().bind(), config=candidate)

    if terminal == "check":
        assert prepared.check().problems[0].code == ("experiment_missing_input")
    else:
        method = prepared.preview if terminal == "preview" else prepared.run
        with pytest.raises(CheckFailed) as error:
            method()
        assert error.value.problems[0].code == ("experiment_missing_input")

    assert candidate_reads == 0
