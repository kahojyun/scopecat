# Benchmark Suite

Scopecat benchmarks share one discoverable local entrypoint:

```console
uv run python -m benchmarks list
uv run python -m benchmarks run historical-project --runs 10000
uv run python -m benchmarks run quantum-program --entities 100,1000 \
  --family-points 10,1000 --family-sequence-length 64
uv run python -m benchmarks run scan-execution --profile waveform \
  --points 1,10,100 --qubit-counts 1,2,4
uv run python -m benchmarks run scan-execution --profile lo-sweep \
  --points 10,100 --runners scopecat
uv run python -m benchmarks run payload-attachments --arrays 300 \
  --samples 1024 --iterations 10
```

Every case emits records beginning with `BENCHMARK_RESULT=` and the common
`scopecat.benchmark_result.v1` identity. Case-specific fields remain typed by
`case_id` and `case_version`; the registry is the source of truth for available
cases and their measurement boundary.

## Boundaries

| Kind | Use | Current cases |
|---|---|---|
| `e2e` | User-visible behavior spanning daemon, compiler, runtime, devices, and persistence | `scan-execution` |
| `component` | One subsystem boundary with realistic inputs and setup outside the measured operation | `adaptive-context`, `historical-project`, `list-mode-compiler`, `quantum-program` |
| `micro` | One pure operation or data structure without service or storage setup | `inspection-index`, `payload-attachments` |

The production `scopecat` runner is the end-to-end product result. `adhoc` is a
descriptive lower bound and `scopecat-core` is a diagnostic that excludes daemon
transport; neither replaces the production result.

Correctness, cache behavior, and retained-structure invariants belong in normal
package tests. The smoke tests here prove that realistic scales remain bounded,
the harness executes, and records keep their declared schema. Wall time, RSS,
and byte measurements are observations rather than machine-independent pytest
thresholds.

Run the deterministic harness contracts serially:

```console
uv run pytest -q -n 0 benchmarks/smoke
```

## Tooling policy

The end-to-end and component cases keep the typed local harness because they
record multiple phases, process RSS, durable bytes, cache facts, and physical
counts in one result. If micro timings become optimization gates, use `pyperf`
for calibrated subprocess timing and comparison rather than extending this
harness with another timing loop. Add `asv` only when cross-commit history and
environment matrices become a routine need.

Raw local results belong under `.benchmarks/`, which is intentionally ignored by
Git. Record the host label and compare equivalent machine and storage profiles.
