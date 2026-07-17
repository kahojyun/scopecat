from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Literal

import pytest
from pydantic import ValidationError

import scopecat.config.resolution as config_workflow
from scopecat.application.services import WorkspaceServices
from scopecat.composition.local import (
    local_config_registry_unit_of_work,
    local_run_repository,
    local_workspace_services,
)
from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_snapshot,
)
from scopecat.config.changes import (
    ParameterChangeDecisionRecord,
    invalidate_parameter_change_proposal,
    load_parameter_change_proposal,
    review_parameter_change_proposal,
)
from scopecat.config.registry import (
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
from scopecat.config.resolution import (
    activate_config_entry,
    register_and_activate_candidate_config,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
    StorageError,
)
from scopecat.kernel.problems import ProblemCategory
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.runs.refs import record_content_ref
from tests.testkit.config_registry import (
    load_config,
    signal_run_with_parameter_change,
)


@dataclass(frozen=True)
class _ResolvedCandidate:
    candidate: CandidateConfig
    config: ConfigProfileSnapshot


def _fail_once_after_replace(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failed_path: Path,
    observed_paths: tuple[Path, ...] = (),
) -> dict[Path, int]:
    real_replace = Path.replace
    replacements = dict.fromkeys((*observed_paths, failed_path), 0)
    failed = False

    def replace_then_fail(source: Path, target: str | Path) -> Path:
        nonlocal failed
        target_path = Path(target)
        replaced = real_replace(source, target)
        if target_path in replacements:
            replacements[target_path] += 1
        if target_path == failed_path and not failed:
            failed = True
            raise OSError("directory sync status is unknown after replace")
        return replaced

    monkeypatch.setattr(Path, "replace", replace_then_fail)
    return replacements


def test_register_config_profile_writes_and_activates_direct_entry(
    tmp_path: Path,
) -> None:
    config = load_config()
    entry = register_config_profile(
        config=config,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
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
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
    )
    assert persisted_config == config

    entry, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="active-seed",
        registered_by="operator",
        operator="operator",
        note="seed active config",
    )
    assert active_state.active_entry_id == entry.id
    assert (
        load_active_config_registry_entry(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == entry
    )
    assert (
        load_active_config_registry_state(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == active_state
    )
    assert (
        load_active_config_registry_config(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == load_config()
    )


def test_registry_rejects_invalid_registration_before_storage(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed) as captured:
        register_config_profile(
            config=load_config(),
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            entry_id="seed",
            registered_by=" ",
        )

    assert captured.value.problems[0].code == ("config_registry.registered_by_missing")
    assert not (tmp_path / "config-registry").exists()


def test_candidate_config_registers_and_activates_parameter_proposal(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
    )
    candidate = CandidateConfig(
        parameter_proposals=(proposal,),
    )
    decision = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
        state="approved",
        reviewer="operator",
        note="looks good",
    )

    activation_result = register_and_activate_candidate_config(
        candidate=candidate,
        services=local_workspace_services(tmp_path),
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
    evidence = entry.source.proposal_evidence[0]
    assert evidence.proposal_id == proposal.id
    assert evidence.approval_event_id == decision.event_id
    assert evidence.proposal_record_content_hash.startswith("sha256:")
    assert evidence.approval_record_content_hash.startswith("sha256:")
    assert active_state.active_entry_id == entry.id

    stored_proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
    )
    assert stored_proposal == proposal
    assert active_state.history[-1] == activation

    config, source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
    )
    assert source.kind == "config_registry"
    assert source.entry_id == entry.id
    assert source.config_ref == entry.config_ref
    assert source.content_hash == entry.content_hash
    assert source.registry_generation == active_state.generation
    assert config == load_config_registry_config(
        entry_id=entry.id, unit_of_work=local_config_registry_unit_of_work(tmp_path)
    )


def test_candidate_activation_rejects_a_stale_base_config(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
    )
    candidate = CandidateConfig(
        parameter_proposals=(proposal,),
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
        state="approved",
        reviewer="operator",
    )
    newer_config = load_config().model_copy(update={"id": "newer-base"})
    _entry, active_state, _activation = register_and_activate_config_profile(
        config=newer_config,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="newer-base",
        registered_by="operator",
        operator="operator",
    )

    with pytest.raises(Conflict) as error:
        register_and_activate_candidate_config(
            candidate=candidate,
            services=local_workspace_services(tmp_path),
            entry_id="stale-candidate",
            registered_by="operator",
            operator="operator",
        )

    assert error.value.problems[0].code == "config_registry.stale_candidate"
    assert (
        load_active_config_registry_state(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == active_state
    )


@pytest.mark.parametrize("decision", (None, "rejected", "invalidated"))
def test_candidate_registration_requires_latest_approval(
    tmp_path: Path,
    decision: str | None,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
    )
    candidate = CandidateConfig(
        parameter_proposals=(proposal,),
    )
    config = resolve_candidate_config_snapshot(
        candidate, services=local_workspace_services(tmp_path)
    )
    if decision == "rejected":
        review_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            services=local_workspace_services(tmp_path),
            state="rejected",
            reviewer="reviewer",
        )
    elif decision == "invalidated":
        review_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            services=local_workspace_services(tmp_path),
            state="approved",
            reviewer="reviewer",
        )
        invalidate_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            services=local_workspace_services(tmp_path),
            reason="superseded",
            invalidated_by="reviewer",
        )

    with pytest.raises(Conflict) as error:
        register_candidate_config(
            config=config,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            entry_id=f"not-approved-{decision or 'missing'}",
            registered_by="operator",
            run_id=run_id,
            proposal_ids=candidate.proposal_ids,
            base_config_content_hash=candidate.base_config_content_hash,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_proposal_not_approved"
    )


def test_candidate_invalidation_after_registration_blocks_load_and_activation(
    tmp_path: Path,
) -> None:
    _base, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="base",
        registered_by="operator",
        operator="operator",
    )
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    entry = register_candidate_config(
        config=resolved.config,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="candidate",
        registered_by="operator",
        run_id=run_id,
        proposal_ids=resolved.candidate.proposal_ids,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )
    invalidate_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=local_workspace_services(tmp_path),
        reason="new evidence",
        invalidated_by="reviewer",
    )

    with pytest.raises(Conflict) as load_error:
        load_config_registry_entry(
            entry_id=entry.id, unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
    with pytest.raises(Conflict) as activation_error:
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=active_state.generation,
        )

    assert load_error.value.problems[0].code == (
        "config_registry.candidate_proposal_not_approved"
    )
    assert activation_error.value.problems[0].code == (
        "config_registry.candidate_proposal_not_approved"
    )
    assert (
        load_active_config_registry_state(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == active_state
    )


@pytest.mark.parametrize("later_decision", ("rejected", "invalidated"))
def test_rollback_can_leave_an_active_candidate_after_later_review(
    tmp_path: Path,
    later_decision: Literal["rejected", "invalidated"],
) -> None:
    base, base_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="rollback-base",
        registered_by="operator",
        operator="operator",
    )
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    candidate = register_and_activate_candidate_config(
        candidate=resolved.candidate,
        services=local_workspace_services(tmp_path),
        entry_id="active-candidate",
        registered_by="operator",
        operator="operator",
        expected_generation=base_state.generation,
    )
    if later_decision == "rejected":
        review_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            services=local_workspace_services(tmp_path),
            state="rejected",
            reviewer="reviewer",
        )
    else:
        invalidate_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            services=local_workspace_services(tmp_path),
            reason="new evidence",
            invalidated_by="reviewer",
        )

    restored, record = rollback_config_registry(
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=candidate.active_state.generation,
        note="leave disallowed candidate",
    )

    assert restored.generation == candidate.active_state.generation + 1
    assert restored.active_entry_id == base.id
    assert record.action == "rollback"
    assert record.previous_entry_id == candidate.entry.id


def test_rollback_still_requires_complete_evidence_for_candidate_target(
    tmp_path: Path,
) -> None:
    _base, base_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="target-base",
        registered_by="operator",
        operator="operator",
    )
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    candidate = register_and_activate_candidate_config(
        candidate=resolved.candidate,
        services=local_workspace_services(tmp_path),
        entry_id="rollback-target-candidate",
        registered_by="operator",
        operator="operator",
        expected_generation=base_state.generation,
    )
    _current, current_state, _current_activation = register_and_activate_config_profile(
        config=load_config().model_copy(update={"id": "target-current"}),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="target-current",
        registered_by="operator",
        operator="operator",
        expected_generation=candidate.active_state.generation,
    )
    invalidate_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=local_workspace_services(tmp_path),
        reason="new evidence",
        invalidated_by="reviewer",
    )

    with pytest.raises(Conflict) as error:
        rollback_config_registry(
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=current_state.generation,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_proposal_not_approved"
    )
    assert (
        load_active_config_registry_state(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == current_state
    )


def test_rollback_from_invalidated_active_candidate_still_checks_content_hash(
    tmp_path: Path,
) -> None:
    _base, base_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="hash-base",
        registered_by="operator",
        operator="operator",
    )
    run_id, proposal, resolved = _resolved_candidate(tmp_path)
    candidate = register_and_activate_candidate_config(
        candidate=resolved.candidate,
        services=local_workspace_services(tmp_path),
        entry_id="hash-active-candidate",
        registered_by="operator",
        operator="operator",
        expected_generation=base_state.generation,
    )
    invalidate_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=local_workspace_services(tmp_path),
        reason="new evidence",
        invalidated_by="reviewer",
    )
    tampered_config = load_config().model_copy(
        update={"id": "tampered-active-candidate"}
    )
    assert candidate.entry.content_hash != config_content_hash(tampered_config)
    (tmp_path / candidate.entry.config_ref).write_text(
        tampered_config.model_dump_json()
    )

    with pytest.raises(DataIntegrityError) as error:
        rollback_config_registry(
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=candidate.active_state.generation,
        )

    assert error.value.problems[0].code == "config_registry.content_hash_mismatch"
    assert (
        load_active_config_registry_state(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == candidate.active_state
    )


def test_activation_generation_is_append_only_and_rejects_stale_writes(
    tmp_path: Path,
) -> None:
    first, first_state, first_record = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
    )
    second = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed-b",
        registered_by="operator",
    )

    assert first_state.generation == 1
    assert first_record.generation == 1
    assert (
        current_config_registry_generation(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == 1
    )
    resolved_first, first_source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
    )

    second_state, second_record = activate_config_registry_entry(
        entry_id=second.id,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=1,
    )
    with pytest.raises(Conflict) as error:
        activate_config_registry_entry(
            entry_id=first.id,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="stale-operator",
            expected_generation=1,
        )

    assert error.value.problems[0].code == "config_registry.conflict"
    unchanged = load_active_config_registry_state(
        unit_of_work=local_config_registry_unit_of_work(tmp_path)
    )
    assert unchanged == second_state
    assert [record.generation for record in unchanged.history] == [1, 2]
    assert second_record.previous_entry_content_hash == first.content_hash
    assert first_source.entry_id == first.id
    assert first_source.content_hash == first.content_hash
    assert first_source.registry_generation == 1
    assert config_content_hash(resolved_first) == first_source.content_hash

    rolled_back, rollback_record = rollback_config_registry(
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
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
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="invalid",
        registered_by="operator",
    )

    with pytest.raises(CheckFailed) as error:
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=0,
        )

    assert error.value.problems[0].code == (
        "configuration.unknown_connection_instrument"
    )
    assert (
        current_config_registry_generation(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == 0
    )


def test_registry_rejects_snapshot_content_that_no_longer_matches_entry(
    tmp_path: Path,
) -> None:
    config = load_config()
    entry = register_config_profile(
        config=config,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
    )
    tampered = config.model_copy(update={"id": "tampered"})
    (tmp_path / entry.config_ref).write_text(tampered.model_dump_json())

    with pytest.raises(DataIntegrityError) as error:
        load_config_registry_config(
            entry_id=entry.id, unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )

    assert error.value.problems[0].code == "config_registry.content_hash_mismatch"


def test_concurrent_registrations_preserve_every_index_entry(tmp_path: Path) -> None:
    barrier = Barrier(2)

    def register(entry_id: str) -> str:
        barrier.wait()
        return register_config_profile(
            config=load_config(),
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            entry_id=entry_id,
            registered_by="operator",
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        registered = set(executor.map(register, ("seed-a", "seed-b")))

    assert registered == {"seed-a", "seed-b"}
    assert {
        entry.id
        for entry in list_config_registry_entries(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
    } == (registered)
    assert not list((tmp_path / "config-registry").rglob("*.tmp"))


def test_concurrent_composite_activations_apply_one_generation(
    tmp_path: Path,
) -> None:
    _seed, initial_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
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
                unit_of_work=local_config_registry_unit_of_work(tmp_path),
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
    state = load_active_config_registry_state(
        unit_of_work=local_config_registry_unit_of_work(tmp_path)
    )
    assert state.generation == initial_state.generation + 1
    assert (
        len(
            list_config_registry_entries(
                unit_of_work=local_config_registry_unit_of_work(tmp_path)
            )
        )
        == 2
    )


def test_idempotent_registration_repairs_a_missing_index_commit(
    tmp_path: Path,
) -> None:
    first = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed-a",
        registered_by="operator",
    )
    index_path = tmp_path / "config-registry" / "index.json"
    committed_index = index_path.read_text()
    second = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed-b",
        registered_by="operator",
    )
    # Simulate a crash after seed-b's config and entry commits but before the
    # index commit marker is replaced.
    index_path.write_text(committed_index)

    with pytest.raises(DataIntegrityError) as uncommitted:
        load_config_registry_entry(
            entry_id="seed-b", unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
    assert uncommitted.value.problems[0].code == ("config_registry.uncommitted_entry")

    repeated = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed-b",
        registered_by="operator",
    )

    assert repeated == second
    assert list_config_registry_entries(
        unit_of_work=local_config_registry_unit_of_work(tmp_path)
    ) == [first, second]


@pytest.mark.parametrize("failed_record", ("entry", "index"))
def test_registration_retry_replays_the_full_durable_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_record: str,
) -> None:
    config_path = (
        tmp_path
        / "config-registry"
        / "configs"
        / "replace-ambiguous.config-profile-snapshot.json"
    )
    entry_path = tmp_path / "config-registry" / "entries" / "replace-ambiguous.json"
    index_path = tmp_path / "config-registry" / "index.json"
    failed_path = entry_path if failed_record == "entry" else index_path
    replacements = _fail_once_after_replace(
        monkeypatch,
        failed_path=failed_path,
        observed_paths=(config_path, entry_path, index_path),
    )

    with pytest.raises(StorageError):
        register_config_profile(
            config=load_config(),
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            entry_id="replace-ambiguous",
            registered_by="operator",
        )

    recovered = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="replace-ambiguous",
        registered_by="operator",
    )

    assert recovered.id == "replace-ambiguous"
    assert replacements[config_path] == 2
    assert replacements[entry_path] == 2
    assert replacements[index_path] == (1 if failed_record == "entry" else 2)
    assert list_config_registry_entries(
        unit_of_work=local_config_registry_unit_of_work(tmp_path)
    ) == [recovered]


def test_activation_retry_recovers_a_visible_post_replace_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="activation-retry",
        registered_by="operator",
    )
    active_path = tmp_path / "config-registry" / "active.json"
    replacements = _fail_once_after_replace(
        monkeypatch,
        failed_path=active_path,
    )

    with pytest.raises(StorageError):
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=0,
            note="deploy",
        )
    visible = load_active_config_registry_state(
        unit_of_work=local_config_registry_unit_of_work(tmp_path)
    )

    recovered, record = activate_config_registry_entry(
        entry_id=entry.id,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=0,
        note="deploy",
    )

    assert recovered == visible
    assert record == visible.history[-1]
    assert replacements[active_path] == 2


def test_composite_activation_retry_recovers_an_implicit_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_path = tmp_path / "config-registry" / "active.json"
    replacements = _fail_once_after_replace(
        monkeypatch,
        failed_path=active_path,
    )

    with pytest.raises(StorageError):
        register_and_activate_config_profile(
            config=load_config(),
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            entry_id="implicit-generation-retry",
            registered_by="operator",
            operator="operator",
            note="deploy",
        )
    visible = load_active_config_registry_state(
        unit_of_work=local_config_registry_unit_of_work(tmp_path)
    )

    entry, recovered, record = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="implicit-generation-retry",
        registered_by="operator",
        operator="operator",
        note="deploy",
    )

    assert entry.id == "implicit-generation-retry"
    assert recovered == visible
    assert recovered.generation == 1
    assert record == visible.history[-1]
    assert replacements[active_path] == 2


def test_activation_workflow_retry_recovers_a_reread_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="workflow-generation-retry",
        registered_by="operator",
    )
    active_path = tmp_path / "config-registry" / "active.json"
    replacements = _fail_once_after_replace(
        monkeypatch,
        failed_path=active_path,
    )

    with pytest.raises(StorageError):
        activate_config_entry(
            entry_id=entry.id,
            services=local_workspace_services(tmp_path),
            operator="operator",
            note="deploy",
        )
    visible = load_active_config_registry_state(
        unit_of_work=local_config_registry_unit_of_work(tmp_path)
    )

    recovered = activate_config_entry(
        entry_id=entry.id,
        services=local_workspace_services(tmp_path),
        operator="operator",
        note="deploy",
    )

    assert recovered.active_state == visible
    assert recovered.active_state.generation == 1
    assert recovered.activation == visible.history[-1]
    assert replacements[active_path] == 2


def test_activation_retry_rejects_a_different_stale_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="activation-conflict",
        registered_by="operator",
    )
    active_path = tmp_path / "config-registry" / "active.json"
    replacements = _fail_once_after_replace(
        monkeypatch,
        failed_path=active_path,
    )
    with pytest.raises(StorageError):
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=0,
            note="deploy",
        )

    with pytest.raises(Conflict) as captured:
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=0,
            note="different request",
        )

    assert captured.value.problems[0].code == "config_registry.conflict"
    assert replacements[active_path] == 1


def test_rollback_retry_recovers_a_visible_post_replace_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _first, _first_state, _first_record = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="rollback-a",
        registered_by="operator",
        operator="operator",
    )
    _second, second_state, _second_record = register_and_activate_config_profile(
        config=load_config().model_copy(update={"id": "rollback-b"}),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="rollback-b",
        registered_by="operator",
        operator="operator",
    )
    active_path = tmp_path / "config-registry" / "active.json"
    replacements = _fail_once_after_replace(
        monkeypatch,
        failed_path=active_path,
    )

    with pytest.raises(StorageError):
        rollback_config_registry(
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=second_state.generation,
            note="undo",
        )
    visible = load_active_config_registry_state(
        unit_of_work=local_config_registry_unit_of_work(tmp_path)
    )

    recovered, record = rollback_config_registry(
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=second_state.generation,
        note="undo",
    )

    assert recovered == visible
    assert record == visible.history[-1]
    assert replacements[active_path] == 2


def test_list_rejects_tampered_entry_and_config_files(tmp_path: Path) -> None:
    config = load_config()
    entry = register_config_profile(
        config=config,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
    )
    tampered = config.model_copy(update={"id": "tampered"})
    tampered_entry = entry.model_copy(
        update={"content_hash": config_content_hash(tampered)}
    )
    (tmp_path / entry.config_ref).write_text(tampered.model_dump_json())
    (tmp_path / "config-registry/entries/seed.json").write_text(
        tampered_entry.model_dump_json()
    )

    with pytest.raises(DataIntegrityError) as error:
        list_config_registry_entries(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )

    assert error.value.problems[0].code == "config_registry.index_entry_mismatch"


def test_registry_maps_malformed_index_to_data_integrity(tmp_path: Path) -> None:
    index_path = tmp_path / "config-registry/index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("not-json")

    with pytest.raises(DataIntegrityError) as captured:
        list_config_registry_entries(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )

    assert captured.value.problems[0].code == "config_registry.record_invalid"
    assert captured.value.problems[0].category is ProblemCategory.DATA_INTEGRITY
    assert isinstance(captured.value.__cause__, ValidationError)


def test_registry_maps_unsafe_durable_entry_id_to_data_integrity(
    tmp_path: Path,
) -> None:
    entry = register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
    )
    index_path = tmp_path / "config-registry/index.json"
    index = ConfigRegistryIndex.model_validate_json(index_path.read_text())
    index_path.write_text(
        index.model_copy(
            update={"entries": (entry.model_copy(update={"id": "../escape"}),)}
        ).model_dump_json()
    )

    with pytest.raises(DataIntegrityError) as captured:
        list_config_registry_entries(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )

    assert captured.value.problems[0].code == "config_registry.entry_id_invalid"


def test_registry_maps_io_failure_without_exposing_raw_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
    )
    index_path = tmp_path / "config-registry/index.json"
    storage_cause = PermissionError("private filesystem details")
    real_stat = Path.stat

    def guarded_stat(path: Path, *args: object, **kwargs: object):
        if path == index_path:
            raise storage_cause
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)

    with pytest.raises(StorageError) as captured:
        list_config_registry_entries(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )

    assert captured.value.__cause__ is storage_cause
    assert captured.value.problems[0].category is ProblemCategory.STORAGE
    assert "private filesystem details" not in str(captured.value)


def test_candidate_registration_rejects_changes_not_derived_from_proposals(
    tmp_path: Path,
) -> None:
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    forged = resolved.config.model_copy(
        update={
            "environment": resolved.config.environment.model_copy(
                update={"id": "not-derived-from-proposals"}
            )
        }
    )

    with pytest.raises(Conflict) as error:
        register_candidate_config(
            config=forged,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            entry_id="forged-candidate",
            registered_by="operator",
            run_id=run_id,
            proposal_ids=resolved.candidate.proposal_ids,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_derivation_mismatch"
    )
    assert (
        list_config_registry_entries(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
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
    storage = local_run_repository(tmp_path)
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
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            entry_id="invalid-proposal-source",
            registered_by="operator",
            run_id=run_id,
            proposal_ids=resolved.candidate.proposal_ids,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_proposal_mismatch"
    )


@pytest.mark.parametrize(
    ("target", "expected_code"),
    (
        ("proposal", "config_registry.candidate_evidence_mismatch"),
        ("approval", "config_registry.candidate_evidence_mismatch"),
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
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="candidate-evidence",
        registered_by="operator",
        run_id=run_id,
        proposal_ids=resolved.candidate.proposal_ids,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )
    assert isinstance(entry.source, CandidateConfigRegistrySource)
    storage = local_run_repository(tmp_path)
    if target == "proposal":
        storage.write_model(
            run_id,
            record_content_ref(
                record_id=proposal.id,
                kind="parameter_change_proposal",
            ),
            proposal.model_copy(update={"reason": "tampered"}),
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

    with pytest.raises((Conflict, DataIntegrityError)) as error:
        load_config_registry_entry(
            entry_id=entry.id, unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )

    assert error.value.problems[0].code == expected_code


def test_candidate_registration_does_not_ignore_operator_metadata(
    tmp_path: Path,
) -> None:
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    register_candidate_config(
        config=resolved.config,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="candidate-metadata",
        registered_by="operator-a",
        note="first review",
        run_id=run_id,
        proposal_ids=resolved.candidate.proposal_ids,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )

    with pytest.raises(Conflict) as error:
        register_candidate_config(
            config=resolved.config,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            entry_id="candidate-metadata",
            registered_by="operator-b",
            note="different review",
            run_id=run_id,
            proposal_ids=resolved.candidate.proposal_ids,
            base_config_content_hash=resolved.candidate.base_config_content_hash,
        )

    assert error.value.problems[0].code == "config_registry.duplicate_entry"


def test_candidate_workflow_captures_generation_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
    )
    candidate = CandidateConfig(
        parameter_proposals=(proposal,),
    )
    register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    original_resolve = resolve_candidate_config_snapshot

    def resolve_with_intervening_activation(
        selected: CandidateConfig,
        *,
        services: WorkspaceServices,
    ) -> ConfigProfileSnapshot:
        resolved = original_resolve(selected, services=services)
        register_and_activate_config_profile(
            config=load_config(),
            unit_of_work=services.config_registry,
            entry_id="intervening",
            registered_by="operator",
            operator="operator",
        )
        return resolved

    monkeypatch.setattr(
        config_workflow,
        "resolve_candidate_config_snapshot",
        resolve_with_intervening_activation,
    )

    with pytest.raises(Conflict) as error:
        register_and_activate_candidate_config(
            candidate=candidate,
            services=local_workspace_services(tmp_path),
            entry_id="candidate-after-race",
            registered_by="operator",
            operator="operator",
        )

    assert error.value.problems[0].code == "config_registry.conflict"
    with pytest.raises(NotFound) as missing:
        load_config_registry_entry(
            entry_id="candidate-after-race",
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
        )
    assert missing.value.problems[0].code == "config_registry.not_found"


def test_activation_validates_the_current_active_snapshot_before_stale_check(
    tmp_path: Path,
) -> None:
    _seed, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    candidate_entry = register_candidate_config(
        config=resolved.config,
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="candidate",
        registered_by="operator",
        run_id=run_id,
        proposal_ids=resolved.candidate.proposal_ids,
        base_config_content_hash=resolved.candidate.base_config_content_hash,
    )
    tampered = load_config().model_copy(update={"id": "tampered"})
    (tmp_path / "config-registry/configs/seed.config-profile-snapshot.json").write_text(
        tampered.model_dump_json()
    )

    with pytest.raises(DataIntegrityError) as error:
        activate_config_registry_entry(
            entry_id=candidate_entry.id,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=active_state.generation,
        )

    assert error.value.problems[0].code == "config_registry.content_hash_mismatch"
    assert (
        load_active_config_registry_state(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
        )
        == active_state
    )


def test_same_entry_reactivation_still_validates_active_integrity(
    tmp_path: Path,
) -> None:
    entry, active_state, _activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    tampered = load_config().model_copy(update={"id": "tampered"})
    (tmp_path / entry.config_ref).write_text(tampered.model_dump_json())

    with pytest.raises(DataIntegrityError) as error:
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=active_state.generation,
        )

    assert error.value.problems[0].code == "config_registry.content_hash_mismatch"


def test_rollback_requires_the_historical_target_content_hash(tmp_path: Path) -> None:
    first, _first_state, _first_activation = register_and_activate_config_profile(
        config=load_config(),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
    )
    _second, second_state, _second_activation = register_and_activate_config_profile(
        config=load_config().model_copy(update={"id": "seed-b"}),
        unit_of_work=local_config_registry_unit_of_work(tmp_path),
        entry_id="seed-b",
        registered_by="operator",
        operator="operator",
    )
    drifted = load_config().model_copy(update={"id": "drifted"})
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
                "entries": tuple(
                    drifted_entry if entry.id == first.id else entry
                    for entry in index.entries
                )
            }
        ).model_dump_json()
    )

    with pytest.raises(DataIntegrityError) as error:
        rollback_config_registry(
            unit_of_work=local_config_registry_unit_of_work(tmp_path),
            operator="operator",
            expected_generation=second_state.generation,
        )

    assert error.value.problems[0].code == ("config_registry.rollback_content_mismatch")


def _resolved_candidate(
    workspace: Path,
) -> tuple[str, ParameterChangeProposal, _ResolvedCandidate]:
    run_id = signal_run_with_parameter_change(workspace)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(workspace),
    )
    candidate = CandidateConfig(
        parameter_proposals=(proposal,),
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=local_workspace_services(workspace),
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
                services=local_workspace_services(workspace),
            ),
        ),
    )
