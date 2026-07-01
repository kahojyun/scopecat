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
from scopecat.workflows.runs import (
    load_run,
    read_run_artifact_bytes,
    read_run_data_array,
    read_run_data_table,
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

    def plan_preview(self) -> PlanSnapshot:
        return self.run.plan

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


__all__ = ["Data"]
