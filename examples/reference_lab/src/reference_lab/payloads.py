"""Pulse-program payload codec shared by planning and the instrument worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry

SAMPLED_WAVEFORM_SCHEMA_ID = "sampled_waveform"
AWG_ENTRY_SCHEMA_ID = "reference_lab.awg_entry.v1"
AWG_PROGRAM_SCHEMA_ID = "reference_lab.awg_program.v1"
VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID = "reference_lab.virtual_capture_queue.v1"
TRIGGER_EPOCH_SCHEMA_ID = "reference_lab.trigger_epoch.v1"
DIGITIZER_DSP_PROGRAM_SCHEMA_ID = "reference_lab.digitizer_dsp_program.v1"


@dataclass(frozen=True, slots=True)
class DecodedSampledWaveform:
    samples: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class DecodedAwgChannelWaveform:
    component_path: tuple[str, ...]
    samples: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class DecodedAwgEntry:
    waveforms: tuple[DecodedAwgChannelWaveform, ...]


@dataclass(frozen=True, slots=True)
class DecodedAwgProgram:
    entries: tuple[DecodedAwgEntry, ...]


@dataclass(frozen=True, slots=True)
class DecodedVirtualCaptureTrace:
    instrument_id: str
    component_path: tuple[str, ...]
    samples: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class DecodedVirtualCapture:
    traces: tuple[DecodedVirtualCaptureTrace, ...]


@dataclass(frozen=True, slots=True)
class DecodedVirtualCaptureQueue:
    captures: tuple[DecodedVirtualCapture, ...]


@dataclass(frozen=True, slots=True)
class DecodedTriggerEpoch:
    epoch_id: str
    awg_instrument_ids: tuple[str, ...]
    digitizer_instrument_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecodedDigitizerDspWindow:
    component_path: tuple[str, ...]
    demodulator_slot_id: str
    start_sample: int
    sample_count: int
    demodulation_frequency_hz: float
    semantics_id: Literal["reference_lab.integrated_iq.ssb_midpoint.v1"]
    normalization: Literal["single_sideband_amplitude"]


@dataclass(frozen=True, slots=True)
class DecodedDigitizerDspProgram:
    windows: tuple[DecodedDigitizerDspWindow, ...]


class _SampledWaveformDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: tuple[float, ...] = Field(min_length=1)


class _AwgChannelWaveformDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_path: tuple[str, ...] = Field(min_length=1)
    samples: tuple[float, ...] = Field(min_length=1)


class _AwgEntryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    waveforms: tuple[_AwgChannelWaveformDocument, ...] = Field(min_length=1)


class _AwgProgramDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: tuple[_AwgEntryDocument, ...] = Field(min_length=1)


class _VirtualCaptureTraceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    component_path: tuple[str, ...] = Field(min_length=1)
    samples: tuple[float, ...] = Field(min_length=1)


class _VirtualCaptureDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traces: tuple[_VirtualCaptureTraceDocument, ...] = ()


class _VirtualCaptureQueueDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    captures: tuple[_VirtualCaptureDocument, ...] = Field(min_length=1)


class _TriggerEpochDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    epoch_id: str = Field(min_length=1)
    awg_instrument_ids: tuple[str, ...]
    digitizer_instrument_ids: tuple[str, ...]


class _DigitizerDspWindowDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_path: tuple[str, ...] = Field(min_length=1)
    demodulator_slot_id: str = Field(min_length=1)
    start_sample: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    demodulation_frequency_hz: float
    semantics_id: Literal["reference_lab.integrated_iq.ssb_midpoint.v1"]
    normalization: Literal["single_sideband_amplitude"]


class _DigitizerDspProgramDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windows: tuple[_DigitizerDspWindowDocument, ...] = Field(min_length=1)


def reference_lab_payload_codecs() -> PayloadCodecRegistry:
    return PayloadCodecRegistry(
        {
            DIGITIZER_DSP_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.digitizer-dsp-program-json",
                version=1,
                media_type="application/json",
                encoder=_encode_digitizer_dsp_program,
                decoder=_decode_digitizer_dsp_program,
            ),
            TRIGGER_EPOCH_SCHEMA_ID: PayloadCodec(
                id="reference_lab.trigger-epoch-json",
                version=1,
                media_type="application/json",
                encoder=_encode_trigger_epoch,
                decoder=_decode_trigger_epoch,
            ),
            VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID: PayloadCodec(
                id="reference_lab.virtual-capture-queue-json",
                version=1,
                media_type="application/json",
                encoder=_encode_virtual_capture_queue,
                decoder=_decode_virtual_capture_queue,
            ),
            AWG_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.awg-program-json",
                version=1,
                media_type="application/json",
                encoder=_encode_awg_program,
                decoder=_decode_awg_program,
            ),
            AWG_ENTRY_SCHEMA_ID: PayloadCodec(
                id="reference_lab.awg-entry-json",
                version=1,
                media_type="application/json",
                encoder=_encode_awg_entry,
                decoder=_decode_awg_entry,
            ),
            SAMPLED_WAVEFORM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.sampled-waveform-json",
                version=1,
                media_type="application/json",
                encoder=_encode_sampled_waveform,
                decoder=_decode_sampled_waveform,
            ),
        }
    )


def _encode_sampled_waveform(value: object) -> bytes:
    document = _SampledWaveformDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_sampled_waveform(content: bytes) -> object:
    document = _SampledWaveformDocument.model_validate_json(content)
    return DecodedSampledWaveform(samples=document.samples)


def _encode_awg_entry(value: object) -> bytes:
    document = _AwgEntryDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_awg_entry(content: bytes) -> object:
    document = _AwgEntryDocument.model_validate_json(content)
    return _decoded_awg_entry(document)


def _encode_awg_program(value: object) -> bytes:
    document = _AwgProgramDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_awg_program(content: bytes) -> object:
    document = _AwgProgramDocument.model_validate_json(content)
    return DecodedAwgProgram(
        entries=tuple(_decoded_awg_entry(entry) for entry in document.entries)
    )


def _decoded_awg_entry(document: _AwgEntryDocument) -> DecodedAwgEntry:
    return DecodedAwgEntry(
        waveforms=tuple(
            DecodedAwgChannelWaveform(
                component_path=waveform.component_path,
                samples=waveform.samples,
            )
            for waveform in document.waveforms
        )
    )


def _encode_virtual_capture_queue(value: object) -> bytes:
    document = _VirtualCaptureQueueDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_virtual_capture_queue(content: bytes) -> object:
    document = _VirtualCaptureQueueDocument.model_validate_json(content)
    return DecodedVirtualCaptureQueue(
        captures=tuple(
            DecodedVirtualCapture(
                traces=tuple(
                    DecodedVirtualCaptureTrace(
                        instrument_id=trace.instrument_id,
                        component_path=trace.component_path,
                        samples=trace.samples,
                    )
                    for trace in capture.traces
                )
            )
            for capture in document.captures
        )
    )


def _encode_trigger_epoch(value: object) -> bytes:
    document = _TriggerEpochDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_trigger_epoch(content: bytes) -> object:
    document = _TriggerEpochDocument.model_validate_json(content)
    return DecodedTriggerEpoch(
        epoch_id=document.epoch_id,
        awg_instrument_ids=document.awg_instrument_ids,
        digitizer_instrument_ids=document.digitizer_instrument_ids,
    )


def _encode_digitizer_dsp_program(value: object) -> bytes:
    document = _DigitizerDspProgramDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_digitizer_dsp_program(content: bytes) -> object:
    document = _DigitizerDspProgramDocument.model_validate_json(content)
    return DecodedDigitizerDspProgram(
        windows=tuple(
            DecodedDigitizerDspWindow(
                component_path=window.component_path,
                demodulator_slot_id=window.demodulator_slot_id,
                start_sample=window.start_sample,
                sample_count=window.sample_count,
                demodulation_frequency_hz=window.demodulation_frequency_hz,
                semantics_id=window.semantics_id,
                normalization=window.normalization,
            )
            for window in document.windows
        )
    )


__all__ = [
    "AWG_ENTRY_SCHEMA_ID",
    "AWG_PROGRAM_SCHEMA_ID",
    "DIGITIZER_DSP_PROGRAM_SCHEMA_ID",
    "SAMPLED_WAVEFORM_SCHEMA_ID",
    "TRIGGER_EPOCH_SCHEMA_ID",
    "VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID",
    "DecodedAwgChannelWaveform",
    "DecodedAwgEntry",
    "DecodedAwgProgram",
    "DecodedDigitizerDspProgram",
    "DecodedDigitizerDspWindow",
    "DecodedSampledWaveform",
    "DecodedTriggerEpoch",
    "DecodedVirtualCapture",
    "DecodedVirtualCaptureQueue",
    "DecodedVirtualCaptureTrace",
    "reference_lab_payload_codecs",
]
