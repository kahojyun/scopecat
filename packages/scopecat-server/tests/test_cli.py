from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest
from scopecat.application import LabBootstrap
from scopecat.automation import ProcedureControlError
from scopecat.config.documents import load_config_snapshot_document
from scopecat.daemon.endpoint import DaemonEndpointRecord
from scopecat.project import Project
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from typer.testing import CliRunner

from scopecat_server.cli import app

_CONFIG_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-snapshot.json"
)


def test_cli_import_keeps_daemon_runtime_cold() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import scopecat_server.cli

forbidden = {
    "fastapi",
    "pandas",
    "pyarrow",
    "scopecat_server.runtime",
    "xarray",
}
loaded = forbidden.intersection(sys.modules)
if loaded:
    raise SystemExit(f"CLI imported daemon runtime modules: {sorted(loaded)}")
""",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_config_check_resolves_lazy_bootstrap_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)
    config = load_config_snapshot_document(_CONFIG_FIXTURE)
    bootstrap_calls = 0

    def bootstrap_config() -> ConfigProfileSnapshot:
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        return config

    bootstrap = LabBootstrap(bootstrap_config=bootstrap_config)
    monkeypatch.setattr(
        Project,
        "load_bootstrap",
        _bootstrap_loader(bootstrap),
    )

    assert bootstrap_calls == 0
    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert bootstrap_calls == 1
    assert f"snapshot={config.id}" in result.output
    assert f"content_hash={config_content_hash(config)}" in result.output
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_rejects_missing_bootstrap_factory(tmp_path: Path) -> None:
    _write_manifest(tmp_path)

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "error: project bootstrap does not define bootstrap_config" in result.output
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_reports_invalid_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)
    config = load_config_snapshot_document(_CONFIG_FIXTURE)
    invalid_route = config.routing.routes[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid_config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "routing": config.routing.model_copy(
                        update={"routes": [invalid_route]}
                    )
                }
            )
        }
    )
    bootstrap = LabBootstrap(bootstrap_config=lambda: invalid_config)
    monkeypatch.setattr(
        Project,
        "load_bootstrap",
        _bootstrap_loader(bootstrap),
    )

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "error:" in result.output
    assert "configuration.unknown_resource_route_instrument" in result.output
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_reports_bootstrap_source_loader_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)

    def bootstrap_config() -> ConfigProfileSnapshot:
        return load_config_snapshot_document(tmp_path / "missing-config.json")

    bootstrap = LabBootstrap(bootstrap_config=bootstrap_config)
    monkeypatch.setattr(
        Project,
        "load_bootstrap",
        _bootstrap_loader(bootstrap),
    )

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "error:" in result.output
    assert "missing-config.json" in result.output
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_reports_bootstrap_import_error(tmp_path: Path) -> None:
    (tmp_path / "scopecat.toml").write_text(
        '[lab]\nbootstrap = "missing_cli_bootstrap:create"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "error:" in result.output
    assert "No module named 'missing_cli_bootstrap'" in result.output


def test_hidden_executor_lease_ttl_option_reaches_start_and_serve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)
    start_ttls: list[timedelta | None] = []
    serve_ttls: list[timedelta | None] = []

    def start_selected(
        project: Project,
        *,
        host: str,
        port: int,
        static_dir: Path | None,
        lease_ttl: timedelta | None,
    ) -> DaemonEndpointRecord:
        del host, port, static_dir
        start_ttls.append(lease_ttl)
        return DaemonEndpointRecord(
            project_root=project.root,
            pid=123,
            process_create_time=1,
            base_url="http://127.0.0.1:4321",
            shutdown_token="test-shutdown-token" * 2,
            started_at=datetime.now(UTC),
        )

    def serve_selected(
        project: Project,
        *,
        host: str,
        port: int,
        static_dir: Path | None,
        lease_ttl: timedelta | None,
    ) -> None:
        del project, host, port, static_dir
        serve_ttls.append(lease_ttl)

    monkeypatch.setattr("scopecat_server.lifecycle.start_project", start_selected)
    monkeypatch.setattr("scopecat_server.lifecycle.serve_project", serve_selected)
    runner = CliRunner()

    default_start = runner.invoke(app, ["start", str(tmp_path), "--api-only"])
    explicit_start = runner.invoke(
        app,
        [
            "start",
            str(tmp_path),
            "--api-only",
            "--executor-lease-ttl-seconds",
            "1.25",
        ],
    )
    explicit_serve = runner.invoke(
        app,
        [
            "serve",
            str(tmp_path),
            "--api-only",
            "--executor-lease-ttl-seconds",
            "1.25",
        ],
    )
    help_result = runner.invoke(app, ["start", "--help"])

    assert default_start.exit_code == 0, default_start.output
    assert explicit_start.exit_code == 0, explicit_start.output
    assert explicit_serve.exit_code == 0, explicit_serve.output
    assert start_ttls == [None, timedelta(seconds=1.25)]
    assert serve_ttls == [timedelta(seconds=1.25)]
    assert "--executor-lease-ttl-seconds" not in help_result.output


def test_procedure_worker_cli_supports_once_and_resident_polling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)
    calls: list[tuple[object, ...]] = []

    class FakeProcedureOperations:
        def interval_planner(self) -> object:
            calls.append(("planner",))
            return "interval-planner"

    procedure_operations = FakeProcedureOperations()

    class FakeCalibrationOperations:
        def publication_finalizer(self) -> object:
            calls.append(("calibration_finalizer",))
            return "calibration-finalizer"

        def evaluator(self) -> object:
            calls.append(("calibration_evaluator",))
            return "calibration-evaluator"

    calibration_operations = FakeCalibrationOperations()

    class FakeLab:
        procedures = procedure_operations
        calibrations = calibration_operations

        def __enter__(self) -> Self:
            calls.append(("enter",))
            return self

        def __exit__(self, *_args: object) -> None:
            calls.append(("exit",))

    class FakeWorker:
        worker_id = "worker-cli"

        def __init__(
            self,
            operations: object,
            *,
            planner: object,
            calibration_evaluator: object,
            calibration_finalizer: object,
        ) -> None:
            calls.append(
                (
                    "worker",
                    operations,
                    planner,
                    calibration_evaluator,
                    calibration_finalizer,
                )
            )

        def cycle(self) -> object:
            calls.append(("cycle",))
            return SimpleNamespace(
                ready_calibration_publications=3,
                prepared_calibration_publications=2,
                published_calibration_publications=1,
                deferred_calibration_publications=1,
                attention_calibration_publications=0,
                reconciled_calibration_publications=1,
                superseded_calibration_publications=1,
                calibration_publication_races=1,
                calibration_publication_failures=0,
                calibration_publication_barrier=True,
                created_interval_schedules=1,
                planner_failures=0,
                interval_schedule_drifts=0,
                calibration_failures=0,
                calibration_cohort_drifts=0,
                admitted_calibrations=2,
                blocked_calibrations=1,
                materialized_schedules=2,
                dispatched_procedures=1,
                schedule_failures=0,
                procedure_failures=0,
                procedure_conflicts=0,
                schedule_conflicts=1,
                lease_conflicts=0,
            )

        def run_forever(
            self,
            stop: object,
            *,
            poll_seconds: float,
            on_cycle: Callable[[object], None],
            on_retry: object,
        ) -> None:
            del stop, on_retry
            calls.append(("run_forever", poll_seconds))
            on_cycle(
                SimpleNamespace(
                    calibration_publication_failures=1,
                    attention_calibration_publications=1,
                    planner_failures=0,
                    interval_schedule_drifts=0,
                    calibration_failures=1,
                    calibration_cohort_drifts=0,
                    schedule_failures=1,
                    procedure_failures=0,
                    procedure_conflicts=1,
                )
            )

    def connect(_project: Project) -> FakeLab:
        return FakeLab()

    monkeypatch.setattr(Project, "connect", connect)
    monkeypatch.setattr(
        "scopecat.api.procedure_worker.ProjectProcedureWorkerLoop",
        FakeWorker,
    )
    runner = CliRunner()

    once = runner.invoke(
        app,
        ["procedures", "work", str(tmp_path), "--once"],
    )
    resident = runner.invoke(
        app,
        ["procedures", "work", str(tmp_path), "--poll-seconds", "2.5"],
    )

    assert once.exit_code == 0, once.output
    assert "publication_ready=3" in once.output
    assert "publication_published=1" in once.output
    assert "publication_reconciled=1" in once.output
    assert "publication_superseded=1" in once.output
    assert "publication_barrier=true" in once.output
    assert "interval_created=1" in once.output
    assert "calibration_admitted=2" in once.output
    assert "materialized=2" in once.output
    assert "dispatched=1" in once.output
    assert resident.exit_code == 0, resident.output
    assert "worker worker-cli" in resident.output
    assert "procedure cycle needs review" in resident.output
    assert "publication_failures=1" in resident.output
    assert "procedure_conflicts=1" in resident.output
    assert ("run_forever", 2.5) in calls

    class OutcomeFailureWorker:
        worker_id = "worker-outcome-failure"

        def __init__(
            self,
            _operations: object,
            *,
            planner: object,
            calibration_evaluator: object,
            calibration_finalizer: object,
        ) -> None:
            assert planner == "interval-planner"
            assert calibration_evaluator == "calibration-evaluator"
            assert calibration_finalizer == "calibration-finalizer"

        def cycle(self) -> object:
            return SimpleNamespace(
                ready_calibration_publications=1,
                prepared_calibration_publications=0,
                published_calibration_publications=0,
                deferred_calibration_publications=0,
                attention_calibration_publications=1,
                reconciled_calibration_publications=0,
                superseded_calibration_publications=0,
                calibration_publication_races=0,
                calibration_publication_failures=1,
                calibration_publication_barrier=False,
                created_interval_schedules=0,
                planner_failures=0,
                interval_schedule_drifts=1,
                calibration_failures=0,
                calibration_cohort_drifts=0,
                admitted_calibrations=0,
                blocked_calibrations=0,
                materialized_schedules=0,
                dispatched_procedures=0,
                schedule_failures=0,
                procedure_failures=0,
                procedure_conflicts=0,
                schedule_conflicts=0,
                lease_conflicts=0,
            )

    monkeypatch.setattr(
        "scopecat.api.procedure_worker.ProjectProcedureWorkerLoop",
        OutcomeFailureWorker,
    )
    failed_outcome = runner.invoke(
        app,
        ["procedures", "work", str(tmp_path), "--once"],
    )

    assert failed_outcome.exit_code == 1
    assert "cycle completed with failures" in failed_outcome.output
    assert "publication_failures=1" in failed_outcome.output
    assert "interval_drifts=1" in failed_outcome.output
    assert "error: procedure worker cycle reported 2 failure" in failed_outcome.output

    class FailingWorker:
        worker_id = "worker-failing"

        def __init__(
            self,
            _operations: object,
            *,
            planner: object,
            calibration_evaluator: object,
            calibration_finalizer: object,
        ) -> None:
            assert planner == "interval-planner"
            assert calibration_evaluator == "calibration-evaluator"
            assert calibration_finalizer == "calibration-finalizer"

        def cycle(self) -> object:
            raise ProcedureControlError(
                "list_due_procedure_schedules",
                RuntimeError("daemon is unavailable"),
            )

    monkeypatch.setattr(
        "scopecat.api.procedure_worker.ProjectProcedureWorkerLoop",
        FailingWorker,
    )
    failed = runner.invoke(
        app,
        ["procedures", "work", str(tmp_path), "--once"],
    )

    assert failed.exit_code == 1
    assert "error: procedure control operation" in failed.output
    assert "daemon is unavailable" in failed.output


def _write_manifest(project: Path) -> None:
    (project / "scopecat.toml").write_text("[lab]\n", encoding="utf-8")


def _bootstrap_loader(
    bootstrap: LabBootstrap,
) -> Callable[[Project], LabBootstrap]:
    def load_bootstrap(_project: Project) -> LabBootstrap:
        return bootstrap

    return load_bootstrap
