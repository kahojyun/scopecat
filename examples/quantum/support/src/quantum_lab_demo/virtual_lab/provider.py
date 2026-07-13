"""Instrument providers backed by configurable virtual devices."""

from __future__ import annotations

from typing import Any

from scopecat.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    DriverFault,
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateField,
    InstrumentStateSnapshot,
    capability,
    float_field,
    payload_field,
    product,
    product_axis,
    quantity_field,
)
from scopecat.models.provider import ProviderOptionDescription

from quantum_lab_demo.virtual_lab.devices import VirtualDevice, VirtualLab
from quantum_lab_demo.virtual_lab.profiles import (
    VirtualLabProfileInput,
    load_virtual_lab_profile,
)
from quantum_lab_demo.virtual_lab.responses import (
    record_quantum_measurement,
)


class _VirtualInstrumentDriver:
    def __init__(
        self,
        *,
        device: VirtualDevice,
        implementation_id: str,
        implementation_version: str,
        capabilities,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._device = device
        self.instrument_id = device.id
        self.implementation_id = implementation_id
        self.implementation_version = implementation_version
        self._capabilities = list(capabilities)
        self._metadata = dict(metadata or {})

    @property
    def virtual_device(self) -> VirtualDevice:
        return self._device

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=list(self._capabilities),
            metadata=self._metadata,
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
    implementation_id = "quantum_lab_demo.experiments_drive_stack"
    implementation_version = "v0"

    def __init__(self, *, device: VirtualDevice) -> None:
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "play_pulse_program",
                    fields=[
                        payload_field("program", schema_id="pulse_program"),
                        quantity_field("length", unit="ns"),
                        quantity_field("amplitude", unit="arb"),
                        quantity_field("frequency", unit="GHz"),
                    ],
                ),
                capability(
                    "play_gate_sequence",
                    fields=[
                        payload_field("sequence", schema_id="gate_sequence"),
                        quantity_field("clifford_count", unit="count"),
                        float_field("seed"),
                    ],
                ),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )


class QuantumReadoutStack(_VirtualInstrumentDriver):
    implementation_id = "quantum_lab_demo.experiments_readout_stack"
    implementation_version = "v0"

    def __init__(self, *, device: VirtualDevice) -> None:
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "readout_pulse",
                    fields=[
                        payload_field("program", schema_id="readout_program"),
                        quantity_field("frequency", unit="GHz"),
                        quantity_field("power", unit="dBm"),
                    ],
                ),
                capability(
                    "submit_backend_batch",
                    fields=[payload_field("job", schema_id="backend_job")],
                ),
                capability(
                    "acquire_iq",
                    fields=[quantity_field("repetitions", unit="count")],
                    products=[
                        product("probability_0", unit="ratio"),
                        product("probability_1", unit="ratio"),
                        product("raw_iq", dtype="complex128", unit="ratio"),
                        product(
                            "multiplexed_iq",
                            dtype="complex128",
                            unit="ratio",
                            axes=[product_axis("qubit", kind="entity")],
                        ),
                        product(
                            "qnd_iq",
                            dtype="complex128",
                            unit="ratio",
                            axes=[
                                product_axis("round", kind="repeat", unit="count"),
                                product_axis("shot", kind="shot", unit="count"),
                            ],
                        ),
                        product(
                            "stabilizer_iq",
                            dtype="complex128",
                            unit="ratio",
                            axes=[
                                product_axis("round", kind="repeat", unit="count"),
                                product_axis("qubit", kind="entity"),
                            ],
                        ),
                        product(
                            "backend_probabilities",
                            unit="ratio",
                            axes=[
                                product_axis(
                                    "backend_point",
                                    kind="backend_point",
                                    unit="count",
                                ),
                            ],
                        ),
                        product("state0_iq", dtype="complex128", unit="ratio"),
                        product("state1_iq", dtype="complex128", unit="ratio"),
                        product("state0_iq_stdev", unit="ratio"),
                        product("state1_iq_stdev", unit="ratio"),
                    ],
                ),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )

    def collect(self, command: CollectCommand) -> CollectReceipt:
        if not command.requests:
            return CollectReceipt(readback=InstrumentReadback())
        return CollectReceipt(
            readback=InstrumentReadback(
                values=record_quantum_measurement(
                    command=command,
                    readout=self.virtual_device,
                    implementation_id=self.implementation_id,
                )
            )
        )


class QuantumCouplerStack(_VirtualInstrumentDriver):
    implementation_id = "quantum_lab_demo.experiments_coupler_stack"
    implementation_version = "v0"

    def __init__(self, *, device: VirtualDevice) -> None:
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "play_coupler_pulse",
                    fields=[payload_field("program", schema_id="pulse_program")],
                ),
                capability(
                    "set_flux_bias",
                    fields=[quantity_field("offset", unit="arb")],
                ),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )


class _VirtualLabProvider:
    def __init__(
        self,
        *,
        profile: VirtualLabProfileInput,
        provider_id: str,
        label: str,
        description: str,
        category: str,
    ) -> None:
        self.profile = load_virtual_lab_profile(profile)
        self._provider_id = provider_id
        self._label = label
        self._description = description
        self._metadata = {
            "mode": "virtual_lab",
            "category": category,
            "virtual_lab_profile": self.profile.id,
        }
        self._options = (
            ProviderOptionDescription(
                id="virtual_lab_profile",
                dtype="VirtualLabProfile",
                required=True,
                label="Virtual lab profile",
                description="Offline virtual devices and response behavior.",
            ),
        )

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription:
        del context
        problems = []
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
            label=self._label,
            description=self._description,
            options=self._options,
            metadata=self._metadata,
        )

    def provide(self, context: InstrumentProviderContext) -> InstrumentProviderResult:
        del context
        problems = []
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

    def _build_virtual_instruments(self, lab: VirtualLab):
        raise NotImplementedError

    def _response_profile(self, device: VirtualDevice):
        if device.response_model_id is None:
            return None
        return self.profile.response_profile(device.response_model_id)


class QuantumLabVirtualProvider(_VirtualLabProvider):
    def __init__(
        self,
        profile: VirtualLabProfileInput,
        provider_id: str = "quantum_lab_demo.experiments_provider",
    ) -> None:
        super().__init__(
            profile=profile,
            provider_id=provider_id,
            label="virtual-lab instrument provider",
            description=(
                "Provides virtual hardware-shaped devices for experiment-system "
                "authoring templates."
            ),
            category="experiment_system",
        )

    def _build_virtual_instruments(self, lab: VirtualLab):
        return [
            QuantumDriveStack(device=lab.device("drive-stack")),
            QuantumReadoutStack(device=lab.device("readout-stack")),
            QuantumCouplerStack(device=lab.device("coupler-stack")),
        ]


__all__ = [
    "QuantumCouplerStack",
    "QuantumDriveStack",
    "QuantumLabVirtualProvider",
    "QuantumReadoutStack",
]
