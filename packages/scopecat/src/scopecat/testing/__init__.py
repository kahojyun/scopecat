"""Reusable support for testing Scopecat integrations."""

from scopecat.testing.composition import (
    memory_project_services,
    sqlite_config_registry_unit_of_work,
    sqlite_execution_services,
    sqlite_project_services,
    sqlite_run_repository,
)
from scopecat.testing.run_operations import ServiceRunOperations

__all__ = [
    "ServiceRunOperations",
    "memory_project_services",
    "sqlite_config_registry_unit_of_work",
    "sqlite_execution_services",
    "sqlite_project_services",
    "sqlite_run_repository",
]
