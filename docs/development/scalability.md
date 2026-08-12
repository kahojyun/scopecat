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

## Scan Execution UX Baseline

The first executable profile compares Scopecat with the useful scaling
properties of a direct lab scan. The direct runner lazily renders one point,
uploads only that point's four real-valued waveforms, retains only the latest
waveforms for an optional live view, collects one integrated-IQ-derived scalar,
and appends the result to one sequential file. It deliberately does not retain
a Python list of all captured entries: total point count must not determine the
waveform working set.

The matched `scopecat` runner executes the reference-lab drag-beta experiment
through the production daemon client, HTTP models, run admission and leases,
operation-scoped payload spooling, instrument service, local driver endpoint,
collection, and durable run storage. `scopecat-core` is an
optional diagnostic that runs the same planning and execution semantics through
a direct test instrument host; it deliberately excludes daemon transport and
must not be used as the product acceptance result. The default comparison is
therefore `adhoc,scopecat`.

The matched runners use a fixed single-shot workload with four physical
channels and a 72-sample point waveform. Point count is the only scale variable
in the zero-delay run. `--point-delay-ms` adds the same logical-point dwell to
both virtual hardware paths for a representative total-time run. Shot-heavy
acquisition and long waveforms use separate matched profiles so their working
sets do not obscure point-count costs.

Run a short comparison with:

```console
uv run python scripts/benchmark_scan_execution.py \
  --points 1,10,100 \
  --host-label lab-pc-hdd \
  --storage-root /path/on/the/experiment-drive
```

`--storage-root` must name an existing directory on the storage device being
measured. The command creates isolated run directories below it and removes
them after each worker. Raw JSON Lines results default to
`.benchmarks/scan-execution.jsonl`. Every worker records the Git revision and
dirty state, host metadata, scenario, phase timings, resident-memory growth,
durable bytes, object-store bytes, file counts, logical point count, and
physical trigger count. `object_store_bytes` is especially important when
comparing `scopecat-core` with `scopecat`: it now measures only durable
content, not ordinary command transport. `peak_payload_spool_bytes` measures
the largest simultaneous command-payload working set and
`payload_spool_bytes_at_finish` must be zero after a completed run.

Use three measured repetitions after one warmup for a comparison run. Increase
the largest point count geometrically only while the previous step remains
within its time and disk budget, for example `300,1000` after the short run.
Run each runner in a separate process, as the command does, so allocator state
and prior Scopecat runs do not contaminate the direct baseline.

To isolate daemon and object-store overhead after a default comparison, add the
core diagnostic explicitly:

```console
uv run python scripts/benchmark_scan_execution.py \
  --runners scopecat-core,scopecat \
  --points 1,10,100
```

Run the same staircase again with a representative acquisition duration when
evaluating total experiment UX:

```console
uv run python scripts/benchmark_scan_execution.py \
  --points 1,10,100 \
  --point-delay-ms 10 \
  --host-label lab-pc-hdd \
  --storage-root /path/on/the/experiment-drive
```

The synthetic dwell makes the two virtual paths wait for equal aggregate
logical-point time. Physical-hardware validation remains necessary for driver
and timing behavior.

### Latest Multichannel Waveform Profile

The waveform profile varies the per-point physical waveform working set while
retaining the same scalar integrated-IQ result. One to four driven qubits map to
four to ten physical output channels: two drive channels per qubit plus one
shared readout I/Q pair. Both runners render and upload the same number of
float64 samples. With `--live-waveform`, each path retains only the latest
completed point for a plotting-tool stand-in.

Run a short staircase with:

```console
uv run python scripts/benchmark_scan_execution.py \
  --profile waveform \
  --points 1,10,100 \
  --waveform-samples 4096 \
  --qubits 4 \
  --live-waveform \
  --host-label lab-pc
```

In addition to timing and RSS, compare `waveform_bytes_uploaded`,
`max_waveform_batch_bytes`, and `live_waveform_bytes_retained`. Live-view
retention must equal exactly one point's channel-by-sample payload. Maximum
batch upload reveals whether target entry batching multiplies that working set.
Increase waveform length independently of point count; do not combine this
profile with shot-heavy or raw-acquisition payloads.

Timing begins after the reusable lab/server and instrument composition exists.
The phase boundaries are:

- **prepare**: experiment submission, invocation construction, validation,
  planning, and compilation until the first physical trigger;
- **active**: first physical trigger through the final completed instrument
  collection; compilation, uploads, execution, and collection may overlap here;
- **finalize**: final collection through the completed, durable run return;
- **wall**: prepare plus active plus finalize;
- **first result**: submission through the first completed collection, retained
  as a secondary diagnostic rather than a required one-point batch.

Interpreter import, daemon cold start, reusable service composition, and backend
endpoint construction are outside this profile. Run-scoped instrument
provisioning and connection are inside preparation. Cold-start costs should be
measured separately if they affect the normal launch workflow. The primary UX
gates are preparation and wall time. Peak resident-memory growth and durable
object/file growth identify whether a failure is caused by eager planning,
in-memory retention, transport, or persistence amplification.

Until measurements justify tighter product budgets, use these provisional
acceptance gates:

- preparation remains below one second at the intended scan size and does not
  grow linearly with total points;
- with representative point dwell, Scopecat adds no more than 10% or one second
  to total wall time, whichever allowance is larger;
- peak memory is bounded by physical batch and current-point payload size, not
  total scan waveform volume;
- durable file and control-record counts grow with batches or checkpoints, not
  one object per logical point.

The absolute one-second limits are UX budgets, not ratios against a nearly
zero-duration direct loop. Change them only with a recorded lab workflow and
repeatable measurements.

### Launch Validation and Materialization

Launch should perform only checks whose cost is expected to remain small
relative to one physical point: symbolic and type verification, configuration
resolution, static resource authority, and one fully compiled domain probe. It
does not render every point's waveforms to discover later lowering failures
before the run starts. The reference target probes one point, then uses the
concrete artifact to size the following batch. The current eager scalar point
domain and durable point catalog remain an explicit exception and the next
dense-spectroscopy preparation limit.

This is an intentional UX tradeoff. Structural mistakes fail before hardware;
shape- or value-dependent failures that require actual waveform lowering may
fail when their bounded batch is reached. A separate explicit exhaustive check
may be useful for unattended runs, but it must not become the default launch
path or silently materialize the full waveform volume.

Physical batching remains expressed as a contiguous point count, but its
capacity is not point-only. The reference compiler currently combines the
device entry limit with an 8 MiB aggregate waveform target derived from the
largest entry in the preceding compiled batch. Waveform channel count, sample
count, and dtype therefore reduce the following point count automatically. A
later abrupt increase in entry size can overshoot the target for one batch; the
next feedback corrects it. This adaptive target is a working-set control, not a
new logical experiment dimension.

The next capacity axes should be added only when their matched profile proves
they dominate a budget:

- shots and acquisition channels determine execution time and result volume;
- fixed or ragged trace samples determine binary result and analysis memory;
- configured topology determines routing and static authority cost;
- logical point count determines scalar point metadata, result rows, and batch
  count even when waveform memory is bounded.

Large shot and trace axes should remain structured result dimensions rather
than being flattened into more control-plane points.

## Current Implementation Boundaries

The present architecture provides a direct end-to-end baseline:

- linking and planning still eagerly materialize logical points, point
  parameter bindings, and the durable point catalog;
- local target preparation retains static route manifests, preview materializes
  only the first point, and execution materializes local compute and effects
  only for the current bounded coverage batch; local-only coverage starts with
  32 points and then uses batches of at most 256 points;
- domain compilation uses a backend-declared point capacity but prepares only
  the current batch during execution; preview compiles the initial one-point
  probe as a fast semantic preflight, and each prepared domain job reports the
  maximum point count for the following batch;
- the reference list-mode target combines its device entry capacity with an
  adaptive 8 MiB aggregate waveform target. Its AWG and virtual-capture codecs
  carry contiguous float64 samples in binary rather than expanding arrays into
  JSON numbers;
- admission uses the domain compiler's static instrument footprint and all
  structurally compatible local route candidates. Point-local routing narrows
  the operations actually emitted, so a run may conservatively reserve an
  unused candidate rather than scanning every point before admission;
- one SQLite writer owns durable ordering while immutable object storage carries
  large content, and measurement records are appended in chunks bounded by both
  record count and value bytes;
- ordinary command payload uploads use an in-memory spool scoped by run and
  hardware operation, or by direct session and command. A completed, rejected,
  or replayed operation releases its bytes immediately; owner termination and
  daemon shutdown clear orphaned uploads. Unique waveform programs therefore
  do not accumulate in the permanent object store or with total point count;
- projected Arrow readers and GUI previews provide bounded read paths.

The next dense-spectroscopy limit is the eager point domain, parameter binding,
and run point catalog: their preparation time and retained memory still grow
with total point count. Local effects and live prepared target artifacts are
bounded by the current physical batch. Inline command payloads retain raw bytes
in memory and convert to base64 only for an actual JSON wire representation;
the daemon client uploads those bytes to an operation-scoped content-addressed
spool before posting a control command containing only the blob descriptor.
Hardware operation identities and durable evidence cover the descriptor rather
than serializing the payload body.

The spool is deliberately transient: if the daemon restarts after an upload but
before the command is accepted, the client must submit the command again and
re-upload its payload. A lost response after execution remains replayable from
the operation ledger without materializing the released bytes. Permanent
publication remains a separate future capability for payloads that must be
inspectable after execution.

The production waveform profile now separates transient transfer, durable
object retention, compilation, and driver work. Its next limit is the eager
point domain, parameter binding, and run point catalog during preparation. The
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
