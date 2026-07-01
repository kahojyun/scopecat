from __future__ import annotations

from pathlib import Path

import scopecat as sc
from demo_lab_readout_frequency_testkit import (
    config_profile_snapshot,
    readout_frequency_adapter,
    readout_frequency_experiment,
)
from demo_lab_records import assert_artifact_ref, read_model
from scopecat.config_registry import (
    load_config_registry_entry,
    resolve_config_registry_config_source,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.runner import execute_runner_adapter
from scopecat.runs import open_run_store
from scopecat.workflows import register_and_activate_config_profile

from quantum_lab_demo.readout.frequency_update import (
    execute_readout_frequency_analysis_update,
)


def test_readout_frequency_parameter_update_loop_activates_config_registry(
    tmp_path: Path,
) -> None:
    initial_config = _config_with_readout_frequency(5.94)
    registration = register_and_activate_config_profile(
        config=initial_config,
        workspace=tmp_path,
        entry_id="readout-frr-seed",
        registered_by="operator",
        operator="operator",
        note="seed readout config",
    )
    initial_entry = registration.entry
    active_state = registration.active_state
    assert initial_entry.source_kind == "direct_config_profile"
    assert active_state.active_entry_id == "readout-frr-seed"

    first_active_config, first_provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    manifest, _snapshot = execute_runner_adapter(
        config=first_active_config,
        experiment=readout_frequency_experiment(),
        adapter=readout_frequency_adapter(),
        workspace=tmp_path,
    )
    run_id = manifest.run_id

    storage = open_run_store(tmp_path)
    first_config = storage.read_config_profile_snapshot(run_id)
    assert _parameter_value(first_config, "readout_frequency") == Quantity(
        value=5.94,
        unit="GHz",
    )
    assert first_config.source is not None
    assert first_config.source.selector == "active"
    assert first_config.source.entry_id == "readout-frr-seed"
    assert first_provenance.entry_id == "readout-frr-seed"

    lab = sc.open(tmp_path, config=first_active_config, mode="native_simulate")
    update_result = execute_readout_frequency_analysis_update(
        run=lab.get_run(run_id),
        workspace=tmp_path,
        operator="operator",
    )

    assert update_result.change_set_id == "readout_frequency"
    assert update_result.candidate_artifact_id == (
        "candidate-readout-frequency-analysis-readout_frequency-candidate-config"
    )
    assert update_result.config_registry_entry_id == f"readout-frr-{run_id}"
    assert update_result.active_entry_id == update_result.config_registry_entry_id
    entry = load_config_registry_entry(
        entry_id=update_result.config_registry_entry_id,
        workspace=tmp_path,
    )
    assert entry.source_kind == "candidate_config"
    assert entry.registered_by == "operator"
    assert entry.source_run_id == run_id
    assert entry.change_set_ids == ["readout_frequency"]
    assert entry.change_set_artifact_ids == [update_result.change_set_artifact_id]
    assert entry.source_candidate_artifact_id == update_result.candidate_artifact_id

    updated_manifest = storage.read_manifest(run_id)
    candidate_config_artifact = assert_artifact_ref(
        updated_manifest.artifact_refs,
        update_result.candidate_artifact_id,
        kind="candidate_config",
    )
    artifact_ids = {artifact.id for artifact in updated_manifest.artifact_refs}
    assert not any("export" in artifact_id for artifact_id in artifact_ids)
    assert not any("promotion" in artifact_id for artifact_id in artifact_ids)
    candidate_config = read_model(
        storage.ref_path(run_id, candidate_config_artifact.path),
        ConfigProfileSnapshot,
    )
    assert _parameter_value(candidate_config, "readout_frequency") == Quantity(
        value=5.953,
        unit="GHz",
    )

    assert not (tmp_path / "runs" / run_id / "comparisons").exists()
    assert not any("comparison" in artifact_id for artifact_id in artifact_ids)

    active_config, provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    assert provenance.selector == "active"
    assert provenance.entry_id == update_result.config_registry_entry_id
    assert _parameter_value(active_config, "readout_frequency") == Quantity(
        value=5.953,
        unit="GHz",
    )

    next_manifest, _next_snapshot = execute_runner_adapter(
        config=active_config,
        experiment=readout_frequency_experiment(),
        adapter=readout_frequency_adapter(),
        workspace=tmp_path,
    )
    next_config = storage.read_config_profile_snapshot(next_manifest.run_id)
    assert _parameter_value(next_config, "readout_frequency") == Quantity(
        value=5.953,
        unit="GHz",
    )
    assert next_config.source is not None
    assert next_config.source.selector == "active"


def _config_with_readout_frequency(value: float) -> ConfigProfileSnapshot:
    config = config_profile_snapshot()
    parameters = []
    for parameter in config.parameter_state.scalar_value_set().values:
        if parameter.id == "readout_frequency":
            parameters.append(
                parameter.model_copy(
                    update={"quantity": Quantity(value=value, unit="GHz")}
                )
            )
            continue
        parameters.append(parameter)
    scalar_values = config.parameter_state.scalar_value_set().model_copy(
        update={"values": parameters}
    )
    parameter_state = config.parameter_state.model_copy(
        update={"scalar_values": scalar_values}
    )
    return ConfigProfileSnapshot.model_validate(
        config.model_dump(mode="python") | {"parameter_state": parameter_state}
    )


def _parameter_value(
    config: ConfigProfileSnapshot,
    parameter_id: str,
) -> Quantity:
    parameter = (
        config.parameter_build.get(parameter_id)
        if config.parameter_build is not None
        else None
    )
    assert parameter is not None
    return parameter.quantity
