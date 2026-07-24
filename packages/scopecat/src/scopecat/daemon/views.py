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

    schema_version: Literal["scopecat.daemon_health.v2"] = "scopecat.daemon_health.v2"
    status: Literal["ok", "degraded"]
    project_id: str
    project_name: str
    project_root: str


class ConfigRegistryView(_ViewModel):
    """Registered entries and the authoritative activation history."""

    schema_version: Literal["scopecat.config_registry_view.v1"] = (
        "scopecat.config_registry_view.v1"
    )
    entries: tuple[ConfigRegistryEntry, ...] = ()
    active_state: ConfigRegistryActiveState | None = None


class ActiveConfigView(_ViewModel):
    """The active registry identity and its resolved immutable snapshot."""

    schema_version: Literal["scopecat.active_config_view.v1"] = (
        "scopecat.active_config_view.v1"
    )
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

    schema_version: Literal["scopecat.config_entry_view.v1"] = (
        "scopecat.config_entry_view.v1"
    )
    entry: ConfigRegistryEntry
    config: ConfigProfileSnapshot

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigEntryView:
        if config_content_hash(self.config) != self.entry.content_hash:
            raise ValueError("config entry view identity is inconsistent")
        return self


class RunResourceView(_ViewModel):
    """Resource state without exposing an executor's authority token."""

    resource: ResourceKey
    status: Literal["required", "active", "quarantined", "released"]
    expires_at: datetime | None = None


class RunDetail(_ViewModel):
    """Control and content state read from the same daemon."""

    schema_version: Literal["scopecat.run_detail.v1"] = "scopecat.run_detail.v1"
    control: ControlRun
    manifest: RunManifest
    resources: tuple[RunResourceView, ...] = ()


class RunConfigView(_ViewModel):
    """The immutable configuration snapshot accepted with one run."""

    schema_version: Literal["scopecat.run_config_view.v1"] = (
        "scopecat.run_config_view.v1"
    )
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

    schema_version: Literal["scopecat.run_request_view.v1"] = (
        "scopecat.run_request_view.v1"
    )
    run_id: str
    request: RunRequest | None = None


class RunAnalysisView(_ViewModel):
    """One persisted analysis record and its manifest identity."""

    schema_version: Literal["scopecat.run_analysis_view.v1"] = (
        "scopecat.run_analysis_view.v1"
    )
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
    schema_version: Literal["scopecat.run_analysis_list_view.v1"] = (
        "scopecat.run_analysis_list_view.v1"
    )
    run_id: str
    items: tuple[RunAnalysisView, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> RunAnalysisListView:
        if any(item.run_id != self.run_id for item in self.items):
            raise ValueError("run analysis list contains a different run")
        return self


class RunArtifactBytesView(_ViewModel):
    schema_version: Literal["scopecat.run_artifact_bytes_view.v1"] = (
        "scopecat.run_artifact_bytes_view.v1"
    )
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
    schema_version: Literal["scopecat.run_artifact_text_view.v1"] = (
        "scopecat.run_artifact_text_view.v1"
    )
    run_id: str
    artifact: RunContentEntry
    content: str

    @model_validator(mode="after")
    def validate_content(self) -> RunArtifactTextView:
        _require_entry_role(self.artifact, "artifact")
        return self


class RunArtifactJsonView(_ViewModel):
    schema_version: Literal["scopecat.run_artifact_json_view.v1"] = (
        "scopecat.run_artifact_json_view.v1"
    )
    run_id: str
    artifact: RunContentEntry
    content: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_content(self) -> RunArtifactJsonView:
        _require_entry_role(self.artifact, "artifact")
        return self


class RunRecordJsonView(_ViewModel):
    schema_version: Literal["scopecat.run_record_json_view.v1"] = (
        "scopecat.run_record_json_view.v1"
    )
    run_id: str
    record: RunContentEntry
    content: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_content(self) -> RunRecordJsonView:
        _require_entry_role(self.record, "record")
        return self


type RunDatasetContent = MeasurementDataset | DataTableArtifact | DataArrayArtifact


class RunDatasetContentView(_ViewModel):
    schema_version: Literal["scopecat.run_dataset_content_view.v1"] = (
        "scopecat.run_dataset_content_view.v1"
    )
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
    schema_version: Literal["scopecat.parameter_proposal_list_view.v1"] = (
        "scopecat.parameter_proposal_list_view.v1"
    )
    run_id: str
    items: tuple[ParameterProposalView, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> ParameterProposalListView:
        if any(item.proposal.source_run_id != self.run_id for item in self.items):
            raise ValueError("parameter proposal list contains a different run")
        return self


class MeasurementPage(_ViewModel):
    """Bounded raw-record preview for interactive browsing."""

    schema_version: Literal["scopecat.measurement_page.v1"] = (
        "scopecat.measurement_page.v1"
    )
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
