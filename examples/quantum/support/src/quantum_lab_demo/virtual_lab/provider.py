"""Instrument providers backed by configurable virtual devices."""

from __future__ import annotations

from collections.abc import Sequence
from typing import override

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
from scopecat.sdk.problems import Problem

from quantum_lab_demo.virtual_lab.devices import VirtualDevice, VirtualLab
from quantum_lab_demo.virtual_lab.profiles import (
    VirtualLabProfileInput,
    load_virtual_lab_profile,
)


class _VirtualInstrumentDriver:
    def __init__(
        self,
        *,
        device: VirtualDevice,
        implementation_id: str,
        implementation_version: str,
        capabilities: Sequence[CapabilityDescription],
        metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        self._device = device
        self.instrument_id = device.id
        self.implementation_id = implementation_id
        self.implementation_version = implementation_version
        self._capabilities = list(capabilities)
        self._metadata = dict(metadata or {})

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
                for (capability_id, field_path), value in sorted(
                    self._device.state.items()
                )
            ],
            metadata=self._metadata,
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self._device.apply(command)
        return ApplyReceipt(status="applied")

    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        return CollectReceipt(readback=InstrumentReadback())

    def cleanup(self) -> None:
        return None

    def abort(self) -> None:
        return None


class QuantumDriveStack(_VirtualInstrumentDriver):
    implementation_id = "quantum_lab_demo.virtual_lab.drive_stack"
    implementation_version = "v0"

    def __init__(self, *, device: VirtualDevice) -> None:
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "play_pulse_program",
                    fields=[payload_field("program", schema_id="pulse_program")],
                ),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )


class QuantumReadoutStack(_VirtualInstrumentDriver):
    implementation_id = "quantum_lab_demo.virtual_lab.readout_stack"
    implementation_version = "v0"

    def __init__(self, *, device: VirtualDevice) -> None:
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability("readout_pulse"),
                capability("acquire_iq"),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )


class _VirtualLabProvider:
    def __init__(
        self,
        *,
        profile: VirtualLabProfileInput,
        provider_id: str,
        category: str,
    ) -> None:
        self.profile = load_virtual_lab_profile(profile)
        self._provider_id = provider_id
        self._metadata: dict[str, JsonValue] = {
            "mode": "virtual_lab",
            "category": category,
            "virtual_lab_profile": self.profile.id,
        }

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription:
        del context
        problems: list[Problem] = []
        try:
            instruments = tuple(
                driver.describe()
                for driver in self._build_virtual_instruments(self._lab())
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
        del context
        problems: list[Problem] = []
        try:
            drivers = tuple(self._build_virtual_instruments(self._lab()))
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

    def _lab(self) -> VirtualLab:
        return VirtualLab.from_profiles(self.profile.devices)

    def _build_virtual_instruments(
        self,
        lab: VirtualLab,
    ) -> Sequence[InstrumentDriver]:
        raise NotImplementedError


class QuantumLabVirtualProvider(_VirtualLabProvider):
    def __init__(
        self,
        profile: VirtualLabProfileInput,
        provider_id: str = "quantum_lab_demo.virtual_lab.provider",
    ) -> None:
        super().__init__(
            profile=profile,
            provider_id=provider_id,
            category="experiment_system",
        )

    @override
    def _build_virtual_instruments(
        self,
        lab: VirtualLab,
    ) -> Sequence[InstrumentDriver]:
        return [
            QuantumDriveStack(device=lab.device("drive-stack")),
            QuantumReadoutStack(device=lab.device("readout-stack")),
        ]


__all__ = [
    "QuantumDriveStack",
    "QuantumLabVirtualProvider",
    "QuantumReadoutStack",
]
