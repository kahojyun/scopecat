from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.workflows import (
    activate_config_entry,
    load_active_config,
    register_and_activate_config_profile,
    register_config_profile,
    resolve_config_source,
    rollback_config,
    validate_config_profile,
)
from tests.support.records import read_model
from tests.support.workflow_fixtures import (
    WORKFLOW_FIXTURE_DIR as EXAMPLE_DIR,
)
from tests.support.workflow_fixtures import (
    load_config,
)


def test_resolve_config_source_loads_file_or_active_registry(
    tmp_path: Path,
) -> None:
    file_source = resolve_config_source(
        workspace=tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    assert file_source.config.workspace_id == "simulated-workspace"
    assert file_source.provenance is None

    registration = register_and_activate_config_profile(
        config=file_source.config,
        workspace=tmp_path,
        entry_id="active-seed",
        registered_by="operator",
        operator="operator",
    )
    entry = registration.entry
    active_source = resolve_config_source(workspace=tmp_path, config_entry="active")
    loaded_active = load_active_config(workspace=tmp_path)

    assert active_source.provenance is not None
    assert active_source.provenance.entry_id == entry.id
    assert loaded_active.provenance is not None
    assert loaded_active.provenance.entry_id == entry.id
    assert loaded_active.config.source is not None


def test_config_workflow_validates_file_and_config_object() -> None:
    file_result = validate_config_profile(EXAMPLE_DIR / "config-profile.json")
    object_result = validate_config_profile(file_result.config)

    assert file_result.config.workspace_id == "simulated-workspace"
    assert object_result.config == file_result.config
    assert file_result.diagnostics == []
    assert object_result.diagnostics == []


def test_config_workflow_validation_rejects_blocking_diagnostics() -> None:
    config = load_config()
    invalid_connection = config.connection_profile.connections[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid_environment = config.environment.model_copy(
        update={
            "connection_profile": config.connection_profile.model_copy(
                update={"connections": [invalid_connection]}
            )
        }
    )
    invalid_config = config.model_copy(update={"environment": invalid_environment})

    with pytest.raises(ValidationFailed) as error:
        validate_config_profile(invalid_config)

    assert error.value.diagnostics[0].code == "unknown_connection_instrument"


def test_config_workflow_registers_direct_entry_idempotently(
    tmp_path: Path,
) -> None:
    config = load_config()
    result = register_config_profile(
        config=config,
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
        note="seed config",
        source_ref="fixtures/core/simulated_scan/config-profile.json",
    )
    repeated = register_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed",
        registered_by="operator",
        note="seed config",
        source_ref="fixtures/core/simulated_scan/config-profile.json",
    )

    assert result.job.id == "seed"
    assert result.job.input_refs == ["fixtures/core/simulated_scan/config-profile.json"]
    assert result.entry.source_kind == "direct_config_profile"
    persisted_config = read_model(
        tmp_path / result.entry.config_ref,
        ConfigProfileSnapshot,
    )
    assert persisted_config == config
    assert repeated.job.id == result.job.id
    assert repeated.entry.id == result.entry.id


def test_config_workflow_register_activate_activate_and_rollback(
    tmp_path: Path,
) -> None:
    first = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
        note="seed a",
    )
    second = register_and_activate_config_profile(
        config=load_config(),
        workspace=tmp_path,
        entry_id="seed-b",
        registered_by="operator",
        operator="operator",
        note="seed b",
        activation_note="activate b",
    )
    reactivated = activate_config_entry(
        entry_id=first.entry.id,
        workspace=tmp_path,
        operator="operator",
        note="switch back to a",
    )
    rollback = rollback_config(
        workspace=tmp_path,
        operator="operator",
        note="restore b",
    )

    assert first.active_state.active_entry_id == "seed-a"
    assert second.active_state.active_entry_id == "seed-b"
    assert second.activation.note == "activate b"
    assert reactivated.active_state.active_entry_id == "seed-a"
    assert reactivated.activation.previous_entry_id == "seed-b"
    assert rollback.active_state.active_entry_id == "seed-b"
    assert rollback.activation.previous_entry_id == "seed-a"


@pytest.mark.parametrize(
    ("config_profile", "config_entry", "code"),
    [
        (EXAMPLE_DIR / "config-profile.json", "active", "conflicting_config_source"),
        (None, None, "missing_config_source"),
    ],
)
def test_resolve_config_source_rejects_invalid_source_selection(
    tmp_path: Path,
    config_profile: Path | None,
    config_entry: str | None,
    code: str,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        resolve_config_source(
            workspace=tmp_path,
            config_profile=config_profile,
            config_entry=config_entry,
        )

    assert error.value.diagnostics[0].code == code
