"""Pulse-program payload codec shared by planning and the instrument worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry

SAMPLED_WAVEFORM_SCHEMA_ID = "sampled_waveform"
AWG_PROGRAM_SCHEMA_ID = "reference_lab.awg_program.v1"
DIGITIZER_PROGRAM_SCHEMA_ID = "reference_lab.digitizer_program.v1"
TRIGGER_PROGRAM_SCHEMA_ID = "reference_lab.trigger_program.v1"


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
class DecodedDigitizerDspWindow:
    component_path: tuple[str, ...]
    demodulator_slot_id: str
    start_sample: int
    sample_count: int
    demodulation_frequency_hz: float
    semantics_id: Literal["reference_lab.integrated_iq.ssb_midpoint.v1"]
    normalization: Literal["single_sideband_amplitude"]


@dataclass(frozen=True, slots=True)
class DecodedDigitizerProgramEntry:
    sample_count: int
    input_component_paths: tuple[tuple[str, ...], ...]
    windows: tuple[DecodedDigitizerDspWindow, ...]


@dataclass(frozen=True, slots=True)
class DecodedDigitizerProgram:
    entries: tuple[DecodedDigitizerProgramEntry, ...]


@dataclass(frozen=True, slots=True)
class DecodedTriggerProgramEntry:
    awg_instrument_ids: tuple[str, ...]
    digitizer_instrument_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecodedTriggerProgram:
    program_id: str
    repetitions: int
    entries: tuple[DecodedTriggerProgramEntry, ...]


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


class _DigitizerDspWindowDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_path: tuple[str, ...] = Field(min_length=1)
    demodulator_slot_id: str = Field(min_length=1)
    start_sample: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    demodulation_frequency_hz: float
    semantics_id: Literal["reference_lab.integrated_iq.ssb_midpoint.v1"]
    normalization: Literal["single_sideband_amplitude"]


class _DigitizerProgramEntryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int = Field(gt=0)
    input_component_paths: tuple[tuple[str, ...], ...]
    windows: tuple[_DigitizerDspWindowDocument, ...]


class _DigitizerProgramDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: tuple[_DigitizerProgramEntryDocument, ...] = Field(min_length=1)


class _TriggerProgramEntryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    awg_instrument_ids: tuple[str, ...]
    digitizer_instrument_ids: tuple[str, ...]


class _TriggerProgramDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(min_length=1)
    repetitions: int = Field(gt=0)
    entries: tuple[_TriggerProgramEntryDocument, ...] = Field(min_length=1)


def reference_lab_payload_codecs() -> PayloadCodecRegistry:
    from reference_lab.virtual_lab.capture_payload import (
        VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID,
        virtual_capture_queue_codec,
    )

    return PayloadCodecRegistry(
        {
            DIGITIZER_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.digitizer-program-json",
                version=1,
                media_type="application/json",
                encoder=_encode_digitizer_program,
                decoder=_decode_digitizer_program,
            ),
            TRIGGER_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.trigger-program-json",
                version=1,
                media_type="application/json",
                encoder=_encode_trigger_program,
                decoder=_decode_trigger_program,
            ),
            VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID: virtual_capture_queue_codec(),
            AWG_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.awg-program-json",
                version=1,
                media_type="application/json",
                encoder=_encode_awg_program,
                decoder=_decode_awg_program,
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


def _encode_digitizer_program(value: object) -> bytes:
    document = _DigitizerProgramDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_digitizer_program(content: bytes) -> object:
    document = _DigitizerProgramDocument.model_validate_json(content)
    return DecodedDigitizerProgram(
        entries=tuple(
            DecodedDigitizerProgramEntry(
                sample_count=entry.sample_count,
                input_component_paths=entry.input_component_paths,
                windows=tuple(
                    _decoded_digitizer_window(window) for window in entry.windows
                ),
            )
            for entry in document.entries
        )
    )


def _decoded_digitizer_window(
    window: _DigitizerDspWindowDocument,
) -> DecodedDigitizerDspWindow:
    return DecodedDigitizerDspWindow(
        component_path=window.component_path,
        demodulator_slot_id=window.demodulator_slot_id,
        start_sample=window.start_sample,
        sample_count=window.sample_count,
        demodulation_frequency_hz=window.demodulation_frequency_hz,
        semantics_id=window.semantics_id,
        normalization=window.normalization,
    )


def _encode_trigger_program(value: object) -> bytes:
    document = _TriggerProgramDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_trigger_program(content: bytes) -> object:
    document = _TriggerProgramDocument.model_validate_json(content)
    return DecodedTriggerProgram(
        program_id=document.program_id,
        repetitions=document.repetitions,
        entries=tuple(
            DecodedTriggerProgramEntry(
                awg_instrument_ids=entry.awg_instrument_ids,
                digitizer_instrument_ids=entry.digitizer_instrument_ids,
            )
            for entry in document.entries
        ),
    )


__all__ = [
    "AWG_PROGRAM_SCHEMA_ID",
    "DIGITIZER_PROGRAM_SCHEMA_ID",
    "SAMPLED_WAVEFORM_SCHEMA_ID",
    "TRIGGER_PROGRAM_SCHEMA_ID",
    "DecodedAwgChannelWaveform",
    "DecodedAwgEntry",
    "DecodedAwgProgram",
    "DecodedDigitizerDspWindow",
    "DecodedDigitizerProgram",
    "DecodedDigitizerProgramEntry",
    "DecodedSampledWaveform",
    "DecodedTriggerProgram",
    "DecodedTriggerProgramEntry",
    "reference_lab_payload_codecs",
]
