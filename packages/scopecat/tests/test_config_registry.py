from __future__ import annotations

from pathlib import Path

from scopecat.config_registry import (
    load_active_config_registry_config,
    load_active_config_registry_entry,
    load_active_config_registry_state,
    register_and_activate_config_profile,
    register_config_profile,
    resolve_config_registry_config_source,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.proposals import (
    ParameterProposalAcceptanceResult,
    accept_parameter_proposal,
    load_parameter_proposal,
    review_parameter_proposal,
)
from scopecat.runs import open_run_store
from tests.support.config_registry import (
    load_config,
    simulate_with_proposal,
)
from tests.support.records import assert_artifact_ref, read_model


def test_register_config_profile_writes_and_activates_direct_entry(
    tmp_path: Path,
) -> None:
    config = load_config()
    job, entry = register_config_profile(
        config=config,
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
        note="seed config",
        source_ref="fixtures/core/simulated_scan/config-profile.json",
    )

    assert job.source_kind == "direct_config_profile"
    assert entry.source_kind == "direct_config_profile"
    assert entry.proposal_id is None
    persisted_config = read_model(tmp_path / entry.config_ref, ConfigProfileSnapshot)
    assert persisted_config == config

    _job, entry, active_state, _activation = register_and_activate_config_profile(
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
    assert load_active_config_registry_config(workspace=tmp_path).source is not None


def test_accept_parameter_proposal_reviews_applies_registers_and_activates(
    tmp_path: Path,
) -> None:
    run_id = simulate_with_proposal(tmp_path)

    (
        result,
        review,
        (registration_job),
        entry,
        active_state,
        activation,
    ) = accept_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        reviewer="operator",
        operator="operator",
        entry_id="accepted-best-signal",
        note="looks good",
    )

    assert review is not None
    assert review.decision == "approved"
    assert registration_job.source_kind == "accepted_parameter_proposal"
    assert entry.source_kind == "accepted_parameter_proposal"
    assert entry.source_run_id == run_id
    assert entry.proposal_id == "best-signal-proposal"
    assert entry.proposal_artifact_id == "best-signal-proposal"
    assert entry.candidate_artifact_id == "best-signal-proposal-candidate-config"
    assert entry.source_candidate_artifact_id == (
        "best-signal-proposal-candidate-config"
    )
    assert active_state.active_entry_id == entry.id

    proposal = load_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
    )
    assert proposal.state == "approved"
    manifest = open_run_store(tmp_path).read_manifest(run_id)
    candidate_config_artifact = assert_artifact_ref(
        manifest.artifact_refs,
        result.candidate_artifact_id,
        kind="candidate_config",
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        result.proposal_artifact_id,
        kind="parameter_change_set",
    )
    candidate_config_path = tmp_path / "runs" / run_id / candidate_config_artifact.path
    assert candidate_config_path.is_file()
    acceptance_path = tmp_path / "runs" / run_id / result.acceptance_ref
    assert acceptance_path.is_file()
    stored_acceptance = read_model(
        acceptance_path,
        ParameterProposalAcceptanceResult,
    )
    assert stored_acceptance == result
    assert stored_acceptance.schema_version == (
        "scopecat.parameter_proposal_acceptance_result.v2"
    )
    assert stored_acceptance.candidate_artifact_id == entry.candidate_artifact_id
    assert stored_acceptance.config_registry_entry_id == entry.id
    assert stored_acceptance.active_entry_id == active_state.active_entry_id
    assert stored_acceptance.active_config_ref == active_state.active_config_ref
    assert stored_acceptance.activation_record_id == activation.id
    assert active_state.history[-1] == activation
    assert registration_job.entry_id == entry.id
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-proposal-acceptance",
        kind="proposal_acceptance_result",
        path=result.acceptance_ref,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-proposal-review",
        kind="proposal_review_record",
        path=stored_acceptance.review_ref,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-proposal-finalization",
        kind="proposal_finalization_record",
    )
    candidate_config = read_model(
        candidate_config_path,
        ConfigProfileSnapshot,
    )
    assert candidate_config.source is not None
    assert candidate_config.source.kind == "accepted_parameter_proposal"
    assert candidate_config.source.proposal_id == "best-signal-proposal"
    assert not (tmp_path / "runs" / run_id / "comparisons").exists()

    config, provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    assert provenance.entry_id == entry.id
    assert config.source is not None
    assert config.source.entry_id == entry.id


def test_accept_parameter_proposal_accepts_already_approved_proposal(
    tmp_path: Path,
) -> None:
    run_id = simulate_with_proposal(tmp_path)
    review_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
        note="manual approval",
    )

    result, review, *_ = accept_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        reviewer="operator",
        operator="operator",
    )

    assert review is None
    assert result.config_registry_entry_id.startswith("best-signal-proposal-")
