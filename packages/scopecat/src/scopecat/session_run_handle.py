"""Run facade handles for notebook workflows."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NoReturn, Protocol

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat._storage.local.io import ensure_durable_directory
from scopecat._storage.refs import artifact_content_ref
from scopecat._workflows.comparison import list_run_comparisons
from scopecat._workflows.runs import (
    list_run_artifacts,
    load_run,
    load_run_config,
    load_run_plan,
    load_run_request,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_measurement_dataset,
    read_run_record_json,
)
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import RunArtifactEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunManifest
from scopecat.models.run_plan import RunPlanRecord
from scopecat.models.run_request import RunRequest
from scopecat.run_comparison import RunComparisonView
from scopecat.run_data import (
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.run_selectors import RunSelector, selected_run_id
from scopecat.runs.access import open_run_store
from scopecat.session_analysis import Analysis, AnalysisContext, AnalysisStep
from scopecat.session_data import Data

if TYPE_CHECKING:
    from scopecat.run_overview import RunOverview


class RunSession(Protocol):
    @property
    def reviewer(self) -> str: ...

    @property
    def operator(self) -> str: ...

    @property
    def workspace(self) -> Path: ...

    def overview(self, run: RunHandle | RunSelector) -> RunOverview: ...


@dataclass(frozen=True)
class RunHandle:
    """Typed handle for a run created by a session."""

    session: RunSession
    manifest: RunManifest

    @property
    def id(self) -> str:
        return self.manifest.run_id

    @property
    def config(self) -> ConfigProfileSnapshot:
        return load_run_config(
            run_id=self.id,
            workspace=self.session.workspace,
        )

    @property
    def request(self) -> RunRequest | None:
        """Load the independently persisted operator request, when present."""

        return load_run_request(
            run_id=self.id,
            workspace=self.session.workspace,
        )

    @property
    def plan(self) -> RunPlanRecord:
        """Load the independently persisted accepted-plan evidence."""

        return load_run_plan(
            run_id=self.id,
            workspace=self.session.workspace,
        )

    @property
    def artifacts(self) -> tuple[str, ...]:
        return tuple(
            artifact.id
            for artifact in list_run_artifacts(
                run_id=self.id,
                workspace=self.session.workspace,
            )
        )

    @property
    def datasets(self) -> tuple[str, ...]:
        return tuple(
            dataset.id
            for dataset in load_run(
                run_id=self.id,
                workspace=self.session.workspace,
            ).manifest.datasets
        )

    def measurements(
        self,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return read_run_measurement_dataset(
            run_id=self.id,
            workspace=self.session.workspace,
            selector=selector,
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
        return Analysis(run=self, title=title, key=key, step_id=step_id)

    def analyze(self, step: AnalysisStep, *, key: str | None = None) -> Analysis:
        analysis = step.run(
            AnalysisContext(
                run=self,
                data=self.data(),
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
        return analysis

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
        metadata: dict[str, object] | None = None,
    ) -> RunArtifactEntry:
        selected_sources = [path is not None, text is not None, content is not None]
        if selected_sources.count(True) != 1:
            _raise_diagnostic(
                "run_attachment_source_invalid",
                "run attachment requires exactly one of path, text, or content",
                "attachment",
            )
        if not key.strip():
            _raise_diagnostic(
                "run_attachment_key_invalid",
                "run attachment key must be a non-empty string",
                "key",
            )
        if not kind.strip():
            _raise_diagnostic(
                "run_attachment_kind_invalid",
                "run attachment kind must be a non-empty string",
                "kind",
            )
        source_path: Path | None = None
        if path is not None:
            source_path = Path(path)
            if not source_path.is_file():
                _raise_diagnostic(
                    "run_attachment_source_missing",
                    f"run attachment source file is missing: {source_path}",
                    "path",
                )
        selected_filename = filename or _default_attachment_filename(
            key=key,
            source_path=source_path,
            text=text,
        )
        if not _is_artifact_filename(selected_filename):
            _raise_diagnostic(
                "run_attachment_filename_invalid",
                f"run attachment filename must be a basename: {selected_filename}",
                "filename",
            )
        selected_media_type = media_type or _attachment_media_type(
            filename=selected_filename,
            text=text,
        )
        ref = artifact_content_ref(artifact_id=key, kind=kind)
        storage = open_run_store(self.session.workspace)
        if source_path is not None:
            ensure_durable_directory(storage.ref_path(self.id, ref).parent)
            storage.ref_path(self.id, ref).write_bytes(source_path.read_bytes())
        elif text is not None:
            storage.write_text(self.id, ref, text)
        elif content is not None:
            ensure_durable_directory(storage.ref_path(self.id, ref).parent)
            storage.ref_path(self.id, ref).write_bytes(content)
        artifact = RunArtifactEntry(
            id=key,
            kind=kind,
            media_type=selected_media_type,
            produced_by="run.attach",
            metadata=dict(metadata or {}),
        )
        write_manifest_artifacts(
            storage=storage,
            manifest=storage.read_manifest(self.id),
            artifacts=[artifact],
        )
        return artifact

    def artifact_text(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        return read_run_artifact_text(
            run_id=self.id,
            workspace=self.session.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return read_run_artifact_json(
            run_id=self.id,
            workspace=self.session.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def record_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunRecordJsonResult:
        return read_run_record_json(
            run_id=self.id,
            workspace=self.session.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def overview(self) -> RunOverview:
        return self.session.overview(self)

    def comparisons(self) -> tuple[RunComparisonView, ...]:
        return tuple(
            list_run_comparisons(run_id=self.id, workspace=self.session.workspace)
        )


def run_handle_id(run: RunHandle | RunSelector) -> str:
    if isinstance(run, RunHandle):
        return run.id
    return selected_run_id(run)


def _raise_diagnostic(code: str, message: str, path: str) -> NoReturn:
    raise ValidationFailed(
        [
            Diagnostic(
                severity="error",
                code=code,
                message=message,
                path=path,
            )
        ]
    )


def _default_attachment_filename(
    *,
    key: str,
    source_path: Path | None,
    text: str | None,
) -> str:
    if source_path is not None:
        return source_path.name
    suffix = ".txt" if text is not None else ".bin"
    return f"{_attachment_slug(key)}{suffix}"


def _attachment_media_type(*, filename: str, text: str | None) -> str:
    guessed, _encoding = mimetypes.guess_type(filename)
    if guessed is not None:
        return guessed
    if text is not None:
        return "text/plain"
    return "application/octet-stream"


def _attachment_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _is_artifact_filename(filename: str) -> bool:
    if not filename or "\\" in filename:
        return False
    path = PurePosixPath(filename)
    return path.name == filename and not path.is_absolute() and ".." not in path.parts


__all__ = ["RunHandle", "RunSession", "run_handle_id"]
