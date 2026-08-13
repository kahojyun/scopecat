from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx2
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

from scopecat_server import LocalDaemonRuntime


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
        event = RunDomainInspectionEvent(
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
        runtime.application.reviews.append_run_inspection("run-1", event)
        runtime.application.reviews.append_run_inspection("run-1", event)

        feed = client.get_run_inspections("run-1")

        assert feed.run_id == "run-1"
        assert len(feed.items) == 1
        assert feed.items[0].outcome == "rejected"
        assert feed.items[0].reason == "proposal used stale observations"


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
