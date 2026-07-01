"""Run facade handles for notebook workflows."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NoReturn, Protocol

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.client import Client, RunRef, run_id
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.run import RunManifest
from scopecat.run_comparison import RunComparisonView
from scopecat.runs.access import get_artifact_by_id, open_run_store
from scopecat.session_analysis import Analysis, AnalysisContext, AnalysisStep
from scopecat.session_data import Data
from scopecat.workflows import (
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    StartRunResult,
)

if TYPE_CHECKING:
    from scopecat.authoring import ExperimentDraft, ResolvedExperiment
    from scopecat.run_overview import RunOverview


class RunSession(Protocol):
    @property
    def client(self) -> Client: ...

    @property
    def reviewer(self) -> str: ...

    @property
    def operator(self) -> str: ...

    @property
    def workspace(self) -> Path: ...

    def overview(self, run: RunHandle | RunRef) -> RunOverview: ...

    def preview(
        self,
        experiment: ExperimentDraft,
    ) -> ResolvedExperiment: ...


@dataclass(frozen=True, init=False)
class RunHandle:
    """Typed handle for a run created by a session."""

    session: RunSession
    _manifest: RunManifest
    _result: StartRunResult | None

    def __init__(
        self,
        *,
        session: RunSession,
        result: StartRunResult | None = None,
        manifest: RunManifest | None = None,
    ) -> None:
        selected_manifest = result.manifest if result is not None else manifest
        if selected_manifest is None:
            _raise_diagnostic(
                "run_handle_manifest_missing",
                "run handle requires a run result or manifest",
                "run",
            )
        object.__setattr__(self, "session", session)
        object.__setattr__(self, "_manifest", selected_manifest)
        object.__setattr__(self, "_result", result)

    @property
    def result(self) -> StartRunResult:
        if self._result is None:
            _raise_diagnostic(
                "run_execution_snapshot_not_loaded",
                "run execution snapshot is not loaded for this workspace run handle",
                "run",
            )
        return self._result

    @property
    def id(self) -> str:
        return self.manifest.run_id

    @property
    def manifest(self) -> RunManifest:
        return self._manifest

    @property
    def resolved_experiment(self) -> ResolvedExperiment | None:
        if self._result is None:
            return None
        return self._result.resolved_experiment

    @property
    def data_ref(self) -> str | None:
        if self._result is not None:
            return self._result.data_ref
        artifact = get_artifact_by_id(self.manifest, "raw-measurements")
        return artifact.path if artifact is not None else None

    @property
    def artifacts(self) -> tuple[str, ...]:
        return tuple(self.session.client.artifacts(self.id))

    def measurements(
        self,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return self.session.client.measurements(self.id, selector=selector)

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
    ) -> Artifact:
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
        ref = f"artifacts/{selected_filename}"
        storage = open_run_store(self.session.workspace)
        if source_path is not None:
            storage.ref_path(self.id, ref).parent.mkdir(parents=True, exist_ok=True)
            storage.ref_path(self.id, ref).write_bytes(source_path.read_bytes())
        elif text is not None:
            storage.write_text(self.id, ref, text)
        elif content is not None:
            storage.ref_path(self.id, ref).parent.mkdir(parents=True, exist_ok=True)
            storage.ref_path(self.id, ref).write_bytes(content)
        artifact_metadata = dict(metadata or {})
        artifact_metadata.update(
            {
                "owner_type": "run",
                "owner_key": key,
                "attachment_key": key,
                "source_run_id": self.id,
            }
        )
        artifact = Artifact(
            id=key,
            kind=kind,
            path=ref,
            media_type=selected_media_type,
            metadata=artifact_metadata,
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
        return self.session.client.artifact_text(
            self.id,
            selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return self.session.client.artifact_json(
            self.id,
            selector,
            expected_kind=expected_kind,
        )

    def overview(self) -> RunOverview:
        return self.session.overview(self)

    def comparisons(self) -> tuple[RunComparisonView, ...]:
        return tuple(self.session.client.run_comparisons(self.id))


def run_handle_id(run: RunHandle | RunRef) -> str:
    if isinstance(run, RunHandle):
        return run.id
    return run_id(run)


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
