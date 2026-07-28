"""Read models returned to GUI and Python clients."""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as BinasciiError
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryEntry,
)
from scopecat.control.models import (
    ControlRun,
    ResourceKey,
    ResourceOwnerKind,
)
from scopecat.kernel.problems import Problem
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    InstrumentSpec,
    config_content_hash,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.parameter_change import (
    ParameterChangeApprovalRecord,
    ParameterChangeProposal,
    ParameterValueDelta,
)
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments.contracts import InstrumentDescription


class _ViewModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class DaemonHealth(_ViewModel):
    """Daemon readiness and the one project owned by this process."""

    status: Literal["ok", "degraded"]
    project_id: str
    project_name: str
    project_root: str


class ConfigRegistryView(_ViewModel):
    """Saved revisions and the current activation head."""

    entries: tuple[ConfigRegistryEntry, ...] = ()
    activation: ConfigRegistryActivationRecord | None = None


class ConfigActivationHistoryView(_ViewModel):
    items: tuple[ConfigRegistryActivationRecord, ...] = ()


class ActiveConfigView(_ViewModel):
    """The active registry identity and its resolved immutable snapshot."""

    entry: ConfigRegistryEntry
    activation: ConfigRegistryActivationRecord
    config: ConfigProfileSnapshot


class ConfigEntryView(_ViewModel):
    """One registry identity paired with its immutable configuration."""

    entry: ConfigRegistryEntry
    config: ConfigProfileSnapshot


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


class InstrumentView(_ViewModel):
    """Configured instrument, pure driver ABI, and current exclusive ownership."""

    spec: InstrumentSpec
    description: InstrumentDescription | None = None
    availability: Literal["available", "active", "quarantined", "unavailable"]
    owner_kind: ResourceOwnerKind | None = None
    owner_id: str | None = None
    owner_actor: str | None = None
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_availability(self) -> InstrumentView:
        if self.availability == "available":
            if (
                self.owner_kind is not None
                or self.owner_id is not None
                or self.owner_actor is not None
            ):
                raise ValueError("available instrument cannot have an owner")
        elif self.availability in {"active", "quarantined"}:
            if self.owner_kind is None or self.owner_id is None:
                raise ValueError("owned instrument requires an owner")
            if self.owner_kind == "instrument_session" and self.owner_actor is None:
                raise ValueError("interactive instrument owner requires an actor")
            if self.owner_kind == "run" and self.owner_actor is not None:
                raise ValueError("run-owned instrument cannot expose an actor")
        return self


class InstrumentListView(_ViewModel):
    config_entry_id: str
    config_content_hash: ConfigContentHash
    items: tuple[InstrumentView, ...] = ()
    problems: tuple[Problem, ...] = ()


class RunResourceView(_ViewModel):
    """Resource state without exposing an executor's authority token."""

    resource: ResourceKey
    status: Literal["required", "active", "quarantined", "released"]
    expires_at: datetime | None = None


class RunSummary(_ViewModel):
    """Scheduler projection paired with the accepted run snapshot."""

    control: ControlRun
    manifest: RunManifest

    @property
    def run_id(self) -> str:
        return self.control.run_id


class RunSummaryPage(_ViewModel):
    """Keyset page retaining scheduler state and terminal outcomes."""

    items: tuple[RunSummary, ...] = ()
    next_cursor: int | None = Field(default=None, ge=1)


class RunDetail(RunSummary):
    """Run summary with scheduler resource state."""

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
    """The operator request accepted with one run."""

    run_id: str
    request: RunRequest


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


class ParameterProposalView(_ViewModel):
    """One proposal and its optional immutable operator approval."""

    proposal: ParameterChangeProposal
    approval: ParameterChangeApprovalRecord | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> ParameterProposalView:
        if self.approval is not None and (
            self.approval.run_id != self.proposal.source_run_id
            or self.approval.proposal_id != self.proposal.id
        ):
            raise ValueError("parameter proposal approval identity is inconsistent")
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
    "ConfigActivationHistoryView",
    "ConfigDraftPreview",
    "ConfigEntryView",
    "ConfigRegistryView",
    "DaemonHealth",
    "InstrumentListView",
    "InstrumentView",
    "MeasurementPage",
    "ParameterProposalListView",
    "ParameterProposalView",
    "RunAnalysisListView",
    "RunAnalysisView",
    "RunArtifactBytesView",
    "RunConfigView",
    "RunDetail",
    "RunRequestView",
    "RunResourceView",
    "RunSummary",
    "RunSummaryPage",
]
