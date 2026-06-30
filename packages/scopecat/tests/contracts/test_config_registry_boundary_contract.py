from __future__ import annotations

from pathlib import Path

from scopecat.config_registry import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    ConfigRegistryIndex,
    ConfigRegistryRegistrationJob,
    list_config_registry_entries,
    load_active_config_registry_entry,
    load_active_config_registry_state,
    load_config_registry_entry,
    register_and_activate_config_profile,
    resolve_config_registry_config_source,
)
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from tests.support.records import assert_model_round_trip, read_model

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simulated_scan"


def test_config_registry_boundary_persists_entry_index_and_active_state(
    tmp_path: Path,
) -> None:
    job, entry, active_state, active_activation = register_and_activate_config_profile(
        config=_load_config_profile_input(),
        workspace=tmp_path,
        entry_id="direct-config",
        registered_by="operator",
        operator="operator",
        note="seed config",
        activation_note="use direct config",
        source_ref="fixtures/core/simulated_scan/config-profile.json",
    )

    store_root = tmp_path / "config-registry"
    persisted_index = read_model(store_root / "index.json", ConfigRegistryIndex)
    persisted_entry = read_model(
        store_root / "entries" / f"{entry.id}.json",
        ConfigRegistryEntry,
    )
    persisted_job = read_model(
        tmp_path / entry.registration_job_ref,
        ConfigRegistryRegistrationJob,
    )
    persisted_config = read_model(tmp_path / entry.config_ref, ConfigProfileSnapshot)
    persisted_active_state = read_model(
        store_root / "active.json",
        ConfigRegistryActiveState,
    )

    assert persisted_index.schema_version == "scopecat.config_registry_index.v0"
    assert persisted_index.entries == [entry]
    assert persisted_entry == entry
    assert persisted_job == job
    assert persisted_config == _load_config_profile_input()
    assert persisted_active_state == active_state
    persisted_activation = ConfigRegistryActivationRecord.model_validate(
        persisted_active_state.history[0].model_dump()
    )
    assert persisted_activation == active_activation

    assert entry.source_kind == "direct_config_profile"
    assert entry.registered_by == "operator"
    assert entry.source_run_id is None
    assert entry.proposal_id is None
    assert entry.config_ref == (
        f"config-registry/configs/{entry.id}.config-profile-snapshot.json"
    )
    assert entry.registration_job_ref == (
        f"config-registry/jobs/{entry.id}.registration.job.json"
    )
    assert job.input_refs == ["fixtures/core/simulated_scan/config-profile.json"]
    assert entry.config_ref in job.output_refs
    assert entry.registration_job_ref in job.output_refs
    assert "config-registry/index.json" in job.output_refs
    assert active_state.active_entry_id == entry.id
    assert active_state.history == [active_activation]
    assert active_activation.schema_version == (
        "scopecat.config_registry_activation_record.v0"
    )
    assert active_activation.entry_id == entry.id
    assert active_activation.operator == "operator"
    assert active_activation.note == "use direct config"
    assert load_config_registry_entry(entry_id=entry.id, workspace=tmp_path) == entry
    assert list_config_registry_entries(workspace=tmp_path) == [entry]
    assert load_active_config_registry_entry(workspace=tmp_path) == entry
    assert load_active_config_registry_state(workspace=tmp_path) == active_state
    active_config, provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    persisted_provenance = assert_model_round_trip(
        provenance,
        schema_version="scopecat.config_registry_config_source_provenance.v0",
    )
    assert persisted_provenance == provenance
    assert provenance.selector == "active"
    assert provenance.entry_id == entry.id
    assert provenance.config_ref == entry.config_ref
    assert provenance.active_state_ref == "config-registry/active.json"
    assert provenance.active_record_id == active_activation.id
    assert active_config.source is not None
    assert active_config.source.selector == provenance.selector
    assert active_config.source.entry_id == provenance.entry_id
    assert active_config.source.config_ref == provenance.config_ref
    assert active_config.source.active_state_ref == provenance.active_state_ref
    assert active_config.source.active_record_id == provenance.active_record_id


def _load_config_profile_input() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")
