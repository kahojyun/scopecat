# pyright: reportUnknownMemberType=false, reportUnknownParameterType=false
# pyright: reportUnknownVariableType=false
"""In-process run operations for repository tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pyarrow as pa
from pydantic import JsonValue
from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    SavedAnalysis,
    save_analysis,
)
from scopecat.daemon.views import (
    MeasurementArrowQuery,
    RunAnalysisListView,
    RunAnalysisView,
)
from scopecat.measurements.datasets import (
    RAW_MEASUREMENTS_DATASET_ID,
)
from scopecat.measurements.paging import project_measurement_page
from scopecat.project_state import ProjectStateServices
from scopecat.records.analysis import AnalysisExecution, AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.access import list_records, require_dataset
from scopecat.runs.attachments import attach_run_artifact
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDatasetBytesResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.service import (
    load_run_request,
    read_run_artifact_bytes,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_dataset_bytes,
    read_run_measurement_dataset,
    read_run_record_json,
)
from scopecat_server.storage.sqlite.execution import (
    SQLiteMeasurementDatasetRepository,
)
from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository


@dataclass(frozen=True, slots=True)
class ServiceRunOperations:
    services: ProjectStateServices

    def load_manifest(self, run_id: str) -> RunManifest:
        return self.services.runs.read_manifest(run_id)

    def load_config(self, run_id: str) -> ConfigProfileSnapshot:
        return self.services.runs.read_config_profile_snapshot(run_id)

    def load_request(self, run_id: str) -> RunRequest:
        return load_run_request(run_id=run_id, services=self.services)

    def load_measurement_dataset(
        self,
        run_id: str,
        *,
        selector: str,
    ) -> RunMeasurementDatasetResult:
        return read_run_measurement_dataset(
            run_id=run_id,
            services=self.services,
            selector=selector,
        )

    def load_dataset_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunDatasetBytesResult:
        return read_run_dataset_bytes(
            run_id=run_id,
            selector=selector,
            expected_kind=expected_kind,
            services=self.services,
        )

    def load_measurement_arrow_page(
        self,
        run_id: str,
        *,
        query: MeasurementArrowQuery,
    ) -> tuple[pa.Table, int | None, int]:
        manifest = self.services.runs.read_manifest(run_id)
        entry = require_dataset(
            manifest=manifest,
            selector=RAW_MEASUREMENTS_DATASET_ID,
        )
        variable_ids = tuple(column.variable_id for column in query.columns)
        items, next_offset, schema, snapshot_size = SQLiteMeasurementDatasetRepository(
            cast("SQLiteRunRepository", self.services.runs),
            run_id=run_id,
        ).measurement_page(
            limit=query.limit,
            offset=query.offset,
            snapshot_size=query.snapshot_size,
            variable_ids=variable_ids,
        )
        if schema is None:
            raise ValueError("measurement dataset has no registered schema")
        table = project_measurement_page(
            items,
            schema=schema,
            entry=entry,
            columns={column.name: column.variable_id for column in query.columns},
            units=query.units,
            diagnostics=query.diagnostics,
            include_identity=query.include_identity,
            layout=query.layout,
        )
        return table, next_offset, snapshot_size

    def save_analysis(
        self,
        *,
        run_id: str,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        executions: Sequence[AnalysisExecution],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis:
        return save_analysis(
            services=self.services,
            run_id=run_id,
            title=title,
            analysis_key=analysis_key,
            step_id=step_id,
            inputs=inputs,
            executions=executions,
            outputs=outputs,
            parameter_proposals=parameter_proposals,
        )

    def analyses(self, run_id: str) -> RunAnalysisListView:
        manifest = self.services.runs.read_manifest(run_id)
        return RunAnalysisListView(
            run_id=run_id,
            items=tuple(
                self.analysis(run_id, record.id)
                for record in list_records(manifest, kind="analysis")
            ),
        )

    def analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        result = read_run_record_json(
            run_id=run_id,
            selector=selector,
            expected_kind="analysis",
            services=self.services,
        )
        return RunAnalysisView(
            run_id=run_id,
            entry=result.record,
            analysis=AnalysisRecord.model_validate(result.content),
        )

    def attach(
        self,
        *,
        run_id: str,
        path: str | Path | None,
        key: str,
        kind: str,
        text: str | None,
        content: bytes | None,
        filename: str | None,
        media_type: str | None,
        metadata: Mapping[str, JsonValue] | None,
    ) -> RunContentEntry:
        return attach_run_artifact(
            services=self.services,
            run_id=run_id,
            path=path,
            key=key,
            kind=kind,
            text=text,
            content=content,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )

    def artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextResult:
        return read_run_artifact_text(
            run_id=run_id,
            services=self.services,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonResult:
        return read_run_artifact_json(
            run_id=run_id,
            services=self.services,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesResult:
        return read_run_artifact_bytes(
            run_id=run_id,
            services=self.services,
            selector=selector,
            expected_kind=expected_kind,
        )

    def record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonResult:
        return read_run_record_json(
            run_id=run_id,
            services=self.services,
            selector=selector,
            expected_kind=expected_kind,
        )
