"""Run records and read-side application service."""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Generator, Sequence
from contextlib import contextmanager

from scopecat.adapters.sqlite import (
    ControlPlaneNotFound,
    SQLiteControlPlane,
    SQLiteMeasurementDatasetRepository,
    SQLiteRunRepository,
)
from scopecat.analysis.service import (
    AnalysisFigureOutput,
    AnalysisInput,
    AnalysisOutput,
    AnalysisParameterProposalOutput,
    AnalysisTableOutput,
    prepare_analysis,
)
from scopecat.config.changes import (
    list_parameter_change_proposals,
    load_parameter_change_approval,
)
from scopecat.control.models import (
    ControlRun,
    ControlRunState,
    DurableEventInput,
    EventPage,
    RunResourceRequirement,
)
from scopecat.daemon.views import (
    MeasurementPage,
    MeasurementSlice,
    MeasurementSliceQuery,
    MeasurementTracePreview,
    MeasurementTracePreviewQuery,
    MeasurementTraceSeries,
    ParameterProposalListView,
    ParameterProposalView,
    RunAdmissionView,
    RunAnalysisListView,
    RunAnalysisView,
    RunArtifactBytesView,
    RunConfigView,
    RunControlView,
    RunDetail,
    RunPlanView,
    RunRequestView,
    RunResourceView,
    RunSummary,
    RunSummaryPage,
)
from scopecat.daemon.wire import (
    AnalysisFigureOutputPayload,
    AnalysisOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    AnalysisTableOutputPayload,
    RunAttachmentCommand,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
)
from scopecat.measurements.datasets import (
    RAW_MEASUREMENTS_DATASET_ID,
    product_grid_slice_indices,
)
from scopecat.measurements.results import MeasurementDatasetSchema
from scopecat.measurements.traces import (
    MeasurementTraceProjection,
    project_measurement_trace_preview,
)
from scopecat.project_state import ProjectStateServices
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.measurement import (
    MeasurementDataset,
    MeasurementProductGridPointDomain,
    MeasurementRecord,
)
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
    if isinstance(item, AnalysisTableOutputPayload):
        return AnalysisTableOutput(
            kind="table",
            title=item.title,
            content=item.content,
            metadata=item.metadata,
        )
    if isinstance(item, AnalysisFigureOutputPayload):
        return AnalysisFigureOutput(
            kind="figure",
            title=item.title,
            content=item.content,
            metadata=item.metadata,
        )
    return AnalysisParameterProposalOutput(
        kind="parameter_change_proposal",
        title=item.title,
        content=item.content,
        metadata=item.metadata,
    )


def _run_control_view(control: ControlRun) -> RunControlView:
    plan = control.admission.plan
    return RunControlView(
        sequence=control.sequence,
        admission=RunAdmissionView(
            run_id=control.run_id,
            admitted_at=control.admission.admitted_at,
            plan=RunPlanView(
                experiment_id=plan.experiment_id,
                experiment_kind=plan.experiment_kind,
                point_count=plan.point_count,
                coordinate_ids=plan.coordinate_ids,
                record_ids=plan.record_ids,
                run_resource_requirements=tuple(
                    RunResourceRequirement(kind=resource.kind, id=resource.id)
                    for resource in plan.run_resource_requirements
                ),
            ),
        ),
        state=control.state,
        updated_at=control.updated_at,
        attention_reason=control.attention_reason,
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
        before: int | None,
        state: ControlRunState | None,
    ) -> RunSummaryPage:
        with self._control.transaction() as connection:
            page = self._control.list_runs_in_transaction(
                connection,
                limit=limit,
                before=before,
                state=state,
            )
            return RunSummaryPage(
                items=tuple(
                    RunSummary(
                        control=_run_control_view(control),
                        manifest=self._runs.read_manifest_in_transaction(
                            connection,
                            control.run_id,
                        ),
                    )
                    for control in page.items
                ),
                next_cursor=page.next_cursor,
            )

    def list_run_stages(
        self,
        *,
        limit: int,
        before: int | None,
        sequence_id: str | None,
    ) -> RunSummaryPage:
        """List staged runs without scanning unrelated run manifests."""

        with self._control.transaction() as connection:
            page = self._control.list_staged_runs_in_transaction(
                connection,
                limit=limit,
                before=before,
                sequence_id=sequence_id,
            )
            return RunSummaryPage(
                items=tuple(
                    RunSummary(
                        control=_run_control_view(control),
                        manifest=self._runs.read_manifest_in_transaction(
                            connection,
                            control.run_id,
                        ),
                    )
                    for control in page.items
                ),
                next_cursor=page.next_cursor,
            )

    def get_run(self, run_id: str) -> RunDetail:
        try:
            with self._control.transaction() as connection:
                control = self._control.get_run_in_transaction(connection, run_id)
                manifest = self._runs.read_manifest_in_transaction(connection, run_id)
                claims = {
                    (claim.resource.kind, claim.resource.id): claim
                    for claim in self._control.list_resource_claims_in_transaction(
                        connection
                    )
                    if claim.owner_kind == "run" and claim.owner_id == run_id
                }
                executor_lease = self._control.executor_lease_for_run_in_transaction(
                    connection,
                    run_id,
                )
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        resources = tuple(
            RunResourceView(
                resource=RunResourceRequirement(
                    kind=logical_resource.kind,
                    id=logical_resource.id,
                ),
                status=(
                    claim.status
                    if (
                        claim := claims.get(
                            (canonical_resource.kind, canonical_resource.id)
                        )
                    )
                    is not None
                    else ("released" if control.state == "closed" else "required")
                ),
                expires_at=(
                    executor_lease.expires_at
                    if claim is not None
                    and claim.status == "active"
                    and executor_lease is not None
                    else None
                ),
            )
            for logical_resource, canonical_resource in zip(
                control.admission.plan.run_resource_requirements,
                control.admission.resource_claims,
                strict=True,
            )
        )
        return RunDetail(
            control=_run_control_view(control),
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

    def measurements(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
        include_schema: bool = True,
    ) -> MeasurementPage:
        with self._config_errors():
            manifest = self._runs.read_manifest(run_id)
            items, next_offset, live_schema = SQLiteMeasurementDatasetRepository(
                self._runs,
                run_id=run_id,
            ).measurement_page(
                limit=limit,
                offset=offset,
                include_schema=include_schema,
            )
        dataset = next(
            (
                entry
                for entry in manifest.datasets
                if entry.id == RAW_MEASUREMENTS_DATASET_ID
            ),
            None,
        )
        terminal_schema = (
            None
            if not include_schema or dataset is None or dataset.data_schema is None
            else MeasurementDatasetSchema.model_validate(dataset.data_schema)
        )
        return MeasurementPage(
            items=items,
            next_offset=next_offset,
            dataset_schema=terminal_schema or live_schema,
        )

    def measurement_slice(
        self,
        run_id: str,
        query: MeasurementSliceQuery,
    ) -> MeasurementSlice:
        """Read one bounded product-grid slice by authored axis indices."""

        with self._config_errors():
            self._runs.read_manifest(run_id)
            repository = SQLiteMeasurementDatasetRepository(self._runs, run_id=run_id)
            schema = repository.measurement_schema()
        if schema is None:
            raise BackendConflict("measurement dataset has no registered schema")
        domain = schema.point_domain
        if not isinstance(domain, MeasurementProductGridPointDomain):
            raise BackendConflict("measurement slices require a product-grid domain")
        try:
            point_indices, selected_point_count = product_grid_slice_indices(
                domain,
                query.fixed_axis_indices,
                limit=query.limit,
            )
        except ValueError as error:
            raise BackendConflict(str(error)) from error
        response_schema = schema
        if query.variable_ids is not None:
            try:
                response_schema = _select_measurement_schema(
                    response_schema,
                    query.variable_ids,
                )
            except ValueError as error:
                raise BackendConflict(str(error)) from error
        with self._config_errors():
            records = repository.measurement_records_at(
                point_indices,
                variable_ids=query.variable_ids,
            )
        return MeasurementSlice(
            items=records,
            dataset_schema=response_schema if query.include_schema else None,
            selected_point_count=selected_point_count,
            truncated=selected_point_count > len(point_indices),
        )

    def measurement_trace_preview(
        self,
        run_id: str,
        query: MeasurementTracePreviewQuery,
    ) -> MeasurementTracePreview:
        """Return bounded numeric trace series for direct plotting."""

        with self._config_errors():
            self._runs.read_manifest(run_id)
            repository = SQLiteMeasurementDatasetRepository(self._runs, run_id=run_id)
            schema = repository.measurement_schema()
        if schema is None:
            raise BackendConflict("measurement dataset has no registered schema")
        series_read_limit = min(query.max_series, query.max_samples // 2)
        selection_offset = 0
        selected_series_count = 0
        records: list[MeasurementRecord] = []
        projection = _project_trace_records(schema, (), query)
        trace_variable_ids = (projection.coordinate_id, projection.observable_id)
        while len(records) < series_read_limit:
            remaining_series = series_read_limit - len(records)
            try:
                point_indices, selected_series_count = _trace_preview_point_indices(
                    schema,
                    query.fixed_axis_indices,
                    offset=selection_offset,
                    limit=remaining_series,
                )
            except ValueError as error:
                raise BackendConflict(str(error)) from error
            if not point_indices:
                break
            with self._config_errors():
                batch = repository.measurement_records_at(
                    point_indices,
                    variable_ids=trace_variable_ids,
                )
            selection_offset += len(point_indices)
            batch_projection = _project_trace_records(schema, batch, query)
            batch_by_point = {record.point_index: record for record in batch}
            records.extend(
                batch_by_point[series.point_index] for series in batch_projection.series
            )
            if selection_offset == selected_series_count:
                break
        if records:
            projection = _project_trace_records(schema, records, query)
        series = tuple(
            MeasurementTraceSeries(
                point_index=item.point_index,
                logical_point_id=item.logical_point_id,
                label=item.label,
                x=tuple(float(value) for value in item.x),
                y=item.y,
                source_sample_count=item.source_sample_count,
            )
            for item in projection.series
        )
        return MeasurementTracePreview(
            fixed_axis_indices=dict(query.fixed_axis_indices),
            dimension_id=projection.dimension_id,
            recording_group_id=projection.recording_group_id,
            coordinate_id=projection.coordinate_id,
            observable_id=projection.observable_id,
            coordinate_label=projection.coordinate_label,
            observable_label=projection.observable_label,
            coordinate_unit=projection.coordinate_unit,
            observable_unit=projection.observable_unit,
            value_mode=projection.value_mode,
            value_unit=projection.value_unit,
            downsampling=projection.downsampling,
            series=series,
            selected_series_count=selected_series_count,
            returned_series_count=len(series),
            truncated_series=selection_offset < selected_series_count,
            source_sample_count=projection.source_sample_count,
            returned_sample_count=projection.returned_sample_count,
            samples_reduced=projection.samples_reduced,
        )

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


def _select_measurement_schema(
    schema: MeasurementDatasetSchema,
    variable_ids: list[str],
) -> MeasurementDatasetSchema:
    selected = set(variable_ids)
    available = {variable.id for variable in schema.variables}
    unknown = selected - available
    if unknown:
        raise ValueError(f"unknown measurement variables: {', '.join(sorted(unknown))}")
    return schema.model_copy(
        update={
            "variables": [
                variable for variable in schema.variables if variable.id in selected
            ],
            "primary_coordinates": [
                variable_id
                for variable_id in schema.primary_coordinates
                if variable_id in selected
            ],
            "primary_observables": [
                variable_id
                for variable_id in schema.primary_observables
                if variable_id in selected
            ],
        }
    )


def _trace_preview_point_indices(
    schema: MeasurementDatasetSchema,
    fixed_axis_indices: dict[str, int],
    *,
    offset: int,
    limit: int,
) -> tuple[tuple[int, ...], int]:
    domain = schema.point_domain
    if isinstance(domain, MeasurementProductGridPointDomain):
        point_indices, selected_count = product_grid_slice_indices(
            domain,
            fixed_axis_indices,
            limit=offset + limit,
        )
        return point_indices[offset:], selected_count
    if fixed_axis_indices:
        raise ValueError("trace fixed-axis selection requires a product-grid domain")
    point_dimension = next(
        dimension for dimension in schema.dimensions if dimension.id == "point"
    )
    assert point_dimension.size is not None
    return (
        tuple(range(offset, min(point_dimension.size, offset + limit))),
        point_dimension.size,
    )


def _project_trace_records(
    schema: MeasurementDatasetSchema,
    records: Sequence[MeasurementRecord],
    query: MeasurementTracePreviewQuery,
) -> MeasurementTraceProjection:
    try:
        return project_measurement_trace_preview(
            MeasurementDataset(dataset_schema=schema, records=tuple(records)),
            query.observable_id,
            coordinate=query.coordinate_id,
            group=query.recording_group_id,
            max_series=query.max_series,
            max_samples=query.max_samples,
            value_mode=query.value_mode,
            downsampling=query.downsampling,
        )
    except ValueError as error:
        raise BackendConflict(str(error)) from error
