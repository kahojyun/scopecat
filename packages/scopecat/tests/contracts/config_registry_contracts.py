"""Reusable behavior for workspace configuration-registry units of work."""

from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.config.profiles import load_config_profile
from scopecat.config.registry.ports import WorkspaceUnitOfWorkFactory
from scopecat.config.registry.service import (
    current_config_registry_generation,
    list_config_registry_entries,
    load_active_config_registry_state,
    load_config_registry_config,
    register_and_activate_config_profile,
    register_config_profile,
    resolve_config_registry_config_source,
)
from scopecat.kernel.errors import Conflict
from tests.testkit.paths import CORE_FIXTURE_DIR


class ConfigRegistryUnitOfWorkContract:
    """Registration, CAS activation, and reads shared by all UoWs."""

    def make_unit_of_work(self, tmp_path: Path) -> WorkspaceUnitOfWorkFactory:
        raise NotImplementedError

    def test_registration_is_idempotent_and_round_trips(self, tmp_path: Path) -> None:
        unit_of_work = self.make_unit_of_work(tmp_path)
        config = load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")

        first = register_config_profile(
            config=config,
            unit_of_work=unit_of_work,
            entry_id="contract-entry",
            registered_by="contract",
            note="same request",
        )
        repeated = register_config_profile(
            config=config.model_copy(deep=True),
            unit_of_work=unit_of_work,
            entry_id="contract-entry",
            registered_by="contract",
            note="same request",
        )

        assert repeated == first
        assert (
            load_config_registry_config(
                entry_id=first.id,
                unit_of_work=unit_of_work,
            )
            == config
        )
        assert list_config_registry_entries(unit_of_work=unit_of_work) == [first]

    def test_duplicate_identity_rejects_different_request(self, tmp_path: Path) -> None:
        unit_of_work = self.make_unit_of_work(tmp_path)
        config = load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")
        register_config_profile(
            config=config,
            unit_of_work=unit_of_work,
            entry_id="contract-conflict",
            registered_by="first",
        )

        with pytest.raises(Conflict) as captured:
            register_config_profile(
                config=config,
                unit_of_work=unit_of_work,
                entry_id="contract-conflict",
                registered_by="different",
            )
        assert captured.value.problems[0].code == "config_registry.duplicate_entry"

    def test_activation_uses_generation_cas_and_resolves_source(
        self,
        tmp_path: Path,
    ) -> None:
        unit_of_work = self.make_unit_of_work(tmp_path)
        config = load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")
        entry, state, _activation = register_and_activate_config_profile(
            config=config,
            unit_of_work=unit_of_work,
            entry_id="contract-active",
            registered_by="contract",
            operator="contract",
            expected_generation=0,
        )

        assert state.generation == 1
        assert current_config_registry_generation(unit_of_work=unit_of_work) == 1
        assert load_active_config_registry_state(unit_of_work=unit_of_work) == state
        resolved, source = resolve_config_registry_config_source(
            selector="active",
            unit_of_work=unit_of_work,
        )
        assert resolved == config
        assert source.entry_id == entry.id

        with pytest.raises(Conflict) as captured:
            register_and_activate_config_profile(
                config=config,
                unit_of_work=unit_of_work,
                entry_id="stale-generation",
                registered_by="contract",
                operator="contract",
                expected_generation=0,
            )
        assert captured.value.problems[0].code == "config_registry.conflict"


__all__ = ["ConfigRegistryUnitOfWorkContract"]
