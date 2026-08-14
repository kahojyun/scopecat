from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from scopecat.adaptive_domains import ResolvedDomainFragment
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.points import RunDomainFragmentView
from scopecat.daemon.reviews import (
    ReviewCompilationResult,
    ReviewCompileCommand,
    ReviewCompletionCommand,
    ReviewCoordinateSpec,
    ReviewPointView,
    ReviewSessionCreateCommand,
    RunDomainInspectionEvent,
)
from scopecat.kernel.quantity import Quantity

from scopecat_server import BackendConflict, BackendNotFound, LocalDaemonRuntime
from scopecat_server.services.reviews import ReviewService, RunInspectionFeedService


def _review_command(index: int) -> ReviewSessionCreateCommand:
    return ReviewSessionCreateCommand(
        session_id=f"review-{index}",
        worker_id=f"worker-{index}",
        title=f"Review {index}",
        experiment_id=f"experiment-{index}",
        experiment_kind="experiment",
        coordinates=(),
    )


def _inspection_event() -> RunDomainInspectionEvent:
    return RunDomainInspectionEvent(
        proposal_index=0,
        occurred_at=datetime.now(UTC),
        fragment=RunDomainFragmentView.from_fragment(
            ResolvedDomainFragment.points(({"beta": Quantity(0.137, "ns")},))
        ),
        region_ids=("region-0",),
        source="optimizer",
        outcome="rejected",
        reason="proposal used stale observations",
    )


def test_review_worker_lease_expires_without_losing_latest_result() -> None:
    now = [datetime(2026, 8, 14, tzinfo=UTC)]
    service = ReviewService(
        worker_ttl=timedelta(seconds=15),
        clock=lambda: now[0],
    )
    initial_result = ReviewCompilationResult(
        request_id="initial",
        completed_at=now[0],
    )
    session = service.create(
        ReviewSessionCreateCommand(
            session_id="review-lease",
            worker_id="worker-lease",
            title="Lease review",
            experiment_id="lease-review",
            experiment_kind="experiment",
            coordinates=(),
            initial_result=initial_result,
        )
    )
    assert session.heartbeat_interval_seconds == 5
    now[0] += timedelta(seconds=10)
    assert service.heartbeat(session.session_id, "worker-lease").active
    now[0] += timedelta(seconds=10)
    receipt = service.enqueue(
        session.session_id,
        ReviewCompileCommand(coordinates={}, coordinate_mode="free"),
    )
    claimed = service.claim(session.session_id, "worker-lease")
    assert claimed is not None
    assert claimed.request_id == receipt.request_id
    assert service.get(session.session_id).pending_request_count == 1

    now[0] += timedelta(seconds=16)
    expired = service.get(session.session_id)

    assert not expired.active
    assert expired.pending_request_count == 0
    assert expired.latest_result == initial_result
    assert not service.heartbeat(session.session_id, "worker-lease").active
    with pytest.raises(BackendConflict, match="closed"):
        service.enqueue(
            session.session_id,
            ReviewCompileCommand(coordinates={}, coordinate_mode="free"),
        )


def test_review_service_retains_only_recent_inactive_sessions() -> None:
    now = [datetime(2026, 8, 14, tzinfo=UTC)]
    service = ReviewService(
        inactive_session_limit=2,
        clock=lambda: now[0],
    )
    for index in range(3):
        command = _review_command(index)
        service.create(command)
        service.close(command.session_id, command.worker_id)
        now[0] += timedelta(seconds=1)

    assert [item.session_id for item in service.list().items] == [
        "review-2",
        "review-1",
    ]
    with pytest.raises(BackendNotFound, match="unknown review session"):
        service.get("review-0")

    active = _review_command(3)
    service.create(active)
    assert service.get(active.session_id).active


def test_review_session_round_trips_compile_work_without_run_admission(
    tmp_path: Path,
) -> None:
    with (
        LocalDaemonRuntime(tmp_path) as runtime,
        TestClient(runtime.app()) as transport,
        _daemon_client(transport) as client,
    ):
        session = client.create_review(
            ReviewSessionCreateCommand(
                session_id="review-1",
                worker_id="worker-1",
                title="DRAG beta",
                experiment_id="drag-beta",
                experiment_kind="experiment",
                coordinates=(
                    ReviewCoordinateSpec(
                        id="beta",
                        kind="quantity",
                        unit="ns",
                        sampled_values=(Quantity(0.0, "ns"),),
                    ),
                ),
            )
        )

        receipt = client.enqueue_review_compile(
            session.session_id,
            ReviewCompileCommand(
                coordinates={"beta": Quantity(0.137, "ns")},
                coordinate_mode="free",
            ),
        )
        work = client.claim_review_work(session.session_id, "worker-1")
        assert work is not None
        assert work.request_id == receipt.request_id
        assert work.coordinates == {"beta": Quantity(0.137, "ns")}

        completed = client.complete_review_work(
            session.session_id,
            ReviewCompletionCommand(
                worker_id="worker-1",
                result=ReviewCompilationResult(
                    request_id=work.request_id,
                    completed_at=datetime.now(UTC),
                    point=ReviewPointView(
                        coordinates={"beta": Quantity(0.137, "ns")},
                        source="operator",
                    ),
                ),
            ),
        )

        assert completed.pending_request_count == 0
        assert completed.latest_result is not None
        assert completed.latest_result.point is not None
        assert completed.latest_result.point.point_index is None
        assert (
            runtime.application.runs.list_runs(
                limit=10,
                before=None,
                state=None,
            ).items
            == ()
        )


def test_run_inspection_feed_exposes_optimizer_decisions(tmp_path: Path) -> None:
    with (
        LocalDaemonRuntime(tmp_path) as runtime,
        TestClient(runtime.app()) as transport,
        _daemon_client(transport) as client,
    ):
        event = _inspection_event()
        runtime.application.run_inspections.append("run-1", event)
        runtime.application.run_inspections.append("run-1", event)

        feed = client.get_run_inspections("run-1")

        assert feed.run_id == "run-1"
        assert len(feed.items) == 1
        assert feed.items[0].outcome == "rejected"
        assert feed.items[0].reason == "proposal used stale observations"


def test_run_inspection_feed_retains_active_and_recent_inactive_runs() -> None:
    service = RunInspectionFeedService(inactive_feed_limit=2)
    for index in range(2):
        run_id = f"run-{index}"
        service.append(run_id, _inspection_event())
        service.mark_inactive(run_id)

    assert service.read("run-0").total_proposal_count == 1
    service.append("run-2", _inspection_event())
    service.mark_inactive("run-2")

    assert service.read("run-0").total_proposal_count == 1
    assert service.read("run-1").total_proposal_count == 0
    assert service.read("run-2").total_proposal_count == 1

    service.append("run-active", _inspection_event())
    service.append("run-3", _inspection_event())
    service.mark_inactive("run-3")
    assert service.read("run-active").total_proposal_count == 1


def _daemon_client(transport: TestClient) -> DaemonClient:
    def send(request: httpx2.Request) -> httpx2.Response:
        response = transport.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx2.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )

    return DaemonClient(
        "http://testserver",
        transport=httpx2.MockTransport(send),
    )
