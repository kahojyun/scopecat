"""High-level notebook client for one daemon-owned lab project."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Self

from pydantic import JsonValue

from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    SavedAnalysis,
)
from scopecat.api.run import RunHandle, RunOperations, run_handle_id
from scopecat.authoring._value_refs import ValueRef
from scopecat.authoring.scans import Scan, ScanCenter, ScanValue
from scopecat.authoring.templates import ExperimentInvocation, ExperimentTemplate
from scopecat.authoring.values import MetadataValue
from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_from_snapshot,
)
from scopecat.config.drafts import ConfigDraft
from scopecat.daemon.connection import DaemonConnection
from scopecat.daemon.views import (
    ConfigDraftPreview,
    ConfigRegistryView,
    DaemonHealth,
    ParameterProposalListView,
    RunAnalysisListView,
    RunAnalysisView,
)
from scopecat.daemon.wire import (
    CandidateConfigActivationReceipt,
    ConfigActivationReceipt,
    ConfigDraftRegistrationReceipt,
    ConfigImportReceipt,
)
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from scopecat.records.parameter_change import (
    ParameterChangeDecisionRecord,
    ParameterChangeProposal,
    ParameterChangeReviewState,
)
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.selectors import RunSelector


@dataclass(frozen=True, slots=True)
class PreparedLabExperiment:
    """A config-bound invocation ready for local planning and delegated execution."""

    lab: LabClient
    invocation: ExperimentInvocation
    config: ConfigProfileSnapshot

    def scan(
        self,
        target: ValueRef | Scan,
        values: Sequence[ScanValue] = (),
        *,
        unit: str | None = None,
        center: ScanCenter | None = None,
        span: Quantity | str | None = None,
        points: int | None = None,
    ) -> PreparedLabExperiment:
        return replace(
            self,
            invocation=self.invocation.scan(
                target,
                values,
                unit=unit,
                center=center,
                span=span,
                points=points,
            ),
        )

    def preview(
        self,
        *,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        return self.lab.preview_invocation(
            self.invocation,
            config=self.config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def run(
        self,
        *,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> RunHandle:
        return self.lab.execute_invocation(
            self.invocation,
            config=self.config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )


class LabClient:
    """Notebook workflow facade over a single project daemon."""

    def __init__(
        self,
        daemon: DaemonConnection,
        *,
        config: ConfigProfileSnapshot | None = None,
        reviewer: str = "operator",
        operator: str = "operator",
    ) -> None:
        self._daemon = daemon
        self._config = config
        self._reviewer = reviewer
        self._operator = operator

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def close(self) -> None:
        self._daemon.close()

    @property
    def run_operations(self) -> RunOperations:
        return self

    @property
    def reviewer(self) -> str:
        return self._reviewer

    @property
    def operator(self) -> str:
        return self._operator

    def health(self) -> DaemonHealth:
        return self._daemon.health()

    def config_registry(self) -> ConfigRegistryView:
        return self._daemon.config_registry()

    def edit_config(
        self,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> ConfigDraft:
        """Create a process-local draft without previewing or registering it."""

        return ConfigDraft.from_snapshot(self.resolve_config(config))

    def preview_config_draft(
        self,
        draft: ConfigDraft,
        *,
        candidate_id: str | None = None,
    ) -> ConfigDraftPreview:
        return self._daemon.preview_config_draft(
            draft,
            candidate_id=candidate_id,
        )

    def register_config_draft(
        self,
        draft: ConfigDraft,
        *,
        preview: ConfigDraftPreview,
        entry_id: str,
        registered_by: str | None = None,
        note: str = "",
    ) -> ConfigDraftRegistrationReceipt:
        return self._daemon.register_config_draft(
            draft,
            preview=preview,
            entry_id=entry_id,
            registered_by=registered_by or self.operator,
            note=note,
        )

    def runs(self) -> tuple[RunHandle, ...]:
        return tuple(
            RunHandle(session=self, id=item.run_id)
            for item in self._daemon.runs().items
        )

    def get_run(self, run: RunSelector | RunHandle) -> RunHandle:
        run_id = run_handle_id(run)
        self._daemon.get_run(run_id)
        return RunHandle(session=self, id=run_id)

    def resolve_config(
        self,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> ConfigProfileSnapshot:
        selected = self._config if config is None else config
        if selected is None:
            return self._daemon.active_config().config
        if isinstance(selected, str):
            if selected == "active":
                return self._daemon.active_config().config
            raise ValueError("daemon config selector must be 'active'")
        if isinstance(selected, CandidateConfig):
            return resolve_candidate_config_from_snapshot(
                selected,
                source_config=self.load_config(selected.source_run_id),
            )
        return selected

    def prepare(
        self,
        experiment: ExperimentInvocation | ExperimentTemplate,
        *,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> PreparedLabExperiment:
        invocation = (
            experiment.bind()
            if isinstance(experiment, ExperimentTemplate)
            else experiment
        )
        return PreparedLabExperiment(
            lab=self,
            invocation=invocation,
            config=self.resolve_config(config),
        )

    def preview_invocation(
        self,
        invocation: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        return self._daemon.preview_scratch(
            invocation,
            config=config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )

    def execute_invocation(
        self,
        invocation: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> RunHandle:
        manifest = self._daemon.run_scratch(
            invocation,
            config=config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return RunHandle(session=self, id=manifest.run_id)

    def load_manifest(self, run_id: str) -> RunManifest:
        return self._daemon.get_run(run_id).manifest

    def load_config(self, run_id: str) -> ConfigProfileSnapshot:
        return self._daemon.run_config(run_id).config

    def load_request(self, run_id: str) -> RunRequest | None:
        return self._daemon.run_request(run_id)

    def measurements(
        self,
        run_id: str,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        return self._daemon.measurement_dataset(run_id, selector)

    def save_analysis(
        self,
        *,
        run_id: str,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis:
        return self._daemon.save_analysis(
            run_id=run_id,
            title=title,
            analysis_key=analysis_key,
            step_id=step_id,
            inputs=inputs,
            outputs=outputs,
            parameter_proposals=parameter_proposals,
        )

    def analyses(self, run_id: str) -> RunAnalysisListView:
        return self._daemon.analyses(run_id)

    def analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        return self._daemon.analysis(run_id, selector)

    def attach(
        self,
        *,
        run_id: str,
        path: str | Path | None,
        key: str,
        kind: str,
        text: str | None,
        content: bytes | None,
        filename: str | None,
        media_type: str | None,
        metadata: Mapping[str, JsonValue] | None,
    ) -> RunContentEntry:
        return self._daemon.attach(
            run_id=run_id,
            path=path,
            key=key,
            kind=kind,
            text=text,
            content=content,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )

    def artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextResult:
        return self._daemon.artifact_text(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonResult:
        return self._daemon.artifact_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    def artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesResult:
        return self._daemon.artifact_bytes(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    def record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonResult:
        return self._daemon.record_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    def data_table(self, run_id: str, selector: str) -> RunDataTableResult:
        return self._daemon.data_table(run_id, selector)

    def data_array(self, run_id: str, selector: str) -> RunDataArrayResult:
        return self._daemon.data_array(run_id, selector)

    def parameter_proposals(
        self,
        run: RunSelector | RunHandle,
    ) -> ParameterProposalListView:
        return self._daemon.parameter_proposals(run_handle_id(run))

    def review_parameter_proposal(
        self,
        run: RunSelector | RunHandle,
        selector: str,
        *,
        reviewer: str | None = None,
        decision: ParameterChangeReviewState = "approved",
        note: str = "",
    ) -> ParameterChangeDecisionRecord:
        return self._daemon.review_parameter_proposal(
            run_handle_id(run),
            selector,
            reviewer=reviewer or self.reviewer,
            decision=decision,
            note=note,
        ).decision

    def import_config(
        self,
        config: ConfigProfileSnapshot,
        *,
        entry_id: str,
        registered_by: str | None = None,
        note: str = "",
    ) -> ConfigImportReceipt:
        return self._daemon.import_direct_config(
            config,
            entry_id=entry_id,
            registered_by=registered_by or self.operator,
            note=note,
        )

    def activate_config_entry(
        self,
        entry_id: str,
        *,
        operator: str | None = None,
        expected_generation: int | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        return self._daemon.activate_config_entry(
            entry_id,
            operator=operator or self.operator,
            expected_generation=expected_generation,
            note=note,
        )

    def activate_config(
        self,
        config: ConfigProfileSnapshot,
        *,
        entry_id: str,
        registered_by: str | None = None,
        operator: str | None = None,
        note: str = "",
        activation_note: str = "",
        expected_generation: int | None = None,
    ) -> ConfigActivationReceipt:
        self.import_config(
            config,
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        )
        return self.activate_config_entry(
            entry_id,
            operator=operator,
            expected_generation=expected_generation,
            note=activation_note,
        )

    def activate(
        self,
        candidate: CandidateConfig,
        *,
        entry_id: str | None = None,
        registered_by: str | None = None,
        operator: str | None = None,
        note: str = "",
        activation_note: str | None = None,
        expected_generation: int | None = None,
    ) -> CandidateConfigActivationReceipt:
        return self._daemon.activate_candidate_config(
            candidate,
            entry_id=entry_id,
            registered_by=registered_by or self.operator,
            operator=operator or self.operator,
            expected_generation=expected_generation,
            note=note,
            activation_note=activation_note,
        )

    def rollback(
        self,
        *,
        expected_generation: int,
        operator: str | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        return self._daemon.rollback_config(
            operator=operator or self.operator,
            expected_generation=expected_generation,
            note=note,
        )


__all__ = ["LabClient", "PreparedLabExperiment"]
