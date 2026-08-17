"""Project-level multi-run analysis application service."""

from __future__ import annotations

from base64 import b64encode

from scopecat.daemon.views import (
    AnalysisContentBytesView,
    ProjectAnalysisListView,
    ProjectAnalysisView,
)
from scopecat.daemon.wire import AnalysisSaveCommand, AnalysisSaveReceipt
from scopecat.kernel.ids import artifact_slug
from scopecat.project_state import ProjectStateServices
from scopecat.records.analysis import AnalysisRecord, ProjectAnalysisOutputReference
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

from ..errors import BackendConflict
from .runs import analysis_output_from_payload


class AnalysisService:
    """Own immutable publications whose inputs span completed project runs."""

    def __init__(
        self,
        *,
        repository: SQLiteAnalysisRepository,
        services: ProjectStateServices,
    ) -> None:
        self._repository = repository
        self._services = services

    def list(self) -> ProjectAnalysisListView:
        return ProjectAnalysisListView(
            items=tuple(
                self._view(manifest.record.id)
                for manifest in self._repository.list_manifests()
            )
        )

    def get(self, selector: str) -> ProjectAnalysisView:
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
        from scopecat.analysis.service import AnalysisInput, prepare_project_analysis

        inputs = tuple(
            AnalysisInput(
                id=item.id,
                run_id=item.run_id,
                target=item.target,
                kind=item.kind,
                content_hash=item.content_hash,
                codec=item.codec,
                role=item.role,
                title=item.title,
                metadata=item.metadata,
                source=item.source,
            )
            for item in command.inputs
        )
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
        if prepared.publication is not None:
            self._repository.publish(prepared.publication)
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
        reference: ProjectAnalysisOutputReference,
        *,
        source_run_id: str,
        proposal_id: str,
    ) -> None:
        """Require evidence over both the proposal source and a candidate run."""

        view = self.get(reference.analysis_record_id)
        if not any(
            output.id == reference.output_id for output in view.analysis.outputs
        ):
            raise BackendConflict(
                "candidate verification output does not exist in its project analysis"
            )
        input_run_ids = {input_ref.run_id for input_ref in view.analysis.inputs}
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


def _content_entry(view: ProjectAnalysisView, selector: str) -> RunContentEntry:
    try:
        return next(entry for entry in view.contents if entry.id == selector)
    except StopIteration:
        raise KeyError(f"analysis has no content: {selector}") from None


__all__ = ["AnalysisService"]
