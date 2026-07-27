"""Executor lease supervision."""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import TYPE_CHECKING

from scopecat.adapters.sqlite import (
    SQLiteControlPlane,
)

if TYPE_CHECKING:
    from .instrument_service import InstrumentService

logger = logging.getLogger(__name__)


class ExecutorLeaseSupervisor:
    """Expire abandoned executor leases and reconcile daemon restarts."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        instruments: InstrumentService | None = None,
        supervisor_interval_seconds: float = 0.5,
    ) -> None:
        self._control = control
        self._instruments = instruments
        self._supervisor_interval_seconds = supervisor_interval_seconds
        self._stop = Event()
        self._supervisor_failed = False
        self._supervisor: Thread | None = None

    @property
    def healthy(self) -> bool:
        supervisor = self._supervisor
        return (
            supervisor is not None
            and supervisor.is_alive()
            and not self._supervisor_failed
        )

    def start(self) -> None:
        if self._supervisor is not None:
            raise RuntimeError("executor lease supervisor already started")
        self._stop.clear()
        self._supervisor_failed = False
        self._reconcile_startup()
        supervisor = Thread(
            target=self._supervise,
            name="scopecat-executor-leases",
            daemon=True,
        )
        self._supervisor = supervisor
        try:
            supervisor.start()
        except BaseException:
            self._supervisor = None
            raise

    def close(self) -> None:
        supervisor = self._supervisor
        self._stop.set()
        if supervisor is not None:
            supervisor.join()
        self._supervisor = None
        if self._instruments is not None:
            self._instruments.shutdown()

    def _supervise(self) -> None:
        while not self._stop.wait(self._supervisor_interval_seconds):
            try:
                self._control.expire_executor_leases()
                if self._instruments is not None:
                    self._instruments.expire_sessions()
            except Exception:
                self._supervisor_failed = True
                logger.exception("executor lease supervisor iteration failed")

    def _reconcile_startup(self) -> None:
        self._control.abandon_executor_leases()
        if self._instruments is not None:
            self._instruments.reconcile_startup()
