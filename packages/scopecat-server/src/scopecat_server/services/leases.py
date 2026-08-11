"""Daemon ownership lease supervision."""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..instruments.service import InstrumentService

logger = logging.getLogger(__name__)


class OwnershipLeaseSupervisor:
    """Expire abandoned ownership leases and reconcile daemon restarts."""

    def __init__(
        self,
        *,
        instruments: InstrumentService,
        supervisor_interval_seconds: float = 0.5,
        shutdown_timeout_seconds: float = 5.0,
    ) -> None:
        self._instruments = instruments
        self._supervisor_interval_seconds = supervisor_interval_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._stop = Event()
        self._supervisor_failed = False
        self._supervisor: Thread | None = None

    @property
    def healthy(self) -> bool:
        supervisor = self._supervisor
        return (
            supervisor is not None
            and supervisor.is_alive()
            and not self._stop.is_set()
            and not self._supervisor_failed
        )

    def start(self) -> None:
        if self._supervisor is not None:
            raise RuntimeError("ownership lease supervisor already started")
        self._stop.clear()
        self._supervisor_failed = False
        self._reconcile_startup()
        supervisor = Thread(
            target=self._supervise,
            name="scopecat-ownership-leases",
            daemon=True,
        )
        self._supervisor = supervisor
        try:
            supervisor.start()
        except BaseException:
            self._supervisor = None
            raise

    def request_stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self.request_stop()
        supervisor = self._supervisor
        if supervisor is not None:
            supervisor.join(self._shutdown_timeout_seconds)
            if supervisor.is_alive():
                self._supervisor_failed = True
                raise RuntimeError("ownership lease supervisor did not stop")
            self._supervisor = None

    def _supervise(self) -> None:
        while not self._stop.wait(self._supervisor_interval_seconds):
            try:
                self._instruments.expire_leases()
            except Exception:
                self._supervisor_failed = True
                logger.exception("ownership lease supervisor iteration failed")
            else:
                self._supervisor_failed = False

    def _reconcile_startup(self) -> None:
        self._instruments.reconcile_startup()
