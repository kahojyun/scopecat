from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.composition.embedded import embedded_workspace_services
from scopecat.config.registry import DirectConfigRegistrySource
from scopecat.config.resolution import (
    activate_config_entry,
    load_active_config,
    register_and_activate_config_profile,
    register_config_profile,
    resolve_config_source,
    resolve_experiment_config,
    rollback_config,
    validate_config_profile,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.records.run import ConfigRegistryRunConfigSource
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.workflow_fixtures import load_config


def test_resolve_config_source_loads_file_or_active_registry(
    tmp_path: Path,
) -> None:
    file_source = resolve_config_source(
        services=embedded_workspace_services(tmp_path),
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    assert file_source.config.id == "simple-scan-profile"
    assert file_source.config_source is None

    registration = register_and_activate_config_profile(
        config=file_source.config,
        services=embedded_workspace_services(tmp_path),
        entry_id="active-seed",
        registered_by="operator",
        operator="operator",
    )
    entry = registration.entry
    active_source = resolve_config_source(
        services=embedded_workspace_services(tmp_path), config_entry="active"
    )
    loaded_active = load_active_config(services=embedded_workspace_services(tmp_path))

    assert isinstance(
        active_source.config_source,
        ConfigRegistryRunConfigSource,
    )
    assert active_source.config_source.entry_id == entry.id
    assert isinstance(
        loaded_active.config_source,
        ConfigRegistryRunConfigSource,
    )
    assert loaded_active.config_source.entry_id == entry.id


def test_resolve_experiment_config_normalizes_snapshot_and_profile(
    tmp_path: Path,
) -> None:
    services = embedded_workspace_services(tmp_path)
    snapshot = load_config()

    direct = resolve_experiment_config(services=services, config=snapshot)
    profile = resolve_experiment_config(
        services=services,
        config="active",
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    assert direct.config == snapshot
    assert direct.config_source is None
    assert profile.config == snapshot
    assert profile.config_source is None


def test_config_workflow_validates_file_and_config_object() -> None:
    file_result = validate_config_profile(EXAMPLE_DIR / "config-profile.json")
    object_result = validate_config_profile(file_result.config)

    assert file_result.config.id == "simple-scan-profile"
    assert object_result.config == file_result.config
    assert file_result.problems == ()
    assert object_result.problems == ()


def test_config_workflow_validation_rejects_blocking_problems() -> None:
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

    with pytest.raises(CheckFailed) as error:
        validate_config_profile(invalid_config)

    assert error.value.problems[0].code == "configuration.unknown_connection_instrument"


def test_config_workflow_registers_direct_entry_idempotently(
    tmp_path: Path,
) -> None:
    config = load_config()
    result = register_config_profile(
        config=config,
        services=embedded_workspace_services(tmp_path),
        entry_id="seed",
        registered_by="operator",
        note="seed config",
    )
    repeated = register_config_profile(
        config=load_config(),
        services=embedded_workspace_services(tmp_path),
        entry_id="seed",
        registered_by="operator",
        note="seed config",
    )

    assert isinstance(result.source, DirectConfigRegistrySource)
    persisted_config = resolve_config_source(
        services=embedded_workspace_services(tmp_path),
        config_entry=result.id,
    )
    assert persisted_config.config.model_copy(update={"source": None}) == (
        config.model_copy(update={"source": None})
    )
    assert repeated.id == result.id


def test_config_workflow_register_activate_activate_and_rollback(
    tmp_path: Path,
) -> None:
    first = register_and_activate_config_profile(
        config=load_config(),
        services=embedded_workspace_services(tmp_path),
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
        note="seed a",
    )
    second = register_and_activate_config_profile(
        config=load_config(),
        services=embedded_workspace_services(tmp_path),
        entry_id="seed-b",
        registered_by="operator",
        operator="operator",
        note="seed b",
        activation_note="activate b",
    )
    reactivated = activate_config_entry(
        entry_id=first.entry.id,
        services=embedded_workspace_services(tmp_path),
        operator="operator",
        note="switch back to a",
    )
    rollback = rollback_config(
        services=embedded_workspace_services(tmp_path),
        operator="operator",
        expected_generation=reactivated.active_state.generation,
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
        (EXAMPLE_DIR / "config-profile.json", "active", "config.source_conflict"),
        (None, None, "config.source_missing"),
    ],
)
def test_resolve_config_source_rejects_invalid_source_selection(
    tmp_path: Path,
    config_profile: Path | None,
    config_entry: str | None,
    code: str,
) -> None:
    with pytest.raises(CheckFailed) as error:
        resolve_config_source(
            services=embedded_workspace_services(tmp_path),
            config_profile=config_profile,
            config_entry=config_entry,
        )

    assert error.value.problems[0].code == code
