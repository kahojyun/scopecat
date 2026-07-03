from __future__ import annotations

from pathlib import Path

import scopecat as sc
from demo_lab_readout_frequency_testkit import (
    config_profile_snapshot,
    readout_frequency_experiment,
    readout_frequency_provider,
)
from scopecat.config_registry import (
    load_config_registry_entry,
    resolve_config_registry_config_source,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.workflows import register_and_activate_config_profile
from scopecat.workflows.runs import start_run

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
    first_run = start_run(
        config=first_active_config,
        experiment=readout_frequency_experiment(),
        instrument_provider=readout_frequency_provider(),
        workspace=tmp_path,
    )
    run_id = first_run.run_id

    lab = sc.open(tmp_path, config=first_active_config)
    run = lab.get_run(run_id)
    first_config = run.config
    assert _parameter_value(first_config, "readout_frequency") == Quantity(
        value=5.94,
        unit="GHz",
    )
    assert first_config.source is not None
    assert first_config.source.selector == "active"
    assert first_config.source.entry_id == "readout-frr-seed"
    assert first_provenance.entry_id == "readout-frr-seed"

    update_result = execute_readout_frequency_analysis_update(
        run=run,
        workspace=tmp_path,
        operator="operator",
    )

    assert update_result.change_set_id == "readout_frequency"
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

    candidate_config = ConfigProfileSnapshot.model_validate(
        run.data()
        .json(
            update_result.candidate_artifact_id,
            expected_kind="candidate_config",
        )
        .content
    )
    candidate_artifact = run.data().artifact(
        update_result.candidate_artifact_id,
        expected_kind="candidate_config",
    )
    assert candidate_artifact.id == entry.source_candidate_artifact_id
    assert _parameter_value(candidate_config, "readout_frequency") == Quantity(
        value=5.953,
        unit="GHz",
    )

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

    next_run = start_run(
        config=active_config,
        experiment=readout_frequency_experiment(),
        instrument_provider=readout_frequency_provider(),
        workspace=tmp_path,
    )
    next_config = lab.get_run(next_run.run_id).config
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
