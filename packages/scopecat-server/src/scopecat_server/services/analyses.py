"""Project-level multi-run analysis application service."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Generator
from contextlib import contextmanager
from threading import Lock
from typing import cast

from pydantic import JsonValue
from scopecat.control.models import DurableEventInput
from scopecat.daemon.views import (
    AnalysisContentBytesView,
    ProjectAnalysisListView,
    ProjectAnalysisView,
)
from scopecat.daemon.wire import AnalysisSaveCommand, AnalysisSaveReceipt
from scopecat.kernel.errors import CheckFailed, Conflict, DataIntegrityError, NotFound
from scopecat.kernel.ids import artifact_slug
from scopecat.project_state import ProjectStateServices
from scopecat.records.analysis import (
    AnalysisFactRecordOutput,
    AnalysisRecord,
    MeasurementAnalysisRecordInput,
    ProjectAnalysisDecisionReference,
    PublishedAnalysisRecordInput,
    RunAnalysisSubject,
)
from scopecat.records.artifact import RunContentEntry
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

    def list(self) -> ProjectAnalysisListView:
        with self._analysis_errors():
            return ProjectAnalysisListView(
                items=tuple(
                    self._view(manifest.record.id)
                    for manifest in self._repository.list_manifests()
                )
            )

    def get(self, selector: str) -> ProjectAnalysisView:
        with self._analysis_errors():
            manifests = self._repository.list_manifests()
            exact = next(
                (manifest for manifest in manifests if manifest.record.id == selector),
                None,
            )
            if exact is not None:
                return self._view(exact.record.id)
            selected_key = artifact_slug(selector, fallback="analysis")
            matches = tuple(
                view
                for manifest in manifests
                for view in (self._view(manifest.record.id),)
                if view.analysis.key == selected_key
            )
            if not matches:
                return self._view(selector)
            return max(matches, key=lambda item: item.analysis.revision)

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
            view = self._view(analysis_id)
            entry = _content_entry(view, selector)
            if entry.role == "dataset":
                ref = dataset_content_ref(dataset_id=entry.id, kind=entry.kind)
            elif entry.role == "artifact":
                ref = artifact_content_ref(artifact_id=entry.id, kind=entry.kind)
            else:
                ref = record_content_ref(record_id=entry.id, kind=entry.kind)
            return AnalysisContentBytesView(
                analysis_id=view.entry.id,
                entry=entry,
                content_base64=b64encode(
                    self._repository.read_bytes(view.entry.id, ref)
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

        view = self.get(reference.analysis_record_id)
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
        input_run_ids = self._input_run_ids(view)
        if source_run_id not in input_run_ids:
            raise BackendConflict(
                "candidate verification does not include the proposal source run"
            )
        for run_id in input_run_ids - {source_run_id}:
            manifest = self._services.runs.read_manifest(run_id)
            source = manifest.config_source
            if (
                isinstance(source, AnalysisCandidateRunConfigSource)
                and source.source_run_id == source_run_id
                and source.proposal_id == proposal_id
            ):
                return
        raise BackendConflict(
            "candidate verification does not include a run using this proposal"
        )

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
        manifest = self._repository.read_manifest(record_id)
        record = self._repository.read_model(
            record_id,
            record_content_ref(record_id=record_id, kind="analysis"),
            AnalysisRecord,
        )
        return ProjectAnalysisView(
            entry=manifest.record,
            analysis=record,
            contents=manifest.contents,
        )

    @contextmanager
    def _analysis_errors(self) -> Generator[None]:
        try:
            yield
        except NotFound as error:
            raise BackendNotFound(str(error)) from error
        except (CheckFailed, Conflict, DataIntegrityError) as error:
            raise BackendConflict(str(error)) from error


def _content_entry(view: ProjectAnalysisView, selector: str) -> RunContentEntry:
    try:
        return next(entry for entry in view.contents if entry.id == selector)
    except StopIteration:
        raise BackendNotFound(f"analysis has no content: {selector}") from None


__all__ = ["AnalysisService"]
