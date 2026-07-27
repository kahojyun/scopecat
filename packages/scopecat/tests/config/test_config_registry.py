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
from scopecat.config.changes import load_parameter_change_proposal
from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.registry import (
    CandidateConfigRegistrySource,
    ConfigRegistryActivationRecord,
    ConfigRegistryEntry,
    ConfigRegistryMutationResult,
    ConfigRegistryUnitOfWorkFactory,
    ConfigRevisionRegistration,
    DirectConfigRegistrySource,
    DirectConfigRevisionSource,
    ManualConfigDraftRegistrySource,
    ManualConfigDraftResult,
    ManualConfigDraftRevisionSource,
    activate_config_registry_entry,
    current_config_registry_generation,
    list_config_registry_entries,
    load_active_config_registry_activation,
    load_active_config_registry_config,
    load_active_config_registry_entry,
    load_config_registry_activation_history,
    preview_manual_config_draft,
    register_and_activate_config_revision,
    register_config_revision,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
)
from scopecat.kernel.quantity import Quantity
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.records.parameter import ScalarParameterValue
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat.runs.refs import record_content_ref
from tests.testkit.config_registry import (
    activate_candidate_config,
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


def test_register_revision_writes_and_activates_direct_entry(
    tmp_path: Path,
) -> None:
    config = load_config()
    entry = _register_direct_revision(
        config=config,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="seed",
        registered_by="operator",
        note="seed config",
    ).entry

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

    activated = _register_and_activate_direct_revision(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="active-seed",
        registered_by="operator",
        operator="operator",
        note="seed active config",
    )
    entry = activated.entry
    activation = activated.activation
    assert activation is not None
    assert activation.entry_id == entry.id
    assert (
        load_active_config_registry_entry(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == entry
    )
    assert (
        load_active_config_registry_activation(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == activation
    )
    assert (
        load_active_config_registry_config(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == load_config()
    )


def test_registry_rejects_invalid_registration_before_storage(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed) as captured:
        _register_direct_revision(
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
    base, activation = _seed_active_config_registry(tmp_path)
    entries_before = list_config_registry_entries(unit_of_work=unit_of_work)

    preview = preview_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=activation.generation,
        candidate_id="manual-preview",
        updates=_manual_config_updates(),
    )

    assert isinstance(preview, ManualConfigDraftResult)
    assert preview.base_entry == base
    assert preview.base_generation == activation.generation
    assert preview.check.ok
    assert preview.check.candidate is not None
    assert preview.check.candidate.id == "manual-preview"
    frequency = preview.check.candidate.parameter_snapshot.get("drive_frequency")
    assert frequency == ScalarParameterValue(
        id="drive_frequency",
        value=Quantity(value=5.2, unit="GHz"),
    )
    assert list_config_registry_entries(unit_of_work=unit_of_work) == entries_before
    assert (
        load_active_config_registry_activation(unit_of_work=unit_of_work) == activation
    )

    mutation = _register_draft_revision(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=activation.generation,
        candidate_id="manual-preview",
        updates=_manual_config_updates(),
        expected_result_content_hash=config_content_hash(
            preview.check.candidate,
        ),
        entry_id="manual-entry",
        registered_by="operator",
        note="adjust drive frequency",
    )

    entry = mutation.entry
    assert mutation.deltas == preview.check.deltas
    assert isinstance(entry.source, ManualConfigDraftRegistrySource)
    assert entry.source.base_entry_id == base.id
    assert entry.source.base_config_content_hash == base.content_hash
    assert entry.source.base_registry_generation == activation.generation
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
        == preview.check.candidate
    )
    assert (
        load_active_config_registry_activation(unit_of_work=unit_of_work) == activation
    )


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
    base, activation = _seed_active_config_registry(tmp_path)
    preview = preview_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=activation.generation,
        candidate_id="stale-preview",
        updates=_manual_config_updates(),
    )
    assert preview.check.candidate is not None
    base_generation = activation.generation
    base_content_hash = base.content_hash
    if stale_field == "generation":
        newer = _register_and_activate_direct_revision(
            config=load_config().model_copy(update={"id": "newer-config"}),
            unit_of_work=unit_of_work,
            entry_id="newer-entry",
            registered_by="operator",
            operator="operator",
            expected_generation=activation.generation,
        )
        assert newer.activation is not None
        assert newer.activation.generation == activation.generation + 1
    else:
        base_content_hash = "sha256:" + ("0" * 64)

    with pytest.raises(Conflict) as error:
        _register_draft_revision(
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
    base, activation = _seed_active_config_registry(tmp_path)

    with pytest.raises(Conflict) as error:
        _register_draft_revision(
            unit_of_work=unit_of_work,
            base_entry_id=base.id,
            base_config_content_hash=base.content_hash,
            base_generation=activation.generation,
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
    assert (
        load_active_config_registry_activation(unit_of_work=unit_of_work) == activation
    )


def test_manual_config_draft_set_default_stale_conflict_leaves_no_entry(
    tmp_path: Path,
) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    base, activation = _seed_active_config_registry(tmp_path)
    preview = preview_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=activation.generation,
        candidate_id="stale-default",
        updates=_manual_config_updates(),
    )
    assert preview.check.candidate is not None
    newer = _register_and_activate_direct_revision(
        config=load_config().model_copy(update={"id": "newer-config"}),
        unit_of_work=unit_of_work,
        entry_id="newer-entry",
        registered_by="operator",
        operator="operator",
        expected_generation=activation.generation,
    )
    newer_activation = newer.activation
    assert newer_activation is not None

    with pytest.raises(Conflict) as error:
        _register_and_activate_draft_revision(
            unit_of_work=unit_of_work,
            base_entry_id=base.id,
            base_config_content_hash=base.content_hash,
            base_generation=activation.generation,
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
    assert (
        load_active_config_registry_activation(unit_of_work=unit_of_work)
        == newer_activation
    )
    assert newer_activation.entry_id == newer.entry.id


def test_manual_config_draft_activation_rejects_a_stale_base(
    tmp_path: Path,
) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    base, activation = _seed_active_config_registry(tmp_path)
    preview = preview_manual_config_draft(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=activation.generation,
        candidate_id="manual-candidate",
        updates=_manual_config_updates(),
    )
    assert preview.check.candidate is not None
    manual = _register_draft_revision(
        unit_of_work=unit_of_work,
        base_entry_id=base.id,
        base_config_content_hash=base.content_hash,
        base_generation=activation.generation,
        candidate_id="manual-candidate",
        updates=_manual_config_updates(),
        expected_result_content_hash=config_content_hash(preview.check.candidate),
        entry_id="manual-candidate",
        registered_by="operator",
    )
    newer = _register_and_activate_direct_revision(
        config=load_config().model_copy(update={"id": "newer-config"}),
        unit_of_work=unit_of_work,
        entry_id="newer-entry",
        registered_by="operator",
        operator="operator",
        expected_generation=activation.generation,
    )
    newer_activation = newer.activation
    assert newer_activation is not None

    with pytest.raises(Conflict) as error:
        activate_config_registry_entry(
            entry_id=manual.entry.id,
            unit_of_work=unit_of_work,
            operator="operator",
            expected_generation=newer_activation.generation,
        )

    assert error.value.problems[0].code == "config_registry.stale_candidate"
    assert (
        load_active_config_registry_activation(unit_of_work=unit_of_work)
        == newer_activation
    )
    assert newer_activation.entry_id == newer.entry.id


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
    approval = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
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

    assert approval.actor == "operator"
    entry = activation_result.entry
    activation = activation_result.activation
    assert activation is not None
    assert isinstance(entry.source, CandidateConfigRegistrySource)
    assert entry.source.run_id == run_id
    assert entry.source.proposal_id == proposal.id
    assert entry.source.approval_record_id == f"{proposal.id}-approval"
    assert activation.entry_id == entry.id

    stored_proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
    )
    assert stored_proposal == proposal
    assert (
        load_config_registry_activation_history(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )[-1]
        == activation
    )

    config, source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
    )
    assert source.kind == "config_registry"
    assert source.entry_id == entry.id
    assert source.config_ref == entry.config_ref
    assert source.content_hash == entry.content_hash
    assert source.registry_generation == activation.generation
    assert config == load_config_registry_config(
        entry_id=entry.id, unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
    )


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
        reviewer="operator",
    )
    newer_config = load_config().model_copy(update={"id": "newer-base"})
    active = _register_and_activate_direct_revision(
        config=newer_config,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="newer-base",
        registered_by="operator",
        operator="operator",
    )
    activation = active.activation
    assert activation is not None

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
        load_active_config_registry_activation(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == activation
    )


def test_candidate_registration_requires_approval(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
    )
    candidate = CandidateConfig(
        parameter_proposal=proposal,
    )
    with pytest.raises(Conflict) as error:
        register_candidate_config(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id="not-approved",
            registered_by="operator",
            run_id=run_id,
            proposal_id=candidate.proposal_id,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_proposal_not_approved"
    )


def test_activation_generation_is_append_only_and_rejects_stale_writes(
    tmp_path: Path,
) -> None:
    first = _register_and_activate_direct_revision(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
    )
    first_record = first.activation
    assert first_record is not None
    second = _register_direct_revision(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="seed-b",
        registered_by="operator",
    ).entry

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

    second_result = activate_config_registry_entry(
        entry_id=second.id,
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=1,
    )
    second_record = second_result.activation
    assert second_record is not None
    with pytest.raises(Conflict) as error:
        activate_config_registry_entry(
            entry_id=first.entry.id,
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            operator="stale-operator",
            expected_generation=1,
        )

    assert error.value.problems[0].code == "config_registry.conflict"
    unchanged = load_active_config_registry_activation(
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
    )
    assert unchanged == second_record
    assert [
        record.generation
        for record in load_config_registry_activation_history(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
    ] == [1, 2]
    assert second_record.previous_entry_content_hash == first.entry.content_hash
    assert isinstance(first_source, ConfigRegistryRunConfigSource)
    assert first_source.entry_id == first.entry.id
    assert first_source.content_hash == first.entry.content_hash
    assert first_source.registry_generation == 1
    assert config_content_hash(resolved_first) == first_source.content_hash

    rollback = rollback_config_registry(
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        operator="operator",
        expected_generation=2,
    )
    rollback_record = rollback.activation
    assert rollback_record is not None
    assert rollback_record.generation == 3
    assert rollback_record.entry_id == first.entry.id
    assert [
        record.generation
        for record in load_config_registry_activation_history(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
    ] == [1, 2, 3]


def test_registration_runs_full_config_semantic_validation(tmp_path: Path) -> None:
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
    with pytest.raises(CheckFailed) as error:
        _register_direct_revision(
            config=invalid_config,
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id="invalid",
            registered_by="operator",
        )

    assert error.value.problems[0].code == (
        "configuration.unknown_routing_binding_instrument"
    )
    assert (
        list_config_registry_entries(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == []
    )


def test_concurrent_registrations_preserve_every_index_entry(tmp_path: Path) -> None:
    unit_of_work = sqlite_config_registry_unit_of_work(tmp_path)
    barrier = Barrier(2)

    def register(entry_id: str) -> str:
        barrier.wait()
        return _register_direct_revision(
            config=load_config(),
            unit_of_work=unit_of_work,
            entry_id=entry_id,
            registered_by="operator",
        ).entry.id

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
    initial = _register_and_activate_direct_revision(
        config=load_config(),
        unit_of_work=unit_of_work,
        entry_id="seed",
        registered_by="operator",
        operator="operator",
    )
    initial_activation = initial.activation
    assert initial_activation is not None
    barrier = Barrier(2)

    def activate(entry_id: str) -> tuple[str, str]:
        barrier.wait()
        try:
            result = _register_and_activate_direct_revision(
                config=load_config().model_copy(update={"id": entry_id}),
                unit_of_work=unit_of_work,
                entry_id=entry_id,
                registered_by="operator",
                operator="operator",
                expected_generation=initial_activation.generation,
            )
        except Conflict as error:
            return "error", error.problems[0].code
        return "activated", result.entry.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(activate, ("candidate-a", "candidate-b")))

    assert sorted(status for status, _detail in outcomes) == ["activated", "error"]
    assert next(detail for status, detail in outcomes if status == "error") == (
        "config_registry.conflict"
    )
    activation = load_active_config_registry_activation(unit_of_work=unit_of_work)
    assert activation.generation == initial_activation.generation + 1
    assert len(list_config_registry_entries(unit_of_work=unit_of_work)) == 2


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
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id="invalid-proposal-source",
            registered_by="operator",
            run_id=run_id,
            proposal_id=resolved.candidate.proposal_id,
        )

    assert error.value.problems[0].code == (
        "config_registry.candidate_proposal_mismatch"
    )


def test_candidate_registration_does_not_ignore_operator_metadata(
    tmp_path: Path,
) -> None:
    run_id, _proposal, resolved = _resolved_candidate(tmp_path)
    register_candidate_config(
        unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
        entry_id="candidate-metadata",
        registered_by="operator-a",
        note="first review",
        run_id=run_id,
        proposal_id=resolved.candidate.proposal_id,
    )

    with pytest.raises(Conflict) as error:
        register_candidate_config(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path),
            entry_id="candidate-metadata",
            registered_by="operator-b",
            note="different review",
            run_id=run_id,
            proposal_id=resolved.candidate.proposal_id,
        )

    assert error.value.problems[0].code == "config_registry.duplicate_entry"


def _register_direct_revision(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    entry_id: str,
    registered_by: str,
    note: str = "",
) -> ConfigRegistryMutationResult:
    return register_config_revision(
        registration=ConfigRevisionRegistration(
            source=DirectConfigRevisionSource(config),
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        ),
        unit_of_work=unit_of_work,
    )


def _register_and_activate_direct_revision(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    entry_id: str,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
    expected_generation: int | None = None,
) -> ConfigRegistryMutationResult:
    generation = (
        current_config_registry_generation(unit_of_work=unit_of_work)
        if expected_generation is None
        else expected_generation
    )
    return register_and_activate_config_revision(
        registration=ConfigRevisionRegistration(
            source=DirectConfigRevisionSource(config),
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        ),
        unit_of_work=unit_of_work,
        operator=operator,
        expected_generation=generation,
        activation_note=activation_note,
    )


def _register_draft_revision(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    base_entry_id: str,
    base_config_content_hash: ConfigContentHash,
    base_generation: int,
    candidate_id: str,
    updates: tuple[ParameterUpdate, ...],
    expected_result_content_hash: ConfigContentHash,
    entry_id: str,
    registered_by: str,
    note: str = "",
) -> ConfigRegistryMutationResult:
    return register_config_revision(
        registration=ConfigRevisionRegistration(
            source=ManualConfigDraftRevisionSource(
                base_entry_id=base_entry_id,
                base_config_content_hash=base_config_content_hash,
                base_generation=base_generation,
                candidate_id=candidate_id,
                updates=updates,
                expected_result_content_hash=expected_result_content_hash,
            ),
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        ),
        unit_of_work=unit_of_work,
    )


def _register_and_activate_draft_revision(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    base_entry_id: str,
    base_config_content_hash: ConfigContentHash,
    base_generation: int,
    candidate_id: str,
    updates: tuple[ParameterUpdate, ...],
    expected_result_content_hash: ConfigContentHash,
    entry_id: str,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
) -> ConfigRegistryMutationResult:
    return register_and_activate_config_revision(
        registration=ConfigRevisionRegistration(
            source=ManualConfigDraftRevisionSource(
                base_entry_id=base_entry_id,
                base_config_content_hash=base_config_content_hash,
                base_generation=base_generation,
                candidate_id=candidate_id,
                updates=updates,
                expected_result_content_hash=expected_result_content_hash,
            ),
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        ),
        unit_of_work=unit_of_work,
        operator=operator,
        expected_generation=base_generation,
        activation_note=activation_note,
    )


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
) -> tuple[ConfigRegistryEntry, ConfigRegistryActivationRecord]:
    result = _register_and_activate_direct_revision(
        config=load_config(),
        unit_of_work=sqlite_config_registry_unit_of_work(project_root),
        entry_id="manual-base",
        registered_by="operator",
        operator="operator",
    )
    assert result.activation is not None
    return result.entry, result.activation


def _manual_config_updates() -> tuple[ParameterUpdate, ...]:
    return (
        replace_scalar_parameter(
            "drive_frequency",
            Quantity(value=5.2, unit="GHz"),
        ),
    )
