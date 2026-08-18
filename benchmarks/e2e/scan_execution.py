"""Measure the reference scan across the complete Scopecat execution path.

The benchmark treats time from submission to the first physical trigger as
preparation. It does not require the first point to be a separate hardware
batch. Subsequent compilation, upload, execution, and collection are reported
together as active experiment time because they may overlap in a streaming
implementation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import sqlite3
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Literal, Self, cast

import httpx2
import numpy as np
import psutil
from fastapi.testclient import TestClient
from pydantic import JsonValue

import scopecat as sc
from benchmarks.record import (
    BENCHMARK_RESULT_PREFIX,
    BENCHMARK_RESULT_SCHEMA,
    git_revision,
)
from reference_lab.bench_interfaces import (
    AWG_LOAD_PROGRAM,
    AWG_PROGRAM,
    TRIGGER_LOAD_PROGRAM,
    TRIGGER_PROGRAM,
    TRIGGER_START_PROGRAM,
    TRIGGER_START_PROGRAM_IDEMPOTENT,
)
from reference_lab.compiler import QuantumLabCompiler
from reference_lab.configuration import bootstrap_config
from reference_lab.parameters import QUBITS
from reference_lab.payloads import (
    DecodedAwgProgram,
    DecodedMaterializedAwgProgram,
    DecodedTriggerProgram,
    materialize_awg_program,
    reference_lab_payload_codecs,
)
from reference_lab.provider import ReferenceLabProvider
from reference_lab.quantum_runner import (
    prepare_quantum_hardware,
    quantum_capture,
)
from reference_lab.targets.list_mode import configured_list_mode_target
from reference_lab.virtual_lab.execution import virtual_quantum_runtime
from reference_lab.workflows.drag_beta_calibration import drag_beta_program
from scopecat.api.lab import LabClient
from scopecat.api.run import RunHandle
from scopecat.authoring import ComputeInput
from scopecat.daemon.client import DaemonClient
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverCatalog,
    DriverOperation,
    DriverOutcome,
    DriverPayload,
    DriverReadback,
    DriverState,
    DriverStatePatch,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)
from scopecat.sdk.instruments.backend import InstrumentBackend
from scopecat_quantum import authoring as q
from scopecat_quantum.measurement_computes import (
    BinaryIqProbabilityProducts,
)
from scopecat_server import LocalDaemonRuntime  # noqa: TID251
from scopecat_server.instruments.backend import (  # noqa: TID251
    LocalInstrumentBackendEndpoint,
)
from scopecat_testkit.instrument_host import compose_test_instruments
from scopecat_testkit.server.in_process_lab import in_process_lab  # noqa: TID251

type RunnerName = Literal["adhoc", "scopecat-core", "scopecat"]
type ProfileName = Literal[
    "drag_beta_integrated_iq",
    "multichannel_waveform_integrated_iq",
    "multiqubit_result_retention",
]
type RetentionMode = Literal["discard", "summary", "bit-shots", "iq-and-bits"]
type AcquisitionDspPolicy = Literal["prefer_device", "target"]
_RUNNERS: tuple[RunnerName, ...] = ("adhoc", "scopecat")
_ALL_RUNNERS: tuple[RunnerName, ...] = ("adhoc", "scopecat-core", "scopecat")
_PROFILE_ALIASES: dict[str, ProfileName] = {
    "dense": "drag_beta_integrated_iq",
    "results": "multiqubit_result_retention",
    "waveform": "multichannel_waveform_integrated_iq",
}
_RETENTION_MODES: tuple[RetentionMode, ...] = (
    "discard",
    "summary",
    "bit-shots",
    "iq-and-bits",
)


@dataclass(frozen=True, slots=True)
class BenchmarkArguments:
    points: str
    runners: str
    repetitions: int
    warmups: int
    point_delay_ms: float
    acquisition_dsp_policy: AcquisitionDspPolicy
    live_waveform: bool
    profile: str
    retention: RetentionMode
    shots: int
    waveform_samples: int
    qubit_counts: str | None
    host_label: str
    storage_root: str | None
    output: str
    worker: RunnerName | None
    point_count: int | None
    qubit_count: int | None
    work_dir: str | None


@dataclass(frozen=True, slots=True)
class ScanScenario:
    """One comparable integrated-IQ scan workload."""

    point_count: int
    point_delay_s: float = 0.0
    acquisition_dsp_policy: AcquisitionDspPolicy = "prefer_device"
    live_waveform: bool = False
    profile: ProfileName = "drag_beta_integrated_iq"
    retention: RetentionMode = "summary"
    waveform_sample_count: int = 72
    qubit_count: int = 1
    physical_channel_count: int = 4
    shots: int = 1

    def __post_init__(self) -> None:
        if self.point_count <= 0:
            raise ValueError("point_count must be positive")
        if self.point_delay_s < 0.0:
            raise ValueError("point_delay_s must not be negative")
        if self.waveform_sample_count <= 0:
            raise ValueError("waveform_sample_count must be positive")
        if self.shots <= 0:
            raise ValueError("shots must be positive")
        if self.qubit_count <= 0:
            raise ValueError("qubit_count must be positive")
        if self.profile == "drag_beta_integrated_iq" and (
            self.waveform_sample_count != 72 or self.qubit_count != 1
        ):
            raise ValueError("drag-beta profile has a fixed waveform shape")
        if self.profile != "multiqubit_result_retention" and (
            self.retention != "summary" or self.shots != 1
        ):
            raise ValueError(
                "retention selection and shot scaling require the results profile"
            )
        expected_channels = (
            4
            if self.profile == "drag_beta_integrated_iq"
            else (2 * self.qubit_count + 2)
        )
        if self.physical_channel_count != expected_channels:
            raise ValueError(
                "physical_channel_count does not match the selected profile"
            )


@dataclass(frozen=True, slots=True)
class PhaseMetrics:
    """User-visible experiment timing split at physical trigger and collection."""

    prepare_s: float
    active_s: float
    finalize_s: float
    wall_s: float
    first_result_s: float


@dataclass(frozen=True, slots=True)
class HostMetadata:
    """Machine identity needed to interpret local benchmark results."""

    label: str
    platform: str
    python: str
    logical_cpu_count: int | None
    physical_memory_bytes: int


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """One isolated benchmark worker result."""

    schema: Literal["scopecat.benchmark_result.v1"]
    case_id: Literal["scan-execution"]
    case_version: Literal[7]
    kind: Literal["e2e"]
    revision: str
    runner: RunnerName
    scenario: ScanScenario
    host: HostMetadata
    phases: PhaseMetrics
    starting_rss_bytes: int
    peak_rss_bytes: int
    peak_rss_growth_bytes: int
    points_completed: int
    trigger_count: int
    acquired_result_bytes: int | None
    selected_result_bytes: int
    waveform_bytes_rendered: int | None
    waveform_bytes_uploaded: int | None
    max_waveform_batch_bytes: int | None
    live_waveform_bytes_retained: int | None
    payload_spool_bytes_at_finish: int
    peak_payload_spool_bytes: int
    object_store_bytes: int
    object_store_file_count: int
    measurement_dataset_bytes: int
    control_and_provenance_bytes: int
    durable_bytes: int
    durable_file_count: int


class ExperimentTimeline:
    """Monotonic timestamps shared by a runner and its instrument boundary."""

    def __init__(self) -> None:
        self.started_ns: int | None = None
        self.first_trigger_ns: int | None = None
        self.first_collect_ns: int | None = None
        self.last_collect_ns: int | None = None
        self.finished_ns: int | None = None
        self.trigger_count = 0

    def start(self) -> None:
        self.started_ns = time.perf_counter_ns()

    def trigger(self) -> None:
        now = time.perf_counter_ns()
        if self.first_trigger_ns is None:
            self.first_trigger_ns = now
        self.trigger_count += 1

    def collect(self) -> None:
        if self.first_trigger_ns is None:
            return
        now = time.perf_counter_ns()
        if self.first_collect_ns is None:
            self.first_collect_ns = now
        self.last_collect_ns = now

    def finish(self) -> None:
        self.finished_ns = time.perf_counter_ns()

    def metrics(self) -> PhaseMetrics:
        started = _required_timestamp(self.started_ns, "start")
        triggered = _required_timestamp(self.first_trigger_ns, "first trigger")
        first_collect = _required_timestamp(self.first_collect_ns, "first collect")
        last_collect = _required_timestamp(self.last_collect_ns, "last collect")
        finished = _required_timestamp(self.finished_ns, "finish")
        return PhaseMetrics(
            prepare_s=_seconds(triggered - started),
            active_s=_seconds(last_collect - triggered),
            finalize_s=_seconds(finished - last_collect),
            wall_s=_seconds(finished - started),
            first_result_s=_seconds(first_collect - started),
        )


class PeakRssSampler:
    """Sample process RSS while retaining native NumPy and SQLite allocations."""

    def __init__(self, *, interval_s: float = 0.005) -> None:
        self._process = psutil.Process()
        self._interval_s = interval_s
        self._peak = int(cast("int", self._process.memory_info().rss))
        self._starting = self._peak
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self.observe()

    @property
    def peak_bytes(self) -> int:
        return self._peak

    @property
    def starting_bytes(self) -> int:
        return self._starting

    @property
    def growth_bytes(self) -> int:
        return self._peak - self._starting

    def observe(self) -> None:
        rss = int(cast("int", self._process.memory_info().rss))
        self._peak = max(self._peak, rss)

    def _sample(self) -> None:
        while not self._stop.wait(self._interval_s):
            self.observe()


class LatestWaveformView:
    """Bounded stand-in for the ad hoc latest-point waveform viewer."""

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled
        self._latest: tuple[np.ndarray, ...] = ()

    def replace(self, waveforms: tuple[np.ndarray, ...]) -> None:
        if self._enabled:
            self._latest = waveforms

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def retained_bytes(self) -> int:
        return sum(waveform.nbytes for waveform in self._latest)


class ScopecatWaveformTracker:
    """Observe AWG batch uploads and retain only the latest completed entry."""

    def __init__(self, *, live_waveform: bool) -> None:
        self._view = LatestWaveformView(live_waveform)
        self._programs: dict[str, DecodedMaterializedAwgProgram] = {}
        self.uploaded_bytes = 0
        self._pending_batch_bytes = 0
        self.max_batch_bytes = 0

    def load(self, instrument_id: str, program: DecodedAwgProgram) -> None:
        materialized = materialize_awg_program(program)
        self._programs[instrument_id] = materialized
        uploaded = sum(
            len(waveform.samples) * np.dtype(np.float64).itemsize
            for entry in materialized.entries
            for waveform in entry.waveforms
        )
        self.uploaded_bytes += uploaded
        self._pending_batch_bytes += uploaded

    def start_batch(self) -> None:
        self.max_batch_bytes = max(self.max_batch_bytes, self._pending_batch_bytes)
        self._pending_batch_bytes = 0

    def publish_latest(self) -> None:
        if not self._view.enabled:
            return
        self._view.replace(
            tuple(
                np.array(waveform.samples, dtype=np.float64, copy=True)
                for instrument_id in sorted(self._programs)
                for waveform in self._programs[instrument_id].entries[-1].waveforms
            )
        )

    @property
    def retained_bytes(self) -> int:
        return self._view.retained_bytes


class AdHocResultWriter:
    """Small sequential result writer that never retains historical rows."""

    _row = struct.Struct("<Qd")

    def __init__(self, root: Path, scenario: ScanScenario) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._stream = (root / "measurements.bin").open("wb", buffering=1024 * 1024)
        with (root / "manifest.json").open("w", encoding="utf-8") as manifest:
            manifest.write(json.dumps(asdict(scenario), sort_keys=True))
            manifest.flush()
            os.fsync(manifest.fileno())

    def append(self, point: int, value: float) -> None:
        self._stream.write(self._row.pack(point, value))

    def finish(self) -> None:
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()


@dataclass(frozen=True, slots=True)
class AdHocMultiqubitResults:
    """One point's actual ad hoc IQ, integer bit, and summary arrays."""

    iq_shots: tuple[np.ndarray, ...]
    bit_shots: tuple[np.ndarray, ...]
    probabilities: np.ndarray


class AdHocRetentionWriter:
    """Measure selected durable writes or a synthetic write-free lower bound."""

    def __init__(self, root: Path, scenario: ScanScenario) -> None:
        self._root = root
        self._scenario = scenario
        self._summary_stream = None
        root.mkdir(parents=True, exist_ok=True)
        if scenario.retention == "discard":
            return
        with (root / "manifest.json").open("w", encoding="utf-8") as manifest:
            manifest.write(json.dumps(asdict(scenario), sort_keys=True))
            manifest.flush()
            os.fsync(manifest.fileno())
        if scenario.retention == "summary":
            self._summary_stream = (root / "measurements.bin").open(
                "wb",
                buffering=1024 * 1024,
            )

    def append(self, point: int, results: AdHocMultiqubitResults) -> None:
        if self._scenario.retention == "discard":
            return
        if self._scenario.retention == "summary":
            assert self._summary_stream is not None
            self._summary_stream.write(struct.pack("<Q", point))
            self._summary_stream.write(
                np.asarray(results.probabilities, dtype="<f8").tobytes()
            )
            return
        bit_arrays = {
            f"q{index}_shots": values for index, values in enumerate(results.bit_shots)
        }
        payload = bit_arrays
        if self._scenario.retention == "iq-and-bits":
            payload = {
                **{
                    f"q{index}_iq_shots": values
                    for index, values in enumerate(results.iq_shots)
                },
                **bit_arrays,
            }
        save_npz = cast("Callable[..., None]", np.savez)
        save_npz(self._root / f"{point:08d}", **payload)

    def finish(self) -> None:
        if self._summary_stream is None:
            return
        self._summary_stream.flush()
        os.fsync(self._summary_stream.fileno())
        self._summary_stream.close()


class AdHocHardware:
    """Current-point-only device facade modeled after the sample scan Runner."""

    def __init__(self, scenario: ScanScenario, timeline: ExperimentTimeline) -> None:
        self._scenario = scenario
        self._timeline = timeline
        self._loaded: tuple[np.ndarray, ...] = ()
        self.uploaded_bytes = 0

    def load(self, waveforms: tuple[np.ndarray, ...]) -> None:
        self._loaded = waveforms
        self.uploaded_bytes += sum(waveform.nbytes for waveform in waveforms)

    def run_and_collect(self, point: int) -> float:
        if not self._loaded:
            raise RuntimeError("no current-point waveform is loaded")
        self._timeline.trigger()
        if self._scenario.point_delay_s:
            time.sleep(self._scenario.point_delay_s)
        value = (math.sin(point * 0.013) + 1.0) / 2.0
        self._timeline.collect()
        return value

    def run_and_collect_multiqubit(self, point: int) -> AdHocMultiqubitResults:
        if not self._loaded:
            raise RuntimeError("no current-point waveform is loaded")
        self._timeline.trigger()
        if self._scenario.point_delay_s:
            time.sleep(self._scenario.point_delay_s)
        shot_phase = (
            math.tau
            * (np.arange(self._scenario.shots, dtype=np.float64) + 0.5)
            / self._scenario.shots
        )
        point_phase = math.tau * point / max(self._scenario.point_count, 1)
        iq_shots = tuple(
            np.ascontiguousarray(
                np.exp(1j * (shot_phase + point_phase + qubit * math.pi / 7.0)),
                dtype=np.complex128,
            )
            for qubit in range(self._scenario.qubit_count)
        )
        bit_shots = tuple(
            np.asarray(values.real >= 0.0, dtype=np.int64) for values in iq_shots
        )
        probabilities = np.asarray(
            [np.count_nonzero(values) / len(values) for values in bit_shots],
            dtype=np.float64,
        )
        self._timeline.collect()
        return AdHocMultiqubitResults(
            iq_shots=iq_shots,
            bit_shots=bit_shots,
            probabilities=probabilities,
        )


def run_ad_hoc(
    scenario: ScanScenario,
    root: Path,
    *,
    host_label: str = "local",
) -> BenchmarkResult:
    """Run the direct point-local baseline without full-run materialization."""

    timeline = ExperimentTimeline()
    view = LatestWaveformView(scenario.live_waveform)
    waveform_bytes = 0
    max_waveform_batch_bytes = 0
    timeline.start()
    with PeakRssSampler() as memory:
        hardware = AdHocHardware(scenario, timeline)
        writer = (
            AdHocRetentionWriter(root, scenario)
            if scenario.profile == "multiqubit_result_retention"
            else AdHocResultWriter(root, scenario)
        )
        for point in range(scenario.point_count):
            waveforms = _render_ad_hoc_point(scenario, point)
            point_waveform_bytes = sum(waveform.nbytes for waveform in waveforms)
            waveform_bytes += point_waveform_bytes
            max_waveform_batch_bytes = max(
                max_waveform_batch_bytes,
                point_waveform_bytes,
            )
            hardware.load(waveforms)
            view.replace(waveforms)
            if isinstance(writer, AdHocRetentionWriter):
                writer.append(point, hardware.run_and_collect_multiqubit(point))
            else:
                writer.append(point, hardware.run_and_collect(point))
        writer.finish()
        timeline.finish()
        memory.observe()
    durable_bytes, durable_files = _tree_size(root)
    measurement_dataset_bytes = _ad_hoc_measurement_bytes(root)
    return BenchmarkResult(
        schema=BENCHMARK_RESULT_SCHEMA,
        case_id="scan-execution",
        case_version=7,
        kind="e2e",
        revision=git_revision(),
        runner="adhoc",
        scenario=scenario,
        host=_host_metadata(host_label),
        phases=timeline.metrics(),
        starting_rss_bytes=memory.starting_bytes,
        peak_rss_bytes=memory.peak_bytes,
        peak_rss_growth_bytes=memory.growth_bytes,
        points_completed=scenario.point_count,
        trigger_count=timeline.trigger_count,
        acquired_result_bytes=_acquired_result_bytes(scenario),
        selected_result_bytes=_selected_result_bytes(scenario),
        waveform_bytes_rendered=waveform_bytes,
        waveform_bytes_uploaded=hardware.uploaded_bytes,
        max_waveform_batch_bytes=max_waveform_batch_bytes,
        live_waveform_bytes_retained=view.retained_bytes,
        payload_spool_bytes_at_finish=0,
        peak_payload_spool_bytes=0,
        object_store_bytes=0,
        object_store_file_count=0,
        measurement_dataset_bytes=measurement_dataset_bytes,
        control_and_provenance_bytes=durable_bytes - measurement_dataset_bytes,
        durable_bytes=durable_bytes,
        durable_file_count=durable_files,
    )


def run_scopecat_core(
    scenario: ScanScenario,
    root: Path,
    *,
    host_label: str = "local",
) -> BenchmarkResult:
    """Run through core planning and persistence with a direct test host."""

    timeline = ExperimentTimeline()
    waveforms = ScopecatWaveformTracker(live_waveform=scenario.live_waveform)
    config = _benchmark_config(scenario)
    reference_provider = ReferenceLabProvider(seed=7)
    provider = TimedInstrumentProvider(
        reference_provider,
        timeline,
        waveforms=waveforms,
        point_delay_s=scenario.point_delay_s,
    )
    catalog = resolve_instrument_contract_catalog(
        config=config,
        provider_id=provider.provider_id,
        describe=provider.describe,
    )
    target = configured_list_mode_target(config, catalog)
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        domain_compiler=QuantumLabCompiler(
            target=target,
            runtime_selector=virtual_quantum_runtime,
        ),
        payload_codecs=reference_lab_payload_codecs(),
    )
    lab = in_process_lab(
        root,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )
    timeline.start()
    with PeakRssSampler() as memory:
        invocation = _scopecat_invocation(scenario)
        run = lab.prepare(invocation).run()
        timeline.finish()
        memory.observe()
    if run.status != "completed":
        raise RuntimeError(f"Scopecat run ended as {run.status}")
    points_completed = _completed_point_count(run, scenario)
    durable_bytes, durable_files = _tree_size(root)
    object_store_bytes, object_store_files = _tree_size(
        root / ".scopecat-test" / "objects"
    )
    measurement_dataset_bytes = _scopecat_measurement_bytes(root / ".scopecat-test")
    return BenchmarkResult(
        schema=BENCHMARK_RESULT_SCHEMA,
        case_id="scan-execution",
        case_version=7,
        kind="e2e",
        revision=git_revision(),
        runner="scopecat-core",
        scenario=scenario,
        host=_host_metadata(host_label),
        phases=timeline.metrics(),
        starting_rss_bytes=memory.starting_bytes,
        peak_rss_bytes=memory.peak_bytes,
        peak_rss_growth_bytes=memory.growth_bytes,
        points_completed=points_completed,
        trigger_count=timeline.trigger_count,
        acquired_result_bytes=_acquired_result_bytes(scenario),
        selected_result_bytes=_selected_result_bytes(scenario),
        waveform_bytes_rendered=waveforms.uploaded_bytes,
        waveform_bytes_uploaded=waveforms.uploaded_bytes,
        max_waveform_batch_bytes=waveforms.max_batch_bytes,
        live_waveform_bytes_retained=waveforms.retained_bytes,
        payload_spool_bytes_at_finish=0,
        peak_payload_spool_bytes=0,
        object_store_bytes=object_store_bytes,
        object_store_file_count=object_store_files,
        measurement_dataset_bytes=measurement_dataset_bytes,
        control_and_provenance_bytes=durable_bytes - measurement_dataset_bytes,
        durable_bytes=durable_bytes,
        durable_file_count=durable_files,
    )


def run_scopecat(
    scenario: ScanScenario,
    root: Path,
    *,
    host_label: str = "local",
) -> BenchmarkResult:
    """Run through the production daemon, payload store, and instrument service."""

    timeline = ExperimentTimeline()
    waveforms = ScopecatWaveformTracker(live_waveform=scenario.live_waveform)
    config = _benchmark_config(scenario)
    reference_provider = ReferenceLabProvider(seed=7)
    provider = TimedInstrumentProvider(
        reference_provider,
        timeline,
        waveforms=waveforms,
        point_delay_s=scenario.point_delay_s,
    )
    backend = InstrumentBackend(
        provider=provider,
        driver_catalog=DriverCatalog(provider_id=provider.provider_id),
        payload_codecs=reference_lab_payload_codecs(),
    )

    def build_system(
        selected_config: ConfigProfileSnapshot,
        catalog: InstrumentContractCatalog,
    ) -> ExperimentSystem:
        target = configured_list_mode_target(selected_config, catalog)
        return ExperimentSystem(
            instrument_catalog=catalog,
            domain_compiler=QuantumLabCompiler(
                target=target,
                runtime_selector=virtual_quantum_runtime,
            ),
            payload_codecs=reference_lab_payload_codecs(),
        )

    with (
        LocalDaemonRuntime(
            root,
            bootstrap_config=config,
            instrument_endpoint=LocalInstrumentBackendEndpoint(backend),
        ) as runtime,
        TestClient(runtime.app()) as transport,
        LabClient(
            _daemon_client(transport),
            build_experiment_system=build_system,
            config=config,
            operator="benchmark",
        ) as lab,
    ):
        timeline.start()
        with PeakRssSampler() as memory:
            invocation = _scopecat_invocation(scenario)
            run = lab.prepare(invocation, config=config).run()
            timeline.finish()
            memory.observe()
        if run.status != "completed":
            raise RuntimeError(f"Scopecat run ended as {run.status}")
        points_completed = _completed_point_count(run, scenario)
        payload_spool_bytes = runtime.application.payloads.spooled_size_bytes()
        peak_payload_spool_bytes = (
            runtime.application.payloads.peak_spooled_size_bytes()
        )
    durable_bytes, durable_files = _tree_size(root)
    object_store_bytes, object_store_files = _tree_size(root / ".scopecat" / "objects")
    measurement_dataset_bytes = _scopecat_measurement_bytes(root / ".scopecat")
    return BenchmarkResult(
        schema=BENCHMARK_RESULT_SCHEMA,
        case_id="scan-execution",
        case_version=7,
        kind="e2e",
        revision=git_revision(),
        runner="scopecat",
        scenario=scenario,
        host=_host_metadata(host_label),
        phases=timeline.metrics(),
        starting_rss_bytes=memory.starting_bytes,
        peak_rss_bytes=memory.peak_bytes,
        peak_rss_growth_bytes=memory.growth_bytes,
        points_completed=points_completed,
        trigger_count=timeline.trigger_count,
        acquired_result_bytes=_acquired_result_bytes(scenario),
        selected_result_bytes=_selected_result_bytes(scenario),
        waveform_bytes_rendered=waveforms.uploaded_bytes,
        waveform_bytes_uploaded=waveforms.uploaded_bytes,
        max_waveform_batch_bytes=waveforms.max_batch_bytes,
        live_waveform_bytes_retained=waveforms.retained_bytes,
        payload_spool_bytes_at_finish=payload_spool_bytes,
        peak_payload_spool_bytes=peak_payload_spool_bytes,
        object_store_bytes=object_store_bytes,
        object_store_file_count=object_store_files,
        measurement_dataset_bytes=measurement_dataset_bytes,
        control_and_provenance_bytes=durable_bytes - measurement_dataset_bytes,
        durable_bytes=durable_bytes,
        durable_file_count=durable_files,
    )


def _daemon_client(transport: TestClient) -> DaemonClient:
    def send(request: httpx2.Request) -> httpx2.Response:
        response = transport.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx2.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )

    return DaemonClient(
        "http://testserver",
        transport=httpx2.MockTransport(send),
    )


def _benchmark_config(scenario: ScanScenario) -> ConfigProfileSnapshot:
    config = bootstrap_config()
    target = config.domain_target
    assert target is not None
    configuration = target.configuration.copy()
    capabilities = cast(
        "dict[str, JsonValue]",
        configuration["capabilities"],
    ).copy()
    capabilities["acquisition_dsp_policy"] = scenario.acquisition_dsp_policy
    configuration["capabilities"] = capabilities
    return config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "domain_target": target.model_copy(
                        update={"configuration": configuration}
                    )
                }
            )
        }
    )


class TimedInstrumentProvider:
    """Observe physical trigger and collection without changing driver behavior."""

    def __init__(
        self,
        delegate: ReferenceLabProvider,
        timeline: ExperimentTimeline,
        *,
        waveforms: ScopecatWaveformTracker,
        point_delay_s: float,
    ) -> None:
        self._delegate = delegate
        self._timeline = timeline
        self._waveforms = waveforms
        self._point_delay_s = point_delay_s

    @property
    def provider_id(self) -> str:
        return self._delegate.provider_id

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return self._delegate.describe(context)

    def connect(self, context: InstrumentConnectionContext) -> InstrumentDriver:
        return TimedInstrumentDriver(
            self._delegate.connect(context),
            self._timeline,
            waveforms=self._waveforms,
            point_delay_s=self._point_delay_s,
        )


class TimedInstrumentDriver:
    """Delegate driver calls while timestamping trigger and completed reads."""

    def __init__(
        self,
        delegate: InstrumentDriver,
        timeline: ExperimentTimeline,
        *,
        waveforms: ScopecatWaveformTracker,
        point_delay_s: float,
    ) -> None:
        self._delegate = delegate
        self._timeline = timeline
        self._waveforms = waveforms
        self._point_delay_s = point_delay_s
        self._loaded_point_count = 0
        self.implementation_id = delegate.implementation_id
        self.implementation_version = delegate.implementation_version

    @property
    def instrument_id(self) -> str:
        return self._delegate.instrument_id

    def describe(self) -> InstrumentDescription:
        return self._delegate.describe()

    def read_state(self) -> DriverState:
        return self._delegate.read_state()

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        return self._delegate.apply_state(request)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        if (
            request.target.interface_id == AWG_LOAD_PROGRAM.interface_id
            and request.target.operation_id == AWG_LOAD_PROGRAM.operation_id
        ):
            program = cast(
                "DecodedAwgProgram",
                cast(
                    "DriverPayload",
                    request.arguments[AWG_PROGRAM.argument_id],
                ).value,
            )
            self._waveforms.load(self.instrument_id, program)
        if (
            request.target.interface_id == TRIGGER_LOAD_PROGRAM.interface_id
            and request.target.operation_id == TRIGGER_LOAD_PROGRAM.operation_id
        ):
            program = cast(
                "DecodedTriggerProgram",
                cast(
                    "DriverPayload",
                    request.arguments[TRIGGER_PROGRAM.argument_id],
                ).value,
            )
            self._loaded_point_count = len(program.entries) * program.repetitions
        if (
            request.target.interface_id == TRIGGER_START_PROGRAM.interface_id
            and request.target.operation_id
            in {
                TRIGGER_START_PROGRAM.operation_id,
                TRIGGER_START_PROGRAM_IDEMPOTENT.operation_id,
            }
        ):
            self._waveforms.start_batch()
            self._timeline.trigger()
            outcome = self._delegate.invoke(request)
            if self._point_delay_s:
                time.sleep(self._loaded_point_count * self._point_delay_s)
            return outcome
        return self._delegate.invoke(request)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        outcome = self._delegate.collect(request)
        self._waveforms.publish_latest()
        self._timeline.collect()
        return outcome

    def disconnect(self) -> None:
        self._delegate.disconnect()

    def abort(self) -> None:
        self._delegate.abort()


@q.program(id="benchmark.multichannel-waveform")
def _multichannel_waveform_program(
    targets: q.QubitSet,
    readout_qubit: q.Qubit,
    *,
    duration: Annotated[
        sc.Quantity,
        sc.ScalarType(sc.QuantityType(unit="ns")),
    ],
    phase: Annotated[
        sc.Quantity,
        sc.ScalarType(sc.QuantityType(unit="rad")),
    ],
) -> q.QuantumFragment:
    return q.parallel(
        q.parallel_each(
            targets,
            lambda qubit: q.play(
                q.drive(qubit),
                q.constant(
                    duration=duration,
                    amplitude=sc.Quantity(0.2, "arb"),
                    phase=phase,
                ),
            ),
        ),
        q.play(
            q.readout(readout_qubit),
            q.constant(
                duration=duration,
                amplitude=sc.Quantity(0.25, "arb"),
            ),
        ),
        q.acquire(
            readout_qubit,
            duration=duration,
            result="iq_shots",
        ),
    )


def _multichannel_waveform_call(
    qubit_count: int,
    *,
    duration: sc.Quantity,
    phase: ComputeInput,
) -> q.QuantumProgramCall:
    return _multichannel_waveform_program(
        targets=q.select_qubits(qubit_count),
        readout_qubit="q0",
        duration=duration,
        phase=phase,
    )


@q.program(id="benchmark.multiqubit-results")
def _multiqubit_result_program(
    targets: q.QubitSet,
    *,
    duration: Annotated[
        sc.Quantity,
        sc.ScalarType(sc.QuantityType(unit="ns")),
    ],
    phase: Annotated[
        sc.Quantity,
        sc.ScalarType(sc.QuantityType(unit="rad")),
    ],
) -> q.QuantumFragment:
    def branch(qubit: q.Qubit) -> q.QuantumFragment:
        return q.parallel(
            q.play(
                q.drive(qubit),
                q.constant(
                    duration=duration,
                    amplitude=sc.Quantity(0.2, "arb"),
                    phase=phase,
                ),
            ),
            q.play(
                q.readout(qubit),
                q.constant(
                    duration=duration,
                    amplitude=sc.Quantity(0.05, "arb"),
                ),
            ),
            q.acquire(
                qubit,
                duration=duration,
                result="iq_shots",
            ),
        )

    return q.parallel_each(targets, branch)


def _multiqubit_result_call(
    qubit_count: int,
    *,
    duration: sc.Quantity,
    phase: ComputeInput,
) -> q.QuantumProgramCall:
    return _multiqubit_result_program(
        targets=q.select_qubits(qubit_count),
        duration=duration,
        phase=phase,
    )


def _classify_iq_shots(*, iq_shots: object) -> np.ndarray:
    values = np.asarray(iq_shots, dtype=np.complex128)
    return np.asarray(values.real >= 0.0, dtype=np.bool_)


def _summarize_iq_shots(*, iq_shots: object) -> np.ndarray:
    values = np.asarray(iq_shots, dtype=np.complex128)
    if values.ndim != 2:
        raise ValueError("multiqubit IQ summary requires [entity, shot] values")
    return np.asarray(np.mean(values.real >= 0.0, axis=1), dtype=np.float64)


def _select_multiqubit_results(
    experiment: sc.ExperimentContext,
    call: q.QuantumProgramCall,
    scenario: ScanScenario,
) -> None:
    prepare_quantum_hardware(experiment)
    results = experiment.use(
        call.with_shots(scenario.shots).with_compiler_inputs(qubits=QUBITS.ref)
    )
    if scenario.retention == "discard":
        return
    iq_shots = results.iq_shots
    entity_dimension = sc.ArrayDimension("entity", scenario.qubit_count)
    if scenario.retention == "summary":
        probabilities = experiment.compute(
            "entity-probabilities",
            fn=_summarize_iq_shots,
            inputs={"iq_shots": iq_shots},
            axes_from=iq_shots,
            output_type=sc.ArrayType(
                dtype="float64",
                unit="ratio",
                dimensions=(entity_dimension,),
            ),
        )
        experiment.alias(probabilities, record_id="probability_1")
        return
    bit_shots = experiment.compute(
        "entity-bit-shots",
        fn=_classify_iq_shots,
        inputs={"iq_shots": iq_shots},
        axes_from=iq_shots,
        output_type=sc.ArrayType(
            dtype="bool",
            dimensions=(
                entity_dimension,
                sc.ArrayDimension("shot", scenario.shots),
            ),
        ),
    )
    experiment.alias(bit_shots, record_id="bit_shots")
    if scenario.retention == "iq-and-bits":
        experiment.alias(iq_shots, record_id="iq_shots")


def _scopecat_invocation(scenario: ScanScenario) -> sc.ExperimentInvocation:
    unit = "ns" if scenario.profile == "drag_beta_integrated_iq" else "rad"
    start = sc.Quantity(
        -0.5 if scenario.profile == "drag_beta_integrated_iq" else 0.0,
        unit,
    )
    stop = sc.Quantity(
        1.5 if scenario.profile == "drag_beta_integrated_iq" else math.tau,
        unit,
    )

    @sc.experiment(id="benchmark.quantum_scan")
    def benchmark_scan(experiment: sc.ExperimentContext) -> None:
        scan_value = (
            experiment.scan("scan_value", (start,))
            if scenario.point_count == 1
            else experiment.scan(
                "scan_value",
                start=start,
                stop=stop,
                points=scenario.point_count,
            )
        )
        if scenario.profile == "drag_beta_integrated_iq":
            call = drag_beta_program(
                qubit="q0",
                amplification=1,
                beta=scan_value,
            )
        elif scenario.profile == "multiqubit_result_retention":
            call = _multiqubit_result_call(
                scenario.qubit_count,
                duration=sc.Quantity(scenario.waveform_sample_count, "ns"),
                phase=scan_value,
            )
        else:
            call = _multichannel_waveform_call(
                scenario.qubit_count,
                duration=sc.Quantity(scenario.waveform_sample_count, "ns"),
                phase=scan_value,
            )
        if scenario.profile == "multiqubit_result_retention":
            _select_multiqubit_results(experiment, call, scenario)
            return
        probabilities: BinaryIqProbabilityProducts = experiment.use(
            quantum_capture(call.with_shots(scenario.shots))
        )
        experiment.alias(probabilities.probability_1)

    return benchmark_scan()


def _render_ad_hoc_point(
    scenario: ScanScenario,
    point: int,
) -> tuple[np.ndarray, ...]:
    sample_count = scenario.waveform_sample_count
    sample = np.arange(sample_count, dtype=np.float64) + 0.5
    phase = math.tau * point / max(scenario.point_count, 1)
    carrier = math.tau * sample / sample_count + phase
    if scenario.profile == "multichannel_waveform_integrated_iq":
        drive_lanes = tuple(
            lane
            for qubit_index in range(scenario.qubit_count)
            for lane in (
                np.ascontiguousarray(
                    0.2 * np.cos(carrier + qubit_index * math.pi / 8.0)
                ),
                np.ascontiguousarray(
                    0.2 * np.sin(carrier + qubit_index * math.pi / 8.0)
                ),
            )
        )
        return (
            *drive_lanes,
            np.full(sample_count, 0.25, dtype=np.float64),
            np.zeros(sample_count, dtype=np.float64),
        )
    envelope = np.exp(
        -((sample - sample_count / 2.0) ** 2) / (2.0 * (sample_count / 8.0) ** 2)
    )
    base = (0.2 * envelope * np.exp(1j * carrier)).astype(np.complex128)
    lanes = (
        np.ascontiguousarray(base.real),
        np.ascontiguousarray(base.imag),
        np.full(sample_count, 0.25, dtype=np.float64),
        np.zeros(sample_count, dtype=np.float64),
    )
    if scenario.physical_channel_count <= len(lanes):
        return lanes[: scenario.physical_channel_count]
    return (
        *lanes,
        *tuple(
            np.zeros(sample_count, dtype=np.float64)
            for _ in range(scenario.physical_channel_count - len(lanes))
        ),
    )


def _worker(args: BenchmarkArguments) -> int:
    runner = cast("RunnerName", args.worker)
    _validate_runner_compatibility(
        acquisition_dsp_policy=args.acquisition_dsp_policy,
        runners=(runner,),
    )
    if args.retention == "discard" and runner != "adhoc":
        raise ValueError(
            "Scopecat cannot yet demand acquisition results without retaining "
            "a dataset; run the discard lower bound with --runners adhoc"
        )
    profile = _PROFILE_ALIASES[args.profile]
    qubit_count = cast("int", args.qubit_count)
    waveform_sample_count = (
        72 if profile == "drag_beta_integrated_iq" else args.waveform_samples
    )
    scenario = ScanScenario(
        point_count=cast("int", args.point_count),
        point_delay_s=args.point_delay_ms / 1000.0,
        acquisition_dsp_policy=args.acquisition_dsp_policy,
        live_waveform=args.live_waveform,
        profile=profile,
        retention=args.retention,
        waveform_sample_count=waveform_sample_count,
        qubit_count=qubit_count,
        physical_channel_count=(
            4 if profile == "drag_beta_integrated_iq" else 2 * qubit_count + 2
        ),
        shots=args.shots,
    )
    root = Path(cast("str", args.work_dir))
    if runner == "adhoc":
        result = run_ad_hoc(scenario, root, host_label=args.host_label)
    elif runner == "scopecat-core":
        result = run_scopecat_core(scenario, root, host_label=args.host_label)
    else:
        result = run_scopecat(scenario, root, host_label=args.host_label)
    print(
        BENCHMARK_RESULT_PREFIX + json.dumps(asdict(result), sort_keys=True),
        flush=True,
    )
    return 0


def _controller(args: BenchmarkArguments) -> int:
    point_counts = _positive_ints(args.points)
    profile = _PROFILE_ALIASES[args.profile]
    qubit_counts = _selected_qubit_counts(args.qubit_counts, profile=profile)
    runners: tuple[RunnerName, ...] = tuple(
        cast("RunnerName", item) for item in args.runners.split(",")
    )
    invalid = sorted(set(runners) - set(_ALL_RUNNERS))
    if invalid:
        raise ValueError(f"unknown runners: {', '.join(invalid)}")
    _validate_runner_compatibility(
        acquisition_dsp_policy=args.acquisition_dsp_policy,
        runners=runners,
    )
    if args.retention == "discard" and any(runner != "adhoc" for runner in runners):
        raise ValueError(
            "Scopecat cannot yet demand acquisition results without retaining "
            "a dataset; run the discard lower bound with --runners adhoc"
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(
        prefix="scopecat-scan-benchmark-",
        dir=args.storage_root,
    ) as selected:
        temporary_root = Path(selected)
        jobs: tuple[tuple[RunnerName, int, int, int, bool], ...] = tuple(
            (
                runner,
                point_count,
                qubit_count,
                repetition,
                repetition < args.warmups,
            )
            for point_count in point_counts
            for qubit_count in qubit_counts
            for runner in runners
            for repetition in range(args.warmups + args.repetitions)
        )
        for index, (
            runner,
            point_count,
            qubit_count,
            repetition,
            warmup,
        ) in enumerate(jobs):
            work_dir = temporary_root / (
                f"{index}-{runner}-p{point_count}-q{qubit_count}-r{repetition}"
            )
            result = _run_worker_process(
                runner=runner,
                point_count=point_count,
                qubit_count=qubit_count,
                args=args,
                work_dir=work_dir,
            )
            shutil.rmtree(work_dir)
            if warmup:
                continue
            result["repetition"] = repetition - args.warmups
            results.append(result)
            print(
                BENCHMARK_RESULT_PREFIX + json.dumps(result, sort_keys=True),
                flush=True,
            )
            print(
                f"{runner:8} points={point_count:<7} "
                f"qubits={qubit_count:<4} "
                f"dsp={_scenario_str(result, 'acquisition_dsp_policy'):<13} "
                f"retention={_scenario_str(result, 'retention'):<11} "
                f"shots={_scenario_int(result, 'shots'):<7} "
                f"samples={_scenario_int(result, 'waveform_sample_count'):<7} "
                f"channels={_scenario_int(result, 'physical_channel_count'):<2} "
                f"prepare={_nested_float(result, 'phases', 'prepare_s'):.6f}s "
                f"wall={_nested_float(result, 'phases', 'wall_s'):.6f}s "
                f"rss+={cast('int', result['peak_rss_growth_bytes']) / 2**20:.1f} MiB "
                f"durable={cast('int', result['durable_bytes']) / 2**20:.2f} MiB",
                flush=True,
            )

    with output.open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(_summaries(results), indent=2, sort_keys=True))
    print(f"raw results: {output}")
    return 0


def _run_worker_process(
    *,
    runner: RunnerName,
    point_count: int,
    qubit_count: int,
    args: BenchmarkArguments,
    work_dir: Path,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "benchmarks",
        "run",
        "scan-execution",
        "--worker",
        runner,
        "--point-count",
        str(point_count),
        "--qubit-count",
        str(qubit_count),
        "--point-delay-ms",
        str(args.point_delay_ms),
        "--acquisition-dsp",
        args.acquisition_dsp_policy,
        "--profile",
        args.profile,
        "--retention",
        args.retention,
        "--shots",
        str(args.shots),
        "--waveform-samples",
        str(args.waveform_samples),
        "--host-label",
        args.host_label,
        "--work-dir",
        str(work_dir),
    ]
    if args.live_waveform:
        command.append("--live-waveform")
    completed = subprocess.run(  # noqa: S603
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"worker failed with exit code {completed.returncode}:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(BENCHMARK_RESULT_PREFIX):
            return cast(
                "dict[str, object]",
                json.loads(line.removeprefix(BENCHMARK_RESULT_PREFIX)),
            )
    raise RuntimeError(
        f"worker returned no result:\n{completed.stdout}\n{completed.stderr}"
    )


def _summaries(results: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    keys = sorted(
        {
            (cast("str", result["runner"]), *_scenario_signature(result))
            for result in results
        }
    )
    summaries: list[dict[str, object]] = []
    for runner, *signature in keys:
        selected = tuple(
            result
            for result in results
            if result["runner"] == runner
            and _scenario_signature(result) == tuple(signature)
        )
        (
            profile,
            acquisition_dsp_policy,
            retention,
            point_count,
            qubit_count,
            shots,
            sample_count,
            channel_count,
        ) = signature
        summaries.append(
            {
                "runner": runner,
                "profile": profile,
                "acquisition_dsp_policy": acquisition_dsp_policy,
                "retention": retention,
                "point_count": point_count,
                "qubit_count": qubit_count,
                "shots": shots,
                "waveform_sample_count": sample_count,
                "physical_channel_count": channel_count,
                "median_prepare_s": statistics.median(
                    _nested_float(result, "phases", "prepare_s") for result in selected
                ),
                "median_wall_s": statistics.median(
                    _nested_float(result, "phases", "wall_s") for result in selected
                ),
                "median_peak_rss_bytes": statistics.median(
                    cast("int", result["peak_rss_bytes"]) for result in selected
                ),
                "median_peak_rss_growth_bytes": statistics.median(
                    cast("int", result["peak_rss_growth_bytes"]) for result in selected
                ),
                "median_selected_result_bytes": statistics.median(
                    cast("int", result["selected_result_bytes"]) for result in selected
                ),
                "median_measurement_dataset_bytes": statistics.median(
                    cast("int", result["measurement_dataset_bytes"])
                    for result in selected
                ),
                "median_control_and_provenance_bytes": statistics.median(
                    cast("int", result["control_and_provenance_bytes"])
                    for result in selected
                ),
                "median_durable_bytes": statistics.median(
                    cast("int", result["durable_bytes"]) for result in selected
                ),
                "median_object_store_bytes": statistics.median(
                    cast("int", result["object_store_bytes"]) for result in selected
                ),
            }
        )
    return summaries


def _scenario_signature(
    result: dict[str, object],
) -> tuple[str, str, str, int, int, int, int, int]:
    scenario = cast("dict[str, object]", result["scenario"])
    return (
        cast("str", scenario["profile"]),
        cast("str", scenario["acquisition_dsp_policy"]),
        cast("str", scenario["retention"]),
        cast("int", scenario["point_count"]),
        cast("int", scenario["qubit_count"]),
        cast("int", scenario["shots"]),
        cast("int", scenario["waveform_sample_count"]),
        cast("int", scenario["physical_channel_count"]),
    )


def _scenario_int(result: dict[str, object], key: str) -> int:
    scenario = cast("dict[str, object]", result["scenario"])
    return cast("int", scenario[key])


def _scenario_str(result: dict[str, object], key: str) -> str:
    scenario = cast("dict[str, object]", result["scenario"])
    return cast("str", scenario[key])


def _nested_float(result: dict[str, object], group: str, key: str) -> float:
    selected = cast("dict[str, object]", result[group])
    return float(cast("float", selected[key]))


def _positive_ints(value: str, *, label: str = "point counts") -> tuple[int, ...]:
    selected = tuple(int(item) for item in value.split(","))
    if not selected or any(item <= 0 for item in selected):
        raise ValueError(f"{label} must be positive")
    return selected


def _selected_qubit_counts(
    value: str | None,
    *,
    profile: ProfileName,
) -> tuple[int, ...]:
    if profile == "drag_beta_integrated_iq":
        if value is not None and value != "1":
            raise ValueError("the dense profile requires exactly one qubit")
        return (1,)
    available = sum(
        entity.kind == "logical_qubit"
        for entity in bootstrap_config().system.topology.entities
    )
    if available <= 0:
        raise ValueError("the benchmark configuration has no logical qubits")
    if value is None:
        return (available,)
    if value == "all":
        return tuple(range(1, available + 1))
    selected = _positive_ints(value, label="qubit counts")
    if len(set(selected)) != len(selected):
        raise ValueError("qubit counts must be unique")
    if any(count > available for count in selected):
        raise ValueError(
            f"qubit counts exceed the configured {available}-qubit topology"
        )
    return selected


def _validate_runner_compatibility(
    *,
    acquisition_dsp_policy: AcquisitionDspPolicy,
    runners: Sequence[RunnerName],
) -> None:
    if acquisition_dsp_policy == "target" and "adhoc" in runners:
        raise ValueError(
            "the ad hoc runner does not model raw-trace transport or target-side "
            "DSP; use --runners scopecat-core,scopecat with "
            "--acquisition-dsp target"
        )


def _completed_point_count(run: RunHandle, scenario: ScanScenario) -> int:
    if scenario.retention == "discard":
        if run.contents(limit=1, role="dataset").items:
            raise RuntimeError("discard benchmark unexpectedly retained a dataset")
        return scenario.point_count
    return len(run.measurements().records)


def _acquired_result_bytes(scenario: ScanScenario) -> int | None:
    if scenario.profile != "multiqubit_result_retention":
        return None
    return (
        scenario.point_count
        * scenario.qubit_count
        * scenario.shots
        * np.dtype(np.complex128).itemsize
    )


def _selected_result_bytes(scenario: ScanScenario) -> int:
    if scenario.profile != "multiqubit_result_retention":
        return scenario.point_count * np.dtype(np.float64).itemsize
    if scenario.retention == "discard":
        return 0
    if scenario.retention == "summary":
        return (
            scenario.point_count * scenario.qubit_count * np.dtype(np.float64).itemsize
        )
    logical_bit_bytes = (
        scenario.point_count * scenario.qubit_count * scenario.shots + 7
    ) // 8
    if scenario.retention == "bit-shots":
        return logical_bit_bytes
    return logical_bit_bytes + cast("int", _acquired_result_bytes(scenario))


def _ad_hoc_measurement_bytes(root: Path) -> int:
    return sum(
        path.stat().st_size
        for path in root.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )


def _scopecat_measurement_bytes(state_root: Path) -> int:
    database = state_root / "control.sqlite3"
    object_root = state_root / "objects"
    if not database.is_file():
        return 0
    with sqlite3.connect(database) as connection:
        rows = cast(
            "list[tuple[str]]",
            connection.execute(
                """
                SELECT DISTINCT digest
                FROM run_repository_refs
                WHERE ref = 'data/measurement_dataset/raw-measurements/header.json'
                   OR ref LIKE 'data/measurement_dataset/raw-measurements/chunks/%'
                """
            ).fetchall(),
        )
    total = 0
    for row in rows:
        digest = row[0]
        hexdigest = digest.removeprefix("sha256:")
        path = object_root / hexdigest[:2] / hexdigest[2:]
        total += path.stat().st_size
    return total


def _tree_size(root: Path) -> tuple[int, int]:
    files = tuple(path for path in root.rglob("*") if path.is_file())
    return sum(path.stat().st_size for path in files), len(files)


def _host_metadata(label: str) -> HostMetadata:
    total_memory = int(cast("int", psutil.virtual_memory().total))
    return HostMetadata(
        label=label,
        platform=platform.platform(),
        python=platform.python_version(),
        logical_cpu_count=os.cpu_count(),
        physical_memory_bytes=total_memory,
    )


def _required_timestamp(value: int | None, label: str) -> int:
    if value is None:
        raise RuntimeError(f"benchmark did not observe {label}")
    return value


def _seconds(nanoseconds: int) -> float:
    return nanoseconds / 1_000_000_000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", default="1,10,100")
    parser.add_argument("--runners", default=",".join(_RUNNERS))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--point-delay-ms", type=float, default=0.0)
    parser.add_argument(
        "--acquisition-dsp",
        choices=("prefer_device", "target"),
        default="prefer_device",
    )
    parser.add_argument("--live-waveform", action="store_true")
    parser.add_argument("--profile", choices=tuple(_PROFILE_ALIASES), default="dense")
    parser.add_argument("--retention", choices=_RETENTION_MODES, default="summary")
    parser.add_argument("--shots", type=int, default=1)
    parser.add_argument("--waveform-samples", type=int, default=4096)
    parser.add_argument(
        "--qubit-counts",
        help=(
            "comma-separated topology-selected sizes, or 'all'; defaults to the "
            "complete configured device for scalable profiles"
        ),
    )
    parser.add_argument("--host-label", default=platform.node() or "local")
    parser.add_argument("--storage-root")
    parser.add_argument(
        "--output",
        default=".benchmarks/scan-execution.jsonl",
    )
    parser.add_argument("--worker", choices=_ALL_RUNNERS, help=argparse.SUPPRESS)
    parser.add_argument("--point-count", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--qubit-count", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--work-dir", help=argparse.SUPPRESS)
    return parser


def _arguments(argv: Sequence[str] | None) -> BenchmarkArguments:
    parsed = _parser().parse_args(argv)
    return BenchmarkArguments(
        points=cast("str", parsed.points),
        runners=cast("str", parsed.runners),
        repetitions=cast("int", parsed.repetitions),
        warmups=cast("int", parsed.warmups),
        point_delay_ms=cast("float", parsed.point_delay_ms),
        acquisition_dsp_policy=cast(
            "AcquisitionDspPolicy",
            parsed.acquisition_dsp,
        ),
        live_waveform=cast("bool", parsed.live_waveform),
        profile=cast("str", parsed.profile),
        retention=cast("RetentionMode", parsed.retention),
        shots=cast("int", parsed.shots),
        waveform_samples=cast("int", parsed.waveform_samples),
        qubit_counts=cast("str | None", parsed.qubit_counts),
        host_label=cast("str", parsed.host_label),
        storage_root=cast("str | None", parsed.storage_root),
        output=cast("str", parsed.output),
        worker=cast("RunnerName | None", parsed.worker),
        point_count=cast("int | None", parsed.point_count),
        qubit_count=cast("int | None", parsed.qubit_count),
        work_dir=cast("str | None", parsed.work_dir),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    if args.worker is not None:
        if (
            args.point_count is None
            or args.qubit_count is None
            or args.work_dir is None
        ):
            raise ValueError(
                "workers require --point-count, --qubit-count, and --work-dir"
            )
        return _worker(args)
    if args.repetitions <= 0 or args.warmups < 0:
        raise ValueError(
            "repetitions must be positive and warmups must not be negative"
        )
    if args.point_delay_ms < 0.0:
        raise ValueError("point delay must not be negative")
    if args.waveform_samples <= 0:
        raise ValueError("waveform samples must be positive")
    if args.shots <= 0:
        raise ValueError("shots must be positive")
    if args.profile != "results" and (args.retention != "summary" or args.shots != 1):
        raise ValueError(
            "retention selection and shot scaling require --profile results"
        )
    return _controller(args)


if __name__ == "__main__":
    raise SystemExit(main())
