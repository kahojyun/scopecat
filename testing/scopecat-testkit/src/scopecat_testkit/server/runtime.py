"""In-process runtime fixtures shared across workspace tests."""

from scopecat_testkit.execution_fakes import (
    FakeExecutionJournal,
    FakeMeasurementDatasetRepository,
)
from scopecat_testkit.planning import (
    check_experiment,
    plan_experiment,
    resolve_test_config,
)
from scopecat_testkit.server.composition import (
    SQLiteTestExecutionJournal,
    SQLiteTestRunRepository,
    admit_test_run,
    list_test_runs,
    sqlite_config_registry_unit_of_work,
    sqlite_execution_session,
    sqlite_project_services,
    sqlite_run_repository,
)
from scopecat_testkit.server.service_run_operations import ServiceRunOperations

__all__ = [
    "FakeExecutionJournal",
    "FakeMeasurementDatasetRepository",
    "SQLiteTestExecutionJournal",
    "SQLiteTestRunRepository",
    "ServiceRunOperations",
    "admit_test_run",
    "check_experiment",
    "list_test_runs",
    "plan_experiment",
    "resolve_test_config",
    "sqlite_config_registry_unit_of_work",
    "sqlite_execution_session",
    "sqlite_project_services",
    "sqlite_run_repository",
]
