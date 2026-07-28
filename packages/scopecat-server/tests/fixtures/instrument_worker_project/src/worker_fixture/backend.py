from __future__ import annotations

import os
import time
from pathlib import Path

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.records.instrument import (
    InstrumentPropertyState,
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.records.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
    InstrumentBackend,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InvokeReceipt,
    acquisition,
    acquisition_result,
    float_property,
    interface,
    operation,
)
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry


class _Driver:
    implementation_id = "tests.spawned_driver"
    implementation_version = "v1"

    def __init__(self, instrument_id: str, project_root: Path) -> None:
        self.instrument_id = instrument_id
        self._project_root = project_root
        self._state: dict[tuple[str, str], StateValue] = {}

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            interfaces=[
                interface(
                    "tests.control/v1",
                    properties=[float_property("gain")],
                    operations=[operation("play"), operation("block")],
                    acquisitions=[
                        acquisition(
                            "sample",
                            results=[acquisition_result("signal", unit="ratio")],
                        )
                    ],
                )
            ],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                InstrumentPropertyState(
                    interface_id=interface_id,
                    property_id=property_id,
                    value=value,
                )
                for (interface_id, property_id), value in sorted(self._state.items())
            ],
            metadata={"worker_pid": os.getpid()},
        )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        for assignment in request.assignments:
            self._state[(assignment.interface_id, assignment.property_id)] = (
                assignment.value
            )
        return ApplyReceipt(status="applied")

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        if request.operation_id == "block":
            entered = self._project_root / f"driver-blocked-{self.instrument_id}"
            release = self._project_root / f"driver-release-{self.instrument_id}"
            entered.touch()
            while not release.exists():
                time.sleep(0.01)
        content = b"".join(
            payload.content for _, payload in sorted(request.payloads.items())
        )
        return InvokeReceipt(
            status="invoked",
            metadata={
                "payload_hex": content.hex(),
                "worker_pid": os.getpid(),
            },
        )

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        return CollectReceipt(
            readback=InstrumentReadback(
                values={
                    result.request_id: _measurement_value(result.result_id)
                    for result in request.results
                },
                metadata={"worker_pid": os.getpid()},
            )
        )

    def abort(self) -> None:
        _append_marker(self._project_root, "abort")

    def disconnect(self) -> None:
        _append_marker(self._project_root, f"disconnect:{self.instrument_id}")


class _Provider:
    provider_id = "tests.spawned_provider"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                _Driver(spec.id, self._project_root).describe()
                for spec in context.config.instrument_registry.instruments
            ),
        )

    def connect(self, context: InstrumentConnectionContext) -> _Driver:
        return _Driver(context.instrument_id, self._project_root)


def create_backend(project_root: Path) -> InstrumentBackend:
    _write_pid(project_root / "worker.pid")
    return InstrumentBackend(
        provider=_Provider(project_root),
        payload_codecs=PayloadCodecRegistry(
            {
                "pulse_program": PayloadCodec(
                    id="tests.raw",
                    version=1,
                    media_type="application/octet-stream",
                    encoder=_encode_bytes,
                    decoder=_decode_bytes,
                )
            }
        ),
    )


def create_failing_backend(project_root: Path) -> InstrumentBackend:
    _write_pid(project_root / "failed-worker.pid")
    raise RuntimeError("fixture startup failure")


def _measurement_value(result_id: str) -> MeasurementValue:
    if result_id == "complex_array":
        return MeasurementArray(
            dtype="complex128",
            unit="ratio",
            shape=(1,),
            values=(ComplexQuantity(real=1.0, imag=-0.5, unit="ratio"),),
        )
    if result_id == "invalid_array":
        return MeasurementArray(
            dtype="complex128",
            unit="ratio",
            shape=(1,),
            values=(1.0 - 0.5j,),
        )
    if result_id == "oversized_array":
        return MeasurementArray(
            dtype="string",
            shape=(1,),
            values=("x" * (2 * 1024 * 1024),),
        )
    return Quantity(value=1.25, unit="ratio")


def _encode_bytes(value: object) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError("fixture codec accepts bytes")
    return value


def _decode_bytes(content: bytes) -> object:
    return content


def _write_pid(path: Path) -> None:
    path.write_text(str(os.getpid()), encoding="utf-8")


def _append_marker(project_root: Path, marker: str) -> None:
    with (project_root / "driver-events.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{marker}\n")
