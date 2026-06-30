from __future__ import annotations

from pathlib import Path

from scopecat.config_registry import (
    activate_config_registry_entry,
    load_config_registry_entry,
    resolve_config_registry_config_source,
)
from tests.support.config_registry import (
    accept_best_signal,
    load_experiment,
    simulate_and_evaluate,
)
from tests.support.signal_testkit import execute_signal_native_run


def test_accept_parameter_proposal_active_config_can_start_next_run(
    tmp_path: Path,
) -> None:
    run_id = simulate_and_evaluate(tmp_path)
    entry_id = accept_best_signal(tmp_path, run_id)
    config, provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )

    next_manifest, _snapshot = execute_signal_native_run(
        config=config,
        experiment=load_experiment(),
        workspace=tmp_path,
    )

    assert provenance.entry_id == entry_id
    assert next_manifest.config_profile_snapshot_ref == "config-profile.snapshot.json"


def test_activate_config_registry_entry_and_rollback(tmp_path: Path) -> None:
    run_id_a = simulate_and_evaluate(tmp_path)
    run_id_b = simulate_and_evaluate(tmp_path)
    entry_a = accept_best_signal(tmp_path, run_id_a, entry_id="entry-a")
    entry_b = accept_best_signal(tmp_path, run_id_b, entry_id="entry-b")

    active_state, _activation = activate_config_registry_entry(
        entry_id=entry_a,
        workspace=tmp_path,
        operator="operator",
        note="switch back",
    )

    assert entry_b != entry_a
    assert active_state.active_entry_id == entry_a
    assert (
        load_config_registry_entry(entry_id=entry_a, workspace=tmp_path).id == entry_a
    )
