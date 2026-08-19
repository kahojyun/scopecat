"""Project-level multi-run analysis application service."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Generator
from contextlib import contextmanager
from threading import Lock
from typing import cast

from pydantic import JsonValue
from scopecat.config.changes import parameter_change_proposal_record_ref
from scopecat.control.models import DurableEventInput
from scopecat.daemon.views import (
    AnalysisContentBytesView,
    ProjectAnalysisContentPage,
    ProjectAnalysisPage,
    ProjectAnalysisSummary,
    ProjectAnalysisView,
)
from scopecat.daemon.wire import AnalysisSaveCommand, AnalysisSaveReceipt
from scopecat.kernel.errors import CheckFailed, Conflict, DataIntegrityError, NotFound
from scopecat.kernel.ids import artifact_slug
from scopecat.project_state import ProjectStateServices
from scopecat.records.analysis import (
    AnalysisFactRecordOutput,
    AnalysisParameterProposalRecordOutput,
    AnalysisRecord,
    MeasurementAnalysisRecordInput,
    ProjectAnalysisDecisionReference,
    PublishedAnalysisRecordInput,
    RunAnalysisSubject,
)
from scopecat.records.config import ConfigContentHash
from scopecat.records.content import ContentEntry
from scopecat.records.run import AnalysisCandidateRunConfigSource
from scopecat.runs.refs import (
    artifact_content_ref,
    dataset_content_ref,
    record_content_ref,
)

from scopecat_server.storage.sqlite.analysis_repository import (
    SQLiteAnalysisRepository,
)
from scopecat_server.storage.sqlite.control_plane import SQLiteControlPlane

from ..errors import BackendConflict, BackendNotFound
from .runs import analysis_input_from_payload, analysis_output_from_payload


class AnalysisService:
    """Own immutable publications whose inputs span completed project runs."""

    def __init__(
        self,
        *,
        repository: SQLiteAnalysisRepository,
        services: ProjectStateServices,
        control: SQLiteControlPlane,
    ) -> None:
        self._repository = repository
        self._services = services
        self._control = control
        self._publication_lock = Lock()

    def list(
        self,
        *,
        limit: int = 100,
        before: int | None = None,
    ) -> ProjectAnalysisPage:
        with self._analysis_errors():
            page = self._repository.list_summaries(limit=limit, before=before)
            return ProjectAnalysisPage(
                items=tuple(
                    ProjectAnalysisSummary(
                        entry=summary.record,
                        title=summary.title,
                        key=summary.analysis_key,
                        revision=summary.revision,
                        publication_hash=summary.publication_hash,
                        published_at=summary.published_at,
                        step_id=summary.step_id,
                        input_count=summary.input_count,
                        output_count=summary.output_count,
                    )
                    for summary in page.items
                ),
                next_cursor=page.next_cursor,
            )

    def get(self, selector: str) -> ProjectAnalysisView:
        with self._analysis_errors():
            try:
                publication = self._repository.read_publication(selector)
            except NotFound as exact_error:
                publication = self._repository.latest_publication(
                    artifact_slug(selector, fallback="analysis")
                )
                if publication is None:
                    raise exact_error
            return self._view(publication.record.id)

    def list_contents(
        self,
        analysis_id: str,
        *,
        limit: int = 100,
        before: int | None = None,
    ) -> ProjectAnalysisContentPage:
        with self._analysis_errors():
            page = self._repository.list_contents(
                analysis_id,
                limit=limit,
                before=before,
            )
            return ProjectAnalysisContentPage(
                analysis_id=analysis_id,
                items=page.items,
                next_cursor=page.next_cursor,
            )

    def content(self, analysis_id: str, selector: str) -> ContentEntry:
        with self._analysis_errors():
            return self._repository.read_content(analysis_id, selector)

    def save(self, command: AnalysisSaveCommand) -> AnalysisSaveReceipt:
        from scopecat.analysis.service import (
            MeasurementAnalysisInput,
            prepare_project_analysis,
        )

        with self._publication_lock, self._analysis_errors():
            inputs = tuple(analysis_input_from_payload(item) for item in command.inputs)
            prepared = prepare_project_analysis(
                services=self._services,
                repository=self._repository,
                title=command.title,
                analysis_key=command.analysis_key,
                step_id=command.step_id,
                inputs=inputs,
                executions=command.executions,
                outputs=tuple(
                    analysis_output_from_payload(item) for item in command.outputs
                ),
            )
            input_run_ids: set[str] = set()
            for input_ref in inputs:
                if isinstance(input_ref, MeasurementAnalysisInput):
                    input_run_ids.add(input_ref.run_id)
                    continue
                subject = input_ref.source.subject
                if isinstance(subject, RunAnalysisSubject):
                    input_run_ids.add(subject.run_id)
                else:
                    input_run_ids.update(
                        self._input_run_ids(
                            self._view(input_ref.source.analysis_record_id)
                        )
                    )
            if prepared.publication is not None:
                publication = self._repository.prepare_publication(prepared.publication)
                with self._control.write_transaction() as connection:
                    created = self._repository.publish_prepared_in_transaction(
                        connection,
                        publication,
                    )
                    if created:
                        event_payload: dict[str, JsonValue] = {
                            "analysis_key": prepared.saved.analysis_key,
                            "record_id": prepared.saved.record.id,
                            "revision": prepared.publication.revision,
                            "publication_hash": prepared.publication.publication_hash,
                            "input_run_ids": [
                                cast("JsonValue", run_id)
                                for run_id in sorted(input_run_ids)
                            ],
                        }
                        self._control.append_event_in_transaction(
                            connection,
                            DurableEventInput(
                                kind="project_analysis_saved",
                                payload=event_payload,
                            ),
                        )
            return AnalysisSaveReceipt(
                record=prepared.saved.record,
                analysis_key=prepared.saved.analysis_key,
                inputs=command.inputs,
            )

    def content_bytes(
        self,
        analysis_id: str,
        selector: str,
    ) -> AnalysisContentBytesView:
        with self._analysis_errors():
            publication = self._repository.read_publication(analysis_id)
            entry = self._repository.read_content(analysis_id, selector)
            if entry.role == "dataset":
                ref = dataset_content_ref(dataset_id=entry.id, kind=entry.kind)
            elif entry.role == "artifact":
                ref = artifact_content_ref(artifact_id=entry.id, kind=entry.kind)
            else:
                ref = record_content_ref(record_id=entry.id, kind=entry.kind)
            return AnalysisContentBytesView(
                analysis_id=publication.record.id,
                entry=entry,
                content_base64=b64encode(
                    self._repository.read_bytes(publication.record.id, ref)
                ).decode("ascii"),
            )

    def validate_candidate_verification(
        self,
        reference: ProjectAnalysisDecisionReference,
        *,
        source_run_id: str,
        proposal_id: str,
    ) -> None:
        """Require evidence over both the proposal source and a candidate run."""

        view = self._validated_decision_view(reference)
        input_run_ids = self._input_run_ids(view)
        if source_run_id not in input_run_ids:
            raise BackendConflict(
                "candidate verification does not include the proposal source run"
            )
        for run_id in input_run_ids - {source_run_id}:
            snapshot = self._services.runs.read_snapshot(run_id)
            source = snapshot.config_source
            if (
                isinstance(source, AnalysisCandidateRunConfigSource)
                and source.source_run_id == source_run_id
                and source.proposal_id == proposal_id
            ):
                return
        raise BackendConflict(
            "candidate verification does not include a run using this proposal"
        )

    def validate_calibration_merge_verification(
        self,
        reference: ProjectAnalysisDecisionReference,
        *,
        source_run_id: str,
        fit_analysis_record_id: str,
        proposal_id: str,
        candidate_run_id: str,
        base_config_content_hash: ConfigContentHash,
    ) -> None:
        """Require one exact fit, candidate run, and two-run verification proof."""

        try:
            publication = self._services.runs.read_analysis_publication(
                source_run_id,
                fit_analysis_record_id,
            )
            fit = self._services.runs.read_model(
                source_run_id,
                record_content_ref(
                    record_id=fit_analysis_record_id,
                    kind="analysis",
                ),
                AnalysisRecord,
            )
        except NotFound as error:
            raise BackendConflict(
                "calibration merge fit must identify an exact run analysis"
            ) from error
        if (
            publication.record.id != fit_analysis_record_id
            or fit.subject != RunAnalysisSubject(run_id=source_run_id)
            or not any(
                isinstance(output, AnalysisParameterProposalRecordOutput)
                and output.content.proposal_id == proposal_id
                and output.content.record_ref
                == parameter_change_proposal_record_ref(proposal_id)
                for output in fit.outputs
            )
        ):
            raise BackendConflict(
                "calibration merge fit does not own its exact proposal record"
            )

        try:
            candidate = self._services.runs.read_snapshot(candidate_run_id)
        except NotFound as error:
            raise BackendConflict(
                "calibration merge candidate must identify an exact run"
            ) from error
        candidate_source = candidate.config_source
        if (
            candidate.outcome is None
            or candidate.outcome.result != "succeeded"
            or not isinstance(candidate_source, AnalysisCandidateRunConfigSource)
            or candidate_source.source_run_id != source_run_id
            or candidate_source.analysis_record_id != fit_analysis_record_id
            or candidate_source.proposal_id != proposal_id
            or candidate_source.base_config_content_hash != base_config_content_hash
        ):
            raise BackendConflict(
                "calibration merge candidate run does not use its exact proposal"
            )

        if set(self.calibration_merge_verification_run_ids(reference)) != {
            source_run_id,
            candidate_run_id,
        }:
            raise BackendConflict(
                "calibration merge verification inputs must be the exact baseline "
                "and candidate runs"
            )

    def calibration_merge_verification_run_ids(
        self,
        reference: ProjectAnalysisDecisionReference,
    ) -> tuple[str, str]:
        """Resolve the two direct run inputs of one accepted project decision."""

        view = self._validated_decision_view(reference)
        direct_inputs = view.analysis.inputs
        run_ids = tuple(
            input_ref.run_id
            for input_ref in direct_inputs
            if isinstance(input_ref, MeasurementAnalysisRecordInput)
        )
        if len(direct_inputs) != 2 or len(run_ids) != 2 or len(set(run_ids)) != 2:
            raise BackendConflict(
                "calibration merge verification must have two distinct direct "
                "run inputs"
            )
        return run_ids

    def _validated_decision_view(
        self,
        reference: ProjectAnalysisDecisionReference,
    ) -> ProjectAnalysisView:
        try:
            view = self._view(reference.analysis_record_id)
        except NotFound as error:
            raise BackendConflict(
                "candidate verification must identify an exact project analysis"
            ) from error
        output = next(
            (
                output
                for output in view.analysis.outputs
                if output.id == reference.output_id
            ),
            None,
        )
        if output is None:
            raise BackendConflict(
                "candidate verification output does not exist in its project analysis"
            )
        if not isinstance(output, AnalysisFactRecordOutput):
            raise BackendConflict(
                "candidate verification decision must be a fact output"
            )
        decision = output.content
        if (
            decision.schema_id != reference.schema_id
            or decision.schema_hash != reference.schema_hash
        ):
            raise BackendConflict(
                "candidate verification decision schema does not match its reference"
            )
        if (
            not isinstance(decision.value, dict)
            or decision.value.get("accepted") is not True
        ):
            raise BackendConflict(
                "candidate verification decision did not accept the candidate"
            )
        return view

    def _input_run_ids(
        self,
        view: ProjectAnalysisView,
        *,
        visited: frozenset[str] | None = None,
    ) -> set[str]:
        visited = frozenset() if visited is None else visited
        if view.entry.id in visited:
            raise BackendConflict("project analysis input lineage contains a cycle")
        lineage = visited | {view.entry.id}
        run_ids: set[str] = set()
        for input_ref in view.analysis.inputs:
            if isinstance(input_ref, MeasurementAnalysisRecordInput):
                run_ids.add(input_ref.run_id)
                continue
            assert isinstance(input_ref, PublishedAnalysisRecordInput)
            subject = input_ref.source.subject
            if isinstance(subject, RunAnalysisSubject):
                run_ids.add(subject.run_id)
                continue
            run_ids.update(
                self._input_run_ids(
                    self._view(input_ref.source.analysis_record_id),
                    visited=lineage,
                )
            )
        return run_ids

    def _view(self, record_id: str) -> ProjectAnalysisView:
        publication = self._repository.read_publication(record_id)
        record = self._repository.read_model(
            record_id,
            record_content_ref(record_id=record_id, kind="analysis"),
            AnalysisRecord,
        )
        return ProjectAnalysisView(
            entry=publication.record,
            analysis=record,
            published_at=publication.published_at,
        )

    @contextmanager
    def _analysis_errors(self) -> Generator[None]:
        try:
            yield
        except NotFound as error:
            raise BackendNotFound(str(error)) from error
        except (CheckFailed, Conflict, DataIntegrityError) as error:
            raise BackendConflict(str(error)) from error


__all__ = ["AnalysisService"]
