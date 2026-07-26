from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Literal

import pytest

from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_snapshot,
)
from scopecat.config.changes import (
    list_parameter_change_decisions,
    load_parameter_change_proposal,
)
from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.registry import (
    CandidateConfigRegistrySource,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
    ManualConfigDraftRegistrySource,
    ManualConfigDraftResult,
    activate_config_registry_entry,
    current_config_registry_generation,
    list_config_registry_entries,
    load_active_config_registry_config,
    load_active_config_registry_entry,
    load_active_config_registry_state,
    preview_manual_config_draft,
    register_and_activate_config_profile,
    register_and_activate_manual_config_draft,
    register_config_profile,
    register_manual_config_draft,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
)
from scopecat.kernel.quantity import Quantity
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.parameter import ScalarParameterValue
from scopecat.records.parameter_change import (
    AutomaticPolicyDecisionAuthority,
    ParameterChangeProposal,
)
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat.runs.refs import record_content_ref
from tests.testkit.config_registry import (
    activate_candidate_config,
    decide_parameter_change_proposal,
    load_config,
    load_config_registry_config,
    load_config_registry_entry,
    register_candidate_config,
    review_parameter_change_proposal,
    signal_run_with_parameter_change,
)
from tests.testkit.runtime import (
    sqlite_config_registry_unit_of_work,
    sqlite_project_services,
    sqlite_run_repository,
)


@dataclass(frozen=True)
class _ResolvedCandidate:
    candidate: CandidateConfig
    config: ConfigProfileSnapshot


def test_register_config_profile_writes_and_activates_direct_entry(
    tmp_path: Path,
) -> None:
    config = load_config()
    entry = register_config_profile(
        config=config,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
        note="seed config",
    )

    assert isinstance(entry.source, DirectConfigRegistrySource)
    assert entry.config_ref == (
        "config-registry/configs/seed.config-profile-snapshot.json"
    )
    assert entry.content_hash == config_content_hash(config)
    persisted_config = load_config_registry_config(
        entry_id=entry.id,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
    )
    assert persisted_config == config

    entry, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="active-seed",
        registered_by="operator",
        operator="operator",
        note="seed active config",
    )
    assert active_state.active_entry_id == entry.id
    assert (
        load_active_config_registry_entry(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == entry
    )
    assert (
        load_active_config_registry_state(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == active_state
    )
    assert (
        load_active_config_registry_config(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == load_config()
    )


def test_registry_rejects_invalid_registration_before_storage(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed) as captured:
        register_config_profile(
            config=load_config(),
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id="seed",
            registered_by=" ",
        )

    assert captured.value.problems[0].code == ("config_registry.registered_by_missing")
    assert (
        list_config_registry_entries(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == []
    )


def test_manual_config_draft_preview_is_read_only_and_registration_records_source(
    tmp_path: Path,
) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    base, active_state = _seed_active_config_registry(tmp_path)
    entries_before = list_config_registry_entries(unit_of_work=unit_of_work)

    preview = preview_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=active_state.generation,
        candidate_id="manual-preview",
        updates=_manual_config_updates(),
    )

    assert isinstance(preview, ManualConfigDraftResult)
    assert preview.base_entry == base
    assert preview.base_generation == active_state.generation
    assert preview.check.ok
    assert preview.check.candidate is not None
    assert preview.check.candidate.id == "manual-preview"
    frequency = preview.check.candidate.parameter_snapshot.get("drive_frequency")
    assert frequency == ScalarParameterValue(
        id="drive_frequency",
        value=Quantity(value=5.2, unit="GHz"),
    )
    assert list_config_registry_entries(unit_of_work=unit_of_work) == entries_before
    assert load_active_config_registry_state(unit_of_work=unit_of_work) == active_state

    entry, registered = register_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=active_state.generation,
        candidate_id="manual-preview",
        updates=_manual_config_updates(),
        expected_result_content_hash=config_content_hash(
            preview.check.candidate,
        ),
        entry_id="manual-entry",
        registered_by="operator",
        note="adjust drive frequency",
    )

    assert registered.check.candidate == preview.check.candidate
    assert isinstance(entry.source, ManualConfigDraftRegistrySource)
    assert entry.source.base_entry_id == base.id
    assert entry.source.base_config_content_hash == base.content_hash
    assert entry.source.base_registry_generation == active_state.generation
    persisted = load_config_registry_entry(
        entry_id=entry.id,
        unit_of_work=unit_of_work,
    )
    assert persisted == entry
    assert isinstance(persisted.source, ManualConfigDraftRegistrySource)
    assert (
        load_config_registry_config(
            entry_id=entry.id,
            unit_of_work=unit_of_work,
        )
        == registered.check.candidate
    )
    assert load_active_config_registry_state(unit_of_work=unit_of_work) == active_state


@pytest.mark.parametrize(
    ("stale_field", "expected_code"),
    (
        ("generation", "config_registry.conflict"),
        ("content_hash", "config_registry.config_draft_base_changed"),
    ),
)
def test_manual_config_draft_registration_rejects_stale_base_identity(
    tmp_path: Path,
    stale_field: Literal["generation", "content_hash"],
    expected_code: str,
) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    base, active_state = _seed_active_config_registry(tmp_path)
    preview = preview_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=active_state.generation,
        candidate_id="stale-preview",
        updates=_manual_config_updates(),
    )
    assert preview.check.candidate is not None
    base_generation = active_state.generation
    base_content_hash = base.content_hash
    if stale_field == "generation":
        _newer, newer_state, _activation = register_and_activate_config_profile(
            config=load_config().model_copy(update={"id": "newer-config"}),
            unit_of_work=unit_of_work,
            entry_id="newer-entry",
            registered_by="operator",
            operator="operator",
            expected_generation=active_state.generation,
        )
        assert newer_state.generation == active_state.generation + 1
    else:
        base_content_hash = "sha256:" + ("0" * 64)

    with pytest.raises(Conflict) as error:
        register_manual_config_draft(
            unit_of_work=unit_of_work,
            base_entry_id=base.id,
            base_config_content_hash=base_content_hash,
            base_generation=base_generation,
            candidate_id="stale-preview",
            updates=_manual_config_updates(),
            expected_result_content_hash=config_content_hash(
                preview.check.candidate,
            ),
            entry_id=f"stale-{stale_field}",
            registered_by="operator",
        )

    assert error.value.problems[0].code == expected_code
    assert f"stale-{stale_field}" not in {
        entry.id for entry in list_config_registry_entries(unit_of_work=unit_of_work)
    }


def test_manual_config_draft_registration_rejects_changed_preview_result(
    tmp_path: Path,
) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    base, active_state = _seed_active_config_registry(tmp_path)

    with pytest.raises(Conflict) as error:
        register_manual_config_draft(
            unit_of_work=unit_of_work,
            base_entry_id=base.id,
            base_config_content_hash=base.content_hash,
            base_generation=active_state.generation,
            candidate_id="changed-result",
            updates=_manual_config_updates(),
            expected_result_content_hash="sha256:" + ("0" * 64),
            entry_id="changed-result",
            registered_by="operator",
        )

    assert error.value.problems[0].code == (
        "config_registry.config_draft_result_changed"
    )
    assert [
        entry.id for entry in list_config_registry_entries(unit_of_work=unit_of_work)
    ] == [base.id]
    assert load_active_config_registry_state(unit_of_work=unit_of_work) == active_state


def test_manual_config_draft_set_default_stale_conflict_leaves_no_entry(
    tmp_path: Path,
) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    base, active_state = _seed_active_config_registry(tmp_path)
    preview = preview_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=active_state.generation,
        candidate_id="stale-default",
        updates=_manual_config_updates(),
    )
    assert preview.check.candidate is not None
    newer, newer_state, _activation = register_and_activate_config_profile(
        config=load_config().model_copy(update={"id": "newer-config"}),
        unit_of_work=unit_of_work,
        entry_id="newer-entry",
        registered_by="operator",
        operator="operator",
        expected_generation=active_state.generation,
    )

    with pytest.raises(Conflict) as error:
        register_and_activate_manual_config_draft(
            unit_of_work=unit_of_work,
            base_entry_id=base.id,
            base_config_content_hash=base.content_hash,
            base_generation=active_state.generation,
            candidate_id="stale-default",
            updates=_manual_config_updates(),
            expected_result_content_hash=config_content_hash(
                preview.check.candidate,
            ),
            entry_id="stale-default",
            registered_by="operator",
            operator="operator",
        )

    assert error.value.problems[0].code == "config_registry.conflict"
    assert "stale-default" not in {
        entry.id for entry in list_config_registry_entries(unit_of_work=unit_of_work)
    }
    assert load_active_config_registry_state(unit_of_work=unit_of_work) == newer_state
    assert newer_state.active_entry_id == newer.id


def test_manual_config_draft_activation_rejects_a_stale_base(
    tmp_path: Path,
) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    base, active_state = _seed_active_config_registry(tmp_path)
    preview = preview_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=active_state.generation,
        candidate_id="manual-candidate",
        updates=_manual_config_updates(),
    )
    assert preview.check.candidate is not None
    manual, _registered = register_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=active_state.generation,
        candidate_id="manual-candidate",
        updates=_manual_config_updates(),
        expected_result_content_hash=config_content_hash(preview.check.candidate),
        entry_id="manual-candidate",
        registered_by="operator",
    )
    newer, newer_state, _activation = register_and_activate_config_profile(
        config=load_config().model_copy(update={"id": "newer-config"}),
        unit_of_work=unit_of_work,
        entry_id="newer-entry",
        registered_by="operator",
        operator="operator",
        expected_generation=active_state.generation,
    )

    with pytest.raises(Conflict) as error:
        activate_config_registry_entry(
            entry_id=manual.id,
            unit_of_work=unit_of_work,
            operator="operator",
            expected_generation=newer_state.generation,
        )

    assert error.value.problems[0].code == "config_registry.stale_candidate"
    assert load_active_config_registry_state(unit_of_work=unit_of_work) == newer_state
    assert newer_state.active_entry_id == newer.id


def test_candidate_config_registers_and_activates_parameter_proposal(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
    )
    candidate = CandidateConfig(
        parameter_proposal=proposal,
    )
    decision = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
        state="approved",
        reviewer="operator",
        note="looks good",
    )

    activation_result = activate_candidate_config(
        candidate=candidate,
        services=sqlite_project_services(tmp_path),
        entry_id="candidate-best-signal",
        registered_by="operator",
        operator="operator",
        note="looks good",
    )

    assert decision.decision == "approved"
    entry = activation_result.entry
    active_state = activation_result.active_state
    activation = activation_result.activation
    assert isinstance(entry.source, CandidateConfigRegistrySource)
    assert entry.source.run_id == run_id
    assert entry.source.proposal_id == "best-signal"
    evidence = entry.source.proposal_evidence
    assert evidence.proposal_id == proposal.id
    assert evidence.approval_event_id == decision.event_id
    assert evidence.proposal_record_content_hash.startswith("sha256:")
    assert evidence.approval_record_content_hash.startswith("sha256:")
    assert active_state.active_entry_id == entry.id

    stored_proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
    )
    assert stored_proposal == proposal
    assert active_state.history[-1] == activation

    config, source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
    )
    assert source.kind == "config_registry"
    assert source.entry_id == entry.id
    assert source.config_ref == entry.config_ref
    assert source.content_hash == entry.content_hash
    assert source.registry_generation == active_state.generation
    assert config == load_config_registry_config(
        entry_id=entry.id, unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
    )


def test_automatic_policy_approval_can_activate_candidate_without_verification(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
    )
    candidate = CandidateConfig(parameter_proposal=proposal)
    authority = AutomaticPolicyDecisionAuthority(
        actor="calibration-scheduler",
        policy_id="accept-high-confidence-fit",
        policy_version="1",
    )
    decision = decide_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=sqlite_project_services(tmp_path),
        decision="approved",
        authority=authority,
    )

    result = activate_candidate_config(
        candidate=candidate,
        services=sqlite_project_services(tmp_path),
        entry_id="automatic-policy-candidate",
        registered_by="calibration-scheduler",
        operator="calibration-scheduler",
    )

    assert result.active_state.active_entry_id == result.entry.id
    assert isinstance(result.entry.source, CandidateConfigRegistrySource)
    assert result.entry.source.proposal_evidence.approval_event_id == (
        decision.event_id
    )
    assert list_parameter_change_decisions(
        run_id=run_id,
        selector=proposal.id,
        storage=sqlite_run_repository(tmp_path),
    ) == [decision]
    assert decision.authority == authority


def test_later_approval_preserves_registered_candidate_evidence(
    tmp_path: Path,
) -> None:
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    entry = register_candidate_config(
        config=resolved.config,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="candidate-original-approval",
        registered_by="operator",
        run_id=run_id,
        proposal_id=resolved.candidate.proposal_id,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )
    assert isinstance(entry.source, CandidateConfigRegistrySource)
    original_event_id = entry.source.proposal_evidence.approval_event_id
    later = review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=sqlite_project_services(tmp_path),
        state="approved",
        reviewer="second-reviewer",
    )

    loaded = load_config_registry_entry(
        entry_id=entry.id,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
    )

    assert loaded == entry
    assert isinstance(loaded.source, CandidateConfigRegistrySource)
    assert loaded.source.proposal_evidence.approval_event_id == original_event_id
    assert later.event_id != original_event_id


def test_candidate_activation_rejects_a_stale_base_config(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
    )
    candidate = CandidateConfig(
        parameter_proposal=proposal,
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
        state="approved",
        reviewer="operator",
    )
    newer_config = load_config().model_copy(update={"id": "newer-base"})
    _entry, active_state, _activation = register_and_activate_config_profile(
        config=newer_config,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="newer-base",
        registered_by="operator",
        operator="operator",
    )

    with pytest.raises(Conflict) as error:
        activate_candidate_config(
            candidate=candidate,
            services=sqlite_project_services(tmp_path),
            entry_id="stale-candidate",
            registered_by="operator",
            operator="operator",
        )

    assert error.value.problems[0].code == "config_registry.stale_candidate"
    assert (
        load_active_config_registry_state(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == active_state
    )


@pytest.mark.parametrize("decision", (None, "rejected"))
def test_candidate_registration_requires_latest_approval(
    tmp_path: Path,
    decision: str | None,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
    )
    candidate = CandidateConfig(
        parameter_proposal=proposal,
    )
    config = resolve_candidate_config_snapshot(
        candidate, services=sqlite_project_services(tmp_path)
    )
    if decision == "rejected":
        review_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            services=sqlite_project_services(tmp_path),
            state="rejected",
            reviewer="reviewer",
        )
    with pytest.raises(Conflict) as error:
        register_candidate_config(
            config=config,
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id=f"not-approved-{decision or 'missing'}",
            registered_by="operator",
            run_id=run_id,
            proposal_id=candidate.proposal_id,
            base_config_content_hash=candidate.base_config_content_hash,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_proposal_not_approved"
    )


def test_later_rejection_does_not_revoke_registered_candidate(
    tmp_path: Path,
) -> None:
    _base, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="base",
        registered_by="operator",
        operator="operator",
    )
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    entry = register_candidate_config(
        config=resolved.config,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="candidate",
        registered_by="operator",
        run_id=run_id,
        proposal_id=resolved.candidate.proposal_id,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=sqlite_project_services(tmp_path),
        state="rejected",
        reviewer="reviewer",
    )

    loaded = load_config_registry_entry(
        entry_id=entry.id,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
    )
    listed = list_config_registry_entries(
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
    )
    config, source = resolve_config_registry_config_source(
        selector=entry.id,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
    )
    activated, _record = activate_config_registry_entry(
        entry_id=entry.id,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=active_state.generation,
    )

    assert loaded == entry
    assert entry in listed
    assert config == resolved.config
    assert isinstance(source, ConfigRegistryRunConfigSource)
    assert source.entry_id == entry.id
    assert activated.active_entry_id == entry.id


def test_later_rejection_does_not_break_active_candidate_rollback(
    tmp_path: Path,
) -> None:
    base, base_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="rollback-base",
        registered_by="operator",
        operator="operator",
    )
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    candidate = activate_candidate_config(
        candidate=resolved.candidate,
        services=sqlite_project_services(tmp_path),
        entry_id="active-candidate",
        registered_by="operator",
        operator="operator",
        expected_generation=base_state.generation,
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=sqlite_project_services(tmp_path),
        state="rejected",
        reviewer="reviewer",
    )

    assert (
        load_active_config_registry_entry(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == candidate.entry
    )
    restored, record = rollback_config_registry(
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=candidate.active_state.generation,
        note="return to base",
    )

    assert restored.generation == candidate.active_state.generation + 1
    assert restored.active_entry_id == base.id
    assert record.action == "rollback"
    assert record.previous_entry_id == candidate.entry.id


def test_rollback_can_restore_candidate_after_later_rejection(
    tmp_path: Path,
) -> None:
    _base, base_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="target-base",
        registered_by="operator",
        operator="operator",
    )
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    candidate = activate_candidate_config(
        candidate=resolved.candidate,
        services=sqlite_project_services(tmp_path),
        entry_id="rollback-target-candidate",
        registered_by="operator",
        operator="operator",
        expected_generation=base_state.generation,
    )
    current, current_state, _current_activation = register_and_activate_config_profile(
        config=load_config().model_copy(update={"id": "target-current"}),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="target-current",
        registered_by="operator",
        operator="operator",
        expected_generation=candidate.active_state.generation,
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=sqlite_project_services(tmp_path),
        state="rejected",
        reviewer="reviewer",
    )

    restored, record = rollback_config_registry(
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=current_state.generation,
    )

    assert restored.active_entry_id == candidate.entry.id
    assert restored.generation == current_state.generation + 1
    assert record.entry_id == candidate.entry.id
    assert record.previous_entry_id == current.id


def test_activation_generation_is_append_only_and_rejects_stale_writes(
    tmp_path: Path,
) -> None:
    first, first_state, first_record = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
    )
    second = register_config_profile(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="seed-b",
        registered_by="operator",
    )

    assert first_state.generation == 1
    assert first_record.generation == 1
    assert (
        current_config_registry_generation(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == 1
    )
    resolved_first, first_source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
    )

    second_state, second_record = activate_config_registry_entry(
        entry_id=second.id,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=1,
    )
    with pytest.raises(Conflict) as error:
        activate_config_registry_entry(
            entry_id=first.id,
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            operator="stale-operator",
            expected_generation=1,
        )

    assert error.value.problems[0].code == "config_registry.conflict"
    unchanged = load_active_config_registry_state(
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
    )
    assert unchanged == second_state
    assert [record.generation for record in unchanged.history] == [1, 2]
    assert second_record.previous_entry_content_hash == first.content_hash
    assert isinstance(first_source, ConfigRegistryRunConfigSource)
    assert first_source.entry_id == first.id
    assert first_source.content_hash == first.content_hash
    assert first_source.registry_generation == 1
    assert config_content_hash(resolved_first) == first_source.content_hash

    rolled_back, rollback_record = rollback_config_registry(
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=2,
    )
    assert rolled_back.generation == 3
    assert rolled_back.active_entry_id == first.id
    assert rollback_record.generation == 3
    assert [record.generation for record in rolled_back.history] == [1, 2, 3]


def test_activation_runs_full_config_semantic_validation(tmp_path: Path) -> None:
    config = load_config()
    invalid_binding = config.routing.bindings[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid_config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "routing": config.routing.model_copy(
                        update={"bindings": [invalid_binding]}
                    )
                }
            )
        }
    )
    entry = register_config_profile(
        config=invalid_config,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="invalid",
        registered_by="operator",
    )

    with pytest.raises(CheckFailed) as error:
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=0,
        )

    assert error.value.problems[0].code == (
        "configuration.unknown_routing_binding_instrument"
    )
    assert (
        current_config_registry_generation(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == 0
    )


def test_concurrent_registrations_preserve_every_index_entry(tmp_path: Path) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    barrier = Barrier(2)

    def register(entry_id: str) -> str:
        barrier.wait()
        return register_config_profile(
            config=load_config(),
            unit_of_work=unit_of_work,
            entry_id=entry_id,
            registered_by="operator",
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        registered = set(executor.map(register, ("seed-a", "seed-b")))

    assert registered == {"seed-a", "seed-b"}
    assert {
        entry.id for entry in list_config_registry_entries(unit_of_work=unit_of_work)
    } == (registered)


def test_concurrent_composite_activations_apply_one_generation(
    tmp_path: Path,
) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    _seed, initial_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=unit_of_work,
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    barrier = Barrier(2)

    def activate(entry_id: str) -> tuple[str, str]:
        barrier.wait()
        try:
            result = register_and_activate_config_profile(
                config=load_config().model_copy(update={"id": entry_id}),
                unit_of_work=unit_of_work,
                entry_id=entry_id,
                registered_by="operator",
                operator="operator",
                expected_generation=initial_state.generation,
            )
        except Conflict as error:
            return "error", error.problems[0].code
        return "activated", result[0].id

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(activate, ("candidate-a", "candidate-b")))

    assert sorted(status for status, _detail in outcomes) == ["activated", "error"]
    assert next(detail for status, detail in outcomes if status == "error") == (
        "config_registry.conflict"
    )
    state = load_active_config_registry_state(unit_of_work=unit_of_work)
    assert state.generation == initial_state.generation + 1
    assert len(list_config_registry_entries(unit_of_work=unit_of_work)) == 2


def test_candidate_registration_rejects_changes_not_derived_from_proposals(
    tmp_path: Path,
) -> None:
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    forged = resolved.config.model_copy(
        update={
            "system": resolved.config.system.model_copy(
                update={"id": "not-derived-from-proposals"}
            )
        }
    )

    with pytest.raises(Conflict) as error:
        register_candidate_config(
            config=forged,
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id="forged-candidate",
            registered_by="operator",
            run_id=run_id,
            proposal_id=resolved.candidate.proposal_id,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_derivation_mismatch"
    )
    assert (
        list_config_registry_entries(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == []
    )


@pytest.mark.parametrize(
    "proposal_update",
    (
        {"source_run_id": "different-run"},
        {"base_config_id": "different-config"},
    ),
)
def test_candidate_registration_validates_durable_proposal_source(
    tmp_path: Path,
    proposal_update: dict[str, str],
) -> None:
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    storage = sqlite_run_repository(tmp_path)
    storage.write_model(
        run_id,
        record_content_ref(
            record_id=proposal.id,
            kind="parameter_change_proposal",
        ),
        proposal.model_copy(update=proposal_update),
    )

    with pytest.raises(DataIntegrityError) as error:
        register_candidate_config(
            config=resolved.config,
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id="invalid-proposal-source",
            registered_by="operator",
            run_id=run_id,
            proposal_id=resolved.candidate.proposal_id,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_proposal_mismatch"
    )


def test_candidate_registration_does_not_ignore_operator_metadata(
    tmp_path: Path,
) -> None:
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    register_candidate_config(
        config=resolved.config,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="candidate-metadata",
        registered_by="operator-a",
        note="first review",
        run_id=run_id,
        proposal_id=resolved.candidate.proposal_id,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )

    with pytest.raises(Conflict) as error:
        register_candidate_config(
            config=resolved.config,
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id="candidate-metadata",
            registered_by="operator-b",
            note="different review",
            run_id=run_id,
            proposal_id=resolved.candidate.proposal_id,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.problems[0].code == "config_registry.duplicate_entry"


def _resolved_candidate(
    project_root: Path,
) -> tuple[str, ParameterChangeProposal, _ResolvedCandidate]:
    run_id = signal_run_with_parameter_change(project_root)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(project_root),
    )
    candidate = CandidateConfig(
        parameter_proposal=proposal,
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=sqlite_project_services(project_root),
        state="approved",
        reviewer="operator",
    )
    return (
        run_id,
        proposal,
        _ResolvedCandidate(
            candidate=candidate,
            config=resolve_candidate_config_snapshot(
                candidate,
                services=sqlite_project_services(project_root),
            ),
        ),
    )


def _seed_active_config_registry(
    project_root: Path,
) -> tuple[ConfigRegistryEntry, ConfigRegistryActiveState]:
    entry, state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(project_root),
        entry_id="manual-base",
        registered_by="operator",
        operator="operator",
    )
    return entry, state


def _manual_config_updates() -> tuple[ParameterUpdate, ...]:
    return (
        replace_scalar_parameter(
            "drive_frequency",
            Quantity(value=5.2, unit="GHz"),
        ),
    )
