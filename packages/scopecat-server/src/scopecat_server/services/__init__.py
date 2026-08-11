"""Lazy public application-service entry points."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat_server.instruments.service import InstrumentService

    from .admission import AdmissionService
    from .application import DaemonApplication
    from .config import ConfigService
    from .executor import ExecutorService
    from .leases import OwnershipLeaseSupervisor
    from .payloads import CommandPayloadService
    from .runs import RunService

_EXPORTS = {
    "AdmissionService": ("scopecat_server.services.admission", "AdmissionService"),
    "CommandPayloadService": (
        "scopecat_server.services.payloads",
        "CommandPayloadService",
    ),
    "ConfigService": ("scopecat_server.services.config", "ConfigService"),
    "DaemonApplication": (
        "scopecat_server.services.application",
        "DaemonApplication",
    ),
    "ExecutorService": ("scopecat_server.services.executor", "ExecutorService"),
    "InstrumentService": (
        "scopecat_server.instruments.service",
        "InstrumentService",
    ),
    "OwnershipLeaseSupervisor": (
        "scopecat_server.services.leases",
        "OwnershipLeaseSupervisor",
    ),
    "RunService": ("scopecat_server.services.runs", "RunService"),
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


__all__ = [
    "AdmissionService",
    "CommandPayloadService",
    "ConfigService",
    "DaemonApplication",
    "ExecutorService",
    "InstrumentService",
    "OwnershipLeaseSupervisor",
    "RunService",
]
