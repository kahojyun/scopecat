"""Notebook configuration intents over one daemon-owned registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from scopecat.api._remote import RemoteRunOperations
from scopecat.api.analysis import Analysis
from scopecat.api.run import RunHandle, run_handle_id
from scopecat.config.candidates import (
    CandidateConfig,
    CandidateSelection,
    resolve_candidate_config_from_snapshot,
)
from scopecat.config.drafts import ConfigDraft
from scopecat.config.registry.records import ConfigRegistryEntry
from scopecat.config.resolution import config_revision_entry_id
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigActivationHistoryView,
    ConfigDraftPreview,
    ConfigEntryView,
    ConfigRegistryView,
    ParameterProposalListView,
)
from scopecat.daemon.wire import (
    CandidateConfigRevisionSource,
    ConfigActivationReceipt,
    ConfigDraftCommand,
    ConfigEntryActivationCommand,
    ConfigRevisionDefaultCommand,
    ConfigRevisionDefaultReceipt,
    ConfigRevisionRegistrationCommand,
    ConfigRevisionRegistrationReceipt,
    ConfigRollbackCommand,
    DirectConfigRevisionSource,
    ManualConfigDraftRevisionSource,
    ParameterProposalApprovalCommand,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.parameter_change import (
    ParameterChangeApprovalRecord,
)
from scopecat.records.run import (
    AnalysisCandidateRunConfigSource,
    ConfigRegistryRunConfigSource,
    RunConfigSource,
)
from scopecat.runs.selectors import RunSelector


@dataclass(frozen=True, slots=True)
class LabConfigOperations:
    """Configuration editing, provenance, and default-selection intents."""

    client: DaemonClient
    runs: RemoteRunOperations
    default_config: ConfigProfileSnapshot | None
    reviewer: str
    operator: str

    def registry(self) -> ConfigRegistryView:
        return self.client.config_registry()

    def history(self) -> ConfigActivationHistoryView:
        return self.client.config_activation_history()

    def active(self) -> ActiveConfigView:
        return self.client.active_config()

    def entry(self, entry_id: str) -> ConfigEntryView:
        return self.client.config_entry(entry_id)

    def edit(
        self,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> ConfigDraft:
        return ConfigDraft.from_snapshot(self.resolve(config))

    def resolve(
        self,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> ConfigProfileSnapshot:
        return self.resolve_with_source(config)[0]

    def resolve_with_source(
        self,
        config: str | ConfigProfileSnapshot | CandidateConfig | None = None,
    ) -> tuple[ConfigProfileSnapshot, RunConfigSource | None]:
        selected = self.default_config if config is None else config
        if selected is None or selected == "active":
            active = self.client.active_config()
            return (
                active.config,
                ConfigRegistryRunConfigSource(
                    selector="active",
                    entry_id=active.entry.id,
                    config_ref=active.entry.config_ref,
                    content_hash=active.entry.content_hash,
                    registry_generation=active.activation.generation,
                ),
            )
        if isinstance(selected, str):
            raise ValueError("daemon config selector must be 'active'")
        if isinstance(selected, CandidateConfig):
            proposals = {
                item.proposal.id: item.proposal
                for item in self.client.parameter_proposals(
                    selected.source_run_id
                ).items
            }
            proposal = selected.parameter_proposal
            if proposals.get(proposal.id) != proposal:
                raise ValueError(
                    "save the producing analysis before using its candidate config"
                )
            analysis = self.runs.analysis(
                selected.source_run_id,
                selected.analysis_record_id,
            )
            if not any(
                output.kind == "parameter_change_proposal"
                and isinstance(output.content, dict)
                and cast("dict[str, object]", output.content).get("proposal_id")
                == proposal.id
                for output in analysis.analysis.outputs
            ):
                raise ValueError(
                    "candidate proposal does not belong to its producing analysis"
                )
            resolved = resolve_candidate_config_from_snapshot(
                selected,
                source_config=self.runs.load_config(selected.source_run_id),
            )
            return (
                resolved,
                AnalysisCandidateRunConfigSource(
                    source_run_id=selected.source_run_id,
                    analysis_record_id=selected.analysis_record_id,
                    proposal_id=selected.proposal_id,
                    base_config_content_hash=selected.base_config_content_hash,
                    content_hash=config_content_hash(resolved),
                ),
            )
        return selected, None

    def preview(
        self,
        draft: ConfigDraft,
        *,
        candidate_id: str | None = None,
    ) -> ConfigDraftPreview:
        active = self.client.active_config()
        if draft.base_content_hash != active.entry.content_hash:
            raise ValueError("config draft base is no longer the active configuration")
        return self.client.preview_config_draft(
            ConfigDraftCommand(
                base_entry_id=active.entry.id,
                base_content_hash=active.entry.content_hash,
                base_generation=active.activation.generation,
                candidate_id=candidate_id or f"{active.config.id}.draft",
                updates=draft.updates,
            )
        )

    def register(
        self,
        draft: ConfigDraft,
        *,
        preview: ConfigDraftPreview,
        entry_id: str,
        registered_by: str | None = None,
        note: str = "",
    ) -> ConfigRevisionRegistrationReceipt:
        if (
            not preview.valid
            or preview.config is None
            or preview.result_content_hash is None
        ):
            raise ValueError("only a valid config draft preview can be registered")
        if draft.base_content_hash != preview.base_content_hash:
            raise ValueError("config draft does not match its reviewed preview base")
        return self.client.register_config_revision(
            ConfigRevisionRegistrationCommand(
                source=ManualConfigDraftRevisionSource(
                    draft=_reviewed_draft_command(draft, preview),
                    expected_result_content_hash=preview.result_content_hash,
                ),
                entry_id=entry_id,
                registered_by=registered_by or self.operator,
                note=note,
            )
        )

    def import_snapshot(
        self,
        config: ConfigProfileSnapshot,
        *,
        entry_id: str,
        registered_by: str | None = None,
        note: str = "",
    ) -> ConfigRegistryEntry:
        return self.client.register_config_revision(
            ConfigRevisionRegistrationCommand(
                source=DirectConfigRevisionSource(config=config),
                entry_id=entry_id,
                registered_by=registered_by or self.operator,
                note=note,
            )
        ).entry

    def set_default(
        self,
        config: ConfigProfileSnapshot | ConfigDraft,
        *,
        entry_id: str | None = None,
        registered_by: str | None = None,
        operator: str | None = None,
        note: str = "",
    ) -> ConfigRevisionDefaultReceipt:
        """Save one immutable revision and atomically make it the default."""

        selected_registered_by = registered_by or self.operator
        selected_operator = operator or self.operator
        if isinstance(config, ConfigDraft):
            preview = self.preview(config)
            if (
                not preview.valid
                or preview.config is None
                or preview.result_content_hash is None
            ):
                raise ValueError("only a valid config draft can become the default")
            return self.client.set_config_default(
                ConfigRevisionDefaultCommand(
                    registration=ConfigRevisionRegistrationCommand(
                        source=ManualConfigDraftRevisionSource(
                            draft=_reviewed_draft_command(config, preview),
                            expected_result_content_hash=preview.result_content_hash,
                        ),
                        entry_id=entry_id or config_revision_entry_id(preview.config),
                        registered_by=selected_registered_by,
                        note=note,
                    ),
                    operator=selected_operator,
                    expected_generation=preview.base_generation,
                )
            )
        return self.client.set_config_default(
            ConfigRevisionDefaultCommand(
                registration=ConfigRevisionRegistrationCommand(
                    source=DirectConfigRevisionSource(config=config),
                    entry_id=entry_id or config_revision_entry_id(config),
                    registered_by=selected_registered_by,
                    note=note,
                ),
                operator=selected_operator,
                expected_generation=self._generation(),
            )
        )

    def activate_entry(
        self,
        entry_id: str,
        *,
        operator: str | None = None,
        expected_generation: int | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        return self.client.activate_config_entry(
            ConfigEntryActivationCommand(
                entry_id=entry_id,
                operator=operator or self.operator,
                expected_generation=(
                    self._generation()
                    if expected_generation is None
                    else expected_generation
                ),
                note=note,
            )
        )

    def activate_candidate(
        self,
        candidate: CandidateConfig,
        *,
        entry_id: str | None = None,
        registered_by: str | None = None,
        operator: str | None = None,
        note: str = "",
        activation_note: str | None = None,
        expected_generation: int | None = None,
    ) -> ConfigRevisionDefaultReceipt:
        return self.client.set_config_default(
            ConfigRevisionDefaultCommand(
                registration=ConfigRevisionRegistrationCommand(
                    source=CandidateConfigRevisionSource(
                        run_id=candidate.source_run_id,
                        proposal_id=candidate.proposal_id,
                    ),
                    entry_id=entry_id,
                    registered_by=registered_by or self.operator,
                    note=note,
                ),
                operator=operator or self.operator,
                expected_generation=(
                    self._generation()
                    if expected_generation is None
                    else expected_generation
                ),
                activation_note=activation_note,
            )
        )

    def proposals(
        self,
        run: RunSelector | RunHandle,
    ) -> ParameterProposalListView:
        return self.client.parameter_proposals(run_handle_id(run))

    def approve(
        self,
        run: RunSelector | RunHandle,
        selector: str,
        *,
        reviewer: str | None = None,
        note: str = "",
    ) -> ParameterChangeApprovalRecord:
        """Record the proposal's immutable operator approval."""

        return self.client.approve_parameter_proposal(
            run_handle_id(run),
            selector,
            ParameterProposalApprovalCommand(
                actor=reviewer or self.reviewer,
                note=note,
            ),
        )

    def accept(
        self,
        candidate: CandidateConfig | Analysis,
        *,
        selection: CandidateSelection = None,
        entry_id: str | None = None,
        registered_by: str | None = None,
        operator: str | None = None,
        note: str = "",
    ) -> ConfigRevisionDefaultReceipt:
        """Persist an analysis if supplied, accept its proposal, and publish."""

        if isinstance(candidate, Analysis):
            candidate.save()
            selected = candidate.candidate_config(selection)
        else:
            if selection is not None:
                raise ValueError("proposal selection belongs on an Analysis")
            selected = candidate
        proposal_id = selected.proposal_id
        self.client.approve_parameter_proposal(
            selected.source_run_id,
            proposal_id,
            ParameterProposalApprovalCommand(
                actor=operator or self.operator,
                note=note,
            ),
        )
        return self.activate_candidate(
            selected,
            entry_id=entry_id,
            registered_by=registered_by,
            operator=operator,
            note=note,
        )

    def undo(
        self,
        *,
        operator: str | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        return self.rollback(operator=operator, note=note)

    def rollback(
        self,
        *,
        expected_generation: int | None = None,
        operator: str | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        return self.client.rollback_config(
            ConfigRollbackCommand(
                operator=operator or self.operator,
                expected_generation=(
                    self._generation()
                    if expected_generation is None
                    else expected_generation
                ),
                note=note,
            )
        )

    def _generation(self) -> int:
        activation = self.registry().activation
        return 0 if activation is None else activation.generation


def _reviewed_draft_command(
    draft: ConfigDraft,
    preview: ConfigDraftPreview,
) -> ConfigDraftCommand:
    config = cast("ConfigProfileSnapshot", preview.config)
    return ConfigDraftCommand(
        base_entry_id=preview.base_entry.id,
        base_content_hash=preview.base_content_hash,
        base_generation=preview.base_generation,
        candidate_id=config.id,
        updates=draft.updates,
    )


__all__ = ["LabConfigOperations"]
