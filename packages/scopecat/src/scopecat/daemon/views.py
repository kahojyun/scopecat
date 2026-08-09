"""Read models returned to GUI and Python clients."""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as BinasciiError
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryEntry,
)
from scopecat.control.models import (
    ControlRunState,
    ResourceOwnerKind,
    RunResourceRequirement,
)
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import Problem
from scopecat.measurements.datasets import (
    MAX_MEASUREMENT_SLICE_SIZE,
    MAX_MEASUREMENT_TRACE_SAMPLES,
    MAX_MEASUREMENT_TRACE_SERIES,
)
from scopecat.measurements.traces import (
    TraceDownsampling,
    TraceValueMode,
)
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.records.measurement import MeasurementDatasetSchema, MeasurementRecord
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


class VirtualInstrumentConnectionSummary(_ViewModel):
    kind: Literal["virtual"] = "virtual"


class TcpipSocketInstrumentConnectionSummary(_ViewModel):
    kind: Literal["tcpip_socket"] = "tcpip_socket"
    host: str
    port: int


type InstrumentConnectionSummary = Annotated[
    VirtualInstrumentConnectionSummary | TcpipSocketInstrumentConnectionSummary,
    Field(discriminator="kind"),
]


class InstrumentView(_ViewModel):
    """Instrument status without exposing configuration policy or driver options."""

    instrument_id: str
    driver_id: str
    connection: InstrumentConnectionSummary
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
    items: tuple[InstrumentView, ...] = ()
    problems: tuple[Problem, ...] = ()


class RunPlanView(_ViewModel):
    """Experiment facts without scheduler or backend identities."""

    experiment_id: str = Field(min_length=1)
    experiment_kind: str = Field(min_length=1)
    point_count: int = Field(ge=0)
    coordinate_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    run_resource_requirements: tuple[RunResourceRequirement, ...] = ()


class RunAdmissionView(_ViewModel):
    run_id: str = Field(min_length=1)
    plan: RunPlanView
    display_name: str | None = Field(default=None, min_length=1)
    tags: tuple[str, ...] = ()
    description: str | None = Field(default=None, min_length=1)
    admitted_at: datetime


class RunControlView(_ViewModel):
    """Run state without durable scheduler internals."""

    sequence: int = Field(ge=1)
    admission: RunAdmissionView
    state: ControlRunState
    updated_at: datetime
    attention_reason: str | None = None
    cancellation_requested_at: datetime | None = None

    @property
    def run_id(self) -> str:
        return self.admission.run_id


class RunResourceView(_ViewModel):
    """Logical resource state without scheduler identity or authority."""

    resource: RunResourceRequirement
    status: Literal["required", "active", "quarantined", "released"]
    expires_at: datetime | None = None


class RunSummary(_ViewModel):
    """Scheduler projection paired with the accepted run snapshot."""

    control: RunControlView
    manifest: RunManifest

    @property
    def run_id(self) -> str:
        return self.control.run_id


class RunSummaryPage(_ViewModel):
    """Keyset page retaining scheduler state and terminal outcomes."""

    items: tuple[RunSummary, ...] = ()
    next_cursor: int | None = Field(default=None, ge=1)


class RunDomainExecutionView(_ViewModel):
    """Compact target-authored provenance for one domain execution."""

    operation_id: str = Field(min_length=1)
    execution_key: str = Field(min_length=1)
    intent_fingerprint: str = Field(min_length=1)
    logical_compute_node_id: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    compiler_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    state: Literal["started", "completed", "failed", "unknown"]
    execution_summary: dict[str, JsonValue]
    receipt_status: Literal["completed", "not_executed", "unknown"] | None = None
    result_count: int | None = Field(default=None, ge=0)
    started_at: datetime
    updated_at: datetime
    problems: tuple[Problem, ...] = ()


class RunDetail(RunSummary):
    """Run summary with scheduler resource state."""

    resources: tuple[RunResourceView, ...] = ()
    domain_executions: tuple[RunDomainExecutionView, ...] = ()


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
    """Bounded typed-record preview for interactive browsing."""

    items: tuple[MeasurementRecord, ...] = ()
    next_offset: int | None = Field(default=None, ge=0)
    dataset_schema: MeasurementDatasetSchema | None = None


class MeasurementSliceQuery(_ViewModel):
    """One bounded product-grid slice selected by authored axis indices."""

    fixed_axis_indices: dict[str, Annotated[int, Field(ge=0)]] = Field(
        default_factory=dict
    )
    limit: Annotated[int, Field(ge=1, le=MAX_MEASUREMENT_SLICE_SIZE)] = (
        MAX_MEASUREMENT_SLICE_SIZE
    )
    variable_ids: list[Annotated[str, Field(min_length=1)]] | None = None
    include_schema: bool = False

    @model_validator(mode="after")
    def validate_axis_ids(self) -> MeasurementSliceQuery:
        if any(not axis_id for axis_id in self.fixed_axis_indices):
            raise ValueError("measurement slice axis ids must be non-empty")
        return self


class MeasurementSlice(_ViewModel):
    """Records for one semantic product-grid slice."""

    items: tuple[MeasurementRecord, ...] = ()
    dataset_schema: MeasurementDatasetSchema | None = None
    selected_point_count: Annotated[int, Field(ge=0)]
    truncated: bool = False


class MeasurementTracePreviewQuery(_ViewModel):
    """Select one bounded, response-ready point-local trace preview."""

    recording_group_id: Annotated[str, Field(min_length=1)] | None = None
    observable_id: Annotated[str, Field(min_length=1)] | None = None
    coordinate_id: Annotated[str, Field(min_length=1)] | None = None
    fixed_axis_indices: dict[str, Annotated[int, Field(ge=0)]] = Field(
        default_factory=dict
    )
    max_series: Annotated[
        int,
        Field(ge=1, le=MAX_MEASUREMENT_TRACE_SERIES),
    ] = MAX_MEASUREMENT_TRACE_SERIES
    max_samples: Annotated[
        int,
        Field(ge=2, le=MAX_MEASUREMENT_TRACE_SAMPLES),
    ] = MAX_MEASUREMENT_TRACE_SAMPLES
    value_mode: TraceValueMode | None = None
    downsampling: TraceDownsampling = "minmax"

    @model_validator(mode="after")
    def validate_selection(self) -> MeasurementTracePreviewQuery:
        if self.recording_group_id is None and self.observable_id is None:
            raise ValueError(
                "trace preview requires a recording_group_id or observable_id"
            )
        if any(not axis_id for axis_id in self.fixed_axis_indices):
            raise ValueError("trace preview axis ids must be non-empty")
        return self


class MeasurementTraceSeries(_ViewModel):
    """One directly plottable numeric trace series."""

    point_index: Annotated[int, Field(ge=0)]
    logical_point_id: str | None = None
    label: str = Field(min_length=1)
    x: tuple[float, ...] = Field(min_length=1)
    y: tuple[float, ...] = Field(min_length=1)
    source_sample_count: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_samples(self) -> MeasurementTraceSeries:
        if len(self.x) != len(self.y):
            raise ValueError("trace preview x and y lengths must match")
        if len(self.y) > self.source_sample_count:
            raise ValueError("trace preview exceeds its source sample count")
        return self


class MeasurementTracePreview(_ViewModel):
    """Bounded numeric series for one selected point-local observable.

    ``selected_series_count`` is the authored domain selection size. It does
    not promise that every selected point is durable yet or has an available
    observable value; ``returned_series_count`` counts response series only.
    """

    fixed_axis_indices: dict[str, Annotated[int, Field(ge=0)]] = Field(
        default_factory=dict
    )
    dimension_id: str = Field(min_length=1)
    recording_group_id: str | None = Field(default=None, min_length=1)
    coordinate_id: str = Field(min_length=1)
    observable_id: str = Field(min_length=1)
    coordinate_label: str | None = None
    observable_label: str | None = None
    coordinate_unit: str | None = None
    observable_unit: str | None = None
    value_mode: TraceValueMode
    value_unit: str | None = None
    downsampling: TraceDownsampling
    series: tuple[MeasurementTraceSeries, ...] = ()
    selected_series_count: Annotated[int, Field(ge=0)]
    returned_series_count: Annotated[int, Field(ge=0)]
    truncated_series: bool = False
    source_sample_count: Annotated[int, Field(ge=0)]
    returned_sample_count: Annotated[int, Field(ge=0)]
    samples_reduced: bool = False

    @model_validator(mode="after")
    def validate_counts(self) -> MeasurementTracePreview:
        if self.returned_series_count != len(self.series):
            raise ValueError("trace preview returned series count is inconsistent")
        if self.returned_series_count > self.selected_series_count:
            raise ValueError("trace preview returns more than its domain selection")
        if self.source_sample_count != sum(
            item.source_sample_count for item in self.series
        ):
            raise ValueError("trace preview source sample count is inconsistent")
        if self.returned_sample_count != sum(len(item.y) for item in self.series):
            raise ValueError("trace preview returned sample count is inconsistent")
        if self.returned_sample_count > self.source_sample_count:
            raise ValueError("trace preview returns more samples than its sources")
        if self.samples_reduced != (
            self.returned_sample_count < self.source_sample_count
        ):
            raise ValueError("trace preview sample reduction flag is inconsistent")
        return self


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
    "InstrumentConnectionSummary",
    "InstrumentListView",
    "InstrumentView",
    "MeasurementPage",
    "MeasurementSlice",
    "MeasurementSliceQuery",
    "MeasurementTracePreview",
    "MeasurementTracePreviewQuery",
    "MeasurementTraceSeries",
    "ParameterProposalListView",
    "ParameterProposalView",
    "RunAdmissionView",
    "RunAnalysisListView",
    "RunAnalysisView",
    "RunArtifactBytesView",
    "RunConfigView",
    "RunControlView",
    "RunDetail",
    "RunDomainExecutionView",
    "RunPlanView",
    "RunRequestView",
    "RunResourceView",
    "RunSummary",
    "RunSummaryPage",
    "TcpipSocketInstrumentConnectionSummary",
    "VirtualInstrumentConnectionSummary",
]
