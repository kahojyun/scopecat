# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Lazy facade for configuration-registry records, ports, and use cases."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.config.registry.ports import (
        ConfigRegistryRepository,
        ConfigRegistryUnitOfWork,
        ConfigRegistryUnitOfWorkFactory,
    )
    from scopecat.config.registry.records import (
        CandidateConfigRegistrySource,
        CandidateProposalRegistryEvidence,
        ConfigRegistryActivationRecord,
        ConfigRegistryActiveState,
        ConfigRegistryEntry,
        ConfigRegistryEntrySource,
        DirectConfigRegistrySource,
        ManualConfigDraftRegistrySource,
    )
    from scopecat.config.registry.service import (
        ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR,
        ActiveConfigRegistrySnapshot,
        ConfigRegistryEntrySnapshot,
        ConfigRegistrySnapshot,
        ManualConfigDraftResult,
        activate_config_registry_entry,
        current_config_registry_generation,
        list_config_registry_entries,
        load_active_config_registry_config,
        load_active_config_registry_entry,
        load_active_config_registry_snapshot,
        load_active_config_registry_state,
        load_config_registry_activation_history,
        load_config_registry_entry_snapshot,
        load_config_registry_snapshot,
        preview_manual_config_draft,
        register_and_activate_candidate_config,
        register_and_activate_config_profile,
        register_and_activate_manual_config_draft,
        register_config_profile,
        register_manual_config_draft,
        resolve_config_registry_config_source,
        rollback_config_registry,
    )


_RECORD_EXPORTS = (
    "CandidateConfigRegistrySource",
    "CandidateProposalRegistryEvidence",
    "ConfigRegistryActivationRecord",
    "ConfigRegistryActiveState",
    "ConfigRegistryEntry",
    "ConfigRegistryEntrySource",
    "DirectConfigRegistrySource",
    "ManualConfigDraftRegistrySource",
)
_PORT_EXPORTS = (
    "ConfigRegistryRepository",
    "ConfigRegistryUnitOfWork",
    "ConfigRegistryUnitOfWorkFactory",
)
_SERVICE_EXPORTS = (
    "ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR",
    "ActiveConfigRegistrySnapshot",
    "ConfigRegistryEntrySnapshot",
    "ConfigRegistrySnapshot",
    "ManualConfigDraftResult",
    "activate_config_registry_entry",
    "current_config_registry_generation",
    "list_config_registry_entries",
    "load_active_config_registry_config",
    "load_active_config_registry_entry",
    "load_active_config_registry_snapshot",
    "load_active_config_registry_state",
    "load_config_registry_activation_history",
    "load_config_registry_entry_snapshot",
    "load_config_registry_snapshot",
    "preview_manual_config_draft",
    "register_and_activate_candidate_config",
    "register_and_activate_config_profile",
    "register_and_activate_manual_config_draft",
    "register_config_profile",
    "register_manual_config_draft",
    "resolve_config_registry_config_source",
    "rollback_config_registry",
)
_EXPORTS = {
    **{name: ("scopecat.config.registry.records", name) for name in _RECORD_EXPORTS},
    **{name: ("scopecat.config.registry.ports", name) for name in _PORT_EXPORTS},
    **{name: ("scopecat.config.registry.service", name) for name in _SERVICE_EXPORTS},
}


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = cast("object", getattr(import_module(module_name), attribute_name))
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = sorted(_EXPORTS)
