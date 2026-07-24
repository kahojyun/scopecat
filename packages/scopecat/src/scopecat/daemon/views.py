"""Read models returned to GUI and Python clients."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.config.registry.records import (
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.control.models import ControlRun, ResourceKey
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.parameter_change import (
    ParameterChangeDecisionRecord,
    ParameterChangeProposal,
)
from scopecat.records.run import RunManifest


class _ViewModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


class DaemonHealth(_ViewModel):
    """Process and workspace readiness."""

    schema_version: Literal["scopecat.daemon_health.v1"] = "scopecat.daemon_health.v1"
    status: Literal["ok", "degraded"]
    workspace_id: str


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


__all__ = [
    "ActiveConfigView",
    "ConfigEntryView",
    "ConfigRegistryView",
    "DaemonHealth",
    "MeasurementPage",
    "ParameterProposalListView",
    "ParameterProposalView",
    "RunConfigView",
    "RunDetail",
    "RunResourceView",
]
