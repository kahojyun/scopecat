from __future__ import annotations

from typing import cast

import numpy as np
from scopecat.sdk.payloads import PayloadDescriptor

from reference_lab.payloads import (
    AWG_PROGRAM_SCHEMA_ID,
    DecodedAwgProgram,
    reference_lab_payload_codecs,
)
from reference_lab.virtual_lab.capture_payload import (
    VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID,
    DecodedVirtualCaptureQueue,
)


def test_awg_program_codec_keeps_samples_in_float64_binary() -> None:
    samples = np.linspace(-1.0, 1.0, 4096, dtype=np.float64)
    codecs = reference_lab_payload_codecs()

    encoded = codecs.encode(
        AWG_PROGRAM_SCHEMA_ID,
        {
            "entries": [
                {
                    "waveforms": [
                        {
                            "component_path": ["outputs", "ch1"],
                            "samples": samples,
                        }
                    ]
                }
            ]
        },
    )
    decoded = cast(
        "DecodedAwgProgram",
        codecs.decode_content(
            cast("PayloadDescriptor", cast("object", encoded)),
            encoded.content,
        ),
    )

    assert encoded.codec_id == "reference_lab.awg-program-float64"
    assert len(encoded.content) < samples.nbytes + 256
    assert np.shares_memory(decoded.entries[0].waveforms[0].samples, samples) is False
    assert decoded.entries[0].waveforms[0].samples.flags.writeable is False
    np.testing.assert_array_equal(decoded.entries[0].waveforms[0].samples, samples)


def test_virtual_capture_codec_keeps_samples_in_float64_binary() -> None:
    samples = np.linspace(-0.5, 0.5, 4096, dtype=np.float64)
    codecs = reference_lab_payload_codecs()

    encoded = codecs.encode(
        VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID,
        {
            "captures": [
                {
                    "traces": [
                        {
                            "instrument_id": "digitizer",
                            "component_path": ["inputs", "ch1"],
                            "samples": samples,
                        }
                    ]
                }
            ]
        },
    )
    decoded = cast(
        "DecodedVirtualCaptureQueue",
        codecs.decode_content(
            cast("PayloadDescriptor", cast("object", encoded)),
            encoded.content,
        ),
    )

    assert encoded.codec_id == "reference_lab.virtual-capture-queue-float64"
    assert len(encoded.content) < samples.nbytes + 256
    trace = decoded.captures[0].traces[0]
    assert trace.samples.flags.writeable is False
    np.testing.assert_array_equal(trace.samples, samples)
