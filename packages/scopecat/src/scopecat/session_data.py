"""Run data facade objects for notebook workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scopecat.experiments import PlanSnapshot
from scopecat.models.artifact import Artifact
from scopecat.models.run import RunManifest
from scopecat.runs.access import list_artifacts, require_artifact
from scopecat.workflows import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunMeasurementDatasetResult,
)

if TYPE_CHECKING:
    from scopecat.session_run_handle import RunHandle


@dataclass(frozen=True)
class Data:
    """Notebook-facing data access for one run."""

    run: RunHandle

    @property
    def artifacts(self) -> tuple[str, ...]:
        return self.run.artifacts

    def list(
        self,
        *,
        kind: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> tuple[Artifact, ...]:
        return list_artifacts(self._manifest(), kind=kind, metadata=metadata)

    def artifact(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> Artifact:
        return require_artifact(
            manifest=self._manifest(),
            selector=selector,
            expected_kind=expected_kind,
        )

    def measurements(
        self,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return self.run.measurements(selector=selector)

    def table(self, selector: str) -> RunDataTableResult:
        return self.run.session.client.data_table(self.run.id, selector)

    def array(self, selector: str) -> RunDataArrayResult:
        return self.run.session.client.data_array(self.run.id, selector)

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
        return self.run.session.client.artifact_bytes(
            self.run.id,
            selector,
            expected_kind=expected_kind,
        )

    def plan_preview(self) -> PlanSnapshot:
        return self.run.session.client.run_details(self.run.id).plan

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
        return self.run.session.client.artifact_bytes(
            self.run.id,
            selector,
            expected_kind=expected_kind,
        )

    def _manifest(self) -> RunManifest:
        return self.run.session.client.run_details(self.run.id).manifest


__all__ = ["Data"]
