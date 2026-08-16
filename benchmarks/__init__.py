"""Discoverable scalability and performance benchmark suite."""

from .model import BenchmarkCase, BenchmarkKind
from .registry import BENCHMARK_CASES, benchmark_case

__all__ = [
    "BENCHMARK_CASES",
    "BenchmarkCase",
    "BenchmarkKind",
    "benchmark_case",
]
