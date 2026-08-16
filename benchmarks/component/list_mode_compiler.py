"""Measure list-mode compiler stages and retained-memory cache bounds."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from dataclasses import asdict, replace
from typing import cast

from benchmarks.record import BENCHMARK_RESULT_PREFIX, benchmark_record_header
from reference_lab.configuration import bootstrap_config
from reference_lab.provider import ReferenceLabProvider
from reference_lab.targets.list_mode import (
    ListModeCompilationCachePolicy,
    ListModeTargetCompiler,
    configured_list_mode_target,
)
from scopecat import Quantity
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    PulseProgramId,
    QubitId,
    TargetCompileEntryId,
    TargetCompilerId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    DriveSignal,
    Play,
    PulseProgram,
    ReadoutSignal,
    schedule,
)
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.pulses import Sequence as PulseSequence
from scopecat_quantum.targets import TargetCompileEntry, TargetCompileRequest


def _options() -> tuple[int, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=int, default=4)
    parser.add_argument("--repetitions", type=int, default=16)
    options = parser.parse_args()
    entries = cast("int", options.entries)
    repetitions = cast("int", options.repetitions)
    if entries <= 0 or repetitions <= 0:
        raise ValueError("entry and repetition counts must be positive")
    return entries, repetitions


def _scheduled_program():
    q0 = QubitId("q0")
    slot = AcquisitionSlot(
        AcquisitionSlotId("result"),
        AcquisitionKind.INTEGRATED_IQ,
        AcquireSignal(q0),
    )
    return schedule(
        PulseProgram(
            PulseProgramId("benchmark-list-mode"),
            PulseSequence(
                (
                    Play(
                        PulseEventId("drive"),
                        DriveSignal(q0),
                        Constant(Quantity(4, "ns"), Quantity(0.25, "arb")),
                    ),
                    PulseParallel(
                        (
                            Play(
                                PulseEventId("readout"),
                                ReadoutSignal(q0),
                                Constant(
                                    Quantity(8, "ns"),
                                    Quantity(0.4, "arb"),
                                ),
                            ),
                            Acquire(
                                PulseEventId("capture"),
                                AcquireSignal(q0),
                                slot.id,
                                Quantity(8, "ns"),
                            ),
                        )
                    ),
                )
            ),
            acquisition_slots=(slot,),
        )
    )


def _request(*, prefix: str, entry_count: int, repetitions: int):
    scheduled = _scheduled_program()
    return TargetCompileRequest(
        entries=tuple(
            TargetCompileEntry(
                TargetCompileEntryId(f"{prefix}-{ordinal}"),
                scheduled,
            )
            for ordinal in range(entry_count)
        ),
        repetitions=repetitions,
    )


def _benchmark(entry_count: int, repetitions: int) -> dict[str, object]:
    config = bootstrap_config()
    provider = ReferenceLabProvider(seed=7)
    catalog = resolve_instrument_contract_catalog(
        config=config,
        provider_id=provider.provider_id,
        describe=provider.describe,
    )
    target = configured_list_mode_target(config, catalog)
    request = _request(
        prefix="cold",
        entry_count=entry_count,
        repetitions=repetitions,
    )
    compiler = ListModeTargetCompiler(
        TargetCompilerId("benchmark-list-mode-compiler.v1"),
        target,
    )

    tracemalloc.start()
    started = time.perf_counter()
    artifact, cold_trace = compiler.compile_with_trace(request)
    cold_seconds = time.perf_counter() - started
    started = time.perf_counter()
    reused, warm_trace = compiler.compile_with_trace(request)
    warm_seconds = time.perf_counter() - started
    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    artifact_bytes = cold_trace.cache_info.artifact.retained_bytes
    byte_policy = replace(
        ListModeCompilationCachePolicy(),
        artifact_max_bytes=artifact_bytes,
    )
    byte_bounded = ListModeTargetCompiler(
        TargetCompilerId("benchmark-byte-bounded.v1"),
        target,
        cache_policy=byte_policy,
    )
    byte_bounded.compile(request)
    byte_bounded.compile(
        _request(
            prefix="next",
            entry_count=entry_count,
            repetitions=repetitions,
        )
    )

    oversize = ListModeTargetCompiler(
        TargetCompilerId("benchmark-oversize.v1"),
        target,
        cache_policy=replace(
            byte_policy,
            artifact_max_bytes=artifact_bytes - 1,
        ),
    )
    oversize.compile(request)
    oversize.compile(request)

    return {
        **benchmark_record_header(
            case_id="list-mode-compiler",
            case_version=1,
            kind="component",
        ),
        "entry_count": entry_count,
        "repetitions": repetitions,
        "event_count": artifact.physical_footprint.event_count,
        "waveform_bytes": artifact.physical_footprint.waveform_bytes,
        "result_bytes": artifact.physical_footprint.result_bytes,
        "artifact_reused": reused is artifact,
        "cold_seconds": cold_seconds,
        "warm_seconds": warm_seconds,
        "cold_trace": asdict(cold_trace),
        "warm_trace": asdict(warm_trace),
        "byte_bounded_artifact_cache": asdict(byte_bounded.cache_info.artifact),
        "oversize_artifact_cache": asdict(oversize.cache_info.artifact),
        "traced_retained_bytes": retained_bytes,
        "traced_peak_bytes": peak_bytes,
    }


def main() -> None:
    entry_count, repetitions = _options()
    print(
        BENCHMARK_RESULT_PREFIX
        + json.dumps(_benchmark(entry_count, repetitions), sort_keys=True)
    )


if __name__ == "__main__":
    main()
