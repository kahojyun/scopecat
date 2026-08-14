from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Lock
from typing import cast

import pytest

import scopecat.api.review as review_module
from scopecat.api.review import ExperimentReviewHandle
from scopecat.authoring.experiments import ExperimentInvocation
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.reviews import (
    ReviewHeartbeatReceipt,
    ReviewSessionCloseReceipt,
    ReviewSessionView,
    ReviewWorkItem,
)
from scopecat.execution.program import RunProgram


class _ReviewClient:
    base_url = "http://review.test"

    def __init__(self, work: ReviewWorkItem) -> None:
        self._lock = Lock()
        self._work = work
        self.heartbeat_seen = Event()
        self.closed = False

    def claim_review_work(
        self,
        session_id: str,
        worker_id: str,
    ) -> ReviewWorkItem | None:
        del session_id, worker_id
        with self._lock:
            work = self._work
            self._work = None
            return work

    def heartbeat_review_worker(
        self,
        session_id: str,
        worker_id: str,
    ) -> ReviewHeartbeatReceipt:
        del worker_id
        self.heartbeat_seen.set()
        return ReviewHeartbeatReceipt(
            session_id=session_id,
            active=True,
            updated_at=datetime.now(UTC),
        )

    def close_review_worker(
        self,
        session_id: str,
        worker_id: str,
    ) -> ReviewSessionCloseReceipt:
        del worker_id
        self.closed = True
        return ReviewSessionCloseReceipt(
            session_id=session_id,
            closed_at=datetime.now(UTC),
        )


def test_review_heartbeat_continues_while_compilation_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compile_started = Event()
    release_compile = Event()

    def block_compilation(
        _handle: ExperimentReviewHandle,
        _item: ReviewWorkItem,
    ) -> None:
        compile_started.set()
        assert release_compile.wait(1)

    monkeypatch.setattr(review_module, "_WORKER_POLL_SECONDS", 0.005)
    monkeypatch.setattr(ExperimentReviewHandle, "_complete", block_compilation)
    client = _ReviewClient(
        ReviewWorkItem(
            session_id="review-1",
            request_id="request-1",
            coordinates={},
            coordinate_mode="free",
        )
    )
    now = datetime.now(UTC)
    handle = ExperimentReviewHandle(
        client=cast("DaemonClient", cast("object", client)),
        program=cast("RunProgram", object()),
        invocation=cast("ExperimentInvocation", object()),
        session=ReviewSessionView(
            session_id="review-1",
            title="Review",
            experiment_id="experiment-1",
            experiment_kind="experiment",
            active=True,
            created_at=now,
            updated_at=now,
            heartbeat_interval_seconds=0.01,
            coordinates=(),
        ),
        worker_id="worker-1",
    )
    try:
        assert compile_started.wait(1)
        assert client.heartbeat_seen.wait(1)
    finally:
        release_compile.set()
        handle.close()

    assert client.closed
