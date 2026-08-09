"""Immutable device programs for the reference-lab list-mode target."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    PulseProgramId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.pulses import (
    AcquireSignal,
    DriveSignal,
    ReadoutSignal,
)


@dataclass(frozen=True, slots=True, order=True)
class AwgChannelId:
    """One routed physical DAC output used by the target."""

    value: str
    instrument_id: str
    component_path: tuple[str, ...]


@dataclass(frozen=True, slots=True, order=True)
class DigitizerInputId:
    """One physical ADC input, independent of target-owned DSP slots."""

    value: str
    instrument_id: str
    component_path: tuple[str, ...]


@dataclass(frozen=True, slots=True, order=True)
class DemodulatorSlotId:
    """One target-owned DSP result slot on a physical ADC stream."""

    value: str


type OutputSignal = DriveSignal | ReadoutSignal


def signal_key(
    signal: OutputSignal | AcquireSignal,
) -> tuple[str, str, str]:
    """Return a canonical hardware-independent key for one logical signal."""

    if isinstance(signal, DriveSignal):
        return ("drive", "qubit", signal.qubit.value)
    if isinstance(signal, ReadoutSignal):
        return ("readout", "qubit", signal.qubit.value)
    return ("acquire", "qubit", signal.qubit.value)


@dataclass(frozen=True, slots=True)
class IqMixerCalibration:
    """Lab-reviewed affine transform from ideal complex IQ to physical DACs."""

    ii: float
    iq: float
    qi: float
    qq: float
    i_offset_v: float
    q_offset_v: float


@dataclass(frozen=True, slots=True)
class IqOutputBinding:
    """Bind one logical envelope and signed IF to two physical DACs."""

    signal: OutputSignal
    iq_chain_id: str
    lo_group_id: str
    i_channel_id: AwgChannelId
    q_channel_id: AwgChannelId
    intermediate_frequency_hz: float
    mixer: IqMixerCalibration

    @property
    def channel_ids(self) -> tuple[AwgChannelId, AwgChannelId]:
        return (self.i_channel_id, self.q_channel_id)


@dataclass(frozen=True, slots=True)
class AcquisitionBinding:
    """Bind a logical result to one ADC input and one DSP slot."""

    signal: AcquireSignal
    input_id: DigitizerInputId
    demodulator_slot_id: DemodulatorSlotId
    demodulation_frequency_hz: float


@dataclass(frozen=True, slots=True, order=True)
class ClockPreparation:
    """Shared reference-clock preparation for one physical instrument."""

    instrument_id: str
    source: Literal["internal", "external"]
    frequency_hz: float


@dataclass(frozen=True, slots=True, order=True)
class LocalOscillatorPreparation:
    """One shared LO group resolved by the laboratory target adapter."""

    group_id: str
    instrument_id: str
    entity_ids: tuple[str, ...]
    frequency_hz: float
    power_dbm: float
    output_enabled: bool = True


@dataclass(frozen=True, slots=True, order=True)
class OutputChannelPreparation:
    """Run-wide analog state for one physical AWG output."""

    channel_id: AwgChannelId
    amplitude_v: float
    offset_v: float
    output_enabled: bool = True


@dataclass(frozen=True, slots=True, order=True)
class TimingDomainPreparation:
    """One shared edge and phase policy for all armed target members."""

    domain_id: str
    trigger_instrument_id: str
    trigger_guarantee: Literal["fire_only", "session_idempotent"]
    digitizer_trigger_source: Literal["external"]
    phase_reference: Literal["entry_trigger_reset"]


@dataclass(frozen=True, slots=True)
class ListModePreparation:
    """Run-wide device state required before loading target programs."""

    clocks: tuple[ClockPreparation, ...]
    outputs: tuple[OutputChannelPreparation, ...]
    local_oscillators: tuple[LocalOscillatorPreparation, ...]
    timing: TimingDomainPreparation


def canonical_fingerprint(payload: object) -> str:
    """Hash canonical JSON data with a stable schema-independent envelope."""

    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def pulse_event_identity_payload(event_id: PulseEventId) -> dict[str, object]:
    """Project structural event identity without coupling hashes to its display."""

    return {
        "scope": list(event_id.scope),
        "local_id": event_id.local_id,
    }


def acquisition_slot_identity_payload(
    slot_id: AcquisitionSlotId,
) -> dict[str, object]:
    """Project structural result identity without coupling hashes to its display."""

    return {
        "scope": list(slot_id.scope),
        "local_id": slot_id.local_id,
    }


def preparation_payload(preparation: ListModePreparation) -> dict[str, object]:
    """Return the canonical preparation representation used by fingerprints."""

    return {
        "clocks": [
            {
                "instrument_id": clock.instrument_id,
                "source": clock.source,
                "frequency_hz": float(clock.frequency_hz).hex(),
            }
            for clock in preparation.clocks
        ],
        "outputs": [
            {
                "channel_id": output.channel_id.value,
                "instrument_id": output.channel_id.instrument_id,
                "component_path": list(output.channel_id.component_path),
                "amplitude_v": float(output.amplitude_v).hex(),
                "offset_v": float(output.offset_v).hex(),
                "output_enabled": output.output_enabled,
            }
            for output in preparation.outputs
        ],
        "local_oscillators": [
            {
                "group_id": oscillator.group_id,
                "instrument_id": oscillator.instrument_id,
                "entity_ids": list(oscillator.entity_ids),
                "frequency_hz": float(oscillator.frequency_hz).hex(),
                "power_dbm": float(oscillator.power_dbm).hex(),
                "output_enabled": oscillator.output_enabled,
            }
            for oscillator in preparation.local_oscillators
        ],
        "timing": {
            "domain_id": preparation.timing.domain_id,
            "trigger_instrument_id": preparation.timing.trigger_instrument_id,
            "trigger_guarantee": preparation.timing.trigger_guarantee,
            "digitizer_trigger_source": (preparation.timing.digitizer_trigger_source),
            "phase_reference": preparation.timing.phase_reference,
        },
    }


@dataclass(frozen=True, slots=True)
class ListModeTarget:
    """Capabilities, physical routes, and preparation of the target."""

    id: TargetId
    sample_rate_hz: int
    max_list_entries: int
    max_samples_per_entry: int
    max_repetitions: int
    max_abs_amplitude: float
    acquisition_dsp_policy: Literal["target", "device", "prefer_device"]
    digitizer_result_representation: Literal["raw_trace", "integrated_iq"]
    preparation: ListModePreparation
    output_bindings: tuple[IqOutputBinding, ...]
    acquisition_bindings: tuple[AcquisitionBinding, ...]
    _capability_fingerprint: str = field(init=False, repr=False)
    _configuration_fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        canonical_outputs = tuple(
            sorted(
                self.output_bindings,
                key=lambda binding: (
                    *signal_key(binding.signal),
                    binding.lo_group_id,
                    binding.i_channel_id,
                    binding.q_channel_id,
                    binding.intermediate_frequency_hz,
                ),
            )
        )
        canonical_acquisitions = tuple(
            sorted(
                self.acquisition_bindings,
                key=lambda binding: (
                    *signal_key(binding.signal),
                    binding.input_id,
                    binding.demodulator_slot_id,
                ),
            )
        )
        object.__setattr__(self, "output_bindings", canonical_outputs)
        object.__setattr__(self, "acquisition_bindings", canonical_acquisitions)
        object.__setattr__(
            self,
            "_capability_fingerprint",
            canonical_fingerprint(self._capability_payload()),
        )
        object.__setattr__(
            self,
            "_configuration_fingerprint",
            canonical_fingerprint(self._configuration_payload()),
        )

    @property
    def capability_fingerprint(self) -> str:
        return self._capability_fingerprint

    @property
    def configuration_fingerprint(self) -> str:
        return self._configuration_fingerprint

    @property
    def supported_envelopes(self) -> tuple[str, ...]:
        return ("constant", "drag")

    def output_binding(self, signal: OutputSignal) -> IqOutputBinding | None:
        for binding in self.output_bindings:
            if binding.signal == signal:
                return binding
        return None

    def acquisition_binding(self, signal: AcquireSignal) -> AcquisitionBinding | None:
        for binding in self.acquisition_bindings:
            if binding.signal == signal:
                return binding
        return None

    def _capability_payload(self) -> dict[str, object]:
        return {
            "schema": "reference_lab.list_mode_target.capabilities.v5",
            "target_id": self.id.value,
            "sample_rate_hz": self.sample_rate_hz,
            "max_list_entries": self.max_list_entries,
            "max_samples_per_entry": self.max_samples_per_entry,
            "max_repetitions": self.max_repetitions,
            "max_abs_amplitude": float(self.max_abs_amplitude).hex(),
            "digitizer_result_representation": (self.digitizer_result_representation),
            "supported_envelopes": list(self.supported_envelopes),
        }

    def _configuration_payload(self) -> dict[str, object]:
        return {
            "schema": "reference_lab.list_mode_target.configuration.v1",
            "target_id": self.id.value,
            "capability_fingerprint": self.capability_fingerprint,
            "acquisition_dsp_policy": self.acquisition_dsp_policy,
            "output_bindings": [
                {
                    "signal": signal_key(binding.signal),
                    "iq_chain_id": binding.iq_chain_id,
                    "lo_group_id": binding.lo_group_id,
                    "instrument_id": binding.i_channel_id.instrument_id,
                    "i_channel_id": binding.i_channel_id.value,
                    "i_component_path": list(binding.i_channel_id.component_path),
                    "q_channel_id": binding.q_channel_id.value,
                    "q_component_path": list(binding.q_channel_id.component_path),
                    "intermediate_frequency_hz": float(
                        binding.intermediate_frequency_hz
                    ).hex(),
                    "mixer": {
                        "ii": float(binding.mixer.ii).hex(),
                        "iq": float(binding.mixer.iq).hex(),
                        "qi": float(binding.mixer.qi).hex(),
                        "qq": float(binding.mixer.qq).hex(),
                        "i_offset_v": float(binding.mixer.i_offset_v).hex(),
                        "q_offset_v": float(binding.mixer.q_offset_v).hex(),
                    },
                }
                for binding in self.output_bindings
            ],
            "acquisition_bindings": [
                {
                    "signal": signal_key(binding.signal),
                    "input_id": binding.input_id.value,
                    "instrument_id": binding.input_id.instrument_id,
                    "component_path": list(binding.input_id.component_path),
                    "demodulator_slot_id": binding.demodulator_slot_id.value,
                    "demodulation_frequency_hz": float(
                        binding.demodulation_frequency_hz
                    ).hex(),
                }
                for binding in self.acquisition_bindings
            ],
            "preparation": preparation_payload(self.preparation),
        }


@dataclass(frozen=True, slots=True)
class AwgChannelWaveform:
    """One immutable, zero-padded physical DAC buffer."""

    channel_id: AwgChannelId
    samples: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class AcquisitionIntent:
    """Semantic acquisition result requested by the pulse program."""

    semantics_id: Literal["reference_lab.integrated_iq.ssb_midpoint.v1"]
    output_representation: Literal["integrated_iq"]
    demodulation_frequency_hz: float
    integration_weight: Literal["rectangular"]
    normalization: Literal["single_sideband_amplitude"]


@dataclass(frozen=True, slots=True)
class TargetAcquisitionLowering:
    """Raw device capture followed by target-side semantic processing."""

    execution: Literal["target"] = "target"
    device_result_representation: Literal["raw_trace"] = "raw_trace"


@dataclass(frozen=True, slots=True)
class DeviceAcquisitionLowering:
    """Semantic processing lowered to an onboard digitizer acquisition."""

    execution: Literal["device"] = "device"
    device_result_representation: Literal["integrated_iq"] = "integrated_iq"


type AcquisitionLowering = TargetAcquisitionLowering | DeviceAcquisitionLowering


@dataclass(frozen=True, slots=True)
class DigitizerAcquisitionWindow:
    """One ADC and demodulation window in a list entry."""

    event_id: PulseEventId
    slot_id: AcquisitionSlotId
    signal: AcquireSignal
    input_id: DigitizerInputId
    demodulator_slot_id: DemodulatorSlotId
    intent: AcquisitionIntent
    lowering: AcquisitionLowering
    start_sample: int
    sample_count: int


@dataclass(frozen=True, slots=True)
class ListModeEntry:
    """One target list row with physical output and acquisition work."""

    list_index: int
    entry_id: TargetCompileEntryId
    program_id: PulseProgramId
    sample_count: int
    waveforms: tuple[AwgChannelWaveform, ...]
    acquisitions: tuple[DigitizerAcquisitionWindow, ...]


@dataclass(frozen=True, slots=True)
class AwgProgramEntry:
    """One list row projected to a single physical AWG."""

    entry_id: TargetCompileEntryId
    sample_count: int
    waveforms: tuple[AwgChannelWaveform, ...]


@dataclass(frozen=True, slots=True)
class AwgProgram:
    """All list rows loaded into one physical AWG."""

    instrument_id: str
    entries: tuple[AwgProgramEntry, ...]


@dataclass(frozen=True, slots=True)
class DigitizerProgramEntry:
    """One raw-capture row projected to one physical digitizer."""

    entry_id: TargetCompileEntryId
    sample_count: int
    input_ids: tuple[DigitizerInputId, ...]


@dataclass(frozen=True, slots=True)
class DigitizerProgram:
    """Physical ADC work after target/device DSP placement."""

    instrument_id: str
    sample_rate_hz: int
    trigger_source: Literal["external", "software"]
    result_representation: Literal["raw_trace", "integrated_iq"]
    entries: tuple[DigitizerProgramEntry, ...]


@dataclass(frozen=True, slots=True)
class TriggerEpoch:
    """One idempotent shared edge and its exact armed participants."""

    id: str
    awg_instrument_ids: tuple[str, ...]
    digitizer_instrument_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListModeArtifact:
    """Deeply immutable target artifact and its device-program projections."""

    id: TargetArtifactId
    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    configuration_fingerprint: str
    artifact_fingerprint: str
    source_entry_ids: tuple[TargetCompileEntryId, ...]
    repetitions: int
    sample_rate_hz: int
    preparation: ListModePreparation
    entries: tuple[ListModeEntry, ...]

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        """Return the exact physical footprint of this compiled batch."""

        return tuple(
            sorted(
                {
                    *(program.instrument_id for program in self.awg_programs),
                    *(program.instrument_id for program in self.digitizer_programs),
                    *(
                        oscillator.instrument_id
                        for oscillator in self.preparation.local_oscillators
                    ),
                    self.preparation.timing.trigger_instrument_id,
                }
            )
        )

    def trigger_epoch(
        self,
        entry: ListModeEntry,
        *,
        execution_id: str,
        shot_index: int,
    ) -> TriggerEpoch:
        """Project one execution position into a stable shared-trigger epoch."""

        return TriggerEpoch(
            id=(
                f"{execution_id}:{self.id.value}:shot-{shot_index}:"
                f"entry-{entry.list_index}"
            ),
            awg_instrument_ids=tuple(
                program.instrument_id
                for program in self.awg_programs
                if next(
                    selected
                    for selected in program.entries
                    if selected.entry_id == entry.entry_id
                ).waveforms
            ),
            digitizer_instrument_ids=tuple(
                program.instrument_id
                for program in self.digitizer_programs
                if next(
                    selected
                    for selected in program.entries
                    if selected.entry_id == entry.entry_id
                ).input_ids
            ),
        )

    @property
    def awg_programs(self) -> tuple[AwgProgram, ...]:
        """Project the artifact into per-instrument AWG programs."""

        instrument_ids = sorted(
            {
                waveform.channel_id.instrument_id
                for entry in self.entries
                for waveform in entry.waveforms
            }
        )
        return tuple(
            AwgProgram(
                instrument_id=instrument_id,
                entries=tuple(
                    AwgProgramEntry(
                        entry_id=entry.entry_id,
                        sample_count=entry.sample_count,
                        waveforms=tuple(
                            waveform
                            for waveform in entry.waveforms
                            if waveform.channel_id.instrument_id == instrument_id
                        ),
                    )
                    for entry in self.entries
                ),
            )
            for instrument_id in instrument_ids
        )

    @property
    def digitizer_programs(self) -> tuple[DigitizerProgram, ...]:
        """Project ADC inputs and demodulator slots per digitizer."""

        instrument_ids = sorted(
            {
                window.input_id.instrument_id
                for entry in self.entries
                for window in entry.acquisitions
            }
        )
        return tuple(
            DigitizerProgram(
                instrument_id=instrument_id,
                sample_rate_hz=self.sample_rate_hz,
                trigger_source=self.preparation.timing.digitizer_trigger_source,
                result_representation=next(
                    window.lowering.device_result_representation
                    for entry in self.entries
                    for window in entry.acquisitions
                    if window.input_id.instrument_id == instrument_id
                ),
                entries=tuple(
                    DigitizerProgramEntry(
                        entry_id=entry.entry_id,
                        sample_count=entry.sample_count,
                        input_ids=tuple(
                            sorted(
                                {
                                    window.input_id
                                    for window in entry.acquisitions
                                    if window.input_id.instrument_id == instrument_id
                                }
                            )
                        ),
                    )
                    for entry in self.entries
                ),
            )
            for instrument_id in instrument_ids
        )


__all__ = [
    "AcquisitionBinding",
    "AcquisitionIntent",
    "AcquisitionLowering",
    "AwgChannelId",
    "AwgChannelWaveform",
    "AwgProgram",
    "AwgProgramEntry",
    "ClockPreparation",
    "DemodulatorSlotId",
    "DeviceAcquisitionLowering",
    "DigitizerAcquisitionWindow",
    "DigitizerInputId",
    "DigitizerProgram",
    "DigitizerProgramEntry",
    "IqMixerCalibration",
    "IqOutputBinding",
    "ListModeArtifact",
    "ListModeEntry",
    "ListModePreparation",
    "ListModeTarget",
    "LocalOscillatorPreparation",
    "OutputChannelPreparation",
    "OutputSignal",
    "TargetAcquisitionLowering",
    "TimingDomainPreparation",
    "TriggerEpoch",
    "preparation_payload",
]
