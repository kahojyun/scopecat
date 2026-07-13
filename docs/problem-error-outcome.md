# Problems, Failures, Outcomes, Events, and Logs

Status: direction and contract

Scopecat keeps five reporting channels separate. They may refer to the same
incident, but they do not substitute for one another.

| Channel | Purpose | Durable |
|---|---|---|
| `Problem` | Expected, machine-readable domain finding | When embedded in durable evidence |
| `ProblemFailure` | Python control flow for an operation blocked by problems | No |
| `RunOutcome` and effect transitions | Authoritative facts about accepted external effects | Yes |
| Runtime event | Lossy live observation for notebooks and UIs | No |
| Python logging | Tracebacks and developer-facing operational detail | No |

## Problem Contract

A problem owns a stable domain code, impact, category, phase, public message,
structured location, JSON-safe details, and optional related locations. The
message is presentation text; callers must not parse it. Machine-readable
identities, expected and actual values, and recovery context belong in
`details` and locations.

`advisory` problems do not prevent a phase from completing. `blocking`
problems do. Informational progress is an event or log record, not a problem.

Problem codes are owned by their domain and remain strings so extensions can
define codes without extending a global enum. Categories and phases are the
small shared vocabulary used for generic handling.

Locations are a discriminated union:

- model locations address a root plus structural string/index path segments;
- storage locations address a run, ref, and optional structural path;
- external locations address an URI and optional sheet/row/column/path;
- runtime locations address a run operation, point, or instrument.

Delimiter-packed paths are not semantic identity.

## Failure Contract

`ProblemFailure` contains an immutable, non-empty tuple with at least one
blocking problem. Check failures, not-found results, conflicts, data-integrity
failures, storage failures, and provider-contract failures have distinct public
types. Internal invariant violations are not converted into expected problems.

Pure host measurement transforms have their own
`MeasurementTransformExecutionError` operation boundary. Source-inventory
mistakes, host-kernel faults, and invalid returned carriers are not provider ABI
failures and never create domain submission uncertainty. Kernel exceptions keep
their Python cause for local debugging, while structured problems and logs keep
only sanitized transform, implementation, semantic, point, and exception-type
identities. Given the same closed source fragments, retry is safe and does not
resubmit, refetch, or reconcile target work.

Pure compiler code catches only declared domain errors. Broad exception
handling is restricted to explicit user callbacks, providers/drivers, storage
boundaries, safety finalization, and top-level workflow boundaries. An
unexpected exception keeps its Python cause and traceback in transient logs;
durable evidence receives only a stable, sanitized problem.

An independent domain invocation is an operation boundary, not a terminal run.
Its submit/fetch/reconcile helpers therefore use operation-level failures and
sealed state capabilities: Known can be fetched, Uncertain can be reconciled,
and Absent can authorize a new idempotency-key generation. These states do not
pretend to be `RunOutcome`. If post-effect journal persistence fails, the error
retains run/operation/call-attempt/key/job context and, for submit, the sealed
Uncertain recovery authority.

## Run Outcome Contract

Run lifecycle, terminal outcome, and certainty are independent:

| Dimension | Values |
|---|---|
| Lifecycle | `accepted`, `running`, `terminal` |
| Outcome | `succeeded`, `failed`, `cancelled` |
| Certainty | `known`, `indeterminate` |

Termination reason and retry disposition are separate fields. A cancelled run
may still be indeterminate when a hardware effect was in flight. A persistence
failure after external effects always reports the run id, committed evidence
refs, pending ref, certainty, reconciliation instruction, and retry disposition.

The execution journal is the authoritative effect and recovery history. Pure
point progress, host computation, and repeatable state readback are runtime
observations rather than recovery facts and are not written to that ledger. A
terminal outcome is the durable projection used for normal reads, while
execution summaries are caches and manifests are indexes and commit markers.

## Events and Logging

Runtime events are typed, lossy projections of both transient progress and
committed effect transitions. Durable projections retain their journal
sequence; transient projections have no journal sequence. Neither is a replay
or audit contract. Raw payload observations remain a separate, explicit opt-in
channel.

Scopecat uses standard Python logging and never configures application
handlers. Expected problems are not logged merely because they were returned.
Unexpected exceptions, observer failures, and unexpected safety or persistence
failures are logged with structured run/operation context. Payload contents,
device responses, secrets, and private configuration are not logged by default.

## Boundary Truth Table

| Situation | Result |
|---|---|
| Invalid authoring/config intent | `CheckFailed` with blocking problems; no run |
| Missing requested object | `NotFound` |
| Concurrent or immutable-state conflict | `Conflict` |
| Persisted data is malformed or inconsistent | `DataIntegrityError` |
| Storage cannot complete an operation | `StorageError` with original cause |
| Provider ABI is invalid before acceptance | `ProviderContractError`; no run |
| Expected driver negative result | Typed apply/collect receipt with problems |
| Unexpected driver fault | Sanitized runtime problem plus transient traceback |
| Run reaches known failed terminal state | `RunFailed` with durable outcome |
| Full-run effect result is uncertain | `RunIndeterminate`; reconcile before retry |
| Domain submit result is uncertain | `DomainSubmissionIndeterminate` with sealed Uncertain state |
| Domain fetch/reconcile read fails | Typed operation failure; same Known/Uncertain state is safe to retry |
| Domain receipt evidence cannot be committed | `DomainRuntimePersistenceError` with operation recovery context |
| Pure host measurement transform fails | `MeasurementTransformExecutionError`; no external uncertainty or reconciliation |
| Terminal evidence cannot be committed | `RunPersistenceError` with run id and committed refs |
| UI observer or event sink fails | Log the observer fault; run semantics are unchanged |
