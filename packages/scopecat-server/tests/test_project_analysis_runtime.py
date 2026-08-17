# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import cast

import httpx2
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient
from scopecat.analysis.facts import AnalysisFactSchema
from scopecat.api.analysis import Analysis, AnalysisContext, analysis_step
from scopecat.api.lab import LabClient
from scopecat.api.published_analysis import PublishedAnalysis
from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.registry import (
    CandidateConfigRegistrySource,
    CrossRunCandidateAcceptance,
)
from scopecat.control.models import (
    DurableEvent,
    DurableEventInput,
    EventPage,
    RunPlanSummary,
    RunResourceRequirement,
)
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.wire import (
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    CandidateConfigRevisionSource,
    ConfigPublishCommand,
    ExecutorStartRequest,
    MeasurementFlushCommand,
    MeasurementHeaderCommand,
    MeasurementSealCommand,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.execution.evidence import build_terminal_contents
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.measurements.recording_arrow import (
    encode_measurement_append,
)
from scopecat.records.analysis import (
    MeasurementAnalysisRecordInput,
    ProjectAnalysisDecisionReference,
    PublishedAnalysisRecordInput,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
)
from scopecat.records.measurement import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementProductGridPointDomain,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementVariable,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.records.parameter_change import (
    ParameterChangeProposal,
)
from scopecat.records.run_request import RunRequest

from scopecat_server import BackendConflict, LocalDaemonRuntime
from scopecat_server.storage.sqlite.control_plane import (
    SQLiteControlPlane,
)

_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-snapshot.json"
)


@dataclass(frozen=True, slots=True)
class _CandidateDecision:
    accepted: bool


_CANDIDATE_DECISION_SCHEMA = AnalysisFactSchema(
    "tests.candidate-decision.v1",
    _CandidateDecision,
)


def _config() -> ConfigProfileSnapshot:
    return load_config_snapshot_document(_FIXTURE)


def _events(
    runtime: LocalDaemonRuntime,
    *,
    run_id: str | None = None,
) -> EventPage:
    return runtime.application.runs.list_events(
        limit=500,
        after=None,
        run_id=run_id,
    )


def _submission(
    submission_id: str = "submission-1",
    *,
    point_count: int = 1,
) -> RunSubmission:
    return RunSubmission(
        submission_id=submission_id,
        config=_config(),
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=point_count,
            initial_point_count=point_count,
            point_limit=point_count,
            run_resource_requirements=(
                RunResourceRequirement(id="source-0", kind="instrument"),
            ),
        ),
    )


def _daemon_client(transport: TestClient) -> DaemonClient:
    def send(request: httpx2.Request) -> httpx2.Response:
        response = transport.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx2.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )

    return DaemonClient(
        "http://testserver",
        transport=httpx2.MockTransport(send),
    )


def _complete_signal_run(
    runtime: LocalDaemonRuntime,
    *,
    submission_id: str,
    signal: float,
    submission: RunSubmission | None = None,
) -> str:
    admission = runtime.application.submit_run(submission or _submission(submission_id))
    run_id = admission.run_id
    lease = runtime.application.executor.start_executor(
        run_id,
        ExecutorStartRequest(executor_id=f"executor-{submission_id}"),
    )
    header = MeasurementDatasetHeader(
        run_id=run_id,
        recording_contract_fingerprint="test.project-analysis.v1",
        dataset_schema=MeasurementDatasetSchema(
            dataset_id="raw-measurements",
            point_domain=MeasurementProductGridPointDomain(axes=[]),
            dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
            variables=[
                MeasurementVariable(
                    id="signal",
                    role="observable",
                    dtype="float64",
                    unit="ratio",
                    dims=["point"],
                )
            ],
        ),
        expected_record_count=1,
        record_count_limit=1,
    )
    record = MeasurementRecord(
        run_id=run_id,
        logical_point_id="point-0",
        point_index=0,
        coordinates={},
        observables={
            "signal": MeasurementScalar.create(
                dtype="float64",
                value=signal,
                unit="ratio",
            )
        },
    )
    append = MeasurementDatasetAppend(
        run_id=run_id,
        header_content_hash=header.content_hash,
        start_index=0,
        records=(record,),
    )
    runtime.application.executor.initialize_measurements(
        run_id,
        MeasurementHeaderCommand(lease_id=lease.lease_id, header=header),
    )
    runtime.application.executor.ingest_measurements(
        run_id,
        lease_id=lease.lease_id,
        content=encode_measurement_append(append, header.dataset_schema),
    )
    runtime.application.executor.flush_measurements(
        run_id,
        MeasurementFlushCommand(lease_id=lease.lease_id),
    )
    runtime.application.executor.seal_measurements(
        run_id,
        MeasurementSealCommand(
            lease_id=lease.lease_id,
            seal=MeasurementDatasetSeal(
                run_id=run_id,
                header_content_hash=header.content_hash,
                point_count=1,
                dataset_content_hash=measurement_dataset_content_hash(
                    header_content_hash=header.content_hash,
                    record_content_hashes=append.record_content_hashes,
                ),
            ),
        ),
    )
    outcome = RunOutcome(
        run_id=run_id,
        result="succeeded",
        certainty="known",
    )
    runtime.application.executor.commit_terminal(
        run_id,
        TerminalRunCommitCommand(
            lease_id=lease.lease_id,
            outcome=outcome,
            contents=build_terminal_contents(
                outcome=outcome,
                measurement_count=1,
                dataset_content_hash=measurement_dataset_content_hash(
                    header_content_hash=header.content_hash,
                    record_content_hashes=append.record_content_hashes,
                ),
                dataset_schema=header.dataset_schema,
                expected_record_count=1,
                instrument_state=None,
            ),
        ),
    )
    return run_id


def _analysis_proposal(run_id: str) -> ParameterChangeProposal:
    return parameter_change_proposal_from_updates(
        source_run_id=run_id,
        source_config=_config(),
        analysis_title="fit",
        analysis_record_id="analysis-fit",
        proposal_id="drive-frequency",
        updates=(
            replace_scalar_parameter(
                "drive_frequency",
                Quantity(value=5.1, unit="GHz"),
            ),
        ),
        reason="fit converged",
        confidence=0.9,
    )


def _analysis_command(proposal: ParameterChangeProposal) -> AnalysisSaveCommand:
    return AnalysisSaveCommand(
        title="fit",
        analysis_key="fit",
        outputs=(
            AnalysisParameterProposalOutputPayload(
                kind="parameter_change_proposal",
                id=proposal.id,
                title=proposal.id,
                content=proposal,
            ),
        ),
    )


def test_project_analysis_compares_completed_runs_and_reloads_outputs(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        baseline_id = _complete_signal_run(
            runtime,
            submission_id="comparison-baseline",
            signal=0.8,
        )
        candidate_id = _complete_signal_run(
            runtime,
            submission_id="comparison-candidate",
            signal=1.1,
        )
        with TestClient(runtime.app()) as transport:
            lab = LabClient(_daemon_client(transport))
            baseline = lab.get_run(baseline_id)
            candidate = lab.get_run(candidate_id)

            @analysis_step(id="candidate-verification")
            def candidate_verification(
                context: AnalysisContext,
                *,
                report: str,
            ) -> Analysis:
                baseline_data = context.measurements(
                    baseline,
                    id="baseline",
                    role="baseline",
                )
                candidate_data = context.measurements(
                    candidate,
                    id="candidate",
                    role="candidate",
                )
                baseline_peak = cast(
                    "float", baseline_data.data_vars["signal"].values[0]
                )
                candidate_peak = cast(
                    "float", candidate_data.data_vars["signal"].values[0]
                )
                return (
                    context.result("Candidate verification")
                    .dataset(
                        "comparison",
                        pa.table(
                            {
                                "role": ["baseline", "candidate"],
                                "run_id": [baseline.id, candidate.id],
                                "peak_signal": [baseline_peak, candidate_peak],
                            }
                        ),
                    )
                    .fact("candidate-improved", candidate_peak >= baseline_peak)
                    .artifact(
                        "report",
                        text=report,
                        filename="candidate-verification.md",
                        media_type="text/markdown",
                    )
                )

            def publish(report: str) -> PublishedAnalysis:
                return lab.analyze(candidate_verification(report=report))

            first = publish("# Candidate verification\n\nInitial comparison.\n")
            retry = publish("# Candidate verification\n\nInitial comparison.\n")
            revised = publish("# Candidate verification\n\nReviewed comparison.\n")

            assert first.id == "analysis-candidate-verification"
            assert retry.id == first.id
            assert revised.id == "analysis-candidate-verification-r2"
            assert revised.revision == 2
            assert revised.view.analysis.subject.kind == "project"
            measurement_inputs = tuple(
                item
                for item in revised.inputs
                if isinstance(item, MeasurementAnalysisRecordInput)
            )
            assert len(measurement_inputs) == len(revised.inputs)
            assert [
                (item.id, item.run_id, item.role) for item in measurement_inputs
            ] == [
                ("baseline", baseline.id, "baseline"),
                ("candidate", candidate.id, "candidate"),
            ]
            assert (
                revised.inputs[0].content_hash
                == baseline.measurements().entry.content_hash
            )
            assert (
                revised.inputs[1].content_hash
                == candidate.measurements().entry.content_hash
            )
            assert revised.fact("candidate-improved").value is True
            assert revised.dataset("comparison").table.to_pylist() == [
                {
                    "role": "baseline",
                    "run_id": baseline.id,
                    "peak_signal": 0.8,
                },
                {
                    "role": "candidate",
                    "run_id": candidate.id,
                    "peak_signal": 1.1,
                },
            ]
            assert revised.artifact("report").text().endswith("Reviewed comparison.\n")
            assert lab.published_analysis("candidate-verification").id == revised.id
            published_page = lab.published_analyses(limit=1)
            assert [item.id for item in published_page.items] == [revised.id]
            assert published_page.next_cursor is not None
            older_published_page = lab.published_analyses(
                limit=1,
                before=published_page.next_cursor,
            )
            assert [item.id for item in older_published_page.items] == [first.id]
            assert older_published_page.next_cursor is None
            summary_page = runtime.application.analyses.list(limit=1)
            assert [
                (
                    summary.entry.id,
                    summary.input_count,
                    summary.output_count,
                )
                for summary in summary_page.items
            ] == [(revised.id, 2, 3)]
            assert summary_page.next_cursor is not None
            assert [
                summary.entry.id
                for summary in runtime.application.analyses.list(
                    limit=1,
                    before=summary_page.next_cursor,
                ).items
            ] == [first.id]
            assert not any(
                entry.kind == "analysis" for entry in baseline.manifest.records
            )
            assert not any(
                entry.kind == "analysis" for entry in candidate.manifest.records
            )
            project_analysis_events = [
                event
                for event in _events(runtime).items
                if event.kind == "project_analysis_saved"
            ]
            assert [event.run_id for event in project_analysis_events] == [None, None]
            assert [
                event.payload["record_id"] for event in project_analysis_events
            ] == [first.id, revised.id]
            assert [event.payload["revision"] for event in project_analysis_events] == [
                1,
                2,
            ]
            assert [
                event.payload["publication_hash"] for event in project_analysis_events
            ] == [
                first.view.analysis.publication_hash,
                revised.view.analysis.publication_hash,
            ]
            assert [
                event.payload["input_run_ids"] for event in project_analysis_events
            ] == [sorted([baseline.id, candidate.id])] * 2

            missing_analysis = transport.get("/api/v1/analyses/missing")
            missing_content = transport.get(
                f"/api/v1/analyses/{revised.id}/contents/missing/bytes"
            )
            assert missing_analysis.status_code == 404
            assert missing_content.status_code == 404

    with (
        LocalDaemonRuntime(tmp_path) as restarted,
        TestClient(restarted.app()) as transport,
    ):
        restored = LabClient(_daemon_client(transport)).published_analysis(
            "candidate-verification"
        )
        assert restored.id == "analysis-candidate-verification-r2"
        assert restored.artifact("report").text().endswith("Reviewed comparison.\n")


def test_project_analysis_allocates_distinct_revisions_for_concurrent_saves(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        run_id = _complete_signal_run(
            runtime,
            submission_id="concurrent-project-analysis",
            signal=0.8,
        )
        with TestClient(runtime.app()) as transport:
            lab = LabClient(_daemon_client(transport))
            run = lab.get_run(run_id)
            pending = []
            for verdict in ("first", "second"):
                context = lab.analysis(
                    "Concurrent comparison",
                    key="concurrent-comparison",
                )
                context.measurements(run, id="measurement")
                pending.append(context.result().fact("verdict", verdict))

            ready = Barrier(len(pending))

            def save(result: Analysis) -> PublishedAnalysis:
                ready.wait()
                return result.save()

            with ThreadPoolExecutor(max_workers=len(pending)) as executor:
                saved = tuple(executor.map(save, pending))

            assert {item.id for item in saved} == {
                "analysis-concurrent-comparison",
                "analysis-concurrent-comparison-r2",
            }
            assert {item.revision for item in saved} == {1, 2}
            assert {cast("str", item.fact("verdict").value) for item in saved} == {
                "first",
                "second",
            }
            assert len(runtime.application.analyses.list().items) == 2
            assert (
                len(
                    [
                        event
                        for event in _events(runtime).items
                        if event.kind == "project_analysis_saved"
                    ]
                )
                == 2
            )


def test_project_analysis_consumes_project_datasets_facts_and_artifacts(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        run_id = _complete_signal_run(
            runtime,
            submission_id="project-analysis-inputs",
            signal=0.8,
        )
        with TestClient(runtime.app()) as transport:
            lab = LabClient(_daemon_client(transport))
            source_context = lab.analysis("Project source", key="project-source")
            source_context.measurements(
                lab.get_run(run_id),
                id="measurements",
            )
            source = (
                source_context.result()
                .dataset("summary", pa.table({"signal": [0.8]}))
                .fact("accepted", True)
                .artifact(
                    "report",
                    text="project source report",
                    filename="source.md",
                    media_type="text/markdown",
                )
                .save()
            )

            consumer_context = lab.analysis(
                "Project consumer",
                key="project-consumer",
            )
            summary = consumer_context.analysis_dataset("project-source", "summary")
            accepted = consumer_context.analysis_fact("project-source", "accepted")
            report = consumer_context.analysis_artifact("project-source", "report")
            consumer = (
                consumer_context.result()
                .fact(
                    "consumed",
                    bool(accepted.value)
                    and summary.table.num_rows == 1
                    and bool(report.text()),
                )
                .save()
            )

            assert consumer.fact("consumed").value is True
            assert {input_ref.kind for input_ref in consumer.inputs} == {
                "analysis_dataset",
                "analysis_fact",
                "analysis_artifact",
            }
            published_inputs = tuple(
                input_ref
                for input_ref in consumer.inputs
                if isinstance(input_ref, PublishedAnalysisRecordInput)
            )
            assert len(published_inputs) == len(consumer.inputs)
            assert all(
                input_ref.source.subject.kind == "project"
                and input_ref.source.analysis_record_id == source.id
                for input_ref in published_inputs
            )
            [consumer_event] = [
                event
                for event in _events(runtime).items
                if event.kind == "project_analysis_saved"
                and event.payload["record_id"] == consumer.id
            ]
            assert consumer_event.payload["input_run_ids"] == [run_id]


def test_project_analysis_publication_rolls_back_index_and_event_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        run_id = _complete_signal_run(
            runtime,
            submission_id="project-analysis-atomic",
            signal=0.8,
        )
        with TestClient(runtime.app()) as transport:
            lab = LabClient(_daemon_client(transport))
            context = lab.analysis("Atomic comparison", key="atomic-comparison")
            context.measurements(
                lab.get_run(run_id),
                id="baseline",
                role="baseline",
            )
            result = context.result().fact("decision", True)
            append_event = SQLiteControlPlane.append_event_in_transaction

            def fail_project_analysis_event(
                control: SQLiteControlPlane,
                connection: sqlite3.Connection,
                event: DurableEventInput,
            ) -> DurableEvent:
                if event.kind == "project_analysis_saved":
                    raise RuntimeError("project analysis event publication failed")
                return append_event(control, connection, event)

            with monkeypatch.context() as patch:
                patch.setattr(
                    SQLiteControlPlane,
                    "append_event_in_transaction",
                    fail_project_analysis_event,
                )
                with pytest.raises(
                    RuntimeError,
                    match="project analysis event publication failed",
                ):
                    result.save()

            assert runtime.application.analyses.list().items == ()
            assert [
                event.kind
                for event in _events(runtime).items
                if event.kind == "project_analysis_saved"
            ] == []

            saved = result.save()

            assert saved.id == "analysis-atomic-comparison"
            assert [
                event.kind
                for event in _events(runtime).items
                if event.kind == "project_analysis_saved"
            ] == ["project_analysis_saved"]


def test_candidate_acceptance_requires_matching_cross_run_verification(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        baseline_id = _complete_signal_run(
            runtime,
            submission_id="verified-baseline",
            signal=0.8,
        )
        unrelated_id = _complete_signal_run(
            runtime,
            submission_id="verified-unrelated",
            signal=1.0,
        )
        proposal = _analysis_proposal(baseline_id)
        runtime.application.runs.save_run_analysis(
            baseline_id,
            _analysis_command(proposal),
        )

        with TestClient(runtime.app()) as transport:
            lab = LabClient(_daemon_client(transport))
            baseline = lab.get_run(baseline_id)
            proposal_analysis = baseline.published_analysis("fit")
            candidate = proposal_analysis.candidate_config()
            candidate_config, candidate_source = lab.config.resolve_with_source(
                candidate
            )
            assert candidate_source is not None
            candidate_submission = _submission("verified-candidate").model_copy(
                update={
                    "config": candidate_config,
                    "config_source": candidate_source,
                }
            )
            candidate_id = _complete_signal_run(
                runtime,
                submission_id="verified-candidate",
                signal=1.1,
                submission=candidate_submission,
            )

            invalid_context = lab.analysis(
                "Unrelated comparison",
                key="unrelated-comparison",
            )
            invalid_context.measurements(baseline, id="baseline", role="baseline")
            invalid_context.measurements(
                lab.get_run(unrelated_id),
                id="candidate",
                role="candidate",
            )
            invalid_verification = (
                invalid_context.result()
                .fact(
                    "decision",
                    _CandidateDecision(accepted=True),
                    schema=_CANDIDATE_DECISION_SCHEMA,
                )
                .save()
            )
            invalid_decision = invalid_verification.fact("decision")
            invalid_acceptance = CrossRunCandidateAcceptance(
                decision=ProjectAnalysisDecisionReference(
                    analysis_record_id=invalid_verification.id,
                    output_id="decision",
                    schema_id=invalid_decision.schema_id,
                    schema_hash=invalid_decision.schema_hash,
                )
            )
            with pytest.raises(
                BackendConflict,
                match="does not include a run using this proposal",
            ):
                runtime.application.config.publish_config(
                    ConfigPublishCommand(
                        source=CandidateConfigRevisionSource(
                            run_id=baseline_id,
                            proposal_id=proposal.id,
                            acceptance=invalid_acceptance,
                        ),
                        entry_id="invalid-verified-candidate",
                        actor="nightly-calibration",
                        expected_generation=1,
                    )
                )

            valid_context = lab.analysis(
                "Candidate comparison",
                key="candidate-comparison",
            )
            valid_context.measurements(baseline, id="baseline", role="baseline")
            valid_context.measurements(
                lab.get_run(candidate_id),
                id="candidate",
                role="candidate",
            )
            verification = (
                valid_context.result()
                .fact(
                    "decision",
                    _CandidateDecision(accepted=True),
                    schema=_CANDIDATE_DECISION_SCHEMA,
                )
                .save()
            )
            verification_decision = verification.fact("decision")
            with pytest.raises(
                BackendConflict,
                match="must identify an exact project analysis",
            ):
                runtime.application.config.publish_config(
                    ConfigPublishCommand(
                        source=CandidateConfigRevisionSource(
                            run_id=baseline_id,
                            proposal_id=proposal.id,
                            acceptance=CrossRunCandidateAcceptance(
                                decision=ProjectAnalysisDecisionReference(
                                    analysis_record_id="candidate-comparison",
                                    output_id="decision",
                                    schema_id=verification_decision.schema_id,
                                    schema_hash=verification_decision.schema_hash,
                                )
                            ),
                        ),
                        entry_id="logical-key-verification",
                        actor="nightly-calibration",
                        expected_generation=1,
                    )
                )
            accepted = lab.config.accept_verified(
                proposal_analysis,
                verified_by=(verification, "decision"),
                entry_id="verified-candidate-config",
            )

            assert isinstance(accepted.entry.source, CandidateConfigRegistrySource)
            assert accepted.entry.source.acceptance == (
                CrossRunCandidateAcceptance(
                    decision=ProjectAnalysisDecisionReference(
                        analysis_record_id=verification.id,
                        output_id="decision",
                        schema_id=_CANDIDATE_DECISION_SCHEMA.id,
                        schema_hash=_CANDIDATE_DECISION_SCHEMA.schema_hash,
                    )
                )
            )

            rejected_context = lab.analysis(
                "Rejected candidate comparison",
                key="rejected-candidate-comparison",
            )
            rejected_context.measurements(baseline, id="baseline", role="baseline")
            rejected_context.measurements(
                lab.get_run(candidate_id),
                id="candidate",
                role="candidate",
            )
            rejected_verification = (
                rejected_context.result()
                .fact(
                    "decision",
                    _CandidateDecision(accepted=False),
                    schema=_CANDIDATE_DECISION_SCHEMA,
                )
                .save()
            )
            rejected_decision = rejected_verification.fact("decision")
            with pytest.raises(
                BackendConflict,
                match="did not accept the candidate",
            ):
                runtime.application.config.publish_config(
                    ConfigPublishCommand(
                        source=CandidateConfigRevisionSource(
                            run_id=baseline_id,
                            proposal_id=proposal.id,
                            acceptance=CrossRunCandidateAcceptance(
                                decision=ProjectAnalysisDecisionReference(
                                    analysis_record_id=rejected_verification.id,
                                    output_id="decision",
                                    schema_id=rejected_decision.schema_id,
                                    schema_hash=rejected_decision.schema_hash,
                                )
                            ),
                        ),
                        entry_id="rejected-verified-candidate",
                        actor="nightly-calibration",
                        expected_generation=2,
                    )
                )

            with pytest.raises(
                ValueError,
                match="must contain accepted=true",
            ):
                lab.config.accept_verified(
                    proposal_analysis,
                    verified_by=(rejected_verification, "decision"),
                    entry_id="client-rejected-candidate",
                )
