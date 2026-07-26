"""Repository boundary for durable run state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.run import RunManifest, RunOutcome


@dataclass(frozen=True, slots=True)
class RunModelWrite:
    ref: str
    value: BaseModel
    replace: bool = True


@dataclass(frozen=True, slots=True)
class RunBytesWrite:
    ref: str
    content: bytes
    replace: bool = True


@dataclass(frozen=True, slots=True)
class TerminalRunCommit:
    """Terminal outcome and evidence to apply to the durable run."""

    run_id: str
    outcome: RunOutcome
    contents: tuple[RunContentEntry, ...] = ()
    models: tuple[RunModelWrite, ...] = ()


@dataclass(frozen=True, slots=True)
class RunContentPublication:
    """Content refs and manifest entries made visible as one operation."""

    run_id: str
    entries: tuple[RunContentEntry, ...]
    models: tuple[RunModelWrite, ...] = ()
    bytes: tuple[RunBytesWrite, ...] = ()


class RunRepository(Protocol):
    """Durable run repository shared by use cases and storage adapters."""

    def exists(self, run_id: str, ref: str) -> bool: ...

    def read_manifest(self, run_id: str) -> RunManifest: ...

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest: ...

    def publish_content(
        self,
        publication: RunContentPublication,
    ) -> RunManifest: ...

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot: ...

    def read_model[TModel: BaseModel](
        self, run_id: str, ref: str, model_type: type[TModel]
    ) -> TModel: ...

    def read_measurement_records(
        self,
        run_id: str,
        ref: str,
    ) -> list[MeasurementRecord]: ...

    def read_text(self, run_id: str, ref: str) -> str: ...

    def read_bytes(self, run_id: str, ref: str) -> bytes: ...
