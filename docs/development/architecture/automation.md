# Durable procedure automation

Scopecat's first automation boundary coordinates a small number of related runs
and analysis publications without moving user-authored Python into the daemon.
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
        `-- future config op --> ConfigActivationOutputRef
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

Workers hold renewable leases. Every state change is fenced by the lease token
and expected revision; heartbeat renewal does not change the business revision.
An expired worker may be replaced, but it cannot checkpoint late work. The
notebook client therefore uses a process-local worker identity by default;
another process waits for lease expiry or supplies its own operator-managed
identity rather than impersonating the previous worker.

A known failure inside a step records a failed attempt and closes the procedure
as failed. A validation failure between steps, such as a rejected verification,
closes only the procedure because every preceding effect is already known. An
unknown child-run or publication outcome instead moves the owning step and
procedure to `attention_required`; the child run retains its own authoritative
terminal or control state. Restart does not retry the effect or execute later
steps. Operator reconciliation remains explicit.

## Present supported slice

The reference DRAG procedure demonstrates the supported boundary:

1. run a baseline scan against an exact configuration snapshot and source;
2. publish the run-scoped fit and parameter proposal;
3. run the candidate configuration with exact analysis provenance;
4. publish a project-owned comparison and require an accepted decision.

Candidate activation, production validation, and undo remain explicit. Current
configuration commands use generation compare-and-swap but do not yet have a
stable operation receipt that can distinguish a lost response from an effect
that never happened. In particular, relative `undo()` must not be replayed.

The initial implementation deliberately has no DAG representation, automatic
retry policy, fan-out scheduler, cron trigger, or dynamic loop checkpoint. A
linear Python procedure with durable step checkpoints is easier to inspect and
already covers the first multi-run calibration loop.

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
- durable scheduling and worker discovery, including version availability,
  heartbeats, cancellation, and operator attention queues;
- bounded procedure, cohort, and lineage queries plus aggregate progress and
  failure summaries for the project console;
- operation receipts for configuration activation and other non-run effects;
- simulation, dry-run planning, workload budgets, and reference-device scale
  tests before enabling a large cohort.

These features should extend the same exact-reference and idempotency contracts.
They should not introduce a second run engine, analysis store, or configuration
authority inside an automation subsystem.

## Evolution order

The next safe increments are:

1. finish the single-worker DRAG vertical test, including response-loss and
   unknown-outcome recovery points;
2. add stable configuration operation IDs and receipt lookup, then support an
   explicit activate-entry step with compare-and-swap;
3. add durable schedules and a project worker loop over ready procedures;
4. add immutable cohorts, freshness/dependency evaluation, and bounded fan-out;
5. add policy gates and hierarchical proposal merge for device-wide campaigns.

A DAG becomes useful only when fan-out and dependency scheduling are real
requirements. Until then, persisted imperative checkpoints remain the smaller
and clearer model.
