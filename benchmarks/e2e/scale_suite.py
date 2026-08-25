"""Run named scale profiles as acceptance gates or repeatable benchmarks."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from benchmarks.record import (
    BENCHMARK_RESULT_PREFIX,
    benchmark_record_header,
)

type ScaleProfileId = Literal["smoke", "small", "medium", "full", "endurance"]
type SuiteMode = Literal["acceptance", "benchmark"]
type ScaleRunner = Literal["scopecat", "scopecat-deployed"]

_REFERENCE_PROGRAM_WAVEFORM_BYTES = 48 * 2**20


@dataclass(frozen=True, slots=True)
class ScaleProfile:
    """One memorable width, waveform, and scan-volume anchor."""

    id: ScaleProfileId
    qubit_count: int
    point_count: int
    waveform_sample_count: int
    purpose: str
    schedule: str

    @property
    def physical_channel_count(self) -> int:
        return 2 * self.qubit_count + 2

    @property
    def entry_waveform_bytes(self) -> int:
        return self.physical_channel_count * self.waveform_sample_count * 8

    @property
    def total_waveform_bytes(self) -> int:
        return self.point_count * self.entry_waveform_bytes


SCALE_PROFILES = (
    ScaleProfile(
        id="smoke",
        qubit_count=1,
        point_count=1,
        waveform_sample_count=1_000,
        purpose="Complete one continuous-buffer execution path",
        schedule="every change",
    ),
    ScaleProfile(
        id="small",
        qubit_count=4,
        point_count=10,
        waveform_sample_count=10_000,
        purpose="Reference-lab parallelism, shared readout, and persistence",
        schedule="every change",
    ),
    ScaleProfile(
        id="medium",
        qubit_count=16,
        point_count=10,
        waveform_sample_count=100_000,
        purpose="Multi-device routing and standard-length waveform batches",
        schedule="daily or before merge",
    ),
    ScaleProfile(
        id="full",
        qubit_count=64,
        point_count=10,
        waveform_sample_count=100_000,
        purpose="Intended parallel width with complete continuous waveforms",
        schedule="before release",
    ),
    ScaleProfile(
        id="endurance",
        qubit_count=64,
        point_count=100,
        waveform_sample_count=10_000,
        purpose="Bounded working set across a longer scan",
        schedule="weekly or before release",
    ),
)

_PROFILES_BY_ID = {profile.id: profile for profile in SCALE_PROFILES}


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    """One machine-readable invariant applied to every measured repetition."""

    id: str
    passed: bool
    expected: object
    observed: object
    detail: str


@dataclass(frozen=True, slots=True)
class SuiteArguments:
    mode: SuiteMode
    runner: ScaleRunner
    profiles: str | None
    through: ScaleProfileId | None
    repetitions: int | None
    warmups: int | None
    max_memory_fraction: float
    host_label: str
    storage_root: str | None
    output: str
    list_profiles: bool
    json: bool


def scale_profile(profile_id: str) -> ScaleProfile:
    """Resolve one stable scale-profile name."""

    try:
        return _PROFILES_BY_ID[cast("ScaleProfileId", profile_id)]
    except KeyError:
        choices = ", ".join(_PROFILES_BY_ID)
        raise ValueError(
            f"unknown scale profile {profile_id!r}; choose from {choices}"
        ) from None


def selected_profiles(
    *,
    profiles: str | None,
    through: ScaleProfileId | None,
) -> tuple[ScaleProfile, ...]:
    """Select explicit profiles or every profile through one named level."""

    if profiles is not None and through is not None:
        raise ValueError("choose either --profiles or --through, not both")
    if through is not None:
        through_index = next(
            index
            for index, profile in enumerate(SCALE_PROFILES)
            if profile.id == through
        )
        return SCALE_PROFILES[: through_index + 1]
    profile_ids = (profiles or "smoke").split(",")
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("scale profiles must be unique")
    return tuple(scale_profile(profile_id) for profile_id in profile_ids)


def acceptance_checks(
    profile: ScaleProfile,
    measurements: tuple[dict[str, object], ...],
    *,
    max_memory_fraction: float,
) -> tuple[AcceptanceCheck, ...]:
    """Evaluate correctness and bounded-resource invariants, never timings."""

    entry_bytes = profile.entry_waveform_bytes
    total_bytes = profile.total_waveform_bytes
    batch_limit = max(_REFERENCE_PROGRAM_WAVEFORM_BYTES, entry_bytes)
    points = tuple(cast("int", item["points_completed"]) for item in measurements)
    rendered = tuple(
        cast("int", item["waveform_bytes_rendered"]) for item in measurements
    )
    uploaded = tuple(
        cast("int", item["waveform_bytes_uploaded"]) for item in measurements
    )
    retained = tuple(
        cast("int", item["live_waveform_bytes_retained"]) for item in measurements
    )
    max_batches = tuple(
        cast("int", item["max_waveform_batch_bytes"]) for item in measurements
    )
    trigger_counts = tuple(cast("int", item["trigger_count"]) for item in measurements)
    final_spool = tuple(
        cast("int", item["payload_spool_bytes_at_finish"]) for item in measurements
    )
    peak_spool = tuple(
        cast("int", item["peak_payload_spool_bytes"]) for item in measurements
    )
    memory_limits = tuple(
        int(
            cast(
                "int",
                cast("dict[str, object]", item["host"])["physical_memory_bytes"],
            )
            * max_memory_fraction
        )
        for item in measurements
    )
    peak_memory = tuple(cast("int", item["peak_rss_bytes"]) for item in measurements)
    checks = [
        AcceptanceCheck(
            id="all-points-completed",
            passed=all(value == profile.point_count for value in points),
            expected=profile.point_count,
            observed=points,
            detail="Every logical point reaches a durable completed result.",
        ),
        AcceptanceCheck(
            id="complete-waveforms-rendered",
            passed=all(value == total_bytes for value in rendered),
            expected=total_bytes,
            observed=rendered,
            detail="The host renders every channel-by-sample float64 buffer.",
        ),
        AcceptanceCheck(
            id="complete-waveforms-uploaded",
            passed=all(value == total_bytes for value in uploaded),
            expected=total_bytes,
            observed=uploaded,
            detail="The driver boundary receives complete contiguous buffers.",
        ),
        AcceptanceCheck(
            id="latest-view-is-one-entry",
            passed=all(value == entry_bytes for value in retained),
            expected=entry_bytes,
            observed=retained,
            detail="Optional waveform inspection retains only the latest entry.",
        ),
        AcceptanceCheck(
            id="waveform-batch-is-bounded",
            passed=all(0 < value <= batch_limit for value in max_batches),
            expected={"maximum_bytes": batch_limit},
            observed=max_batches,
            detail=(
                "Materialization is bounded by target capacity, not total scan volume."
            ),
        ),
        AcceptanceCheck(
            id="physical-triggers-are-bounded",
            passed=all(0 < value <= profile.point_count for value in trigger_counts),
            expected={"minimum": 1, "maximum": profile.point_count},
            observed=trigger_counts,
            detail="Batching may reduce triggers but cannot create extra executions.",
        ),
        AcceptanceCheck(
            id="payload-spool-is-released",
            passed=all(value == 0 for value in final_spool),
            expected=0,
            observed=final_spool,
            detail="Transient command payloads do not become retained run content.",
        ),
        AcceptanceCheck(
            id="payload-spool-is-bounded",
            passed=all(
                value <= 2 * max_batch
                for value, max_batch in zip(peak_spool, max_batches, strict=True)
            ),
            expected="no more than twice the largest materialized batch",
            observed=peak_spool,
            detail="Transport encoding does not retain the complete scan payload.",
        ),
        AcceptanceCheck(
            id="host-memory-budget",
            passed=all(
                peak <= limit
                for peak, limit in zip(peak_memory, memory_limits, strict=True)
            ),
            expected={"maximum_fraction": max_memory_fraction},
            observed=peak_memory,
            detail="Peak process RSS stays within the configured host-memory fraction.",
        ),
    ]
    if profile.id == "endurance":
        checks.append(
            AcceptanceCheck(
                id="endurance-working-set-is-not-total-volume",
                passed=all(value < total_bytes for value in max_batches),
                expected={"less_than_total_bytes": total_bytes},
                observed=max_batches,
                detail="A long scan streams multiple bounded waveform batches.",
            )
        )
    return tuple(checks)


def _run_profile(
    profile: ScaleProfile,
    *,
    repetitions: int,
    warmups: int,
    runner: ScaleRunner,
    host_label: str,
    storage_root: str | None,
    work_root: Path,
) -> tuple[dict[str, object], ...]:
    output = work_root / f"{profile.id}.jsonl"
    command = [
        sys.executable,
        "-m",
        "benchmarks",
        "run",
        "scan-execution",
        "--profile",
        "waveform",
        "--runners",
        runner,
        "--points",
        str(profile.point_count),
        "--qubit-counts",
        str(profile.qubit_count),
        "--waveform-samples",
        str(profile.waveform_sample_count),
        "--live-waveform",
        "--repetitions",
        str(repetitions),
        "--warmups",
        str(warmups),
        "--host-label",
        host_label,
        "--output",
        str(output),
    ]
    if storage_root is not None:
        command.extend(("--storage-root", storage_root))
    completed = subprocess.run(  # noqa: S603
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"scale profile {profile.id!r} failed with exit code "
            f"{completed.returncode}:\n{completed.stdout}\n{completed.stderr}"
        )
    return tuple(
        cast("dict[str, object]", json.loads(line))
        for line in output.read_text(encoding="utf-8").splitlines()
    )


def _result_record(
    profile: ScaleProfile,
    *,
    mode: SuiteMode,
    runner: ScaleRunner,
    repetitions: int,
    warmups: int,
    max_memory_fraction: float,
    measurements: tuple[dict[str, object], ...],
) -> dict[str, object]:
    checks = acceptance_checks(
        profile,
        measurements,
        max_memory_fraction=max_memory_fraction,
    )
    return {
        **benchmark_record_header(case_id="scale-suite", case_version=2, kind="e2e"),
        "mode": mode,
        "runner": runner,
        "profile": asdict(profile),
        "repetitions": repetitions,
        "warmups": warmups,
        "passed": all(check.passed for check in checks),
        "checks": [asdict(check) for check in checks],
        "measurements": measurements,
    }


def _print_profiles(*, as_json: bool) -> None:
    documents = [
        {
            **asdict(profile),
            "physical_channel_count": profile.physical_channel_count,
            "entry_waveform_bytes": profile.entry_waveform_bytes,
            "total_waveform_bytes": profile.total_waveform_bytes,
        }
        for profile in SCALE_PROFILES
    ]
    if as_json:
        print(json.dumps(documents, indent=2))
        return
    for profile, document in zip(SCALE_PROFILES, documents, strict=True):
        print(
            f"{profile.id:<10} q={profile.qubit_count:<2} "
            f"points={profile.point_count:<3} "
            f"samples={profile.waveform_sample_count:<6} "
            "payload="
            f"{cast('int', document['total_waveform_bytes']) / 2**20:>7.1f} MiB "
            f"{profile.purpose}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("acceptance", "benchmark"),
        default="acceptance",
    )
    parser.add_argument(
        "--runner",
        choices=("scopecat", "scopecat-deployed"),
        default="scopecat-deployed",
    )
    parser.add_argument("--profiles")
    parser.add_argument("--through", choices=tuple(_PROFILES_BY_ID))
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--warmups", type=int)
    parser.add_argument("--max-memory-fraction", type=float, default=0.75)
    parser.add_argument("--host-label", default=platform.node() or "local")
    parser.add_argument("--storage-root")
    parser.add_argument("--output", default=".benchmarks/scale-suite.jsonl")
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _arguments() -> SuiteArguments:
    selected = _parser().parse_args()
    return SuiteArguments(
        mode=cast("SuiteMode", selected.mode),
        runner=cast("ScaleRunner", selected.runner),
        profiles=cast("str | None", selected.profiles),
        through=cast("ScaleProfileId | None", selected.through),
        repetitions=cast("int | None", selected.repetitions),
        warmups=cast("int | None", selected.warmups),
        max_memory_fraction=cast("float", selected.max_memory_fraction),
        host_label=cast("str", selected.host_label),
        storage_root=cast("str | None", selected.storage_root),
        output=cast("str", selected.output),
        list_profiles=cast("bool", selected.list_profiles),
        json=cast("bool", selected.json),
    )


def main() -> int:
    args = _arguments()
    if args.list_profiles:
        _print_profiles(as_json=args.json)
        return 0
    profiles = selected_profiles(profiles=args.profiles, through=args.through)
    repetitions = (
        args.repetitions
        if args.repetitions is not None
        else (1 if args.mode == "acceptance" else 3)
    )
    warmups = (
        args.warmups
        if args.warmups is not None
        else (0 if args.mode == "acceptance" else 1)
    )
    if repetitions <= 0 or warmups < 0:
        raise ValueError("repetitions must be positive and warmups non-negative")
    if not 0.0 < args.max_memory_fraction <= 1.0:
        raise ValueError("max memory fraction must be in (0, 1]")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="scopecat-scale-suite-") as selected:
        work_root = Path(selected)
        for profile in profiles:
            measurements = _run_profile(
                profile,
                repetitions=repetitions,
                warmups=warmups,
                runner=args.runner,
                host_label=args.host_label,
                storage_root=args.storage_root,
                work_root=work_root,
            )
            record = _result_record(
                profile,
                mode=args.mode,
                runner=args.runner,
                repetitions=repetitions,
                warmups=warmups,
                max_memory_fraction=args.max_memory_fraction,
                measurements=measurements,
            )
            records.append(record)
            print(
                BENCHMARK_RESULT_PREFIX + json.dumps(record, sort_keys=True),
                flush=True,
            )
            print(
                f"{profile.id:<10} {'PASS' if record['passed'] else 'FAIL'} "
                f"q={profile.qubit_count:<2} points={profile.point_count:<3} "
                f"samples={profile.waveform_sample_count}",
                flush=True,
            )
    with output.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"scale-suite results: {output}")
    if args.mode == "acceptance" and not all(
        cast("bool", record["passed"]) for record in records
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
