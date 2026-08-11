# Scalability Benchmarks

This document turns the scalability direction in the
[project charter](project-charter.md) into representative workloads and
measurements. It separates current implementation facts from target envelopes
so measured bottlenecks can guide each internal change.

Scopecat preserves scalable semantics before optimizing every mechanism.
Logical point, product, and lineage identities remain independent of physical
batching; completed measurement prefixes are durable; and large data has a
bounded read path. Planning, storage, and orchestration may evolve behind those
contracts.

Benchmark results use three labels:

- **demonstrated**: completed repeatably within a recorded resource budget;
- **target**: the next useful single-lab NISQ envelope;
- **stress**: a larger profile that reveals the next mechanism to evolve.

Profiles are provisional until a repeatable benchmark records results. Routine
benchmarks use virtual backends and generated or replayed data so execution
volume, payload shape, and failure points remain reproducible. Physical-hardware
validation can then cover timing and integration behavior separately.

## Workload Model

An individual experiment normally fits a useful hardware and stability window.
Scale accumulates through configured topology, repeated acquisition, structured
result payloads, and analysis-driven runs:

```text
execution volume = sum(points × shots × measured groups)
data volume      = sum(points × products × result payload)
workflow scale   = related runs × configuration and analysis lineage
```

Result payload may itself include measured qubits or channels, shots, and fixed
or ragged sample axes. Backend capacity determines physical partitions without
changing the logical workload.

## Reference Profiles

| Profile | Target shape | Primary pressure |
|---|---|---|
| Full-device calibration | 128 qubits; 100–1,000 related runs; 100–10,000 points per run | topology, resource claims, configuration, and lineage |
| Shot-heavy acquisition | at least 100 million aggregate shots; representative packed-bit and integrated-IQ payloads | batching, binary content, checkpoints, and bounded reads |
| Structured trace | 1,000–10,000 outer points; 1,601-sample complex VNA traces plus representative waveforms and per-shot arrays | object throughput, array shape, slicing, and analysis memory |
| Dense spectroscopy | 100,000 logical points, with a 1,000,000-point stress variant | planning time, peak memory, and compiler partitioning |
| Historical project | 10,000 retained runs, with a 100,000-run stress variant | pagination, indexing, and GUI/API latency |

The profiles exercise characteristic combinations rather than maximizing every
dimension at once. Compiler request size remains backend-declared. Shot counts,
trace lengths, and run duration can be varied independently to locate a specific
resource boundary.

## Shared Invariants

Every applicable profile should verify that:

- logical point and product identities remain identical across physical batch
  sizes;
- compiler requests respect backend-declared capacity;
- completed measurement prefixes are readable before terminal completion;
- SQLite events and control records grow at batch, checkpoint, or durable state
  transition granularity;
- binary objects carry large values while control responses remain bounded
  descriptors;
- notebook reads keep memory proportional to the requested measurement batch;
- GUI tables and plots use bounded pages, selections, and previews;
- configuration, analysis, and run lineage remain queryable across a workflow.

Structured acquisition profiles should additionally preserve shot, channel,
and fixed or ragged sample axes instead of flattening them into control-plane
logical points. Dense spectroscopy should record planning costs separately from
execution and measurement costs.

## Measurements

Record the repository revision, machine description, workload shape, wall time,
peak resident memory, durable object bytes, database rows and bytes, event
count, and relevant cold and warm query latencies. Record planning, execution,
persistence, and analysis separately so one result identifies one limiting
boundary.

A target becomes demonstrated when the workload, resource budget, and result
are repeatable. Optimizations should address the first measured limit while
preserving the shared invariants.

## Current Implementation Boundaries

The present architecture provides a direct end-to-end baseline:

- linking and planning eagerly materialize logical points and coverage blocks;
- domain compilation uses a backend-declared point capacity;
- one SQLite writer owns durable ordering while immutable object storage carries
  large content;
- notebook measurement batches and GUI previews provide bounded read paths.

The dense spectroscopy profile measures when eager planning should evolve. The
other profiles establish whether acquisition volume or history reaches its
resource budget first. Workflow scalability awaits a workflow ownership model.

## Development Cadence

1. Maintain deterministic generators for the reference profiles.
2. Record the demonstrated envelope before changing a scalability mechanism.
3. Select the first resource budget that prevents the next useful workload.
4. Replace that mechanism and rerun semantic tests across physical batch sizes.
5. Promote a target after its measurements are repeatable and its normal user
   workflow remains approachable.

This cadence keeps performance work tied to end-to-end product value while
leaving room for decisive internal changes during early development.
