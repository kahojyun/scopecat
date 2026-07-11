"""Internal local run store."""

from __future__ import annotations

from collections.abc import Generator, Iterable
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path

from pydantic import BaseModel

from scopecat._storage.local.io import (
    ensure_durable_directory,
)
from scopecat._storage.local.io import (
    read_jsonl as _read_jsonl,
)
from scopecat._storage.local.io import (
    read_model as _read_model,
)
from scopecat._storage.local.io import (
    read_text as _read_text,
)
from scopecat._storage.local.io import (
    write_jsonl as _write_jsonl,
)
from scopecat._storage.local.io import (
    write_model as _write_model,
)
from scopecat._storage.local.io import (
    write_model_atomic as _write_model_atomic,
)
from scopecat._storage.local.io import (
    write_model_if_absent as _write_model_if_absent,
)
from scopecat._storage.local.io import (
    write_text as _write_text,
)
from scopecat._storage.local.layout import LocalRunLayout
from scopecat._storage.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    CONFIG_REGISTRY_LOCK_REF,
    MANIFEST_REF,
    RUN_PLAN_REF,
    RUN_REQUEST_REF,
)
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunManifest
from scopecat.models.run_plan import RunPlanRecord
from scopecat.models.run_request import RunRequest


class LocalRunStore:
    """Internal entrypoint for local run persistence."""

    def __init__(self, workspace: str | Path) -> None:
        self.layout = LocalRunLayout.from_workspace(workspace)

    def display_run_path(self, run_id: str) -> Path:
        return self.layout.display_run_path(run_id)

    def display_ref_path(self, run_id: str, ref: str) -> Path:
        return self.layout.display_ref_path(run_id, ref)

    def ref_path(self, run_id: str, ref: str) -> Path:
        return self.layout.ref_path(run_id, ref)

    def exists(self, run_id: str, ref: str) -> bool:
        return self.ref_path(run_id, ref).exists()

    def read_manifest(self, run_id: str) -> RunManifest:
        manifest_path = self.ref_path(run_id, MANIFEST_REF)
        if not manifest_path.is_file():
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "run_not_found",
                        f"run not found: {run_id}",
                        "run_id",
                    )
                ]
            )
        return _read_model(manifest_path, RunManifest)

    def write_manifest(self, manifest: RunManifest) -> None:
        _write_model_atomic(self.ref_path(manifest.run_id, MANIFEST_REF), manifest)

    @contextmanager
    def run_lock(self, run_id: str) -> Generator[None]:
        """Serialize mutations of one run's content and manifest.

        Callers that also hold the config-registry lock must acquire that lock
        first. This lock is intentionally not re-entrant; locked helpers avoid
        acquiring it a second time.
        """

        lock_path = self.layout.run_dir(run_id) / ".run.lock"
        ensure_durable_directory(lock_path.parent)
        with lock_path.open("a+b") as lock_file:
            flock(lock_file.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(lock_file.fileno(), LOCK_UN)

    @contextmanager
    def config_registry_lock(self) -> Generator[None]:
        """Join the registry-to-run lock order used by promotion decisions."""

        lock_path = self.layout.workspace / CONFIG_REGISTRY_LOCK_REF
        ensure_durable_directory(lock_path.parent)
        with lock_path.open("a+b") as lock_file:
            flock(lock_file.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(lock_file.fileno(), LOCK_UN)

    def list_runs(self) -> list[RunManifest]:
        if not self.layout.runs_root.is_dir():
            return []
        manifests: list[RunManifest] = []
        for manifest_path in sorted(self.layout.runs_root.glob("*/manifest.json")):
            manifests.append(_read_model(manifest_path, RunManifest))
        return sorted(manifests, key=lambda manifest: manifest.created_at)

    def write_structured_run_inputs(
        self,
        *,
        manifest: RunManifest,
        request: RunRequest | None,
        plan: RunPlanRecord,
        config: ConfigProfileSnapshot,
    ) -> None:
        # Publish accepted inputs before the manifest makes the run visible.
        if request is not None:
            self.write_model_atomic(manifest.run_id, RUN_REQUEST_REF, request)
        self.write_model_atomic(manifest.run_id, RUN_PLAN_REF, plan)
        self.write_model_atomic(
            manifest.run_id,
            CONFIG_PROFILE_SNAPSHOT_REF,
            config,
        )
        self.write_manifest(manifest)

    def write_run_skeleton(
        self,
        *,
        manifest: RunManifest,
        request: RunRequest | None,
        plan: RunPlanRecord,
        config: ConfigProfileSnapshot,
    ) -> None:
        """Durably accept a run before any instrument interaction begins."""

        if manifest.status not in {"planned", "running"}:
            msg = "run skeleton manifest must be planned or running"
            raise ValueError(msg)
        self.write_structured_run_inputs(
            manifest=manifest,
            request=request,
            plan=plan,
            config=config,
        )

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot:
        return self.read_model(
            run_id, CONFIG_PROFILE_SNAPSHOT_REF, ConfigProfileSnapshot
        )

    def read_model[TModel: BaseModel](
        self, run_id: str, ref: str, model_type: type[TModel]
    ) -> TModel:
        return _read_model(self.ref_path(run_id, ref), model_type)

    def write_model(self, run_id: str, ref: str, model: BaseModel) -> None:
        _write_model(self.ref_path(run_id, ref), model)

    def write_model_atomic(self, run_id: str, ref: str, model: BaseModel) -> None:
        _write_model_atomic(self.ref_path(run_id, ref), model)

    def write_model_if_absent(
        self,
        run_id: str,
        ref: str,
        model: BaseModel,
    ) -> bool:
        return _write_model_if_absent(self.ref_path(run_id, ref), model)

    def read_jsonl[TModel: BaseModel](
        self, run_id: str, ref: str, model_type: type[TModel]
    ) -> list[TModel]:
        return _read_jsonl(self.ref_path(run_id, ref), model_type)

    def write_jsonl(self, run_id: str, ref: str, records: Iterable[BaseModel]) -> None:
        _write_jsonl(self.ref_path(run_id, ref), records)

    def read_text(self, run_id: str, ref: str) -> str:
        return _read_text(self.ref_path(run_id, ref))

    def write_text(self, run_id: str, ref: str, content: str) -> None:
        _write_text(self.ref_path(run_id, ref), content)


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
