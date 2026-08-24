"""Measure multi-array structured payload conversion and carrier boundaries."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from collections.abc import Callable
from typing import ClassVar, cast

import numpy as np
from pydantic import BaseModel, ConfigDict

from benchmarks.record import BENCHMARK_RESULT_PREFIX, benchmark_record_header
from scopecat.sdk.attachments import AttachmentBundle
from scopecat.sdk.structured_payloads import (
    FrozenFloat64Vector,
    pydantic_buffer_bundle_value_codec,
)


class _FragmentedPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    id: str
    fragments: tuple[FrozenFloat64Vector, ...]


def _options() -> tuple[int, int, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arrays", type=int, default=300)
    parser.add_argument("--samples", type=int, default=1024)
    parser.add_argument("--iterations", type=int, default=10)
    options = parser.parse_args()
    array_count = cast("int", options.arrays)
    samples = cast("int", options.samples)
    iterations = cast("int", options.iterations)
    if array_count <= 0:
        raise ValueError("array count must be positive")
    if samples <= 0:
        raise ValueError("samples per array must be positive")
    if iterations <= 0:
        raise ValueError("iteration count must be positive")
    return array_count, samples, iterations


def _elapsed_per_iteration(
    operation: Callable[[], object],
    iterations: int,
) -> float:
    started = time.perf_counter()
    for _ in range(iterations):
        operation()
    return (time.perf_counter() - started) / iterations


def _benchmark(
    array_count: int,
    samples: int,
    iterations: int,
) -> dict[str, object]:
    source = _FragmentedPayload(
        id="fragmented-waveforms",
        fragments=tuple(
            np.linspace(index, index + 1, samples, dtype=np.float64)
            for index in range(array_count)
        ),
    )
    codec = pydantic_buffer_bundle_value_codec(_FragmentedPayload)

    bundle = codec.encode(source)
    flat = bundle.to_bytes()
    restored = AttachmentBundle.from_bytes(flat)
    decoded = codec.decode(restored)

    tracemalloc.start()
    encode_seconds = _elapsed_per_iteration(lambda: codec.encode(source), iterations)
    flatten_seconds = _elapsed_per_iteration(bundle.to_bytes, iterations)
    restore_seconds = _elapsed_per_iteration(
        lambda: AttachmentBundle.from_bytes(flat),
        iterations,
    )
    decode_seconds = _elapsed_per_iteration(lambda: codec.decode(restored), iterations)
    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    shared_attachment_count = sum(
        np.shares_memory(
            fragment,
            np.frombuffer(attachment, dtype=np.float64),
        )
        for fragment, attachment in zip(
            decoded.fragments,
            restored.attachments,
            strict=True,
        )
    )
    return {
        **benchmark_record_header(
            case_id="payload-attachments",
            case_version=1,
            kind="micro",
        ),
        "array_count": array_count,
        "samples_per_array": samples,
        "iterations": iterations,
        "attachment_count": len(bundle.attachments),
        "header_bytes": len(bundle.header),
        "attachment_bytes": bundle.attachment_size_bytes,
        "flat_bytes": len(flat),
        "encode_seconds_per_iteration": encode_seconds,
        "flatten_seconds_per_iteration": flatten_seconds,
        "restore_seconds_per_iteration": restore_seconds,
        "decode_seconds_per_iteration": decode_seconds,
        "decoded_immutable_count": sum(
            not fragment.flags.writeable for fragment in decoded.fragments
        ),
        "decoded_shared_attachment_count": shared_attachment_count,
        "retained_bytes": retained_bytes,
        "peak_bytes": peak_bytes,
    }


def main() -> None:
    array_count, samples, iterations = _options()
    print(
        BENCHMARK_RESULT_PREFIX
        + json.dumps(
            _benchmark(array_count, samples, iterations),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
