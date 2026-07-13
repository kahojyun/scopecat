from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import pytest

import scopecat as sc
import scopecat.runs.service as run_workflows
from scopecat import (
    CheckPhase,
    CheckPhaseReport,
    CheckStatus,
    ExperimentCheckReport,
)
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
from scopecat.planning.checks import (
    check_invocation,
    check_template,
    check_template_builder,
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
        execution_backend=sc.ExecutionBackend(provider=TestSignalInstrumentProvider()),
    )


def test_template_check_is_explicitly_definition_only() -> None:
    template = simple_template()

    report = check_template(template)

    assert report.ok
    assert report.complete
    assert report.status is CheckStatus.PASSED
    assert [phase.phase for phase in report.phases] == [CheckPhase.DEFINITION]
    assert report.summary is None
    assert report.explain() == ("experiment check: passed\n- definition: passed")


def test_template_builder_check_returns_definition_problems() -> None:
    builder = SIMPLE_MODULE.template("test.check.duplicate", kind="check").inputs(
        InputDescription("subject"),
        InputDescription("subject"),
    )

    report = check_template_builder(builder)

    assert not report.ok
    phase = report.for_phase(CheckPhase.DEFINITION)
    assert phase.status is CheckStatus.FAILED
    assert phase.problems[0].code == "experiment_template_input_duplicate"


def test_invocation_check_compiles_the_complete_config_free_graph() -> None:
    invalid = simple_template().bind()
    valid = simple_template().bind(subject="q0")

    invalid_report = check_invocation(invalid)
    valid_report = check_invocation(valid)

    assert invalid_report.status is CheckStatus.FAILED
    assert invalid_report.problems[0].code == "experiment_template_missing_input"
    assert [phase.phase for phase in invalid_report.phases] == [CheckPhase.AUTHORING]
    assert valid_report.status is CheckStatus.PASSED
    assert valid_report.inputs["subject"] == "q0"
    assert check_invocation(invalid).explain() == invalid_report.explain()
    assert invalid_report.explain() == (
        "experiment check: failed\n"
        "- authoring: failed\n"
        "  - blocking experiment_template_missing_input [template.inputs]: "
        "experiment template missing required input: subject"
    )


def test_prepared_check_reports_each_phase_and_summary(tmp_path: Path) -> None:
    lab = _workspace(tmp_path)

    report = lab.prepare(load_invocation()).check()

    assert report.status is CheckStatus.PASSED
    assert report.complete
    assert [phase.phase for phase in report.phases] == [
        CheckPhase.AUTHORING,
        CheckPhase.CONFIGURATION,
        CheckPhase.PLANNING,
    ]
    assert report.summary is not None
    assert report.summary.point_count == 3
    assert lab.prepare(load_invocation()).explain() == report.explain()


def test_prepared_check_skips_planning_after_configuration_failure(
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

    assert report.for_phase(CheckPhase.AUTHORING).status is CheckStatus.PASSED
    assert report.for_phase(CheckPhase.CONFIGURATION).status is CheckStatus.FAILED
    assert report.for_phase(CheckPhase.PLANNING).status is CheckStatus.SKIPPED
    assert report.summary is None


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


def test_check_report_inputs_are_read_only(tmp_path: Path) -> None:
    report = _workspace(tmp_path).prepare(load_invocation()).check()

    with pytest.raises(TypeError):
        cast("dict[str, object]", report.inputs)["subject"] = "mutated"


def test_preview_and_validation_problem_results_are_frozen(tmp_path: Path) -> None:
    prepared = _workspace(tmp_path).prepare(load_invocation())
    validation = prepared.validate()
    preview = prepared.preview()

    assert isinstance(validation.problems, tuple)
    assert isinstance(preview.problems, tuple)
    with pytest.raises(TypeError):
        cast("dict[str, object]", validation.inputs)["subject"] = "mutated"
    with pytest.raises(TypeError):
        cast("dict[str, object]", preview.inputs)["subject"] = "mutated"


def test_public_check_records_enforce_phase_invariants() -> None:
    blocking = Problem(
        code="test_error",
        impact=ProblemImpact.BLOCKING,
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.AUTHORING,
        message="test error",
    )

    with pytest.raises(ValueError, match="at least one phase"):
        ExperimentCheckReport(phases=())
    with pytest.raises(ValueError, match="passed check phase"):
        CheckPhaseReport(
            phase=CheckPhase.AUTHORING,
            status=CheckStatus.PASSED,
            problems=(blocking,),
        )
    with pytest.raises(ValueError, match="requires a blocking problem"):
        CheckPhaseReport(
            phase=CheckPhase.AUTHORING,
            status=CheckStatus.FAILED,
        )
    with pytest.raises(ValueError, match="same phase"):
        CheckPhaseReport(
            phase=CheckPhase.DEFINITION,
            status=CheckStatus.FAILED,
            problems=(blocking,),
        )
    with pytest.raises(ValueError, match="duplicated, incomplete, or out of order"):
        ExperimentCheckReport(
            phases=(
                CheckPhaseReport(
                    phase=CheckPhase.CONFIGURATION,
                    status=CheckStatus.PASSED,
                ),
            )
        )


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
    ["check", "validate", "preview", "explain", "run"],
)
def test_session_candidate_config_is_not_read_before_authoring(
    terminal: Literal["check", "validate", "preview", "explain", "run"],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_reads = 0

    def unexpected_candidate_read(*_args: object, **_kwargs: object) -> object:
        nonlocal candidate_reads
        candidate_reads += 1
        raise AssertionError("candidate config must not be read for invalid authoring")

    monkeypatch.setattr(
        run_workflows,
        "resolve_candidate_config_snapshot",
        unexpected_candidate_read,
    )
    monkeypatch.setattr(
        run_workflows,
        "materialize_candidate_config",
        unexpected_candidate_read,
    )
    candidate = CandidateConfig(
        analysis_title="ordering",
        analysis_key="ordering",
        parameter_proposals=(),
    )
    lab = _workspace(tmp_path)
    prepared = lab.prepare(simple_template().bind(), config=candidate)

    if terminal == "check":
        assert prepared.check().problems[0].code == (
            "experiment_template_missing_input"
        )
    elif terminal == "validate":
        assert prepared.validate().problems[0].code == (
            "experiment_template_missing_input"
        )
    elif terminal == "explain":
        assert "experiment_template_missing_input" in prepared.explain()
    else:
        method = prepared.preview if terminal == "preview" else prepared.run
        with pytest.raises(CheckFailed) as error:
            method()
        assert error.value.problems[0].code == ("experiment_template_missing_input")

    assert candidate_reads == 0
