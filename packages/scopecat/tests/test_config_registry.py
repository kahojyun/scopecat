from __future__ import annotations

from pathlib import Path

from scopecat._workflows.config import register_and_activate_candidate_config
from scopecat.candidate_configs import CandidateConfig
from scopecat.config_registry import (
    CandidateConfigRegistrySource,
    DirectConfigRegistrySource,
    load_active_config_registry_config,
    load_active_config_registry_entry,
    load_active_config_registry_state,
    load_config_registry_config,
    register_and_activate_config_profile,
    register_config_profile,
    resolve_config_registry_config_source,
)
from scopecat.parameter_changes import load_parameter_change, review_parameter_changes
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


def test_candidate_config_registers_and_activates_parameter_change(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
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
    entry = activation_result.entry
    active_state = activation_result.active_state
    activation = activation_result.activation
    assert isinstance(entry.source, CandidateConfigRegistrySource)
    assert entry.source.run_id == run_id
    assert entry.source.change_set_ids == ["best-signal"]
    assert entry.source.candidate_record_id
    assert active_state.active_entry_id == entry.id

    stored_change = load_parameter_change(
        run_id=run_id, selector="best-signal", workspace=tmp_path
    )
    assert stored_change == change_set
    assert active_state.history[-1] == activation

    config, source = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    assert source.kind == "config_registry"
    assert source.entry_id == entry.id
    assert config == load_config_registry_config(entry_id=entry.id, workspace=tmp_path)
