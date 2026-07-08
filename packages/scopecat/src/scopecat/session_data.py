"""Run data facade objects for notebook workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scopecat._workflows.runs import (
    load_run,
    read_run_artifact_bytes,
    read_run_data_array,
    read_run_data_table,
)
from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry
from scopecat.models.run import RunManifest
from scopecat.results import MeasurementDatasetSchema
from scopecat.run_data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunMeasurementDatasetResult,
)
from scopecat.runs.access import list_payload_entries, require_artifact, require_dataset

if TYPE_CHECKING:
    from scopecat.session_run_handle import RunHandle


@dataclass(frozen=True)
class DataDatasetSummary:
    id: str
    kind: str
    role: str | None
    record_count: int | None
    coordinate_ids: tuple[str, ...]
    observable_ids: tuple[str, ...]
    dimensions: dict[str, int]
    metadata: dict[str, object]


@dataclass(frozen=True)
class DataSummary:
    datasets: tuple[DataDatasetSummary, ...]
    artifacts: tuple[RunArtifactEntry, ...]


@dataclass(frozen=True)
class Data:
    """Notebook-facing data access for one run."""

    run: RunHandle

    @property
    def artifacts(self) -> tuple[str, ...]:
        return self.run.artifacts

    @property
    def datasets(self) -> tuple[str, ...]:
        return self.run.datasets

    def list(
        self,
        *,
        kind: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> tuple[RunArtifactEntry | RunDatasetEntry, ...]:
        return list_payload_entries(self._manifest(), kind=kind, metadata=metadata)

    def artifact(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactEntry:
        return require_artifact(
            manifest=self._manifest(),
            selector=selector,
            expected_kind=expected_kind,
        )

    def dataset(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunDatasetEntry:
        return require_dataset(
            manifest=self._manifest(),
            selector=selector,
            expected_kind=expected_kind,
        )

    def measurements(
        self,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return self.run.measurements(selector=selector)

    def schema(self, selector: str = "raw-measurements") -> MeasurementDatasetSchema:
        return self.measurements(selector).dataset.dataset_schema

    def metadata(self, selector: str = "raw-measurements") -> dict[str, object]:
        return dict(self.measurements(selector).dataset.metadata)

    def summary(self, selector: str | None = None) -> DataSummary | DataDatasetSummary:
        if selector is not None:
            return self._dataset_summary(self.dataset(selector))
        manifest = self._manifest()
        return DataSummary(
            datasets=tuple(
                self._dataset_summary(dataset) for dataset in manifest.datasets
            ),
            artifacts=tuple(manifest.artifacts),
        )

    def table(self, selector: str) -> RunDataTableResult:
        return read_run_data_table(
            run_id=self.run.id,
            workspace=self.run.session.workspace,
            selector=selector,
        )

    def array(self, selector: str) -> RunDataArrayResult:
        return read_run_data_array(
            run_id=self.run.id,
            workspace=self.run.session.workspace,
            selector=selector,
        )

    def figure(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesResult:
        artifact = self.artifact(selector)
        if expected_kind is not None:
            self.artifact(selector, expected_kind=expected_kind)
        elif artifact.kind not in {"figure", "plot"}:
            self.artifact(selector, expected_kind="figure")
        return read_run_artifact_bytes(
            run_id=self.run.id,
            workspace=self.run.session.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def text(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        return self.run.artifact_text(selector, expected_kind=expected_kind)

    def json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return self.run.artifact_json(selector, expected_kind=expected_kind)

    def bytes(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesResult:
        return read_run_artifact_bytes(
            run_id=self.run.id,
            workspace=self.run.session.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def _manifest(self) -> RunManifest:
        return load_run(
            run_id=self.run.id,
            workspace=self.run.session.workspace,
        ).manifest

    def _dataset_summary(self, dataset: RunDatasetEntry) -> DataDatasetSummary:
        if dataset.kind != "measurement_dataset":
            return DataDatasetSummary(
                id=dataset.id,
                kind=dataset.kind,
                role=dataset.role,
                record_count=None,
                coordinate_ids=(),
                observable_ids=(),
                dimensions={},
                metadata=dict(dataset.metadata),
            )
        measurements = self.measurements(dataset.id)
        schema = measurements.dataset.dataset_schema
        return DataDatasetSummary(
            id=dataset.id,
            kind=dataset.kind,
            role=dataset.role,
            record_count=len(measurements.dataset.records),
            coordinate_ids=tuple(schema.primary_coordinates),
            observable_ids=tuple(schema.primary_observables),
            dimensions={
                dimension.id: dimension.size
                for dimension in schema.dimensions
                if dimension.size is not None
            },
            metadata={
                **dict(dataset.metadata),
                **dict(measurements.dataset.metadata),
            },
        )


__all__ = ["Data", "DataDatasetSummary", "DataSummary"]
