"""Run facade handles for notebook workflows."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, overload

from pydantic import JsonValue

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
from scopecat.daemon.views import MeasurementPage
from scopecat.measurements.datasets import (
    MAX_MEASUREMENT_PAGE_SIZE,
    MEASUREMENT_DATASET_KIND,
    RAW_MEASUREMENTS_DATASET_ID,
)
from scopecat.measurements.results import (
    Dataset,
    ExperimentResultView,
    MeasurementDataset,
    StoredExperimentResultView,
)
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

    def load_measurement_page(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> MeasurementPage: ...

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
