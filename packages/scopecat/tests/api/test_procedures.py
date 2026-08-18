from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import httpx2
import pytest
from scopecat_testkit.workflow_fixtures import load_config, load_invocation

import scopecat.api.procedures as procedures_module
from scopecat.api._config import LabConfigOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.analysis import Analysis, AnalysisContext, AnalysisStep
from scopecat.api.procedures import (
    LabProcedureContext,
    ProcedureLabSession,
    _validate_run_analysis,
)
from scopecat.api.published_analysis import PublishedAnalysis
from scopecat.api.run import RunHandle
from scopecat.automation import (
    ProcedureContext,
    ProcedureStepOperation,
    ProcedureStepOutputRef,
    RunOutputRef,
)
from scopecat.automation.worker import ProcedureNeedsAttention
from scopecat.config.candidates import CandidateConfig
from scopecat.daemon.client import DaemonNotFoundError
from scopecat.daemon.views import RunAnalysisView
from scopecat.records.analysis import (
    AnalysisRecord,
    MeasurementAnalysisRecordInput,
    RunAnalysisSubject,
    analysis_record_id,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.content import ContentEntry, Sha256ContentHash
from scopecat.records.run import RunConfigSource, RunSnapshot
from scopecat.runs.selectors import RunSelector


class _ImmediateProcedureContext:
    procedure_run_id = "procedure-test"

    def step(
        self,
        step_key: str,
        *,
        operation: ProcedureStepOperation,
        intent_hash: Sha256ContentHash,
        effect: Callable[[str], ProcedureStepOutputRef],
        inputs: tuple[ProcedureStepOutputRef, ...] = (),
    ) -> ProcedureStepOutputRef:
        del step_key, operation, intent_hash, inputs
        return effect("operation-test")


@dataclass(frozen=True, slots=True)
class _DirectConfig:
    def resolve_with_source(
        self,
        config: ConfigProfileSnapshot | CandidateConfig,
    ) -> tuple[ConfigProfileSnapshot, RunConfigSource | None]:
        if isinstance(config, CandidateConfig):
            raise AssertionError("test expects a direct config snapshot")
        return config, None


@dataclass(frozen=True, slots=True)
class _TransportFailingRunner:
    planned: object

    def _plan(self, _experiment: object, **_kwargs: object) -> object:
        return self.planned

    def execute(
        self,
        _planned: object,
        *,
        executor_id: str = "notebook",
        submission_id: str | None = None,
    ) -> RunSnapshot:
        del executor_id, submission_id
        raise httpx2.ReadError("child run response was lost")


def _stub_prepare_run_submission(
    _planned: object,
    *,
    submission_id: str,
) -> tuple[object, str]:
    del submission_id
    return object(), "sha256:" + "a" * 64


@dataclass(frozen=True, slots=True)
class _TestAnalysisStep:
    id: str = "test-analysis"

    def run(self, context: AnalysisContext) -> Analysis:
        del context
        raise AssertionError("analysis execution is outside this transport test")


class _UnknownProjectAnalysisSession:
    def get_run(self, run: RunSelector | RunHandle) -> RunHandle:
        del run
        raise AssertionError("run lookup is outside this project-analysis test")

    def analyze(
        self,
        step: AnalysisStep,
        *,
        key: str | None = None,
    ) -> PublishedAnalysis:
        del step, key
        raise httpx2.ReadError("analysis response was lost")

    def published_analysis(self, selector: str) -> PublishedAnalysis:
        del selector
        response = httpx2.Response(
            404,
            request=httpx2.Request("GET", "http://daemon.local/analysis"),
        )
        raise DaemonNotFoundError("analysis does not exist", response=response)


def test_child_run_transport_error_requires_procedure_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    monkeypatch.setattr(
        procedures_module,
        "_prepare_run_submission",
        _stub_prepare_run_submission,
    )
    context = LabProcedureContext(
        cast("ProcedureContext", cast("object", _ImmediateProcedureContext())),
        runner=cast(
            "_DaemonRunner",
            cast("object", _TransportFailingRunner(object())),
        ),
        config=cast("LabConfigOperations", cast("object", _DirectConfig())),
        session=cast("ProcedureLabSession", object()),
    )

    with pytest.raises(ProcedureNeedsAttention, match="transport outcome"):
        context.run("child", load_invocation(), config=config)


def test_analysis_transport_with_no_confirmed_r1_requires_attention() -> None:
    context = LabProcedureContext(
        cast("ProcedureContext", cast("object", _ImmediateProcedureContext())),
        runner=cast("_DaemonRunner", object()),
        config=cast("LabConfigOperations", object()),
        session=_UnknownProjectAnalysisSession(),
    )

    with pytest.raises(ProcedureNeedsAttention, match="unknown outcome"):
        context.analyze_project(
            "fit",
            _TestAnalysisStep(),
            inputs=(),
        )


def test_run_analysis_rejects_durable_upstream_mismatch() -> None:
    run_id = "run-subject"
    step_id = "fit-step"
    key = "procedure-fit-key"
    record_id = analysis_record_id(key, 1)
    published = PublishedAnalysis(
        source=object(),  # pyright: ignore[reportArgumentType]
        view=RunAnalysisView(
            run_id=run_id,
            entry=ContentEntry(
                role="record",
                id=record_id,
                kind="analysis",
                content_hash="sha256:analysis-record",
            ),
            analysis=AnalysisRecord(
                subject=RunAnalysisSubject(run_id=run_id),
                title="Fit",
                key=key,
                revision=1,
                publication_hash="sha256:publication",
                step_id=step_id,
                inputs=[
                    MeasurementAnalysisRecordInput(
                        id="measurement-input",
                        target="measurement-dataset",
                        content_hash="sha256:measurements",
                        codec="scopecat.measurement-dataset.v1",
                        role="dataset",
                        run_id=run_id,
                    )
                ],
                outputs=[],
            ),
            published_at=datetime(2026, 8, 18, tzinfo=UTC),
        ),
    )

    with pytest.raises(ValueError, match="upstreams"):
        _validate_run_analysis(
            published,
            run_id=run_id,
            step_id=step_id,
            key=key,
            inputs=(
                RunOutputRef(run_id=run_id),
                RunOutputRef(run_id="run-unpublished-upstream"),
            ),
        )
