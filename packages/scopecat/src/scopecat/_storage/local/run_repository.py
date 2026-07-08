"""Internal local run store."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

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
    write_text as _write_text,
)
from scopecat._storage.local.layout import LocalRunLayout
from scopecat._storage.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    EXPERIMENT_SPEC_REF,
    MANIFEST_REF,
    RUN_REQUEST_REF,
)
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunManifest


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
        experiment: ExperimentSpec,
        config: ConfigProfileSnapshot,
    ) -> None:
        self.write_model(manifest.run_id, MANIFEST_REF, manifest)
        if experiment.request is not None:
            self.write_model(manifest.run_id, RUN_REQUEST_REF, experiment.request)
        self.write_model(manifest.run_id, EXPERIMENT_SPEC_REF, experiment)
        self.write_model(manifest.run_id, CONFIG_PROFILE_SNAPSHOT_REF, config)

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
