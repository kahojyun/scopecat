"""Internal local run storage layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scopecat._storage.refs import ARTIFACTS_DIR, RUNS_DIR
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed


@dataclass(frozen=True)
class LocalRunLayout:
    """Path calculation and run-relative ref validation for local storage."""

    workspace: Path

    @classmethod
    def from_workspace(cls, workspace: str | Path) -> LocalRunLayout:
        return cls(workspace=Path(workspace))

    @property
    def runs_root(self) -> Path:
        return self.workspace / RUNS_DIR

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def artifacts_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / ARTIFACTS_DIR

    def ref_path(self, run_id: str, ref: str) -> Path:
        relative = _validate_run_relative_ref(ref)
        candidate = self.run_dir(run_id) / relative.as_posix()
        run_root = self.run_dir(run_id).resolve(strict=False)
        resolved = candidate.resolve(strict=False)
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
    if relative.is_absolute() or ".." in relative.parts:
        raise _path_escape(ref)
    return relative


def _path_escape(ref: str) -> ValidationFailed:
    return ValidationFailed(
        [
            _diagnostic(
                "error",
                "run_ref_path_escape",
                f"run ref path escapes run directory: {ref}",
                "ref",
            )
        ]
    )


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
