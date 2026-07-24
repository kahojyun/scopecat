"""Repository boundary for durable run state.

The run model owns this protocol.  Filesystem details belong to an adapter and
are selected by a composition root, never by a use case or executor.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class RunModelWrite:
    ref: str
    value: BaseModel


@dataclass(frozen=True, slots=True)
class RunRecordSetWrite:
    ref: str
    records: tuple[BaseModel, ...]


@dataclass(frozen=True, slots=True)
class TerminalRunCommit:
    """All durable content published by one terminal run transition."""

    manifest: RunManifest
    models: tuple[RunModelWrite, ...] = ()
    record_sets: tuple[RunRecordSetWrite, ...] = ()


class RunRepository(Protocol):
    """Durable run repository shared by use cases and storage adapters."""

    def exists(self, run_id: str, ref: str) -> bool: ...

    def read_manifest(self, run_id: str) -> RunManifest: ...

    def write_manifest(self, manifest: RunManifest) -> None: ...

    def list_runs(self) -> list[RunManifest]: ...

    def write_run_skeleton(
        self,
        *,
        manifest: RunManifest,
        request: RunRequest | None,
        config: ConfigProfileSnapshot,
    ) -> None: ...

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest: ...

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot: ...

    def read_model[TModel: BaseModel](
        self, run_id: str, ref: str, model_type: type[TModel]
    ) -> TModel: ...

    def write_model(self, run_id: str, ref: str, model: BaseModel) -> None: ...

    def write_model_if_absent(
        self, run_id: str, ref: str, model: BaseModel
    ) -> bool: ...

    def read_jsonl[TModel: BaseModel](
        self, run_id: str, ref: str, model_type: type[TModel]
    ) -> list[TModel]: ...

    def read_measurement_records(
        self,
        run_id: str,
        ref: str,
    ) -> list[MeasurementRecord]: ...

    def write_jsonl(
        self, run_id: str, ref: str, records: Iterable[BaseModel]
    ) -> None: ...

    def read_text(self, run_id: str, ref: str) -> str: ...

    def read_bytes(self, run_id: str, ref: str) -> bytes: ...

    def write_bytes(self, run_id: str, ref: str, content: bytes) -> None: ...

    def write_text(self, run_id: str, ref: str, content: str) -> None: ...
