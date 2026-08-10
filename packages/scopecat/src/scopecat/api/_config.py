"""Notebook configuration intents over one daemon-owned registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from scopecat.api._remote import RemoteRunOperations
from scopecat.api.analysis import AnalysisOutcome
from scopecat.api.run import RunHandle, run_handle_id
from scopecat.config.candidates import (
    CandidateConfig,
    CandidateSelection,
    resolve_candidate_config_from_snapshot,
)
from scopecat.config.drafts import ConfigDraft
from scopecat.config.inventory import InstrumentInventoryChange
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
    ConfigPublishCommand,
    ConfigPublishReceipt,
    ConfigUndoCommand,
    DirectConfigRevisionSource,
    InstrumentInventoryMigrationCommand,
    InstrumentInventoryMigrationReceipt,
    ManualConfigDraftRevisionSource,
)
from scopecat.records.analysis import AnalysisParameterProposalRecordOutput
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
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
                isinstance(output, AnalysisParameterProposalRecordOutput)
                and output.content.proposal_id == proposal.id
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

    def set_default(
        self,
        config: ConfigProfileSnapshot | ConfigDraft,
        *,
        entry_id: str | None = None,
        actor: str | None = None,
        note: str = "",
    ) -> ConfigPublishReceipt:
        """Save one immutable revision and atomically make it the default."""

        selected_actor = actor or self.operator
        if isinstance(config, ConfigDraft):
            preview = self.preview(config)
            if (
                not preview.valid
                or preview.config is None
                or preview.result_content_hash is None
            ):
                raise ValueError("only a valid config draft can become the default")
            return self.client.publish_config(
                ConfigPublishCommand(
                    source=ManualConfigDraftRevisionSource(
                        draft=_reviewed_draft_command(config, preview),
                        expected_result_content_hash=preview.result_content_hash,
                    ),
                    entry_id=entry_id or config_revision_entry_id(preview.config),
                    actor=selected_actor,
                    expected_generation=preview.base_generation,
                    note=note,
                )
            )
        return self.client.publish_config(
            ConfigPublishCommand(
                source=DirectConfigRevisionSource(config=config),
                entry_id=entry_id or config_revision_entry_id(config),
                actor=selected_actor,
                expected_generation=self._generation(),
                note=note,
            )
        )

    def activate_entry(
        self,
        entry_id: str,
        *,
        actor: str | None = None,
        expected_generation: int | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        return self.client.activate_config_entry(
            ConfigEntryActivationCommand(
                entry_id=entry_id,
                actor=actor or self.operator,
                expected_generation=(
                    self._generation()
                    if expected_generation is None
                    else expected_generation
                ),
                note=note,
            )
        )

    def migrate_instrument_inventory(
        self,
        config: ConfigProfileSnapshot,
        *,
        changes: tuple[InstrumentInventoryChange, ...],
        entry_id: str | None = None,
        actor: str | None = None,
        note: str = "",
    ) -> InstrumentInventoryMigrationReceipt:
        """Publish changed physical identities after their owners are drained."""

        return self.client.migrate_instrument_inventory(
            InstrumentInventoryMigrationCommand(
                config=config,
                entry_id=entry_id or config_revision_entry_id(config),
                changes=changes,
                actor=actor or self.operator,
                expected_generation=self._generation(),
                note=note,
            )
        )

    def proposals(
        self,
        run: RunSelector | RunHandle,
    ) -> ParameterProposalListView:
        return self.client.parameter_proposals(run_handle_id(run))

    def accept(
        self,
        candidate: CandidateConfig | AnalysisOutcome,
        *,
        selection: CandidateSelection = None,
        entry_id: str | None = None,
        actor: str | None = None,
        note: str = "",
    ) -> ConfigPublishReceipt:
        """Accept a saved analysis proposal or an already selected candidate."""

        if isinstance(candidate, AnalysisOutcome):
            selected = candidate.candidate_config(selection)
        else:
            if selection is not None:
                raise ValueError("proposal selection belongs on an AnalysisOutcome")
            selected = candidate
        return self.client.publish_config(
            ConfigPublishCommand(
                source=CandidateConfigRevisionSource(
                    run_id=selected.source_run_id,
                    proposal_id=selected.proposal_id,
                ),
                actor=actor or self.operator,
                expected_generation=self._generation(),
                entry_id=entry_id,
                note=note,
            )
        )

    def undo(
        self,
        *,
        actor: str | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        return self.client.undo_config(
            ConfigUndoCommand(
                actor=actor or self.operator,
                expected_generation=self._generation(),
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
