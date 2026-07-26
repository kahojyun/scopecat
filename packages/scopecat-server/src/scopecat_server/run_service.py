"""Run records and read-side application service."""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Generator
from contextlib import contextmanager

from scopecat.adapters.sqlite import (
    ControlPlaneNotFound,
    SQLiteControlPlane,
    SQLiteMeasurementDatasetRepository,
    SQLiteRunRepository,
)
from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    prepare_analysis,
)
from scopecat.config.changes import (
    list_parameter_change_proposals,
    load_parameter_change_approval,
    prepare_parameter_change_approval,
)
from scopecat.control.models import (
    ControlRunState,
    DurableEventInput,
    EventPage,
)
from scopecat.daemon.views import (
    MeasurementPage,
    ParameterProposalListView,
    ParameterProposalView,
    RunAnalysisListView,
    RunAnalysisView,
    RunArtifactBytesView,
    RunConfigView,
    RunDetail,
    RunRequestView,
    RunResourceView,
    RunSummary,
    RunSummaryPage,
)
from scopecat.daemon.wire import (
    AnalysisOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    ParameterProposalApprovalCommand,
    RunAttachmentCommand,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
)
from scopecat.project_state import ProjectStateServices
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.parameter_change import ParameterChangeApprovalRecord
from scopecat.runs.access import list_records
from scopecat.runs.attachments import attach_run_artifact
from scopecat.runs.data import (
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.service import (
    load_run_request,
    read_run_artifact_bytes,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_measurement_dataset,
    read_run_record_json,
)

from .errors import BackendConflict, BackendNotFound


def _analysis_output(item: AnalysisOutputPayload) -> AnalysisOutput:
    return AnalysisOutput(
        kind=item.kind,
        title=item.title,
        content=item.content,
        metadata=item.metadata,
    )


class RunService:
    """Own run records, analysis content, and read-side queries."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
        services: ProjectStateServices,
    ) -> None:
        self._control = control
        self._runs = runs
        self._services = services

    def list_runs(
        self,
        *,
        limit: int,
        after: int | None,
        before: int | None,
        state: ControlRunState | None,
        latest: bool = False,
    ) -> RunSummaryPage:
        with self._control.transaction() as connection:
            page = self._control.list_runs_in_transaction(
                connection,
                limit=limit,
                after=after,
                before=before,
                state=state,
                latest=latest,
            )
            return RunSummaryPage(
                items=tuple(
                    RunSummary(
                        control=control,
                        manifest=self._runs.read_manifest_in_transaction(
                            connection,
                            control.run_id,
                        ),
                    )
                    for control in page.items
                ),
                next_cursor=page.next_cursor,
                previous_cursor=page.previous_cursor,
            )

    def get_run(self, run_id: str) -> RunDetail:
        try:
            with self._control.transaction() as connection:
                control = self._control.get_run_in_transaction(connection, run_id)
                manifest = self._runs.read_manifest_in_transaction(connection, run_id)
                leases = {
                    (lease.resource.kind, lease.resource.id): lease
                    for lease in self._control.list_resource_leases_in_transaction(
                        connection
                    )
                    if lease.run_id == run_id
                }
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        resources = tuple(
            RunResourceView(
                resource=resource,
                status=(
                    lease.status
                    if (lease := leases.get((resource.kind, resource.id))) is not None
                    else ("released" if control.state == "closed" else "required")
                ),
                expires_at=None if lease is None else lease.expires_at,
            )
            for resource in control.admission.resource_claims
        )
        return RunDetail(
            control=control,
            manifest=manifest,
            resources=resources,
        )

    def get_run_config(self, run_id: str) -> RunConfigView:
        with self._config_errors():
            manifest = self._runs.read_manifest(run_id)
            return RunConfigView(
                run_id=run_id,
                config_content_hash=manifest.config_content_hash,
                config=self._runs.read_config_profile_snapshot(run_id),
            )

    def get_run_request(self, run_id: str) -> RunRequestView:
        with self._config_errors():
            return RunRequestView(
                run_id=run_id,
                request=load_run_request(run_id=run_id, services=self._services),
            )

    def list_run_analyses(self, run_id: str) -> RunAnalysisListView:
        with self._config_errors():
            manifest = self._runs.read_manifest(run_id)
            return RunAnalysisListView(
                run_id=run_id,
                items=tuple(
                    self._run_analysis_view(run_id, record.id)
                    for record in list_records(manifest, kind="analysis")
                ),
            )

    def get_run_analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        with self._config_errors():
            return self._run_analysis_view(run_id, selector)

    def _run_analysis_view(self, run_id: str, selector: str) -> RunAnalysisView:
        result = read_run_record_json(
            run_id=run_id,
            selector=selector,
            expected_kind="analysis",
            services=self._services,
        )
        return RunAnalysisView(
            run_id=run_id,
            entry=result.record,
            analysis=AnalysisRecord.model_validate(result.content),
        )

    def save_run_analysis(
        self,
        run_id: str,
        command: AnalysisSaveCommand,
    ) -> AnalysisSaveReceipt:
        inputs = tuple(
            AnalysisInput(
                target=item.target,
                kind=item.kind,
                role=item.role,
                title=item.title,
                metadata=item.metadata,
            )
            for item in command.inputs
        )
        outputs = tuple(_analysis_output(item) for item in command.outputs)
        proposals = tuple(
            item.content
            for item in command.outputs
            if isinstance(item, AnalysisParameterProposalOutputPayload)
        )
        with self._config_errors():
            prepared = prepare_analysis(
                services=self._services,
                run_id=run_id,
                title=command.title,
                analysis_key=command.analysis_key,
                step_id=command.step_id,
                inputs=inputs,
                outputs=outputs,
                parameter_proposals=proposals,
            )
            publication = self._runs.prepare_content_publication(prepared.publication)
            with self._control.transaction() as connection:
                existing = {
                    entry.id: entry.content_hash
                    for entry in self._runs.read_manifest_in_transaction(
                        connection,
                        run_id,
                    ).records
                }
                self._runs.publish_prepared_content_in_transaction(
                    connection,
                    publication,
                )
                if (
                    existing.get(prepared.saved.record.id)
                    != prepared.saved.record.content_hash
                ):
                    self._control.append_event_in_transaction(
                        connection,
                        DurableEventInput(
                            run_id=run_id,
                            kind="analysis_saved",
                            payload={
                                "analysis_key": prepared.saved.analysis_key,
                                "record_id": prepared.saved.record.id,
                            },
                        ),
                    )
        return AnalysisSaveReceipt(
            record=prepared.saved.record,
            analysis_key=prepared.saved.analysis_key,
            inputs=command.inputs,
        )

    def get_run_artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesView:
        with self._config_errors():
            result = read_run_artifact_bytes(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self._services,
            )
            return RunArtifactBytesView(
                run_id=run_id,
                artifact=result.artifact,
                content_base64=b64encode(result.content).decode("ascii"),
            )

    def get_run_artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextResult:
        with self._config_errors():
            return read_run_artifact_text(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self._services,
            )

    def get_run_artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonResult:
        with self._config_errors():
            return read_run_artifact_json(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self._services,
            )

    def get_run_record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonResult:
        with self._config_errors():
            return read_run_record_json(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self._services,
            )

    def get_run_dataset_content(
        self,
        run_id: str,
        selector: str,
    ) -> RunMeasurementDatasetResult:
        with self._config_errors():
            return read_run_measurement_dataset(
                run_id=run_id,
                selector=selector,
                services=self._services,
            )

    def attach_run_content(
        self,
        run_id: str,
        command: RunAttachmentCommand,
    ) -> RunContentEntry:
        content = (
            None
            if command.content_base64 is None
            else b64decode(command.content_base64, validate=True)
        )
        with self._config_errors():
            artifact = attach_run_artifact(
                services=self._services,
                run_id=run_id,
                key=command.key,
                kind=command.kind,
                text=command.text,
                content=content,
                filename=command.filename,
                media_type=command.media_type,
                metadata=command.metadata,
            )
        return artifact

    def list_parameter_proposals(self, run_id: str) -> ParameterProposalListView:
        with self._config_errors():
            proposals = list_parameter_change_proposals(
                run_id=run_id,
                services=self._services,
            )
            return ParameterProposalListView(
                run_id=run_id,
                items=tuple(
                    ParameterProposalView(
                        proposal=proposal,
                        approval=load_parameter_change_approval(
                            run_id=run_id,
                            selector=proposal.id,
                            storage=self._runs,
                        ),
                    )
                    for proposal in proposals
                ),
            )

    def approve_parameter_proposal(
        self,
        run_id: str,
        proposal_id: str,
        command: ParameterProposalApprovalCommand,
    ) -> ParameterChangeApprovalRecord:
        with self._config_errors():
            prepared = prepare_parameter_change_approval(
                run_id=run_id,
                selector=proposal_id,
                services=self._services,
                actor=command.actor,
                note=command.note,
            )
            if prepared.publication is None:
                return prepared.approval
            publication = self._runs.prepare_content_publication(prepared.publication)
            with self._control.transaction() as connection:
                self._runs.publish_prepared_content_in_transaction(
                    connection,
                    publication,
                )
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        run_id=run_id,
                        kind="parameter_proposal_approved",
                        payload={
                            "proposal_id": prepared.approval.proposal_id,
                            "actor": prepared.approval.actor,
                        },
                        occurred_at=prepared.approval.approved_at,
                    ),
                )
        return prepared.approval

    def measurements(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> MeasurementPage:
        with self._config_errors():
            self._runs.read_manifest(run_id)
            records = SQLiteMeasurementDatasetRepository(
                self._runs,
                run_id=run_id,
            ).measurements()
        items = records[offset : offset + limit]
        next_offset = (
            offset + len(items) if offset + len(items) < len(records) else None
        )
        return MeasurementPage(items=items, next_offset=next_offset)

    @contextmanager
    def _config_errors(self) -> Generator[None]:
        try:
            yield
        except NotFound as error:
            raise BackendNotFound(str(error)) from error
        except (CheckFailed, Conflict, DataIntegrityError) as error:
            raise BackendConflict(str(error)) from error

    def list_events(
        self,
        *,
        limit: int,
        after: int | None,
        run_id: str | None,
        latest: bool = False,
    ) -> EventPage:
        return self._control.list_events(
            limit=limit,
            after=after,
            run_id=run_id,
            latest=latest,
        )
