"""Instrument providers backed by configurable virtual devices."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from pydantic import JsonValue
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CapabilityDescription,
    CollectCommand,
    CollectReceipt,
    DriverFault,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateField,
    InstrumentStateSnapshot,
    capability,
    payload_field,
)
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)

from quantum_lab_demo.virtual_lab.models import VirtualDeviceProfile
from quantum_lab_demo.virtual_lab.profiles import load_virtual_lab_profile


class _VirtualInstrumentDriver:
    _implementation_id: ClassVar[str]

    def __init__(
        self,
        *,
        profile: VirtualDeviceProfile,
        capabilities: Sequence[CapabilityDescription],
    ) -> None:
        self.instrument_id = profile.id
        self.implementation_id = self._implementation_id
        self.implementation_version = "v0"
        self._capabilities = list(capabilities)
        self._metadata: dict[str, JsonValue] = {
            "mode": "virtual_lab",
            "source": "quantum-lab-demo",
        }
        self._state = {
            _decode_state_key(key): value
            for key, value in profile.initial_state.items()
        }

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=list(self._capabilities),
        )

    def read_state(self) -> InstrumentStateSnapshot:
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            fields=[
                InstrumentStateField(
                    capability_id=capability_id,
                    field_path=field_path,
                    value=value,
                )
                for (capability_id, field_path), value in sorted(self._state.items())
            ],
            metadata=self._metadata,
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        if command.instrument_id != self.instrument_id:
            raise DriverFault(
                problem(
                    "virtual_lab_device_mismatch",
                    f"{self.instrument_id} cannot apply command for "
                    f"{command.instrument_id}",
                    phase=ProblemPhase.EXECUTION,
                    location=model_location(
                        "instrument_state_command",
                        "instrument_id",
                    ),
                )
            )
        for field in command.fields:
            self._state[(field.capability_id, field.field_path)] = field.value
        return ApplyReceipt(status="applied")

    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        return CollectReceipt(readback=InstrumentReadback())

    def cleanup(self) -> None:
        return None

    def close(self) -> None:
        return None

    def abort(self) -> None:
        return None


class QuantumDriveStack(_VirtualInstrumentDriver):
    _implementation_id = "quantum_lab_demo.virtual_lab.drive_stack"

    def __init__(self, *, profile: VirtualDeviceProfile) -> None:
        super().__init__(
            profile=profile,
            capabilities=[
                capability(
                    "play_pulse_program",
                    fields=[payload_field("program", schema_id="pulse_program")],
                ),
            ],
        )


class QuantumReadoutStack(_VirtualInstrumentDriver):
    _implementation_id = "quantum_lab_demo.virtual_lab.readout_stack"

    def __init__(self, *, profile: VirtualDeviceProfile) -> None:
        super().__init__(
            profile=profile,
            capabilities=[
                capability("readout_pulse"),
                capability("acquire_iq"),
            ],
        )


class QuantumLabVirtualProvider:
    provider_id = "quantum_lab_demo.virtual_lab.provider"

    def __init__(
        self,
        profile: str | Path,
    ) -> None:
        self.profile = load_virtual_lab_profile(profile)
        self._metadata: dict[str, JsonValue] = {
            "mode": "virtual_lab",
            "category": "experiment_system",
            "virtual_lab_profile": self.profile.id,
        }

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

    def provide(self, context: InstrumentProviderContext) -> InstrumentProviderResult:
        problems: list[Problem] = []
        try:
            selected = set(context.instrument_ids)
            drivers = tuple(
                driver
                for driver in self._build_virtual_instruments()
                if not selected or driver.instrument_id in selected
            )
        except DriverFault as error:
            problems.append(error.problem)
            drivers = ()
        return InstrumentProviderResult(
            drivers=drivers,
            problems=tuple(problems),
            metadata={
                "provider_id": self.provider_id,
                **self._metadata,
            },
        )

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


def _decode_state_key(key: str) -> tuple[str, str]:
    capability_id, separator, field_path = key.partition(".")
    if not separator or not capability_id or not field_path:
        raise ValueError(
            "virtual device initial_state keys must use '<capability_id>.<field_path>'"
        )
    return capability_id, field_path


__all__ = [
    "QuantumDriveStack",
    "QuantumLabVirtualProvider",
    "QuantumReadoutStack",
]
