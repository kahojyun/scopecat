from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from scopecat.config.documents import load_config_snapshot_document
from scopecat.control.models import (
    DurableEvent,
    EventPage,
    RunPlanSummary,
)
from scopecat.daemon.views import (
    RunDetail,
)
from scopecat.daemon.wire import (
    ExecutorLease,
    ExecutorStartRequest,
    RunAdmission,
    RunSubmission,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest

from scopecat_server import (
    BackendConflict,
    BackendNotFound,
    DaemonHealth,
    create_app,
)
from scopecat_server.application import DaemonApplication

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)
_HASH = f"sha256:{'a' * 64}"
_REQUEST = RunRequest(experiment_id="request-1")
_CONFIG_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-snapshot.json"
)


class FakeApplication:
    def __init__(self) -> None:
        self.runs = FakeRuns(
            events=(
                DurableEvent(
                    event_id=1,
                    run_id="run-1",
                    kind="run_admitted",
                    payload={"state": "accepted"},
                    occurred_at=_NOW,
                ),
                DurableEvent(
                    event_id=2,
                    run_id="run-1",
                    kind="run_state_changed",
                    payload={"state": "running"},
                    occurred_at=_NOW + timedelta(seconds=1),
                ),
            )
        )
        self.executor = FakeExecutor()
        self.last_submission: RunSubmission | None = None

    def health(self) -> DaemonHealth:
        return DaemonHealth(
            status="ok",
            project_id="test-project",
            project_name="test-lab",
            project_root="/projects/test-lab",
        )

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        if submission.submission_id == "duplicate":
            raise BackendConflict("submission already exists")
        self.last_submission = submission
        return _wire_admission(submission.submission_id)


class FakeRuns:
    def __init__(self, *, events: tuple[DurableEvent, ...]) -> None:
        self.events = events
        self.event_afters: list[int | None] = []

    def get_run(self, run_id: str) -> RunDetail:
        raise BackendNotFound(f"run was not found: {run_id}")

    def list_events(
        self,
        *,
        limit: int,
        after: int | None,
        run_id: str | None,
        latest: bool,
    ) -> EventPage:
        del latest
        self.event_afters.append(after)
        selected = tuple(
            event
            for event in self.events
            if event.event_id > (after or 0)
            and (run_id is None or event.run_id == run_id)
        )
        return EventPage(items=selected[:limit])


class FakeExecutor:
    def __init__(self) -> None:
        self.last_start: ExecutorStartRequest | None = None

    def start_executor(
        self,
        run_id: str,
        request: ExecutorStartRequest,
    ) -> ExecutorLease:
        if run_id != "run-1":
            raise BackendNotFound(f"run was not found: {run_id}")
        self.last_start = request
        return _executor_lease()


def _create_test_app(
    backend: FakeApplication,
    *,
    static_dir: Path | None = None,
) -> FastAPI:
    # Each test supplies only the service methods reachable through its route.
    return create_app(
        cast("DaemonApplication", cast("object", backend)),
        static_dir=static_dir,
    )


def test_run_queries_reject_conflicting_page_modes() -> None:
    client = TestClient(_create_test_app(FakeApplication()))

    both_cursors = client.get(
        "/api/v1/runs",
        params={"after": 1, "before": 2},
    )
    latest_cursor = client.get(
        "/api/v1/runs",
        params={"latest": "true", "before": 2},
    )

    assert both_cursors.status_code == 422
    assert latest_cursor.status_code == 422


def test_run_submission_and_backend_error_mapping() -> None:
    backend = FakeApplication()
    client = TestClient(_create_test_app(backend))

    response = client.post("/api/v1/runs", json=_submission("submission-1"))
    conflict = client.post("/api/v1/runs", json=_submission("duplicate"))
    missing = client.get("/api/v1/runs/missing")
    invalid = client.post(
        "/api/v1/runs",
        json={**_submission("invalid"), "unexpected": True},
    )

    assert response.status_code == 201
    assert response.json()["manifest"]["run_id"] == "run-1"
    assert isinstance(backend.last_submission, RunSubmission)
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "submission already exists"}
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_event_replay_and_sse_resume_from_durable_event_id() -> None:
    backend = FakeApplication()
    client = TestClient(_create_test_app(backend))

    replay = client.get("/api/v1/events", params={"after": 1, "run_id": "run-1"})
    stream = client.get(
        "/api/v1/events/stream",
        params={"follow": "false"},
        headers={"Last-Event-ID": "1"},
    )
    reconnect = client.get(
        "/api/v1/events/stream",
        params={"after": 0, "follow": "false"},
        headers={"Last-Event-ID": "2"},
    )

    assert [item["event_id"] for item in replay.json()["items"]] == [2]
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "id: 2\nevent: project\ndata: " in stream.text
    assert '"event_id":2' in stream.text
    assert reconnect.text == ""
    assert backend.runs.event_afters[-1] == 2


def test_executor_path_is_the_start_request_run_identity() -> None:
    backend = FakeApplication()
    client = TestClient(_create_test_app(backend))

    response = client.post(
        "/api/v1/runs/other/executor/start",
        json=ExecutorStartRequest(
            executor_id="notebook-1",
        ).model_dump(mode="json"),
    )

    assert response.status_code == 404
    assert backend.executor.last_start is None


def test_static_dist_serves_files_and_spa_without_shadowing_api(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text("<main>Scopecat GUI</main>")
    (tmp_path / "app.js").write_text("window.SCOPECAT = true")
    client = TestClient(
        _create_test_app(FakeApplication(), static_dir=tmp_path),
    )

    assert client.get("/").text == "<main>Scopecat GUI</main>"
    assert client.get("/runs/run-1").text == "<main>Scopecat GUI</main>"
    assert client.get("/app.js").text == "window.SCOPECAT = true"
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/unknown").status_code == 404


def _config() -> ConfigProfileSnapshot:
    return load_config_snapshot_document(_CONFIG_FIXTURE)


def _wire_admission(submission_id: str) -> RunAdmission:
    return RunAdmission(
        submission_id=submission_id,
        manifest=_accepted_manifest(),
    )


def _submission(submission_id: str) -> dict[str, object]:
    return RunSubmission(
        submission_id=submission_id,
        config=_config(),
        request=_REQUEST,
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
        ),
    ).model_dump(mode="json")


def _executor_lease() -> ExecutorLease:
    return ExecutorLease(
        lease_id="lease-1",
        run_id="run-1",
        executor_id="notebook-1",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=30),
        heartbeat_interval_seconds=10,
    )


def _accepted_manifest() -> RunManifest:
    return RunManifest(
        run_id="run-1",
        created_at=_NOW,
        config_content_hash=_HASH,
    )
