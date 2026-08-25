"""Driver-boundary telemetry for the real multiprocess scale benchmark."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Protocol, cast

import numpy as np

from reference_lab.bench_interfaces import (
    AWG_LOAD_PROGRAM,
    AWG_PROGRAM,
    TRIGGER_LOAD_PROGRAM,
    TRIGGER_PROGRAM,
    TRIGGER_START_PROGRAM,
    TRIGGER_START_PROGRAM_IDEMPOTENT,
)
from reference_lab.payloads import (
    AwgProgramDocument,
    MaterializedAwgProgramDocument,
    TriggerProgramDocument,
    materialize_awg_program,
)
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverOperation,
    DriverOutcome,
    DriverPayload,
    DriverReadback,
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)


class DriverTelemetry:
    """Share batch observations across every driver in one worker process."""

    def __init__(
        self,
        project_root: Path,
        *,
        live_waveform: bool,
        point_delay_s: float,
    ) -> None:
        self._path = project_root / "benchmark-telemetry.jsonl"
        self._live_waveform = live_waveform
        self._point_delay_s = point_delay_s
        self._lock = Lock()
        self._programs: dict[str, MaterializedAwgProgramDocument] = {}
        self._latest: tuple[np.ndarray, ...] = ()
        self._pending_batch_bytes = 0
        self.record("worker_ready", worker_pid=os.getpid())

    def load_awg(self, instrument_id: str, program: AwgProgramDocument) -> None:
        materialized = materialize_awg_program(program)
        uploaded = sum(
            len(waveform.samples) * np.dtype(np.float64).itemsize
            for entry in materialized.entries
            for waveform in entry.waveforms
        )
        with self._lock:
            self._programs[instrument_id] = materialized
            self._pending_batch_bytes += uploaded
            self._record_locked(
                "awg_load",
                instrument_id=instrument_id,
                waveform_bytes=uploaded,
            )

    def trigger(self, *, loaded_point_count: int) -> None:
        with self._lock:
            batch_bytes = self._pending_batch_bytes
            self._pending_batch_bytes = 0
            self._record_locked(
                "trigger",
                waveform_batch_bytes=batch_bytes,
                loaded_point_count=loaded_point_count,
            )
        if self._point_delay_s:
            time.sleep(loaded_point_count * self._point_delay_s)

    def collect(self) -> None:
        with self._lock:
            if self._live_waveform:
                self._latest = tuple(
                    np.array(waveform.samples, dtype=np.float64, copy=True)
                    for instrument_id in sorted(self._programs)
                    for waveform in self._programs[instrument_id].entries[-1].waveforms
                )
            self._record_locked(
                "collect",
                live_waveform_bytes=sum(value.nbytes for value in self._latest),
            )

    def record(self, kind: str, **values: object) -> None:
        with self._lock:
            self._record_locked(kind, **values)

    def _record_locked(self, kind: str, **values: object) -> None:
        document = {
            "kind": kind,
            "time_ns": time.perf_counter_ns(),
            **values,
        }
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(document, sort_keys=True) + "\n")
            stream.flush()


class TelemetryProvider:
    """Wrap the reference provider without moving the real driver boundary."""

    def __init__(
        self,
        delegate: object,
        *,
        project_root: Path,
        live_waveform: bool,
        point_delay_s: float,
    ) -> None:
        self._delegate = cast("_Provider", delegate)
        self._telemetry = DriverTelemetry(
            project_root,
            live_waveform=live_waveform,
            point_delay_s=point_delay_s,
        )

    @property
    def provider_id(self) -> str:
        return self._delegate.provider_id

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return self._delegate.describe(context)

    def connect(self, context: InstrumentConnectionContext) -> InstrumentDriver:
        return TelemetryDriver(
            self._delegate.connect(context),
            telemetry=self._telemetry,
        )


class _Provider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription: ...

    def connect(self, context: InstrumentConnectionContext) -> InstrumentDriver: ...


class TelemetryDriver:
    """Observe materialized uploads, triggers, and collections in the worker."""

    def __init__(
        self,
        delegate: InstrumentDriver,
        *,
        telemetry: DriverTelemetry,
    ) -> None:
        self._delegate = delegate
        self._telemetry = telemetry
        self._loaded_point_count = 0
        self.implementation_id = delegate.implementation_id
        self.implementation_version = delegate.implementation_version

    @property
    def instrument_id(self) -> str:
        return self._delegate.instrument_id

    def describe(self) -> InstrumentDescription:
        return self._delegate.describe()

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        return self._delegate.read_state(request)

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        return self._delegate.apply_state(request)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]:
        if (
            request.target.interface_id == AWG_LOAD_PROGRAM.interface_id
            and request.target.operation_id == AWG_LOAD_PROGRAM.operation_id
        ):
            program = cast(
                "AwgProgramDocument",
                cast(
                    "DriverPayload",
                    request.arguments[AWG_PROGRAM.argument_id],
                ).value,
            )
            self._telemetry.load_awg(self.instrument_id, program)
        if (
            request.target.interface_id == TRIGGER_LOAD_PROGRAM.interface_id
            and request.target.operation_id == TRIGGER_LOAD_PROGRAM.operation_id
        ):
            program = cast(
                "TriggerProgramDocument",
                cast(
                    "DriverPayload",
                    request.arguments[TRIGGER_PROGRAM.argument_id],
                ).value,
            )
            self._loaded_point_count = len(program.entries) * program.repetitions
        if (
            request.target.interface_id == TRIGGER_START_PROGRAM.interface_id
            and request.target.operation_id
            in {
                TRIGGER_START_PROGRAM.operation_id,
                TRIGGER_START_PROGRAM_IDEMPOTENT.operation_id,
            }
        ):
            outcome = self._delegate.invoke(request)
            self._telemetry.trigger(loaded_point_count=self._loaded_point_count)
            return outcome
        return self._delegate.invoke(request)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        outcome = self._delegate.collect(request)
        self._telemetry.collect()
        return outcome

    def disconnect(self) -> None:
        self._delegate.disconnect()

    def abort(self) -> None:
        self._delegate.abort()


__all__ = ["TelemetryProvider"]
