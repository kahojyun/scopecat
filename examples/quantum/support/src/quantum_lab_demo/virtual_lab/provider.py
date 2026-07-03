"""Managed instrument providers backed by configurable virtual devices."""

from __future__ import annotations

from typing import Any

from scopecat.instruments import (
    ManagedInstrument,
    ManagedInstrumentProvider,
    MeasurementContext,
    ProviderBuildContext,
    StateChange,
    asset_field,
    capability,
    number_field,
    quantity_field,
)
from scopecat.models.provider import ProviderOptionDescription
from scopecat.results import MeasurementSink

from quantum_lab_demo.virtual_lab.devices import VirtualDevice, VirtualLab
from quantum_lab_demo.virtual_lab.profiles import (
    VirtualLabProfileInput,
    load_virtual_lab_profile,
)
from quantum_lab_demo.virtual_lab.responses import (
    readout_iq_response_model,
    readout_response_model,
    record_readout_frequency_measurement,
    record_readout_iq_measurements,
    record_sample_measurement,
)


class _VirtualManagedInstrument(ManagedInstrument):
    def __init__(self, *, device: VirtualDevice, **kwargs: Any) -> None:
        self._device = device
        super().__init__(instrument_id=device.id, initial_state=device.state, **kwargs)

    @property
    def virtual_device(self) -> VirtualDevice:
        return self._device

    def apply_state(self, changes: StateChange) -> None:
        self._device.apply(changes)


class ReadoutFrequencyStack(_VirtualManagedInstrument):
    implementation_id = "quantum_lab_demo.readout_frequency_stack"
    implementation_version = "v0"

    def __init__(
        self,
        *,
        device: VirtualDevice,
        flux_bias: VirtualDevice,
        response_profile,
    ) -> None:
        self._flux_bias = flux_bias
        self._response_model = readout_response_model(response_profile)
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "readout_pulse",
                    fields=[
                        quantity_field("frequency", unit="GHz"),
                        quantity_field("power", unit="dBm"),
                        quantity_field("phase", unit="rad"),
                    ],
                ),
                capability(
                    "demodulate_iq",
                    fields=[
                        quantity_field("lo_frequency", unit="GHz"),
                        quantity_field("demod_frequency", unit="MHz"),
                    ],
                ),
                capability(
                    "capture_dataset",
                    fields=[
                        quantity_field("start_delay", unit="ns"),
                        quantity_field("repetitions", unit="count"),
                    ],
                    acquisition=True,
                ),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )

    def measure(
        self,
        context: MeasurementContext,
        sink: MeasurementSink,
    ) -> None:
        if context.acquisition_kind != "iq":
            return
        record_readout_frequency_measurement(
            sink=sink,
            context=context,
            readout=self.virtual_device,
            flux_bias=self._flux_bias,
            response_model=self._response_model,
            instrument_id=self.implementation_id,
        )


class ReadoutIQStack(_VirtualManagedInstrument):
    implementation_id = "quantum_lab_demo.readout_iq_stack"
    implementation_version = "v0"

    def __init__(self, *, device: VirtualDevice, response_profile) -> None:
        self._response_model = readout_iq_response_model(response_profile)
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "readout_pulse",
                    fields=[
                        quantity_field("frequency", unit="GHz"),
                        quantity_field("power", unit="dBm"),
                    ],
                ),
                capability(
                    "capture_shots",
                    fields=[quantity_field("shots", unit="count")],
                    acquisition=True,
                ),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )

    def measure(
        self,
        context: MeasurementContext,
        sink: MeasurementSink,
    ) -> None:
        if context.acquisition_kind != "iq":
            return
        record_readout_iq_measurements(
            sink=sink,
            context=context,
            readout=self.virtual_device,
            response_model=self._response_model,
            instrument_id=self.implementation_id,
        )


class FluxBiasSource(_VirtualManagedInstrument):
    implementation_id = "quantum_lab_demo.flux_bias_source"
    implementation_version = "v0"

    def __init__(self, *, device: VirtualDevice) -> None:
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "set_offset",
                    fields=[quantity_field("offset", unit="arb")],
                )
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )


class SampleDriveStack(_VirtualManagedInstrument):
    implementation_id = "quantum_lab_demo.sample_drive_stack"
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
                        asset_field("program", asset_kinds=("pulse_program",)),
                        quantity_field("length", unit="ns"),
                        quantity_field("amplitude", unit="arb"),
                        quantity_field("frequency", unit="GHz"),
                    ],
                ),
                capability(
                    "play_gate_sequence",
                    fields=[
                        asset_field("sequence", asset_kinds=("gate_sequence",)),
                        quantity_field("clifford_count", unit="count"),
                        number_field("seed"),
                    ],
                ),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )


class SampleReadoutStack(_VirtualManagedInstrument):
    implementation_id = "quantum_lab_demo.sample_readout_stack"
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
                        asset_field("program", asset_kinds=("readout_program",)),
                        quantity_field("frequency", unit="GHz"),
                        quantity_field("power", unit="dBm"),
                    ],
                ),
                capability(
                    "capture_dataset",
                    fields=[quantity_field("repetitions", unit="count")],
                    acquisition=True,
                ),
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )

    def measure(
        self,
        context: MeasurementContext,
        sink: MeasurementSink,
    ) -> None:
        record_sample_measurement(
            sink=sink,
            context=context,
            readout=self.virtual_device,
            implementation_id=self.implementation_id,
        )


class SampleCouplerStack(_VirtualManagedInstrument):
    implementation_id = "quantum_lab_demo.sample_coupler_stack"
    implementation_version = "v0"

    def __init__(self, *, device: VirtualDevice) -> None:
        super().__init__(
            device=device,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[
                capability(
                    "play_coupler_pulse",
                    fields=[asset_field("program", asset_kinds=("pulse_program",))],
                )
            ],
            metadata={"mode": "virtual_lab", "source": "quantum-lab-demo"},
        )


class _VirtualLabProvider(ManagedInstrumentProvider):
    def __init__(
        self,
        *,
        profile: VirtualLabProfileInput,
        provider_id: str,
        label: str,
        description: str,
        provided_instrument_ids: tuple[str, ...],
        capabilities: tuple[str, ...],
        category: str,
    ) -> None:
        self.profile = load_virtual_lab_profile(profile)
        super().__init__(
            provider_id=provider_id,
            label=label,
            description=description,
            options=(
                ProviderOptionDescription(
                    id="virtual_lab_profile",
                    dtype="VirtualLabProfile",
                    required=True,
                    label="Virtual lab profile",
                    description="Offline virtual devices and response behavior.",
                ),
            ),
            provided_instrument_ids=provided_instrument_ids,
            capabilities=capabilities,
            metadata={
                "mode": "virtual_lab",
                "category": category,
                "virtual_lab_profile": self.profile.id,
            },
            build=self._build,
        )

    def _lab(self) -> VirtualLab:
        return VirtualLab.from_profiles(self.profile.devices)

    def _build(self, context: ProviderBuildContext):
        del context
        return self._build_virtual_instruments(self._lab())

    def _build_virtual_instruments(self, lab: VirtualLab):
        raise NotImplementedError

    def _response_profile(self, device: VirtualDevice):
        if device.response_model_id is None:
            return None
        return self.profile.response_profile(device.response_model_id)


class ReadoutFrequencyVirtualProvider(_VirtualLabProvider):
    def __init__(
        self,
        profile: VirtualLabProfileInput,
        provider_id: str = ("quantum_lab_demo.readout_frequency_provider"),
    ) -> None:
        super().__init__(
            profile=profile,
            provider_id=provider_id,
            label="Quantum readout frequency virtual-lab provider",
            description=(
                "Provides virtual readout-stack and flux-bias-source devices "
                "for readout frequency calibration."
            ),
            provided_instrument_ids=("readout-stack", "flux-bias-source"),
            capabilities=(
                "readout_pulse",
                "demodulate_iq",
                "capture_dataset",
                "set_offset",
            ),
            category="readout_frequency",
        )

    def _build_virtual_instruments(self, lab: VirtualLab):
        readout = lab.device("readout-stack")
        flux_bias = lab.device("flux-bias-source")
        response_profile = self._response_profile(readout)
        if response_profile is None:
            raise KeyError("readout-stack requires response_model_id")
        return [
            ReadoutFrequencyStack(
                device=readout,
                flux_bias=flux_bias,
                response_profile=response_profile,
            ),
            FluxBiasSource(device=flux_bias),
        ]


class ReadoutIQVirtualProvider(_VirtualLabProvider):
    def __init__(
        self,
        profile: VirtualLabProfileInput,
        provider_id: str = "quantum_lab_demo.readout_iq_provider",
    ) -> None:
        super().__init__(
            profile=profile,
            provider_id=provider_id,
            label="Quantum readout IQ virtual-lab provider",
            description=(
                "Provides a virtual readout-stack device for shot-level "
                "readout IQ quality runs."
            ),
            provided_instrument_ids=("readout-stack",),
            capabilities=("readout_pulse", "capture_shots"),
            category="readout_iq_quality",
        )

    def _build_virtual_instruments(self, lab: VirtualLab):
        readout = lab.device("readout-stack")
        response_profile = self._response_profile(readout)
        if response_profile is None:
            raise KeyError("readout-stack requires response_model_id")
        return [
            ReadoutIQStack(
                device=readout,
                response_profile=response_profile,
            )
        ]


class SampleVirtualProvider(_VirtualLabProvider):
    def __init__(
        self,
        profile: VirtualLabProfileInput,
        provider_id: str = "quantum_lab_demo.sample_provider",
    ) -> None:
        super().__init__(
            profile=profile,
            provider_id=provider_id,
            label="Sample virtual-lab instrument provider",
            description=(
                "Provides virtual hardware-shaped devices for sample-backed "
                "authoring templates."
            ),
            provided_instrument_ids=("drive-stack", "readout-stack", "coupler-stack"),
            capabilities=(
                "play_pulse_program",
                "play_gate_sequence",
                "readout_pulse",
                "capture_dataset",
                "play_coupler_pulse",
            ),
            category="sample_templates",
        )

    def _build_virtual_instruments(self, lab: VirtualLab):
        return [
            SampleDriveStack(device=lab.device("drive-stack")),
            SampleReadoutStack(device=lab.device("readout-stack")),
            SampleCouplerStack(device=lab.device("coupler-stack")),
        ]


__all__ = [
    "FluxBiasSource",
    "ReadoutFrequencyStack",
    "ReadoutFrequencyVirtualProvider",
    "ReadoutIQStack",
    "ReadoutIQVirtualProvider",
    "SampleCouplerStack",
    "SampleDriveStack",
    "SampleReadoutStack",
    "SampleVirtualProvider",
]
