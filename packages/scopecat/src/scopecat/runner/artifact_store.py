"""Runner adapter artifact allocation API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from scopecat._storage import ARTIFACTS_DIR
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.models.artifact import Artifact
from scopecat.runner.constants import (
    RUNNER_ADAPTER_RAW_MEASUREMENTS_ARTIFACT_ID,
    RUNNER_ADAPTER_RAW_MEASUREMENTS_FILENAME,
    RUNNER_ADAPTER_SNAPSHOT_FILENAME,
)


@dataclass(frozen=True)
class RunnerArtifactHandle:
    """Adapter-owned artifact file allocated by Scopecat."""

    id: str
    kind: str
    filename: str
    path: Path
    media_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _RunnerArtifactRegistration:
    handle: RunnerArtifactHandle
    valid: bool


class RunnerArtifactWriter(Protocol):
    """Artifact writer surface exposed to runner adapters."""

    def reserve_file(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        media_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunnerArtifactHandle: ...

    def write_text(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        content: str,
        media_type: str | None = "text/plain",
        metadata: dict[str, Any] | None = None,
    ) -> RunnerArtifactHandle: ...

    def write_bytes(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        content: bytes,
        media_type: str | None = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> RunnerArtifactHandle: ...


class RunnerArtifactStore:
    """Internal adapter artifact store used by execution."""

    def __init__(self, *, artifacts_dir: Path) -> None:
        self._artifacts_dir = artifacts_dir
        self._registrations: list[_RunnerArtifactRegistration] = []
        self._diagnostics: list[Diagnostic] = []
        self._seen_ids = {
            RUNNER_ADAPTER_RAW_MEASUREMENTS_ARTIFACT_ID,
            "runner-adapter-snapshot",
        }
        self._seen_filenames = {
            RUNNER_ADAPTER_RAW_MEASUREMENTS_FILENAME,
            RUNNER_ADAPTER_SNAPSHOT_FILENAME,
        }

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(self._diagnostics)

    @property
    def artifacts(self) -> tuple[Artifact, ...]:
        artifacts: list[Artifact] = []
        for registration in self._registrations:
            handle = registration.handle
            if not registration.valid or not handle.path.is_file():
                continue
            artifacts.append(
                Artifact(
                    id=handle.id,
                    kind=handle.kind,
                    path=f"{ARTIFACTS_DIR}/{handle.filename}",
                    media_type=handle.media_type,
                    metadata=handle.metadata,
                )
            )
        return tuple(artifacts)

    def reserve_file(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        media_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunnerArtifactHandle:
        registration = self._register(
            id=id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )
        return registration.handle

    def write_text(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        content: str,
        media_type: str | None = "text/plain",
        metadata: dict[str, Any] | None = None,
    ) -> RunnerArtifactHandle:
        registration = self._register(
            id=id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )
        if registration.valid:
            registration.handle.path.write_text(content)
        return registration.handle

    def write_bytes(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        content: bytes,
        media_type: str | None = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> RunnerArtifactHandle:
        registration = self._register(
            id=id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )
        if registration.valid:
            registration.handle.path.write_bytes(content)
        return registration.handle

    def _register(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        media_type: str | None,
        metadata: dict[str, Any] | None,
    ) -> _RunnerArtifactRegistration:
        diagnostics = self._registration_diagnostics(
            id=id,
            kind=kind,
            filename=filename,
        )
        valid = not diagnostics
        handle = RunnerArtifactHandle(
            id=id,
            kind=kind,
            filename=filename,
            path=self._handle_path(filename=filename, valid=valid),
            media_type=media_type,
            metadata=dict(metadata or {}),
        )
        registration = _RunnerArtifactRegistration(handle=handle, valid=valid)
        self._registrations.append(registration)
        if valid:
            self._seen_ids.add(id)
            self._seen_filenames.add(filename)
            handle.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._diagnostics.extend(diagnostics)
        return registration

    def _registration_diagnostics(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        if not id:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "runner_adapter_artifact_missing_id",
                    "runner adapter artifact id must be non-empty",
                    "artifacts.id",
                )
            )
        elif id in self._seen_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "runner_adapter_duplicate_artifact",
                    f"runner adapter artifact id is duplicated: {id}",
                    f"artifacts.{id}",
                )
            )
        if not kind:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "runner_adapter_artifact_missing_kind",
                    "runner adapter artifact kind must be non-empty",
                    f"artifacts.{id}.kind" if id else "artifacts.kind",
                )
            )
        if not _is_artifact_filename(filename):
            diagnostics.append(
                _diagnostic(
                    "error",
                    "runner_adapter_invalid_artifact_filename",
                    f"runner adapter artifact filename must be a basename: {filename}",
                    f"artifacts.{id}.filename" if id else "artifacts.filename",
                )
            )
        elif filename in self._seen_filenames:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "runner_adapter_duplicate_artifact_filename",
                    f"runner adapter artifact filename is duplicated: {filename}",
                    f"artifacts.{id}.filename" if id else "artifacts.filename",
                )
            )
        return diagnostics

    def _handle_path(self, *, filename: str, valid: bool) -> Path:
        if valid:
            return self._artifacts_dir / filename
        fallback = f"_invalid-runner-artifact-{len(self._registrations):04d}"
        return self._artifacts_dir / fallback


def _is_artifact_filename(filename: str) -> bool:
    if not filename or "\\" in filename:
        return False
    path = PurePosixPath(filename)
    return path.name == filename and not path.is_absolute() and ".." not in path.parts


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
