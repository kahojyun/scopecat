"""Instrument providers backed by configurable virtual devices."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from pydantic import JsonValue
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverFault,
    DriverInvokeRequest,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentPropertyState,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentReadback,
    InstrumentStateSnapshot,
    InterfaceSpec,
    InvokeReceipt,
)
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)

from quantum_lab_demo.interfaces import (
    acquire_iq_interface,
    play_pulse_program_interface,
    readout_pulse_interface,
)
from quantum_lab_demo.virtual_lab.models import VirtualDeviceProfile
from quantum_lab_demo.virtual_lab.profiles import load_virtual_lab_profile


class _VirtualInstrumentDriver:
    _implementation_id: ClassVar[str]

    def __init__(
        self,
        *,
        profile: VirtualDeviceProfile,
        interfaces: Sequence[InterfaceSpec],
    ) -> None:
        self.instrument_id = profile.id
        self.implementation_id = self._implementation_id
        self.implementation_version = "v0"
        self._interfaces = list(interfaces)
        self._metadata: dict[str, JsonValue] = {
            "mode": "virtual_lab",
            "source": "quantum-lab-demo",
        }
        self._state = {
            _decode_property_key(key): value
            for key, value in profile.seed_state.items()
        }

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            interfaces=list(self._interfaces),
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
            metadata=self._metadata,
        )

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        for assignment in request.assignments:
            self._state[(assignment.interface_id, assignment.property_id)] = (
                assignment.value
            )
        return ApplyReceipt(status="applied")

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return InvokeReceipt(
            metadata={
                "interface_id": request.interface_id,
                "operation_id": request.operation_id,
                "payload_count": len(request.payloads),
            }
        )

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        del request
        return CollectReceipt(readback=InstrumentReadback())

    def disconnect(self) -> None:
        return None

    def abort(self) -> None:
        return None


class QuantumDriveStack(_VirtualInstrumentDriver):
    _implementation_id = "quantum_lab_demo.virtual_lab.drive_stack"

    def __init__(self, *, profile: VirtualDeviceProfile) -> None:
        super().__init__(
            profile=profile,
            interfaces=[play_pulse_program_interface()],
        )


class QuantumReadoutStack(_VirtualInstrumentDriver):
    _implementation_id = "quantum_lab_demo.virtual_lab.readout_stack"

    def __init__(self, *, profile: VirtualDeviceProfile) -> None:
        super().__init__(
            profile=profile,
            interfaces=[
                readout_pulse_interface(),
                acquire_iq_interface(),
            ],
        )


class QuantumLabVirtualProvider:
    provider_id = "quantum_lab_demo.virtual_lab.provider"

    def __init__(
        self,
        profile: str | Path,
    ) -> None:
        self.profile = load_virtual_lab_profile(profile)

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription:
        del context
        problems: list[Problem] = []
        try:
            instruments = tuple(
                driver.describe() for driver in self._build_virtual_instruments()
            )
        except DriverFault as error:
            problems.append(error.problem)
            instruments = ()
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=instruments,
            problems=tuple(problems),
        )

    def connect(self, context: InstrumentConnectionContext) -> InstrumentDriver:
        driver = next(
            (
                candidate
                for candidate in self._build_virtual_instruments()
                if candidate.instrument_id == context.instrument_id
            ),
            None,
        )
        if driver is None:
            raise DriverFault(
                problem(
                    "virtual_lab_unknown_instrument",
                    f"virtual lab does not define {context.instrument_id}",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("instrument_connection", "instrument_id"),
                    details={"instrument_id": context.instrument_id},
                )
            )
        return driver

    def _build_virtual_instruments(self) -> Sequence[InstrumentDriver]:
        profiles = {profile.id: profile for profile in self.profile.devices}
        return [
            QuantumDriveStack(
                profile=_required_profile(profiles, "drive-stack"),
            ),
            QuantumReadoutStack(
                profile=_required_profile(profiles, "readout-stack"),
            ),
        ]


def _required_profile(
    profiles: dict[str, VirtualDeviceProfile],
    device_id: str,
) -> VirtualDeviceProfile:
    try:
        return profiles[device_id]
    except KeyError as error:
        raise DriverFault(
            problem(
                "virtual_lab_missing_device",
                f"virtual lab profile does not define {device_id}",
                phase=ProblemPhase.PROVIDER_PREFLIGHT,
                location=model_location("virtual_lab_profile", "devices"),
                details={"device_id": device_id},
            )
        ) from error


def _decode_property_key(key: str) -> tuple[str, str]:
    interface_id, separator, property_id = key.partition("::")
    if not separator or not interface_id or not property_id:
        raise ValueError(
            "virtual device seed_state keys must use '<interface_id>::<property_id>'"
        )
    return interface_id, property_id


__all__ = [
    "QuantumDriveStack",
    "QuantumLabVirtualProvider",
    "QuantumReadoutStack",
]
