"""Read models returned to GUI and Python clients."""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as BinasciiError
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.config.registry.records import (
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.control.models import ControlRun, ResourceKey
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import Problem, has_blocking_problems
from scopecat.measurements.results import MeasurementDataset
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.records.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.parameter_change import (
    ParameterChangeDecisionRecord,
    ParameterChangeProposal,
    ParameterValueDelta,
)
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest


class _ViewModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


class DaemonHealth(_ViewModel):
    """Daemon readiness and the one project owned by this process."""

    status: Literal["ok", "degraded"]
    project_id: str
    project_name: str
    project_root: str


class ConfigRegistryView(_ViewModel):
    """Registered entries and the authoritative activation history."""

    entries: tuple[ConfigRegistryEntry, ...] = ()
    active_state: ConfigRegistryActiveState | None = None


class ActiveConfigView(_ViewModel):
    """The active registry identity and its resolved immutable snapshot."""

    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    config: ConfigProfileSnapshot

    @model_validator(mode="after")
    def validate_identity(self) -> ActiveConfigView:
        if (
            self.active_state.active_entry_id != self.entry.id
            or self.active_state.active_entry_content_hash != self.entry.content_hash
            or config_content_hash(self.config) != self.entry.content_hash
        ):
            raise ValueError("active config view identity is inconsistent")
        return self


class ConfigEntryView(_ViewModel):
    """One registry identity paired with its immutable configuration."""

    entry: ConfigRegistryEntry
    config: ConfigProfileSnapshot

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigEntryView:
        if config_content_hash(self.config) != self.entry.content_hash:
            raise ValueError("config entry view identity is inconsistent")
        return self


class ConfigDraftPreview(_ViewModel):
    """Normalized result of transient typed edits against an active config."""

    valid: bool
    base_entry: ConfigRegistryEntry
    base_generation: int
    base_content_hash: ConfigContentHash
    config: ConfigProfileSnapshot | None = None
    result_content_hash: ConfigContentHash | None = None
    deltas: tuple[ParameterValueDelta, ...] = ()
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> ConfigDraftPreview:
        if self.base_entry.content_hash != self.base_content_hash:
            raise ValueError("config draft preview base identity is inconsistent")
        if self.valid:
            if (
                self.config is None
                or self.result_content_hash is None
                or not self.deltas
                or config_content_hash(self.config) != self.result_content_hash
                or has_blocking_problems(self.problems)
            ):
                raise ValueError("valid config draft preview is incomplete")
        elif self.config is not None or self.result_content_hash is not None:
            raise ValueError("invalid config draft preview cannot expose a candidate")
        return self


class RunResourceView(_ViewModel):
    """Resource state without exposing an executor's authority token."""

    resource: ResourceKey
    status: Literal["required", "active", "quarantined", "released"]
    expires_at: datetime | None = None


class RunDetail(_ViewModel):
    """Control and content state read from the same daemon."""

    control: ControlRun
    manifest: RunManifest
    resources: tuple[RunResourceView, ...] = ()


class RunConfigView(_ViewModel):
    """The immutable configuration snapshot accepted with one run."""

    run_id: str
    config_content_hash: ConfigContentHash
    config: ConfigProfileSnapshot

    @model_validator(mode="after")
    def validate_identity(self) -> RunConfigView:
        if config_content_hash(self.config) != self.config_content_hash:
            raise ValueError("run config view content hash is inconsistent")
        return self


class RunRequestView(_ViewModel):
    """The independently persisted operator request, when one was accepted."""

    run_id: str
    request: RunRequest | None = None


class RunAnalysisView(_ViewModel):
    """One persisted analysis record and its manifest identity."""

    run_id: str
    entry: RunContentEntry
    analysis: AnalysisRecord

    @model_validator(mode="after")
    def validate_identity(self) -> RunAnalysisView:
        if (
            self.entry.role != "record"
            or self.entry.kind != "analysis"
            or self.analysis.run_id != self.run_id
        ):
            raise ValueError("run analysis view identity is inconsistent")
        return self


class RunAnalysisListView(_ViewModel):
    run_id: str
    items: tuple[RunAnalysisView, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> RunAnalysisListView:
        if any(item.run_id != self.run_id for item in self.items):
            raise ValueError("run analysis list contains a different run")
        return self


class RunArtifactBytesView(_ViewModel):
    run_id: str
    artifact: RunContentEntry
    content_base64: str

    @model_validator(mode="after")
    def validate_content(self) -> RunArtifactBytesView:
        _require_entry_role(self.artifact, "artifact")
        _validate_base64(self.content_base64)
        return self

    def content_bytes(self) -> bytes:
        return b64decode(self.content_base64, validate=True)


class RunArtifactTextView(_ViewModel):
    run_id: str
    artifact: RunContentEntry
    content: str

    @model_validator(mode="after")
    def validate_content(self) -> RunArtifactTextView:
        _require_entry_role(self.artifact, "artifact")
        return self


class RunArtifactJsonView(_ViewModel):
    run_id: str
    artifact: RunContentEntry
    content: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_content(self) -> RunArtifactJsonView:
        _require_entry_role(self.artifact, "artifact")
        return self


class RunRecordJsonView(_ViewModel):
    run_id: str
    record: RunContentEntry
    content: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_content(self) -> RunRecordJsonView:
        _require_entry_role(self.record, "record")
        return self


type RunDatasetContent = MeasurementDataset | DataTableArtifact | DataArrayArtifact


class RunDatasetContentView(_ViewModel):
    run_id: str
    dataset: RunContentEntry
    content: RunDatasetContent

    @model_validator(mode="after")
    def validate_content(self) -> RunDatasetContentView:
        _require_entry_role(self.dataset, "dataset")
        mismatched = (
            (
                self.dataset.kind == "measurement_dataset"
                and not isinstance(self.content, MeasurementDataset)
            )
            or (
                self.dataset.kind == "data_table"
                and not isinstance(self.content, DataTableArtifact)
            )
            or (
                self.dataset.kind == "data_array"
                and not isinstance(self.content, DataArrayArtifact)
            )
        )
        if (
            self.dataset.kind
            not in {
                "measurement_dataset",
                "data_table",
                "data_array",
            }
            or mismatched
        ):
            raise ValueError("run dataset content does not match its manifest kind")
        return self


class ParameterProposalView(_ViewModel):
    """One proposal and its append-only operator review history."""

    proposal: ParameterChangeProposal
    decisions: tuple[ParameterChangeDecisionRecord, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> ParameterProposalView:
        if any(
            decision.run_id != self.proposal.source_run_id
            or decision.proposal_id != self.proposal.id
            for decision in self.decisions
        ):
            raise ValueError("parameter proposal decision identity is inconsistent")
        return self


class ParameterProposalListView(_ViewModel):
    run_id: str
    items: tuple[ParameterProposalView, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> ParameterProposalListView:
        if any(item.proposal.source_run_id != self.run_id for item in self.items):
            raise ValueError("parameter proposal list contains a different run")
        return self


class MeasurementPage(_ViewModel):
    """Bounded raw-record preview for interactive browsing."""

    items: tuple[MeasurementRecord, ...] = ()
    next_offset: int | None = Field(default=None, ge=0)


def _require_entry_role(
    entry: RunContentEntry,
    role: Literal["artifact", "dataset", "record"],
) -> None:
    if entry.role != role:
        raise ValueError(f"run content view requires a {role}")


def _validate_base64(value: str) -> None:
    try:
        b64decode(value, validate=True)
    except (BinasciiError, ValueError) as error:
        raise ValueError("content_base64 must be valid base64") from error


__all__ = [
    "ActiveConfigView",
    "ConfigDraftPreview",
    "ConfigEntryView",
    "ConfigRegistryView",
    "DaemonHealth",
    "MeasurementPage",
    "ParameterProposalListView",
    "ParameterProposalView",
    "RunAnalysisListView",
    "RunAnalysisView",
    "RunArtifactBytesView",
    "RunArtifactJsonView",
    "RunArtifactTextView",
    "RunConfigView",
    "RunDatasetContent",
    "RunDatasetContentView",
    "RunDetail",
    "RunRecordJsonView",
    "RunRequestView",
    "RunResourceView",
]
