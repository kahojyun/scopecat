"""Internal local run storage layout."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scopecat.kernel.errors import CheckFailed, DataIntegrityError, StorageError
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    StorageLocation,
)
from scopecat.runs.refs import ARTIFACTS_DIR, RUNS_DIR

SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class FilesystemRunLayout:
    """Path calculation and run-relative ref validation for local storage."""

    workspace: Path

    @classmethod
    def from_workspace(cls, workspace: str | Path) -> FilesystemRunLayout:
        return cls(workspace=Path(workspace))

    @property
    def runs_root(self) -> Path:
        return self.workspace / RUNS_DIR

    def validated_runs_root(self) -> Path:
        """Return the run root after proving it remains inside the workspace."""

        _resolve_in_workspace(
            workspace=self.workspace,
            candidate=self.runs_root,
            ref=RUNS_DIR,
        )
        return self.runs_root

    def workspace_ref_path(self, ref: str) -> Path:
        """Resolve a workspace ref without permitting symlink escape."""

        relative = _validate_run_relative_ref(ref)
        candidate = self.workspace / relative.as_posix()
        _resolve_in_workspace(
            workspace=self.workspace,
            candidate=candidate,
            ref=ref,
        )
        return candidate

    def run_dir(self, run_id: str) -> Path:
        _validate_run_id(run_id)
        return self.runs_root / run_id

    def artifacts_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / ARTIFACTS_DIR

    def ref_path(self, run_id: str, ref: str) -> Path:
        relative = _validate_run_relative_ref(ref)
        candidate = self.run_dir(run_id) / relative.as_posix()
        run_root = _resolve_in_workspace(
            workspace=self.workspace,
            candidate=self.run_dir(run_id),
            run_id=run_id,
            ref=ref,
        )
        resolved = _resolve_storage_path(candidate, run_id=run_id, ref=ref)
        try:
            resolved.relative_to(run_root)
        except ValueError as error:
            raise _path_escape(ref) from error
        return candidate

    def display_run_path(self, run_id: str) -> Path:
        return self.run_dir(run_id)

    def display_ref_path(self, run_id: str, ref: str) -> Path:
        return self.ref_path(run_id, ref)


def _validate_run_relative_ref(ref: str) -> PurePosixPath:
    relative = PurePosixPath(ref)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise _path_escape(ref)
    return relative


def _resolve_in_workspace(
    *,
    workspace: Path,
    candidate: Path,
    ref: str,
    run_id: str | None = None,
) -> Path:
    workspace_root = _resolve_storage_path(workspace, run_id=run_id, ref=ref)
    resolved = _resolve_storage_path(candidate, run_id=run_id, ref=ref)
    try:
        resolved.relative_to(workspace_root)
    except ValueError as error:
        raise DataIntegrityError(
            [
                Problem(
                    code="storage.namespace_escape",
                    impact=ProblemImpact.BLOCKING,
                    category=ProblemCategory.DATA_INTEGRITY,
                    phase=ProblemPhase.PERSISTENCE,
                    message="storage namespace resolves outside the workspace",
                    location=StorageLocation(run_id=run_id, ref=ref),
                )
            ]
        ) from error
    return resolved


def _resolve_storage_path(
    path: Path,
    *,
    ref: str,
    run_id: str | None = None,
) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError as error:
        raise StorageError(
            [
                Problem(
                    code="storage.path_resolution_failed",
                    impact=ProblemImpact.BLOCKING,
                    category=ProblemCategory.STORAGE,
                    phase=ProblemPhase.PERSISTENCE,
                    message="storage could not resolve a path",
                    location=StorageLocation(run_id=run_id, ref=ref),
                )
            ]
        ) from error


def _validate_run_id(run_id: str) -> None:
    if SAFE_RUN_ID_RE.fullmatch(run_id):
        return
    raise CheckFailed(
        [
            Problem(
                code="run.id_invalid",
                impact=ProblemImpact.BLOCKING,
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.PERSISTENCE,
                message="run id is not safe for storage access",
                location=ModelLocation(root="run", path=("run_id",)),
                details={"run_id": run_id},
            )
        ]
    )


def _path_escape(ref: str) -> CheckFailed:
    return CheckFailed(
        [
            Problem(
                code="run.ref_path_escape",
                impact=ProblemImpact.BLOCKING,
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.PERSISTENCE,
                message="run ref must stay within the run directory",
                location=ModelLocation(root="run_ref", path=("ref",)),
                details={"ref": ref},
            )
        ]
    )
