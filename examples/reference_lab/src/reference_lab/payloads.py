"""Pulse-program payload codec shared by planning and the instrument worker."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry

SAMPLED_WAVEFORM_SCHEMA_ID = "sampled_waveform"


@dataclass(frozen=True, slots=True)
class DecodedSampledWaveform:
    samples: tuple[float, ...]


class _SampledWaveformDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: tuple[float, ...] = Field(min_length=1)


def reference_lab_payload_codecs() -> PayloadCodecRegistry:
    return PayloadCodecRegistry(
        {
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


__all__ = [
    "SAMPLED_WAVEFORM_SCHEMA_ID",
    "DecodedSampledWaveform",
    "reference_lab_payload_codecs",
]
