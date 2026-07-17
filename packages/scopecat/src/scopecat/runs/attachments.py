"""Run attachment ingestion use case."""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import NoReturn

from pydantic import JsonValue

from scopecat.application.services import WorkspaceServices
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    LocationPathItem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.records.artifact import RunArtifactEntry
from scopecat.runs.manifest import write_manifest_artifacts
from scopecat.runs.refs import artifact_content_ref


def attach_run_artifact(
    *,
    services: WorkspaceServices,
    run_id: str,
    path: str | Path | None = None,
    key: str,
    kind: str = "attachment",
    text: str | None = None,
    content: bytes | None = None,
    filename: str | None = None,
    media_type: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> RunArtifactEntry:
    """Validate and ingest one user-owned attachment into a run."""

    selected_sources = [path is not None, text is not None, content is not None]
    if selected_sources.count(True) != 1:
        _raise_run_problem(
            "run_attachment_source_invalid",
            "run attachment requires exactly one of path, text, or content",
            "attachment",
        )
    if not key.strip():
        _raise_run_problem(
            "run_attachment_key_invalid",
            "run attachment key must be a non-empty string",
            "key",
        )
    if not kind.strip():
        _raise_run_problem(
            "run_attachment_kind_invalid",
            "run attachment kind must be a non-empty string",
            "kind",
        )
    source_path: Path | None = None
    if path is not None:
        source_path = Path(path)
        if not source_path.is_file():
            _raise_run_problem(
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
        _raise_run_problem(
            "run_attachment_filename_invalid",
            f"run attachment filename must be a basename: {selected_filename}",
            "filename",
        )
    selected_media_type = media_type or _attachment_media_type(
        filename=selected_filename,
        text=text,
    )
    ref = artifact_content_ref(artifact_id=key, kind=kind)
    storage = services.runs
    if source_path is not None:
        storage.write_bytes(run_id, ref, source_path.read_bytes())
    elif text is not None:
        storage.write_text(run_id, ref, text)
    elif content is not None:
        storage.write_bytes(run_id, ref, content)
    artifact = RunArtifactEntry(
        id=key,
        kind=kind,
        media_type=selected_media_type,
        produced_by="run.attach",
        metadata=dict(metadata or {}),
    )
    write_manifest_artifacts(
        storage=storage,
        manifest=storage.read_manifest(run_id),
        artifacts=[artifact],
    )
    return artifact


def _raise_run_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> NoReturn:
    raise CheckFailed(
        [
            blocking_problem(
                code,
                message,
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.ANALYSIS,
                location=model_location("run_attachment", *path),
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
