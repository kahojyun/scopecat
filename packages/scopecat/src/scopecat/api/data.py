"""Run data facade objects for notebook workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scopecat.measurements.results import MeasurementDatasetSchema
from scopecat.records.artifact import RunContentEntry
from scopecat.records.run import RunManifest
from scopecat.runs.access import list_payload_entries, require_artifact, require_dataset
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunMeasurementDatasetResult,
)

if TYPE_CHECKING:
    from scopecat.api.run import RunHandle


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
    ) -> tuple[RunContentEntry, ...]:
        return list_payload_entries(self._manifest(), kind=kind, metadata=metadata)

    def artifact(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunContentEntry:
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
    ) -> RunContentEntry:
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

    def table(self, selector: str) -> RunDataTableResult:
        return self.run.session.run_operations.data_table(self.run.id, selector)

    def array(self, selector: str) -> RunDataArrayResult:
        return self.run.session.run_operations.data_array(self.run.id, selector)

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
        return self.run.session.run_operations.artifact_bytes(
            self.run.id,
            selector,
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
        return self.run.session.run_operations.artifact_bytes(
            self.run.id,
            selector,
            expected_kind=expected_kind,
        )

    def _manifest(self) -> RunManifest:
        return self.run.manifest
