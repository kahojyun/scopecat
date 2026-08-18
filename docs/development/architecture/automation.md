# Durable procedure automation

Scopecat's first automation boundary coordinates a small number of related runs,
analysis publications, exact configuration publications, and saved-entry
activations without moving
user-authored Python into the daemon.
It is intended for one-lab calibration procedures that must survive a notebook
or worker restart. It is not yet a scheduler for a whole device.

## Ownership split

The project application owns a versioned `ProcedureRegistry`. A procedure is a
deterministic imperative Python function with a typed, JSON-encoded initial
intent. The daemon stores only its definition reference, intent, current state,
step attempts, leases, and typed output references. A project worker loads the
same registry and replays the function from its beginning.

The definition fingerprint covers the registered function source and intent
schema. Analysis invocation fingerprints additionally cover their bound
arguments, defaults, and nonlocal closure values. Authors must still bump the
explicit procedure version when a transitive imported dependency changes; a
source fingerprint is not a Python environment lockfile.

The daemon must never pickle, import, or deserialize a procedure closure. The
worker must never replace the authoritative run, analysis, configuration, or
procedure stores. A procedure step invokes those existing services and records
only the resulting durable reference.

```text
project procedure function
        |
        v
lease-fenced ProcedureContext
        |
        +-- run step ----------> RunOutputRef
        +-- analysis step -----> AnalysisPublicationOutputRef
        +-- config publish ----> ConfigPublishOutputRef
        `-- config activation -> ConfigActivationOutputRef
                 |
                 v
      existing authoritative services
```

## Replay contract

A submission is unique by `(procedure_id, request_key)`. Its content hash covers
the exact definition version and fingerprint plus the canonical initial intent.
Reusing the key with different content is a conflict.

A step is unique within a procedure run by its stable key. The persisted intent
records the operation kind, exact upstream output references, and an intent
hash. Replaying the same key and intent returns its recorded output. Reusing the
key with different content is a conflict and does not execute an effect.

The daemon derives a stable operation ID from the procedure run, step key, and
attempt. A child run uses it as both the run submission ID and executor intent.
Analysis uses a procedure-specific logical key and first reopens the exact `r1`
record after a possible response loss. The publication subject, analysis step,
and declared durable upstream owners are checked before the reference is
checkpointed. Output-level lineage remains in the immutable analysis record
rather than being duplicated in the procedure step.

An activate-entry step passes the same stable operation ID to the configuration
command. The configuration registry commits that operation's canonical intent
and activation generation atomically with the mutation. After transport loss,
the worker reopens that exact operation before checkpointing a
`ConfigActivationOutputRef`. The target entry and expected generation are
explicit step intent; the worker never refreshes the generation during replay.

A config-publish step uses the same contract for a new immutable revision. Its
intent pins the exact candidate proposal, project-owned decision fact, target
entry, and expected generation. The candidate analysis and verification
publication are exact step inputs. Proposal approval, entry creation, activation,
and the operation receipt share one transaction; a lost response is reconciled
through the exact publish-operation lookup before the worker checkpoints a
`ConfigPublishOutputRef`.

Workers hold renewable leases. Every state change is fenced by the lease token
and expected revision; heartbeat renewal does not change the business revision.
An expired worker may be replaced, but it cannot checkpoint late work. The
notebook client therefore uses a process-local worker identity by default;
another process waits for lease expiry or supplies its own operator-managed
identity rather than impersonating the previous worker.

A known failure inside a step records a failed attempt and closes the procedure
as failed; a rejected verification therefore fails the candidate-publication
step without changing the registry. A validation failure between steps closes
only the procedure because every preceding effect is already known. An unknown
child-run, publication, or configuration-operation outcome instead moves the
owning step and procedure to `attention_required`; each domain service keeps its
own authoritative result. Restart does not retry the effect or execute later
steps. Operator reconciliation remains explicit.

## Present supported slice

The reference DRAG procedure demonstrates the supported boundary:

1. run a baseline scan against an exact configuration snapshot and source;
2. publish the run-scoped fit and parameter proposal;
3. run the candidate configuration with exact analysis provenance;
4. publish a project-owned comparison and require an accepted decision;
5. publish and activate that candidate using the exact proposal and decision.

The procedure API can publish a verified candidate or activate one already-saved
configuration entry with generation compare-and-swap and an exact operation
receipt. Policy remains explicit in the procedure: only the project verification
fact authorizes DRAG candidate acceptance. The production run remains outside
the procedure, and final cleanup reactivates the exact starting entry instead of
calling relative `undo()`. Relative `undo()` is not a replayable compensation
action.

The initial implementation deliberately has no DAG representation, automatic
retry policy, fan-out scheduler, cron trigger, or dynamic loop checkpoint. A
linear Python procedure with durable step checkpoints is easier to inspect and
already covers the first multi-run calibration loop.

## One-shot schedules and project workers

A durable procedure schedule freezes one exact definition reference, canonical
intent, and UTC due time. Materialization derives a stable request key from that
whole schedule and atomically admits one `ProcedureRun`. Recreating the same
schedule is idempotent; changing its exact content under the same schedule ID is
a conflict. Due-time processing never rebuilds intent from the active
configuration or the worker's current Python environment.

`scopecat procedures work PROJECT` runs the project-owned Python worker as a
process separate from the daemon. Each bounded cycle first materializes due
schedules, then asks the daemon for oldest-first runnable procedures matching
the worker registry's exact definition references. A live lease or acquisition
race does not stop later work. A definition unavailable in this worker is not
returned by capability-filtered discovery and is not changed to operator
attention; another exact-version worker can claim it later.

Due discovery is keyset-paged in durable insertion order, oldest insertion
first; `due_at` remains a server-clock eligibility filter rather than the sort
key. Each traversal freezes the current highest durable sequence, so sustained
new arrivals cannot make that scan infinite. Reaching the high-water clears the
cursor and the next traversal wraps to the beginning, where it can observe a
lower-sequence schedule that became due after the prior cursor passed it. A
still-pending materialization conflict therefore cannot pin all later due
schedules behind the first bounded page.

Before due discovery, the same project worker evaluates an immutable
`ProcedureScheduleRegistry`. Its first recurring trigger is deliberately narrow:
an aware UTC anchor plus a fixed positive `timedelta`. Evaluation selects only
the latest due ordinal in constant time. It neither expands every missed slot
nor creates a future occurrence before its due time. Cron, civil-time zones,
DST policy, and catch-up-all remain outside this contract.
There is no durable series cursor yet: if the project wall clock moves backward,
the latest-only calculation can select an older ordinal that was never
materialized. Exact IDs still deduplicate ordinals that do exist, but deployments
must provide a trustworthy UTC clock until an explicit clock-watermark policy is
added.

Each selected interval slot becomes an ordinary exact one-shot schedule. Its ID
depends only on the logical schedule ID, schedule version, and ordinal—not on
the current procedure fingerprint, active configuration, or generated intent.
The planner first reopens that ID. Only a definite not-found result may invoke
the context-aware intent builder, whose context exposes read-only exact
configuration views. This ordering makes an existing occurrence authoritative
after restart or rolling code changes and prevents rebuilding the same slot from
mutable configuration. A concurrent create conflict or lost response is
reconciled by reopening the same ID. A different due time or exact procedure ref
under that existing shell is reported as drift and never overwritten.

The only overlap policy is currently `enqueue`: a newly selected slot is admitted
independently even if the previous occurrence has not closed. The registry
allows only one active version for a logical schedule ID, so registering v1 and
v2 together cannot accidentally double a stream. Removing or upgrading a
definition does not cancel one-shots already committed to the daemon. The
explicit schedule version is the policy compatibility boundary: changing its
builder, anchor, interval, target procedure, or overlap policy requires a version
bump. Reusing a version with a different shell is reported as drift for an
existing ordinal; future ordinals otherwise have no historical spec to compare.

`--once` performs one bounded plan-materialize-dispatch cycle for manual
operation and testing. The resident form polls with interruptible waits and
exponential control-plane backoff. Shutdown stops new work on `SIGINT` or
`SIGTERM`. An already-started effect completes and checkpoints; at the next
durable step boundary the worker releases the procedure ready for another exact
worker. If there is no next step, the procedure closes successfully. There is no
mid-effect cancellation contract.

## Capabilities needed at larger chip scale

Moving from one calibration to hundreds or thousands of related calibrations
requires additional control-plane concepts, not a larger procedure function:

- selectors and immutable cohorts for qubits, couplers, channels, and regions;
- dependency and freshness records that explain why a calibration is due and
  which downstream values become stale after a change;
- resource-aware bounded fan-out, backpressure, priorities, and maintenance
  windows while retaining stable per-unit step identities;
- hierarchical configuration proposals and merge/conflict checks, so parallel
  calibrations do not publish whole-device snapshots over one another;
- explicit quality gates, approval policy, stop conditions, and rollback to an
  exact entry rather than a relative undo;
- richer recurring scheduling and worker-fleet discovery, including cron/civil
  time, version availability, worker heartbeats, maintenance windows, and
  operator attention queues;
- bounded procedure, cohort, and lineage queries plus aggregate progress and
  failure summaries for the project console;
- operation receipts for other mutating non-run effects, including inventory
  migration or exact rollback commands;
- simulation, dry-run planning, workload budgets, and reference-device scale
  tests before enabling a large cohort.

These features should extend the same exact-reference and idempotency contracts.
They should not introduce a second run engine, analysis store, or configuration
authority inside an automation subsystem.

## Evolution order

The next safe increments are:

1. add immutable cohorts, freshness/dependency evaluation, and bounded fan-out;
2. add policy gates and hierarchical proposal merge for device-wide campaigns;
3. extend fixed-UTC latest-only intervals with explicit maintenance-window and
   richer missed-slot policies only when operators require them.

A DAG becomes useful only when fan-out and dependency scheduling are real
requirements. Until then, persisted imperative checkpoints remain the smaller
and clearer model.
