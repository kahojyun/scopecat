"""Common identity and serialization markers for benchmark records."""

from __future__ import annotations

import shutil
import subprocess
from typing import Final

from .model import BenchmarkKind

BENCHMARK_RESULT_SCHEMA: Final = "scopecat.benchmark_result.v1"
BENCHMARK_RESULT_PREFIX: Final = "BENCHMARK_RESULT="


def benchmark_record_header(
    *,
    case_id: str,
    case_version: int,
    kind: BenchmarkKind,
) -> dict[str, object]:
    """Build the stable identity shared by every case-specific record."""

    return {
        "schema": BENCHMARK_RESULT_SCHEMA,
        "case_id": case_id,
        "case_version": case_version,
        "kind": kind,
        "revision": git_revision(),
    }


def git_revision() -> str:
    """Record the exact repository state measured by one benchmark."""

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


__all__ = [
    "BENCHMARK_RESULT_PREFIX",
    "BENCHMARK_RESULT_SCHEMA",
    "benchmark_record_header",
    "git_revision",
]
