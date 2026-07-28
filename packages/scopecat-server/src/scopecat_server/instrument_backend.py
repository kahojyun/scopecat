"""Opaque runtime endpoint for instrument drivers."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from threading import RLock
from typing import Protocol
from uuid import uuid4

from scopecat.kernel.problems import Problem, ProblemPhase, model_location, problem
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.planning.provider_validation import (
    describe_instruments,
    validate_instruments,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.backend import InstrumentBackend
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectReceipt,
    DriverFault,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InvokeReceipt,
)
from scopecat.sdk.instruments.driver import (
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
)
from scopecat.sdk.payloads import PayloadCodecCatalog


class InstrumentBackendError(RuntimeError):
    """Base error for backend endpoint failures."""


class InstrumentBackendRejected(InstrumentBackendError):
    def __init__(self, message: str, *, problems: tuple[Problem, ...]) -> None:
        self.problems = problems
        super().__init__(message)


class InstrumentBackendUnavailable(InstrumentBackendError):
    """The backend cannot create or serve an instrument handle."""


class InstrumentHandleInvalid(InstrumentBackendError):
    """A handle is stale or belongs to another endpoint generation."""


@dataclass(frozen=True, slots=True)
class InstrumentHandle:
    endpoint_id: str
    token: str


@dataclass(frozen=True, slots=True)
class ConnectedInstrument:
    handle: InstrumentHandle
    description: InstrumentDescription


class InstrumentBackendEndpoint(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def payload_catalog(self) -> PayloadCodecCatalog: ...

    def resolve_contracts(
        self,
        config: ConfigProfileSnapshot,
    ) -> InstrumentContractCatalog: ...

    def connect(
        self,
        *,
        config: ConfigProfileSnapshot,
        instrument_id: str,
        expected: InstrumentDescription,
    ) -> ConnectedInstrument: ...

    def read_state(self, handle: InstrumentHandle) -> InstrumentStateSnapshot: ...

    def apply_state(
        self,
        handle: InstrumentHandle,
        request: DriverApplyRequest,
    ) -> ApplyReceipt: ...

    def invoke(
        self,
        handle: InstrumentHandle,
        request: DriverInvokeRequest,
    ) -> InvokeReceipt: ...

    def collect(
        self,
        handle: InstrumentHandle,
        request: DriverCollectRequest,
    ) -> CollectReceipt: ...

    def abort(self, handle: InstrumentHandle) -> None: ...

    def disconnect(self, handle: InstrumentHandle) -> None: ...

    def shutdown(self) -> None: ...


@dataclass(slots=True)
class _LocalConnection:
    driver: InstrumentDriver
    lock: RLock


class LocalInstrumentBackendEndpoint:
    """Own raw drivers behind handles and serialize provider entry points."""

    def __init__(self, backend: InstrumentBackend) -> None:
        self._provider = backend.provider
        self._payload_catalog = backend.payload_codecs.catalog
        self._endpoint_id = uuid4().hex
        self._connections: dict[InstrumentHandle, _LocalConnection] = {}
        self._lock = RLock()
        self._provider_lock = RLock()
        self._closed = False

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    @property
    def payload_catalog(self) -> PayloadCodecCatalog:
        return self._payload_catalog

    def resolve_contracts(
        self,
        config: ConfigProfileSnapshot,
    ) -> InstrumentContractCatalog:
        with self._provider_lock:
            with self._lock:
                if self._closed:
                    raise InstrumentBackendUnavailable(
                        "instrument backend is shut down"
                    )
            return resolve_instrument_contract_catalog(
                config=config,
                instrument_provider=self._provider,
            )

    def connect(
        self,
        *,
        config: ConfigProfileSnapshot,
        instrument_id: str,
        expected: InstrumentDescription,
    ) -> ConnectedInstrument:
        with self._provider_lock:
            with self._lock:
                if self._closed:
                    raise InstrumentBackendUnavailable(
                        "instrument backend is shut down"
                    )
            driver: InstrumentDriver | None = None
            try:
                driver = self._provider.connect(
                    InstrumentConnectionContext(
                        config=config,
                        instrument_id=instrument_id,
                    )
                )
                problems = validate_instruments(config=config, instruments=[driver])
                described, description_problems = describe_instruments([driver])
                problems.extend(description_problems)
                actual = described[0] if described else None
                if actual is not None and actual != expected:
                    problems.append(_description_changed_problem(instrument_id))
                if problems:
                    raise InstrumentBackendRejected(
                        "instrument provider returned an invalid driver",
                        problems=tuple(problems),
                    )
                if actual is None:
                    raise AssertionError(
                        "validated instrument connection has no description"
                    )
            except DriverFault as error:
                if driver is not None:
                    with suppress(Exception):
                        driver.disconnect()
                raise InstrumentBackendRejected(
                    "instrument provider rejected connection",
                    problems=(error.problem,),
                ) from error
            except InstrumentBackendRejected:
                if driver is not None:
                    with suppress(Exception):
                        driver.disconnect()
                raise
            except Exception as error:
                if driver is not None:
                    with suppress(Exception):
                        driver.disconnect()
                raise InstrumentBackendUnavailable(
                    "instrument connection could not be established"
                ) from error

            handle = InstrumentHandle(
                endpoint_id=self._endpoint_id,
                token=uuid4().hex,
            )
            connection = _LocalConnection(driver=driver, lock=RLock())
            with self._lock:
                if self._closed:
                    with suppress(Exception):
                        driver.disconnect()
                    raise InstrumentBackendUnavailable(
                        "instrument backend is shut down"
                    )
                self._connections[handle] = connection
            return ConnectedInstrument(handle=handle, description=actual)

    def read_state(self, handle: InstrumentHandle) -> InstrumentStateSnapshot:
        with self._locked_connection(handle) as connection:
            return connection.driver.read_state()

    def apply_state(
        self,
        handle: InstrumentHandle,
        request: DriverApplyRequest,
    ) -> ApplyReceipt:
        with self._locked_connection(handle) as connection:
            return connection.driver.apply_state(request)

    def invoke(
        self,
        handle: InstrumentHandle,
        request: DriverInvokeRequest,
    ) -> InvokeReceipt:
        with self._locked_connection(handle) as connection:
            return connection.driver.invoke(request)

    def collect(
        self,
        handle: InstrumentHandle,
        request: DriverCollectRequest,
    ) -> CollectReceipt:
        with self._locked_connection(handle) as connection:
            return connection.driver.collect(request)

    def abort(self, handle: InstrumentHandle) -> None:
        with self._locked_connection(handle) as connection:
            connection.driver.abort()

    def disconnect(self, handle: InstrumentHandle) -> None:
        connection = self._pop_connection(handle)
        with connection.lock:
            connection.driver.disconnect()

    def shutdown(self) -> None:
        with self._provider_lock, self._lock:
            if self._closed:
                return
            self._closed = True
            connections = tuple(reversed(self._connections.values()))
            self._connections.clear()
        errors: list[Exception] = []
        for connection in connections:
            try:
                with connection.lock:
                    connection.driver.disconnect()
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("instrument backend shutdown failed", errors)

    @contextmanager
    def _locked_connection(
        self,
        handle: InstrumentHandle,
    ) -> Generator[_LocalConnection]:
        with self._lock:
            connection = self._find_connection(handle)
            connection.lock.acquire()
        try:
            yield connection
        finally:
            connection.lock.release()

    def _pop_connection(self, handle: InstrumentHandle) -> _LocalConnection:
        with self._lock:
            connection = self._find_connection(handle)
            del self._connections[handle]
            return connection

    def _find_connection(self, handle: InstrumentHandle) -> _LocalConnection:
        if handle.endpoint_id != self._endpoint_id:
            raise InstrumentHandleInvalid(
                "instrument handle belongs to another backend endpoint"
            )
        try:
            return self._connections[handle]
        except KeyError as error:
            raise InstrumentHandleInvalid("instrument handle is stale") from error


def _description_changed_problem(instrument_id: str) -> Problem:
    return problem(
        "instrument_description_changed",
        f"instrument description changed while provisioning {instrument_id}",
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("instrument_provider", "instruments", instrument_id),
    )


__all__ = [
    "ConnectedInstrument",
    "InstrumentBackendEndpoint",
    "InstrumentBackendError",
    "InstrumentBackendRejected",
    "InstrumentBackendUnavailable",
    "InstrumentHandle",
    "InstrumentHandleInvalid",
    "LocalInstrumentBackendEndpoint",
]
