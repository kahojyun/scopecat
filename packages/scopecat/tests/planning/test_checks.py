from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

import scopecat as sc
import scopecat.config.resolution as config_resolution
from scopecat import ExperimentCheckResult
from scopecat.api.workspace import Workspace
from scopecat.composition.embedded import open_embedded_workspace
from scopecat.config.candidates import CandidateConfig
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
)
from scopecat.records.config import ConfigProfileSnapshot
from tests.testkit.authoring import simple_template
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_invocation


def _workspace(
    tmp_path: Path,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> Workspace:
    return open_embedded_workspace(
        tmp_path,
        config=load_config() if config is None else config,
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )


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
            "system": config.system.model_copy(
                update={"primary_entity_id": "missing-entity"}
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
