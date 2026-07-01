from __future__ import annotations

from pathlib import Path

from scopecat.candidate_configs import CandidateConfig
from scopecat.config_registry import (
    load_active_config_registry_config,
    load_active_config_registry_entry,
    load_active_config_registry_state,
    register_and_activate_config_profile,
    register_config_profile,
    resolve_config_registry_config_source,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.parameter_changes import load_parameter_change, review_parameter_changes
from scopecat.runs import open_run_store
from scopecat.workflows import register_and_activate_candidate_config
from tests.support.config_registry import (
    load_config,
    simulate_with_parameter_change,
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
    assert entry.change_set_ids == []
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


def test_candidate_config_registers_and_activates_parameter_change(
    tmp_path: Path,
) -> None:
    run_id = simulate_with_parameter_change(tmp_path)
    change_set = load_parameter_change(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    candidate = CandidateConfig(
        analysis_title="best signal fixture",
        analysis_key="best-signal",
        changes=(change_set,),
    )
    decision = review_parameter_changes(
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
    registration_job = activation_result.job
    entry = activation_result.entry
    active_state = activation_result.active_state
    activation = activation_result.activation
    assert registration_job.source_kind == "candidate_config"
    assert entry.source_kind == "candidate_config"
    assert entry.source_run_id == run_id
    assert entry.change_set_ids == ["best-signal"]
    assert entry.change_set_artifact_ids == ["best-signal"]
    assert entry.candidate_artifact_id is not None
    assert entry.source_candidate_artifact_id == entry.candidate_artifact_id
    assert active_state.active_entry_id == entry.id

    stored_change = load_parameter_change(
        run_id=run_id, selector="best-signal", workspace=tmp_path
    )
    assert stored_change == change_set
    manifest = open_run_store(tmp_path).read_manifest(run_id)
    candidate_config_artifact = assert_artifact_ref(
        manifest.artifact_refs,
        entry.candidate_artifact_id,
        kind="candidate_config",
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal",
        kind="parameter_change_set",
    )
    candidate_config_path = tmp_path / "runs" / run_id / candidate_config_artifact.path
    assert candidate_config_path.is_file()
    assert active_state.history[-1] == activation
    assert registration_job.entry_id == entry.id
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-decision",
        kind="parameter_change_decision_record",
        path="reviews/best-signal.parameter-change-decision.json",
    )
    candidate_config = read_model(
        candidate_config_path,
        ConfigProfileSnapshot,
    )
    assert candidate_config.source is not None
    assert candidate_config.source.kind == "analysis_candidate_config"
    assert candidate_config.source.change_set_ids == ["best-signal"]
    assert not (tmp_path / "runs" / run_id / "comparisons").exists()

    config, provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    assert provenance.entry_id == entry.id
    assert config.source is not None
    assert config.source.entry_id == entry.id
