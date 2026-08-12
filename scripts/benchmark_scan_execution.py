"""Compare a direct point-local scan with the reference Scopecat execution path.

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
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Self, cast

import numpy as np
import psutil

import scopecat as sc
from reference_lab.bench_interfaces import (
    TRIGGER_LOAD_PROGRAM,
    TRIGGER_PROGRAM,
    TRIGGER_START_PROGRAM,
    TRIGGER_START_PROGRAM_IDEMPOTENT,
)
from reference_lab.compiler import QuantumLabCompiler
from reference_lab.configuration import bootstrap_config
from reference_lab.payloads import (
    DecodedTriggerProgram,
    reference_lab_payload_codecs,
)
from reference_lab.provider import ReferenceLabProvider
from reference_lab.quantum_runner import quantum_capture
from reference_lab.targets.list_mode import configured_list_mode_target
from reference_lab.virtual_lab.execution import virtual_quantum_runtime
from reference_lab.workflows.drag_beta_calibration import drag_beta_program
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.sdk.instruments import (
    DriverAcquisition,
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
from scopecat_quantum.measurement_computes import BinaryIqProbabilityProducts
from scopecat_testkit.instrument_host import compose_test_instruments
from scopecat_testkit.server.in_process_lab import in_process_lab  # noqa: TID251

_RESULT_PREFIX = "SCAN_BENCHMARK_RESULT="
type RunnerName = Literal["adhoc", "scopecat"]
_RUNNERS: tuple[RunnerName, ...] = ("adhoc", "scopecat")


@dataclass(frozen=True, slots=True)
class BenchmarkArguments:
    points: str
    runners: str
    repetitions: int
    warmups: int
    point_delay_ms: float
    live_waveform: bool
    host_label: str
    storage_root: str | None
    output: str
    worker: RunnerName | None
    point_count: int | None
    work_dir: str | None


@dataclass(frozen=True, slots=True)
class ScanScenario:
    """One comparable integrated-IQ scan workload."""

    point_count: int
    point_delay_s: float = 0.0
    live_waveform: bool = False
    profile: Literal["drag_beta_integrated_iq"] = field(
        default="drag_beta_integrated_iq",
        init=False,
    )
    waveform_sample_count: int = field(default=72, init=False)
    physical_channel_count: int = field(default=4, init=False)
    shots: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        if self.point_count <= 0:
            raise ValueError("point_count must be positive")
        if self.point_delay_s < 0.0:
            raise ValueError("point_delay_s must not be negative")


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

    schema: Literal["scopecat.scan_execution_benchmark.v1"]
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
    waveform_bytes_rendered: int | None
    waveform_bytes_uploaded: int | None
    live_waveform_bytes_retained: int | None
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
    def retained_bytes(self) -> int:
        return sum(waveform.nbytes for waveform in self._latest)


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
    timeline.start()
    with PeakRssSampler() as memory:
        hardware = AdHocHardware(scenario, timeline)
        writer = AdHocResultWriter(root, scenario)
        for point in range(scenario.point_count):
            waveforms = _render_ad_hoc_point(scenario, point)
            waveform_bytes += sum(waveform.nbytes for waveform in waveforms)
            hardware.load(waveforms)
            view.replace(waveforms)
            writer.append(point, hardware.run_and_collect(point))
        writer.finish()
        timeline.finish()
        memory.observe()
    durable_bytes, durable_files = _tree_size(root)
    return BenchmarkResult(
        schema="scopecat.scan_execution_benchmark.v1",
        revision=_git_revision(),
        runner="adhoc",
        scenario=scenario,
        host=_host_metadata(host_label),
        phases=timeline.metrics(),
        starting_rss_bytes=memory.starting_bytes,
        peak_rss_bytes=memory.peak_bytes,
        peak_rss_growth_bytes=memory.growth_bytes,
        points_completed=scenario.point_count,
        trigger_count=timeline.trigger_count,
        waveform_bytes_rendered=waveform_bytes,
        waveform_bytes_uploaded=hardware.uploaded_bytes,
        live_waveform_bytes_retained=view.retained_bytes,
        durable_bytes=durable_bytes,
        durable_file_count=durable_files,
    )


def run_scopecat(
    scenario: ScanScenario,
    root: Path,
    *,
    host_label: str = "local",
) -> BenchmarkResult:
    """Run the same scan through current planning, execution, and persistence."""

    if scenario.live_waveform:
        raise ValueError("the Scopecat latest-waveform path is not implemented")
    timeline = ExperimentTimeline()
    config = bootstrap_config()
    reference_provider = ReferenceLabProvider(seed=7)
    provider = TimedInstrumentProvider(
        reference_provider,
        timeline,
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
    if run.manifest.status != "completed":
        raise RuntimeError(f"Scopecat run ended as {run.manifest.status}")
    points_completed = len(run.measurements().records)
    durable_bytes, durable_files = _tree_size(root)
    return BenchmarkResult(
        schema="scopecat.scan_execution_benchmark.v1",
        revision=_git_revision(),
        runner="scopecat",
        scenario=scenario,
        host=_host_metadata(host_label),
        phases=timeline.metrics(),
        starting_rss_bytes=memory.starting_bytes,
        peak_rss_bytes=memory.peak_bytes,
        peak_rss_growth_bytes=memory.growth_bytes,
        points_completed=points_completed,
        trigger_count=timeline.trigger_count,
        waveform_bytes_rendered=None,
        waveform_bytes_uploaded=None,
        live_waveform_bytes_retained=None,
        durable_bytes=durable_bytes,
        durable_file_count=durable_files,
    )


class TimedInstrumentProvider:
    """Observe physical trigger and collection without changing driver behavior."""

    def __init__(
        self,
        delegate: ReferenceLabProvider,
        timeline: ExperimentTimeline,
        *,
        point_delay_s: float,
    ) -> None:
        self._delegate = delegate
        self._timeline = timeline
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
            point_delay_s=self._point_delay_s,
        )


class TimedInstrumentDriver:
    """Delegate driver calls while timestamping trigger and completed reads."""

    def __init__(
        self,
        delegate: InstrumentDriver,
        timeline: ExperimentTimeline,
        *,
        point_delay_s: float,
    ) -> None:
        self._delegate = delegate
        self._timeline = timeline
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
        self._timeline.collect()
        return outcome

    def disconnect(self) -> None:
        self._delegate.disconnect()

    def abort(self) -> None:
        self._delegate.abort()


def _scopecat_invocation(scenario: ScanScenario) -> sc.ExperimentInvocation:
    beta_values = tuple(
        sc.Quantity(float(value), "ns")
        for value in np.linspace(-0.5, 1.5, scenario.point_count)
    )

    @sc.experiment(id="benchmark.quantum_scan")
    def benchmark_scan(experiment: sc.ExperimentContext) -> None:
        beta = experiment.scan("beta", beta_values)
        probabilities: BinaryIqProbabilityProducts = experiment.use(
            quantum_capture(
                drag_beta_program(
                    qubit="q0",
                    amplification=1,
                    beta=beta,
                ).with_shots(scenario.shots)
            )
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
    scenario = ScanScenario(
        point_count=cast("int", args.point_count),
        point_delay_s=args.point_delay_ms / 1000.0,
        live_waveform=args.live_waveform,
    )
    root = Path(cast("str", args.work_dir))
    result = (
        run_ad_hoc(scenario, root, host_label=args.host_label)
        if runner == "adhoc"
        else run_scopecat(scenario, root, host_label=args.host_label)
    )
    print(_RESULT_PREFIX + json.dumps(asdict(result), sort_keys=True), flush=True)
    return 0


def _controller(args: BenchmarkArguments) -> int:
    point_counts = _positive_ints(args.points)
    runners: tuple[RunnerName, ...] = tuple(
        cast("RunnerName", item) for item in args.runners.split(",")
    )
    invalid = sorted(set(runners) - set(_RUNNERS))
    if invalid:
        raise ValueError(f"unknown runners: {', '.join(invalid)}")
    if args.live_waveform and "scopecat" in runners:
        raise ValueError("--live-waveform currently requires --runners adhoc")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(
        prefix="scopecat-scan-benchmark-",
        dir=args.storage_root,
    ) as selected:
        temporary_root = Path(selected)
        jobs: tuple[tuple[RunnerName, int, int, bool], ...] = tuple(
            (runner, point_count, repetition, repetition < args.warmups)
            for point_count in point_counts
            for runner in runners
            for repetition in range(args.warmups + args.repetitions)
        )
        for index, (runner, point_count, repetition, warmup) in enumerate(jobs):
            work_dir = temporary_root / f"{index}-{runner}-{point_count}-{repetition}"
            result = _run_worker_process(
                runner=runner,
                point_count=point_count,
                args=args,
                work_dir=work_dir,
            )
            shutil.rmtree(work_dir)
            if warmup:
                continue
            result["repetition"] = repetition - args.warmups
            results.append(result)
            print(
                f"{runner:8} points={point_count:<7} "
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
    args: BenchmarkArguments,
    work_dir: Path,
) -> dict[str, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        runner,
        "--point-count",
        str(point_count),
        "--point-delay-ms",
        str(args.point_delay_ms),
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
        if line.startswith(_RESULT_PREFIX):
            return cast(
                "dict[str, object]",
                json.loads(line.removeprefix(_RESULT_PREFIX)),
            )
    raise RuntimeError(
        f"worker returned no result:\n{completed.stdout}\n{completed.stderr}"
    )


def _summaries(results: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    keys = sorted(
        {
            (cast("str", result["runner"]), _scenario_point_count(result))
            for result in results
        },
        key=lambda item: (item[1], item[0]),
    )
    return [
        {
            "runner": runner,
            "point_count": point_count,
            "median_prepare_s": statistics.median(
                _nested_float(result, "phases", "prepare_s")
                for result in results
                if result["runner"] == runner
                and _scenario_point_count(result) == point_count
            ),
            "median_wall_s": statistics.median(
                _nested_float(result, "phases", "wall_s")
                for result in results
                if result["runner"] == runner
                and _scenario_point_count(result) == point_count
            ),
            "median_peak_rss_bytes": statistics.median(
                cast("int", result["peak_rss_bytes"])
                for result in results
                if result["runner"] == runner
                and _scenario_point_count(result) == point_count
            ),
            "median_peak_rss_growth_bytes": statistics.median(
                cast("int", result["peak_rss_growth_bytes"])
                for result in results
                if result["runner"] == runner
                and _scenario_point_count(result) == point_count
            ),
            "median_durable_bytes": statistics.median(
                cast("int", result["durable_bytes"])
                for result in results
                if result["runner"] == runner
                and _scenario_point_count(result) == point_count
            ),
        }
        for runner, point_count in keys
    ]


def _scenario_point_count(result: dict[str, object]) -> int:
    scenario = cast("dict[str, object]", result["scenario"])
    return cast("int", scenario["point_count"])


def _nested_float(result: dict[str, object], group: str, key: str) -> float:
    selected = cast("dict[str, object]", result[group])
    return float(cast("float", selected[key]))


def _positive_ints(value: str) -> tuple[int, ...]:
    selected = tuple(int(item) for item in value.split(","))
    if not selected or any(item <= 0 for item in selected):
        raise ValueError("point counts must be positive")
    return selected


def _tree_size(root: Path) -> tuple[int, int]:
    files = tuple(path for path in root.rglob("*") if path.is_file())
    return sum(path.stat().st_size for path in files), len(files)


def _git_revision() -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to record the benchmark revision")
    completed = subprocess.run(  # noqa: S603
        (git, "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    status = subprocess.run(  # noqa: S603
        (git, "status", "--porcelain"),
        check=True,
        capture_output=True,
        text=True,
    )
    return f"{revision}-dirty" if status.stdout else revision


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
    parser.add_argument("--live-waveform", action="store_true")
    parser.add_argument("--host-label", default=platform.node() or "local")
    parser.add_argument("--storage-root")
    parser.add_argument(
        "--output",
        default=".benchmarks/scan-execution.jsonl",
    )
    parser.add_argument("--worker", choices=_RUNNERS, help=argparse.SUPPRESS)
    parser.add_argument("--point-count", type=int, help=argparse.SUPPRESS)
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
        live_waveform=cast("bool", parsed.live_waveform),
        host_label=cast("str", parsed.host_label),
        storage_root=cast("str | None", parsed.storage_root),
        output=cast("str", parsed.output),
        worker=cast("RunnerName | None", parsed.worker),
        point_count=cast("int | None", parsed.point_count),
        work_dir=cast("str | None", parsed.work_dir),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    if args.worker is not None:
        if args.point_count is None or args.work_dir is None:
            raise ValueError("workers require --point-count and --work-dir")
        return _worker(args)
    if args.repetitions <= 0 or args.warmups < 0:
        raise ValueError(
            "repetitions must be positive and warmups must not be negative"
        )
    if args.point_delay_ms < 0.0:
        raise ValueError("point delay must not be negative")
    return _controller(args)


if __name__ == "__main__":
    raise SystemExit(main())
