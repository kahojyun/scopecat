# pyright: reportUnknownMemberType=false, reportUnknownParameterType=false
# pyright: reportUnknownVariableType=false
"""Run facade handles for notebook workflows."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, overload

import pyarrow as pa
from pydantic import JsonValue

from scopecat.analysis.datasets import DerivedDataset, DerivedDatasetSchema
from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    SavedAnalysis,
)
from scopecat.api.analysis import (
    Analysis,
    AnalysisContext,
    AnalysisOutcome,
    AnalysisStep,
)
from scopecat.api.data import Data
from scopecat.api.published_analysis import PublishedAnalysis
from scopecat.daemon.views import (
    MeasurementArrowColumn,
    MeasurementArrowQuery,
    MeasurementPage,
    RunAnalysisListView,
    RunAnalysisView,
)
from scopecat.kernel.ids import artifact_slug
from scopecat.measurements.datasets import (
    MAX_MEASUREMENT_PAGE_SIZE,
    MEASUREMENT_DATASET_KIND,
    RAW_MEASUREMENTS_DATASET_ID,
)
from scopecat.measurements.results import (
    Dataset,
    ExperimentResultView,
    MeasurementDataset,
    MeasurementDatasetSchema,
    ProjectionDiagnostics,
    ProjectionLayout,
    StoredExperimentResultView,
)
from scopecat.program.products import ProductRef
from scopecat.program.record_refs import RecordRef
from scopecat.program.value_refs import ValueRef
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.access import require_dataset
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDatasetBytesResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.selectors import RunSelector, selected_run_id


class RunOperations(Protocol):
    """Storage-neutral operations used by run and data handles."""

    def load_manifest(self, run_id: str) -> RunManifest: ...

    def load_config(self, run_id: str) -> ConfigProfileSnapshot: ...

    def load_request(self, run_id: str) -> RunRequest: ...

    def load_measurement_dataset(
        self,
        run_id: str,
        *,
        selector: str,
    ) -> RunMeasurementDatasetResult: ...

    def load_dataset_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunDatasetBytesResult: ...

    def load_measurement_page(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> MeasurementPage: ...

    def load_measurement_arrow_page(
        self,
        run_id: str,
        *,
        query: MeasurementArrowQuery,
    ) -> tuple[pa.Table, int | None, int]: ...

    def save_analysis(
        self,
        *,
        run_id: str,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis: ...

    def analyses(self, run_id: str) -> RunAnalysisListView: ...

    def analysis(self, run_id: str, selector: str) -> RunAnalysisView: ...

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
    ) -> RunContentEntry: ...

    def artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextResult: ...

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonResult: ...

    def artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesResult: ...

    def record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonResult: ...


class RunSession(Protocol):
    @property
    def run_operations(self) -> RunOperations: ...


@dataclass(frozen=True)
class RunHandle:
    """Typed handle for a run created by a session."""

    session: RunSession
    id: str

    @property
    def manifest(self) -> RunManifest:
        """Load the current durable manifest for this run."""

        return self.session.run_operations.load_manifest(self.id)

    @property
    def config(self) -> ConfigProfileSnapshot:
        return self.session.run_operations.load_config(self.id)

    @property
    def request(self) -> RunRequest:
        """Load the operator request accepted with this run."""

        return self.session.run_operations.load_request(self.id)

    @property
    def artifacts(self) -> tuple[str, ...]:
        return tuple(artifact.id for artifact in self.manifest.artifacts)

    @property
    def datasets(self) -> tuple[str, ...]:
        return tuple(dataset.id for dataset in self.manifest.datasets)

    def measurements(
        self,
        *,
        selector: str = "raw-measurements",
    ) -> Dataset:
        """Load one labeled measurement dataset for notebook analysis."""

        loaded = self.session.run_operations.load_measurement_dataset(
            self.id,
            selector=selector,
        )
        return Dataset(raw=loaded.dataset, entry=loaded.dataset_entry)

    def derived_dataset(self, selector: str) -> DerivedDataset:
        """Load one analysis-authored dataset into its exact Arrow schema."""

        loaded = self.session.run_operations.load_dataset_bytes(
            self.id,
            selector,
            expected_kind="analysis_dataset",
        )
        if loaded.dataset.data_schema is None:
            raise ValueError("analysis dataset is missing its semantic schema")
        return DerivedDataset.from_arrow_ipc(
            loaded.content,
            schema=DerivedDatasetSchema.model_validate(loaded.dataset.data_schema),
        )

    @overload
    def result(
        self,
        /,
        *,
        selector: str = "raw-measurements",
    ) -> StoredExperimentResultView: ...

    @overload
    def result[ResultT](
        self,
        output: ResultT,
        /,
        *,
        selector: str = "raw-measurements",
    ) -> ExperimentResultView[ResultT]: ...

    def result[ResultT](
        self,
        output: ResultT | None = None,
        /,
        *,
        selector: str = "raw-measurements",
    ) -> StoredExperimentResultView | ExperimentResultView[ResultT]:
        """Load the experiment return value as a historical or typed result."""

        dataset = self.measurements(selector=selector)
        if output is None:
            return dataset.result
        return dataset.bind(output)

    def measurement_batches(self, *, batch_size: int = 100) -> Iterator[Dataset]:
        """Iterate over raw measurements without loading the complete dataset.

        Every yielded dataset keeps durable ``point_index`` values while its
        ``point`` dimension describes only the records in that batch. Its schema
        remains the complete planned dataset schema.
        """

        if not 1 <= batch_size <= MAX_MEASUREMENT_PAGE_SIZE:
            raise ValueError(
                "measurement batch_size must be between 1 and "
                f"{MAX_MEASUREMENT_PAGE_SIZE}"
            )
        return self._measurement_batches(batch_size=batch_size)

    def _measurement_batches(self, *, batch_size: int) -> Iterator[Dataset]:
        entry = require_dataset(
            manifest=self.manifest,
            selector=RAW_MEASUREMENTS_DATASET_ID,
            expected_kind=MEASUREMENT_DATASET_KIND,
        )
        offset = 0
        while True:
            page = self.session.run_operations.load_measurement_page(
                self.id,
                limit=batch_size,
                offset=offset,
            )
            schema = page.dataset_schema
            if schema is None:
                raise ValueError("measurement dataset page has no registered schema")
            yield Dataset(
                raw=MeasurementDataset(
                    dataset_schema=schema,
                    records=list(page.items),
                    metadata={
                        **entry.metadata,
                        "scopecat_batch_offset": offset,
                    },
                ),
                entry=entry,
            )
            if page.next_offset is None:
                return
            if page.next_offset <= offset:
                raise ValueError("measurement page next_offset must advance")
            offset = page.next_offset

    def measurement_record_batches(
        self,
        *,
        columns: Mapping[
            str,
            str | ProductRef | RecordRef | ValueRef[object],
        ]
        | None = None,
        units: Mapping[str, str] | None = None,
        diagnostics: ProjectionDiagnostics = "reason",
        include_identity: bool = True,
        layout: ProjectionLayout = "points",
        batch_size: int = 100,
    ) -> pa.RecordBatchReader:
        """Read a finite run through one server-projected Arrow stream."""

        if not 1 <= batch_size <= MAX_MEASUREMENT_PAGE_SIZE:
            raise ValueError(
                "measurement batch_size must be between 1 and "
                f"{MAX_MEASUREMENT_PAGE_SIZE}"
            )
        query = self._measurement_arrow_query(
            columns=columns,
            units=units,
            diagnostics=diagnostics,
            include_identity=include_identity,
            layout=layout,
            batch_size=batch_size,
        )
        first, next_offset, snapshot_size = (
            self.session.run_operations.load_measurement_arrow_page(
                self.id,
                query=query,
            )
        )

        def batches() -> Iterator[pa.RecordBatch]:
            yield from first.to_batches(max_chunksize=batch_size)
            offset = next_offset
            previous_offset = query.offset
            while offset is not None:
                if offset <= previous_offset:
                    raise ValueError("measurement Arrow page next_offset must advance")
                table, following_offset, page_snapshot_size = (
                    self.session.run_operations.load_measurement_arrow_page(
                        self.id,
                        query=query.model_copy(
                            update={
                                "offset": offset,
                                "snapshot_size": snapshot_size,
                            }
                        ),
                    )
                )
                if page_snapshot_size != snapshot_size:
                    raise ValueError("measurement Arrow snapshot changed between pages")
                if table.schema != first.schema:
                    raise ValueError("measurement pages produced different projections")
                yield from table.to_batches(max_chunksize=batch_size)
                previous_offset = offset
                offset = following_offset

        return pa.RecordBatchReader.from_batches(first.schema, batches())

    def _measurement_arrow_query(
        self,
        *,
        columns: Mapping[
            str,
            str | ProductRef | RecordRef | ValueRef[object],
        ]
        | None,
        units: Mapping[str, str] | None,
        diagnostics: ProjectionDiagnostics,
        include_identity: bool,
        layout: ProjectionLayout,
        batch_size: int,
    ) -> MeasurementArrowQuery:
        entry = require_dataset(
            manifest=self.manifest,
            selector=RAW_MEASUREMENTS_DATASET_ID,
            expected_kind=MEASUREMENT_DATASET_KIND,
        )
        if entry.data_schema is None:
            raise ValueError("measurement dataset has no registered schema")
        schema = MeasurementDatasetSchema.model_validate(entry.data_schema)
        projection = Dataset(
            raw=MeasurementDataset(
                dataset_schema=schema,
                records=(),
                metadata=entry.metadata,
            ),
            entry=entry,
        ).project(
            columns,
            units=units,
            diagnostics=diagnostics,
            identity=include_identity,
            layout=layout,
        )
        return MeasurementArrowQuery(
            columns=tuple(
                MeasurementArrowColumn(
                    name=field.name,
                    variable_id=field.variable_id,
                )
                for field in projection.schema.fields
            ),
            units=dict(units or {}),
            diagnostics=diagnostics,
            include_identity=include_identity,
            layout=layout,
            limit=batch_size,
        )

    def data(self) -> Data:
        return Data(run=self)

    def analysis(
        self,
        title: str,
        *,
        key: str | None = None,
        step_id: str | None = None,
    ) -> Analysis:
        """Start an exploratory analysis draft that the caller may save."""

        return Analysis(run=self, title=title, key=key, step_id=step_id)

    def published_analyses(self) -> tuple[PublishedAnalysis, ...]:
        """Load every durable analysis publication in manifest order."""

        return tuple(
            PublishedAnalysis(run=self, view=view)
            for view in self.session.run_operations.analyses(self.id).items
        )

    def published_analysis(self, selector: str) -> PublishedAnalysis:
        """Load an exact analysis record ID or the latest matching logical key."""

        analyses = self.published_analyses()
        exact = next(
            (analysis for analysis in analyses if analysis.id == selector),
            None,
        )
        if exact is not None:
            return exact
        selected_key = artifact_slug(selector, fallback="analysis")
        matches = tuple(
            analysis for analysis in analyses if analysis.key == selected_key
        )
        if not matches:
            raise KeyError(f"run has no published analysis: {selector}")
        return matches[-1]

    def save_analysis(
        self,
        *,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis:
        """Persist analysis through this run's owning execution boundary."""

        return self.session.run_operations.save_analysis(
            run_id=self.id,
            title=title,
            analysis_key=analysis_key,
            step_id=step_id,
            inputs=inputs,
            outputs=outputs,
            parameter_proposals=parameter_proposals,
        )

    def analyze(
        self,
        step: AnalysisStep,
        *,
        key: str | None = None,
    ) -> AnalysisOutcome:
        """Run and durably publish one declared analysis step."""

        analysis = step.run(
            AnalysisContext(
                run=self,
                default_key=key or step.id,
                step_id=step.id,
            )
        )
        if analysis.key is None or analysis.step_id is None:
            analysis = replace(
                analysis,
                key=analysis.key or key or step.id,
                step_id=analysis.step_id or step.id,
            )
        return analysis.save()

    def attach(
        self,
        path: str | Path | None = None,
        *,
        key: str,
        kind: str = "attachment",
        text: str | None = None,
        content: bytes | None = None,
        filename: str | None = None,
        media_type: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> RunContentEntry:
        return self.session.run_operations.attach(
            run_id=self.id,
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
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        return self.session.run_operations.artifact_text(
            self.id,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_bytes(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesResult:
        return self.session.run_operations.artifact_bytes(
            self.id,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return self.session.run_operations.artifact_json(
            self.id,
            selector=selector,
            expected_kind=expected_kind,
        )

    def record_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunRecordJsonResult:
        return self.session.run_operations.record_json(
            self.id,
            selector=selector,
            expected_kind=expected_kind,
        )


def run_handle_id(run: RunHandle | RunSelector) -> str:
    if isinstance(run, RunHandle):
        return run.id
    return selected_run_id(run)
