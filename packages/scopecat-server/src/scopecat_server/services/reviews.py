"""Process-local coordination for live experiment review workers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from scopecat.daemon.reviews import (
    ReviewCompilationResult,
    ReviewCompileCommand,
    ReviewCompileReceipt,
    ReviewCompletionCommand,
    ReviewHeartbeatReceipt,
    ReviewSessionCloseReceipt,
    ReviewSessionCreateCommand,
    ReviewSessionListView,
    ReviewSessionView,
    ReviewWorkItem,
    RunDomainInspectionEvent,
    RunInspectionView,
)

from ..errors import BackendConflict, BackendNotFound

_RUN_INSPECTION_EVENT_LIMIT = 64


@dataclass(slots=True)
class _ReviewSession:
    command: ReviewSessionCreateCommand
    created_at: datetime
    updated_at: datetime
    active: bool = True
    pending: deque[ReviewWorkItem] = field(default_factory=deque)
    claimed_request_ids: set[str] = field(default_factory=set)
    latest_result: ReviewCompilationResult | None = None


@dataclass(slots=True)
class _RunInspectionFeed:
    items: deque[RunDomainInspectionEvent] = field(
        default_factory=lambda: deque(maxlen=_RUN_INSPECTION_EVENT_LIMIT)
    )
    total_proposal_count: int = 0


class ReviewService:
    """Coordinate a GUI with a notebook-owned pure compiler."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, _ReviewSession] = {}

    def create(self, command: ReviewSessionCreateCommand) -> ReviewSessionView:
        now = datetime.now(UTC)
        with self._lock:
            if command.session_id in self._sessions:
                raise BackendConflict("review session already exists")
            session = _ReviewSession(
                command=command,
                created_at=now,
                updated_at=now,
                latest_result=command.initial_result,
            )
            self._sessions[command.session_id] = session
            return _view(session)

    def list(self) -> ReviewSessionListView:
        with self._lock:
            sessions = sorted(
                self._sessions.values(),
                key=lambda session: session.updated_at,
                reverse=True,
            )
            return ReviewSessionListView(items=tuple(_view(item) for item in sessions))

    def get(self, session_id: str) -> ReviewSessionView:
        with self._lock:
            return _view(self._require(session_id))

    def enqueue(
        self,
        session_id: str,
        command: ReviewCompileCommand,
    ) -> ReviewCompileReceipt:
        with self._lock:
            session = self._require_active(session_id)
            request_id = uuid4().hex
            session.pending.append(
                ReviewWorkItem(
                    session_id=session_id,
                    request_id=request_id,
                    point_index=command.point_index,
                    coordinates=command.coordinates,
                    coordinate_mode=command.coordinate_mode,
                )
            )
            session.updated_at = datetime.now(UTC)
            return ReviewCompileReceipt(
                session_id=session_id,
                request_id=request_id,
            )

    def claim(self, session_id: str, worker_id: str) -> ReviewWorkItem | None:
        with self._lock:
            session = self._require_worker(session_id, worker_id)
            if not session.active or not session.pending:
                return None
            item = session.pending.popleft()
            session.claimed_request_ids.add(item.request_id)
            session.updated_at = datetime.now(UTC)
            return item

    def complete(
        self,
        session_id: str,
        command: ReviewCompletionCommand,
    ) -> ReviewSessionView:
        with self._lock:
            session = self._require_worker(session_id, command.worker_id)
            request_id = command.result.request_id
            if request_id not in session.claimed_request_ids:
                raise BackendConflict("review request is not claimed by this worker")
            session.claimed_request_ids.remove(request_id)
            session.latest_result = command.result
            session.updated_at = datetime.now(UTC)
            return _view(session)

    def heartbeat(self, session_id: str, worker_id: str) -> ReviewHeartbeatReceipt:
        with self._lock:
            session = self._require_worker(session_id, worker_id)
            session.updated_at = datetime.now(UTC)
            return ReviewHeartbeatReceipt(
                session_id=session_id,
                active=session.active,
                updated_at=session.updated_at,
            )

    def close(self, session_id: str, worker_id: str) -> ReviewSessionCloseReceipt:
        with self._lock:
            session = self._require_worker(session_id, worker_id)
            closed_at = datetime.now(UTC)
            session.active = False
            session.pending.clear()
            session.updated_at = closed_at
            return ReviewSessionCloseReceipt(
                session_id=session_id,
                closed_at=closed_at,
            )

    def _require(self, session_id: str) -> _ReviewSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise BackendNotFound(f"unknown review session {session_id!r}")
        return session

    def _require_active(self, session_id: str) -> _ReviewSession:
        session = self._require(session_id)
        if not session.active:
            raise BackendConflict("review session is closed")
        return session

    def _require_worker(self, session_id: str, worker_id: str) -> _ReviewSession:
        session = self._require(session_id)
        if session.command.worker_id != worker_id:
            raise BackendConflict("review worker does not own this session")
        return session


class RunInspectionFeedService:
    """Retain the bounded, process-local compiled inspection feed for each run."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._feeds: dict[str, _RunInspectionFeed] = {}

    def append(
        self,
        run_id: str,
        event: RunDomainInspectionEvent,
    ) -> RunInspectionView:
        with self._lock:
            feed = self._feeds.setdefault(run_id, _RunInspectionFeed())
            if event.proposal_index < feed.total_proposal_count:
                retained = next(
                    (
                        item
                        for item in feed.items
                        if item.proposal_index == event.proposal_index
                    ),
                    None,
                )
                if retained != event:
                    raise BackendConflict("run proposal already has different content")
                return _run_inspection_view(run_id, feed)
            if event.proposal_index > feed.total_proposal_count:
                raise BackendConflict("run proposal indices must be contiguous")
            feed.items.append(event)
            feed.total_proposal_count += 1
            return _run_inspection_view(run_id, feed)

    def read(self, run_id: str) -> RunInspectionView:
        with self._lock:
            feed = self._feeds.get(run_id, _RunInspectionFeed())
            return _run_inspection_view(run_id, feed)


def _view(session: _ReviewSession) -> ReviewSessionView:
    latest_result = session.latest_result
    command = session.command
    return ReviewSessionView(
        session_id=command.session_id,
        title=command.title,
        experiment_id=command.experiment_id,
        experiment_kind=command.experiment_kind,
        active=session.active,
        created_at=session.created_at,
        updated_at=session.updated_at,
        coordinates=command.coordinates,
        planned_points=command.planned_points,
        planned_points_truncated=command.planned_points_truncated,
        pending_request_count=(len(session.pending) + len(session.claimed_request_ids)),
        latest_result=latest_result,
    )


def _run_inspection_view(
    run_id: str,
    feed: _RunInspectionFeed,
) -> RunInspectionView:
    return RunInspectionView(
        run_id=run_id,
        items=tuple(feed.items),
        total_proposal_count=feed.total_proposal_count,
        items_truncated=feed.total_proposal_count > len(feed.items),
    )


__all__ = ["ReviewService", "RunInspectionFeedService"]
