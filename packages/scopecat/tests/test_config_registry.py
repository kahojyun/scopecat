from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

import scopecat._workflows.config as config_workflow
from scopecat._storage.refs import record_content_ref
from scopecat._workflows.config import register_and_activate_candidate_config
from scopecat.candidate_configs import (
    CandidateConfig,
    ResolvedCandidateConfig,
    resolve_candidate_config,
)
from scopecat.config_registry import (
    CandidateConfigRegistrySource,
    ConfigRegistryIndex,
    DirectConfigRegistrySource,
    activate_config_registry_entry,
    current_config_registry_generation,
    list_config_registry_entries,
    load_active_config_registry_config,
    load_active_config_registry_entry,
    load_active_config_registry_state,
    load_config_registry_config,
    load_config_registry_entry,
    register_and_activate_config_profile,
    register_candidate_config,
    register_config_profile,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.errors import ValidationFailed
from scopecat.models.config import config_content_hash
from scopecat.models.parameter_change import ParameterChangeProposal
from scopecat.parameter_changes import (
    ParameterChangeDecisionRecord,
    invalidate_parameter_change_proposal,
    load_parameter_change_proposal,
    review_parameter_change_proposal,
)
from scopecat.runs import open_run_store
from tests.support.config_registry import (
    load_config,
    signal_run_with_parameter_change,
)


def test_register_config_profile_writes_and_activates_direct_entry(
    tmp_path: Path,
) -> None:
    config = load_config()
    entry = register_config_profile(
        config=config,
        workspace=tmp_path,
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
        workspace=tmp_path,
    )
    assert persisted_config == config

    entry, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="active-seed",
        registered_by="operator",
        operator="operator",
        note="seed active config",
    )
    assert active_state.active_entry_id == entry.id
    assert load_active_config_registry_entry(workspace=tmp_path) == entry
    assert load_active_config_registry_state(workspace=tmp_path) == active_state
    assert load_active_config_registry_config(workspace=tmp_path) == load_config()


def test_candidate_config_registers_and_activates_parameter_proposal(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    candidate = CandidateConfig(
        analysis_title="best signal fixture",
        analysis_key="best-signal",
        parameter_proposals=(proposal,),
    )
    decision = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
        note="looks good",
    )

    activation_result = register_and_activate_candidate_config(
        candidate=candidate,
        workspace=tmp_path,
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
    assert entry.source.proposal_ids == ["best-signal"]
    assert entry.source.candidate_record_id
    evidence = entry.source.proposal_evidence[0]
    assert evidence.proposal_id == proposal.id
    assert evidence.approval_event_id == decision.event_id
    assert evidence.proposal_record_content_hash.startswith("sha256:")
    assert evidence.approval_record_content_hash.startswith("sha256:")
    assert entry.source.candidate_record_content_hash.startswith("sha256:")
    with pytest.raises(ValidationError):
        entry.source.model_copy(
            update={"candidate_record_content_hash": "not-a-content-hash"}
        )
    assert active_state.active_entry_id == entry.id

    stored_proposal = load_parameter_change_proposal(
        run_id=run_id, selector="best-signal", workspace=tmp_path
    )
    assert stored_proposal == proposal
    assert active_state.history[-1] == activation

    config, source = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    assert source.kind == "config_registry"
    assert source.entry_id == entry.id
    assert source.config_ref == entry.config_ref
    assert source.content_hash == entry.content_hash
    assert source.registry_generation == active_state.generation
    assert config == load_config_registry_config(entry_id=entry.id, workspace=tmp_path)


def test_candidate_activation_rejects_a_stale_base_config(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    candidate = CandidateConfig(
        analysis_title="best signal fixture",
        analysis_key="best-signal",
        parameter_proposals=(proposal,),
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
    )
    newer_config = load_config().model_copy(
        update={"metadata": {"config_revision": "newer"}}
    )
    _entry, active_state, _activation = register_and_activate_config_profile(
        config=newer_config,
        workspace=tmp_path,
        entry_id="newer-base",
        registered_by="operator",
        operator="operator",
    )

    with pytest.raises(ValidationFailed) as error:
        register_and_activate_candidate_config(
            candidate=candidate,
            workspace=tmp_path,
            entry_id="stale-candidate",
            registered_by="operator",
            operator="operator",
        )

    assert error.value.diagnostics[0].code == "config_registry_stale_candidate"
    assert load_active_config_registry_state(workspace=tmp_path) == active_state


@pytest.mark.parametrize("decision", (None, "rejected", "invalidated"))
def test_candidate_registration_requires_latest_approval(
    tmp_path: Path,
    decision: str | None,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    candidate = resolve_candidate_config(
        CandidateConfig(
            analysis_title="review gate",
            analysis_key="review-gate",
            parameter_proposals=(proposal,),
        ),
        workspace=tmp_path,
    )
    if decision == "rejected":
        review_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            workspace=tmp_path,
            state="rejected",
            reviewer="reviewer",
        )
    elif decision == "invalidated":
        review_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            workspace=tmp_path,
            state="approved",
            reviewer="reviewer",
        )
        invalidate_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            workspace=tmp_path,
            reason="superseded",
            invalidated_by="reviewer",
        )

    with pytest.raises(ValidationFailed) as error:
        register_candidate_config(
            config=candidate.config,
            workspace=tmp_path,
            entry_id=f"not-approved-{decision or 'missing'}",
            registered_by="operator",
            run_id=run_id,
            proposal_ids=candidate.candidate.proposal_ids,
            candidate_record_id=candidate.candidate_config_record_id,
            base_config_content_hash=candidate.candidate.base_config_content_hash,
        )

    assert error.value.diagnostics[0].code == (
        "config_registry_candidate_proposal_not_approved"
    )


def test_candidate_invalidation_after_registration_blocks_load_and_activation(
    tmp_path: Path,
) -> None:
    _base, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="base",
        registered_by="operator",
        operator="operator",
    )
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    entry = register_candidate_config(
        config=resolved.config,
        workspace=tmp_path,
        entry_id="candidate",
        registered_by="operator",
        run_id=run_id,
        proposal_ids=resolved.candidate.proposal_ids,
        candidate_record_id=resolved.candidate_config_record_id,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )
    invalidate_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        workspace=tmp_path,
        reason="new evidence",
        invalidated_by="reviewer",
    )

    with pytest.raises(ValidationFailed) as load_error:
        load_config_registry_entry(entry_id=entry.id, workspace=tmp_path)
    with pytest.raises(ValidationFailed) as activation_error:
        activate_config_registry_entry(
            entry_id=entry.id,
            workspace=tmp_path,
            operator="operator",
            expected_generation=active_state.generation,
        )

    assert load_error.value.diagnostics[0].code == (
        "config_registry_candidate_proposal_not_approved"
    )
    assert activation_error.value.diagnostics[0].code == (
        "config_registry_candidate_proposal_not_approved"
    )
    assert load_active_config_registry_state(workspace=tmp_path) == active_state


def test_activation_generation_is_append_only_and_rejects_stale_writes(
    tmp_path: Path,
) -> None:
    first, first_state, first_record = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
    )
    second = register_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed-b",
        registered_by="operator",
    )

    assert first_state.generation == 1
    assert first_record.generation == 1
    assert current_config_registry_generation(workspace=tmp_path) == 1
    resolved_first, first_source = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )

    second_state, second_record = activate_config_registry_entry(
        entry_id=second.id,
        workspace=tmp_path,
        operator="operator",
        expected_generation=1,
    )
    with pytest.raises(ValidationFailed) as error:
        activate_config_registry_entry(
            entry_id=first.id,
            workspace=tmp_path,
            operator="stale-operator",
            expected_generation=1,
        )

    assert error.value.diagnostics[0].code == "config_registry_conflict"
    unchanged = load_active_config_registry_state(workspace=tmp_path)
    assert unchanged == second_state
    assert [record.generation for record in unchanged.history] == [1, 2]
    assert second_record.previous_entry_content_hash == first.content_hash
    assert first_source.entry_id == first.id
    assert first_source.content_hash == first.content_hash
    assert first_source.registry_generation == 1
    assert config_content_hash(resolved_first) == first_source.content_hash

    rolled_back, rollback_record = rollback_config_registry(
        workspace=tmp_path,
        operator="operator",
        expected_generation=2,
    )
    assert rolled_back.generation == 3
    assert rolled_back.active_entry_id == first.id
    assert rollback_record.generation == 3
    assert [record.generation for record in rolled_back.history] == [1, 2, 3]


def test_activation_runs_full_config_semantic_validation(tmp_path: Path) -> None:
    config = load_config()
    invalid_connection = config.connection_profile.connections[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid_config = config.model_copy(
        update={
            "environment": config.environment.model_copy(
                update={
                    "connection_profile": config.connection_profile.model_copy(
                        update={"connections": [invalid_connection]}
                    )
                }
            )
        }
    )
    entry = register_config_profile(
        config=invalid_config,
        workspace=tmp_path,
        entry_id="invalid",
        registered_by="operator",
    )

    with pytest.raises(ValidationFailed) as error:
        activate_config_registry_entry(
            entry_id=entry.id,
            workspace=tmp_path,
            operator="operator",
            expected_generation=0,
        )

    assert error.value.diagnostics[0].code == "unknown_connection_instrument"
    assert current_config_registry_generation(workspace=tmp_path) == 0


def test_registry_rejects_snapshot_content_that_no_longer_matches_entry(
    tmp_path: Path,
) -> None:
    config = load_config()
    entry = register_config_profile(
        config=config,
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
    )
    tampered = config.model_copy(update={"metadata": {"tampered": True}})
    (tmp_path / entry.config_ref).write_text(tampered.model_dump_json())

    with pytest.raises(ValidationFailed) as error:
        load_config_registry_config(entry_id=entry.id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == ("config_registry_content_hash_mismatch")


def test_concurrent_registrations_preserve_every_index_entry(tmp_path: Path) -> None:
    barrier = Barrier(2)

    def register(entry_id: str) -> str:
        barrier.wait()
        return register_config_profile(
            config=load_config(),
            workspace=tmp_path,
            entry_id=entry_id,
            registered_by="operator",
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        registered = set(executor.map(register, ("seed-a", "seed-b")))

    assert registered == {"seed-a", "seed-b"}
    assert {entry.id for entry in list_config_registry_entries(workspace=tmp_path)} == (
        registered
    )
    assert not list((tmp_path / "config-registry").rglob("*.tmp"))


def test_concurrent_composite_activations_apply_one_generation(
    tmp_path: Path,
) -> None:
    _seed, initial_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    barrier = Barrier(2)

    def activate(entry_id: str) -> tuple[str, str]:
        barrier.wait()
        try:
            result = register_and_activate_config_profile(
                config=load_config().model_copy(
                    update={"metadata": {"entry_id": entry_id}}
                ),
                workspace=tmp_path,
                entry_id=entry_id,
                registered_by="operator",
                operator="operator",
                expected_generation=initial_state.generation,
            )
        except ValidationFailed as error:
            return "error", error.diagnostics[0].code
        return "activated", result[0].id

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(activate, ("candidate-a", "candidate-b")))

    assert sorted(status for status, _detail in outcomes) == ["activated", "error"]
    assert next(detail for status, detail in outcomes if status == "error") == (
        "config_registry_conflict"
    )
    state = load_active_config_registry_state(workspace=tmp_path)
    assert state.generation == initial_state.generation + 1
    assert len(list_config_registry_entries(workspace=tmp_path)) == 2


def test_idempotent_registration_repairs_a_missing_index_commit(
    tmp_path: Path,
) -> None:
    first = register_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed-a",
        registered_by="operator",
    )
    index_path = tmp_path / "config-registry" / "index.json"
    committed_index = index_path.read_text()
    second = register_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed-b",
        registered_by="operator",
    )
    # Simulate a crash after seed-b's config and entry commits but before the
    # index commit marker is replaced.
    index_path.write_text(committed_index)

    with pytest.raises(ValidationFailed) as uncommitted:
        load_config_registry_entry(entry_id="seed-b", workspace=tmp_path)
    assert uncommitted.value.diagnostics[0].code == (
        "config_registry_uncommitted_entry"
    )

    repeated = register_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed-b",
        registered_by="operator",
    )

    assert repeated == second
    assert list_config_registry_entries(workspace=tmp_path) == [first, second]


def test_list_rejects_tampered_entry_and_config_files(tmp_path: Path) -> None:
    config = load_config()
    entry = register_config_profile(
        config=config,
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
    )
    tampered = config.model_copy(update={"metadata": {"tampered": True}})
    tampered_entry = entry.model_copy(
        update={"content_hash": config_content_hash(tampered)}
    )
    (tmp_path / entry.config_ref).write_text(tampered.model_dump_json())
    (tmp_path / "config-registry/entries/seed.json").write_text(
        tampered_entry.model_dump_json()
    )

    with pytest.raises(ValidationFailed) as error:
        list_config_registry_entries(workspace=tmp_path)

    assert error.value.diagnostics[0].code == ("config_registry_index_entry_mismatch")


def test_candidate_registration_is_bound_to_its_durable_record(
    tmp_path: Path,
) -> None:
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    forged = resolved.config.model_copy(
        update={"metadata": {"not_from_candidate_record": True}}
    )

    with pytest.raises(ValidationFailed) as error:
        register_candidate_config(
            config=forged,
            workspace=tmp_path,
            entry_id="forged-candidate",
            registered_by="operator",
            run_id=run_id,
            proposal_ids=resolved.candidate.proposal_ids,
            candidate_record_id=resolved.candidate_config_record_id,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.diagnostics[0].code == (
        "config_registry_candidate_record_mismatch"
    )
    assert list_config_registry_entries(workspace=tmp_path) == []


def test_candidate_record_must_be_derived_from_its_proposals(tmp_path: Path) -> None:
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    storage = open_run_store(tmp_path)
    forged = resolved.config.model_copy(
        update={"metadata": {"not_derived_from_proposals": True}}
    )
    storage.write_model(
        run_id,
        record_content_ref(
            record_id=resolved.candidate_config_record.id,
            kind=resolved.candidate_config_record.kind,
        ),
        forged,
    )

    with pytest.raises(ValidationFailed) as error:
        register_candidate_config(
            config=forged,
            workspace=tmp_path,
            entry_id="forged-derivation",
            registered_by="operator",
            run_id=run_id,
            proposal_ids=resolved.candidate.proposal_ids,
            candidate_record_id=resolved.candidate_config_record_id,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.diagnostics[0].code == (
        "config_registry_candidate_derivation_mismatch"
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
    storage = open_run_store(tmp_path)
    proposal_record = resolved.proposal_records[0]
    storage.write_model(
        run_id,
        record_content_ref(
            record_id=proposal_record.id,
            kind=proposal_record.kind,
        ),
        proposal.model_copy(update=proposal_update),
    )

    with pytest.raises(ValidationFailed) as error:
        register_candidate_config(
            config=resolved.config,
            workspace=tmp_path,
            entry_id="invalid-proposal-source",
            registered_by="operator",
            run_id=run_id,
            proposal_ids=resolved.candidate.proposal_ids,
            candidate_record_id=resolved.candidate_config_record_id,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.diagnostics[0].code == (
        "config_registry_candidate_proposal_mismatch"
    )


@pytest.mark.parametrize(
    ("target", "expected_code"),
    (
        ("proposal", "config_registry_candidate_evidence_mismatch"),
        ("candidate", "config_registry_candidate_record_mismatch"),
        ("approval", "config_registry_candidate_evidence_mismatch"),
    ),
)
def test_candidate_load_revalidates_content_addressed_evidence(
    tmp_path: Path,
    target: str,
    expected_code: str,
) -> None:
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    entry = register_candidate_config(
        config=resolved.config,
        workspace=tmp_path,
        entry_id="candidate-evidence",
        registered_by="operator",
        run_id=run_id,
        proposal_ids=resolved.candidate.proposal_ids,
        candidate_record_id=resolved.candidate_config_record_id,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )
    assert isinstance(entry.source, CandidateConfigRegistrySource)
    storage = open_run_store(tmp_path)
    if target == "proposal":
        storage.write_model(
            run_id,
            record_content_ref(
                record_id=proposal.id,
                kind="parameter_change_proposal",
            ),
            proposal.model_copy(update={"reason": "tampered"}),
        )
    elif target == "candidate":
        storage.write_model(
            run_id,
            record_content_ref(
                record_id=resolved.candidate_config_record.id,
                kind=resolved.candidate_config_record.kind,
            ),
            resolved.config.model_copy(update={"metadata": {"tampered": True}}),
        )
    else:
        evidence = entry.source.proposal_evidence[0]
        decision_entry_id = f"{proposal.id}-decision-{evidence.approval_event_id}"
        decision_ref = record_content_ref(
            record_id=decision_entry_id,
            kind="parameter_change_decision_record",
        )
        decision = storage.read_model(
            run_id,
            decision_ref,
            ParameterChangeDecisionRecord,
        )
        storage.write_model(
            run_id,
            decision_ref,
            decision.model_copy(update={"actor": "tampered"}),
        )

    with pytest.raises(ValidationFailed) as error:
        load_config_registry_entry(entry_id=entry.id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == expected_code


def test_candidate_registration_does_not_ignore_operator_metadata(
    tmp_path: Path,
) -> None:
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    register_candidate_config(
        config=resolved.config,
        workspace=tmp_path,
        entry_id="candidate-metadata",
        registered_by="operator-a",
        note="first review",
        run_id=run_id,
        proposal_ids=resolved.candidate.proposal_ids,
        candidate_record_id=resolved.candidate_config_record_id,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )

    with pytest.raises(ValidationFailed) as error:
        register_candidate_config(
            config=resolved.config,
            workspace=tmp_path,
            entry_id="candidate-metadata",
            registered_by="operator-b",
            note="different review",
            run_id=run_id,
            proposal_ids=resolved.candidate.proposal_ids,
            candidate_record_id=resolved.candidate_config_record_id,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.diagnostics[0].code == "config_registry_duplicate_entry"


def test_candidate_workflow_captures_generation_before_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    candidate = CandidateConfig(
        analysis_title="best signal fixture",
        analysis_key="best-signal",
        parameter_proposals=(proposal,),
    )
    register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    original_resolve = resolve_candidate_config

    def resolve_with_intervening_activation(
        selected: CandidateConfig,
        *,
        workspace: str | Path,
    ) -> ResolvedCandidateConfig:
        resolved = original_resolve(selected, workspace=workspace)
        register_and_activate_config_profile(
            config=load_config(),
            workspace=workspace,
            entry_id="intervening",
            registered_by="operator",
            operator="operator",
        )
        return resolved

    monkeypatch.setattr(
        config_workflow,
        "resolve_candidate_config",
        resolve_with_intervening_activation,
    )

    with pytest.raises(ValidationFailed) as error:
        register_and_activate_candidate_config(
            candidate=candidate,
            workspace=tmp_path,
            entry_id="candidate-after-race",
            registered_by="operator",
            operator="operator",
        )

    assert error.value.diagnostics[0].code == "config_registry_conflict"
    with pytest.raises(ValidationFailed) as missing:
        load_config_registry_entry(
            entry_id="candidate-after-race",
            workspace=tmp_path,
        )
    assert missing.value.diagnostics[0].code == "config_registry_not_found"


def test_activation_validates_the_current_active_snapshot_before_stale_check(
    tmp_path: Path,
) -> None:
    _seed, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    candidate_entry = register_candidate_config(
        config=resolved.config,
        workspace=tmp_path,
        entry_id="candidate",
        registered_by="operator",
        run_id=run_id,
        proposal_ids=resolved.candidate.proposal_ids,
        candidate_record_id=resolved.candidate_config_record_id,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )
    tampered = load_config().model_copy(update={"metadata": {"tampered": True}})
    (tmp_path / "config-registry/configs/seed.config-profile-snapshot.json").write_text(
        tampered.model_dump_json()
    )

    with pytest.raises(ValidationFailed) as error:
        activate_config_registry_entry(
            entry_id=candidate_entry.id,
            workspace=tmp_path,
            operator="operator",
            expected_generation=active_state.generation,
        )

    assert error.value.diagnostics[0].code == ("config_registry_content_hash_mismatch")
    assert load_active_config_registry_state(workspace=tmp_path) == active_state


def test_same_entry_reactivation_still_validates_active_integrity(
    tmp_path: Path,
) -> None:
    entry, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    tampered = load_config().model_copy(update={"metadata": {"tampered": True}})
    (tmp_path / entry.config_ref).write_text(tampered.model_dump_json())

    with pytest.raises(ValidationFailed) as error:
        activate_config_registry_entry(
            entry_id=entry.id,
            workspace=tmp_path,
            operator="operator",
            expected_generation=active_state.generation,
        )

    assert error.value.diagnostics[0].code == ("config_registry_content_hash_mismatch")


def test_rollback_requires_the_historical_target_content_hash(tmp_path: Path) -> None:
    first, _first_state, _first_activation = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
    )
    _second, second_state, _second_activation = register_and_activate_config_profile(
        config=load_config().model_copy(update={"metadata": {"revision": "b"}}),
        workspace=tmp_path,
        entry_id="seed-b",
        registered_by="operator",
        operator="operator",
    )
    drifted = load_config().model_copy(update={"metadata": {"revision": "drifted"}})
    drifted_entry = first.model_copy(
        update={"content_hash": config_content_hash(drifted)}
    )
    (tmp_path / first.config_ref).write_text(drifted.model_dump_json())
    (tmp_path / "config-registry/entries/seed-a.json").write_text(
        drifted_entry.model_dump_json()
    )
    index_path = tmp_path / "config-registry/index.json"
    index = ConfigRegistryIndex.model_validate_json(index_path.read_text())
    index_path.write_text(
        index.model_copy(
            update={
                "entries": [
                    drifted_entry if entry.id == first.id else entry
                    for entry in index.entries
                ]
            }
        ).model_dump_json()
    )

    with pytest.raises(ValidationFailed) as error:
        rollback_config_registry(
            workspace=tmp_path,
            operator="operator",
            expected_generation=second_state.generation,
        )

    assert error.value.diagnostics[0].code == (
        "config_registry_rollback_content_mismatch"
    )


def _resolved_candidate(
    workspace: Path,
) -> tuple[str, ParameterChangeProposal, ResolvedCandidateConfig]:
    run_id = signal_run_with_parameter_change(workspace)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=workspace,
    )
    candidate = CandidateConfig(
        analysis_title="best signal fixture",
        analysis_key="best-signal",
        parameter_proposals=(proposal,),
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        workspace=workspace,
        state="approved",
        reviewer="operator",
    )
    return run_id, proposal, resolve_candidate_config(candidate, workspace=workspace)
