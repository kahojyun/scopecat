# Pain-Discovery Fixture Drafts

## Status

Draft validation fixtures. These are not accepted journey candidates,
contracts, schemas, product requirements, or architecture decisions.

## Purpose

These fixtures test whether several solution-shaped ideas in the evidence
inventory are real user pains, enabling capabilities, or premature design.

The main ideas under review are:

- managed execution;
- code registry or automatic code version management;
- batch or queue intent;
- explicit recording versus arbitrary code inference;
- migration support for legacy sidecars and hand-built artifact bundles.

Each fixture is public-safe and synthetic. The fixtures are intentionally small
so the user can critique the pain framing before implementation details harden.

## Fixture Set

| Fixture | Path | Main question |
| --- | --- | --- |
| Batch intent and outcome | `tests/fixtures/pain-discovery-batch-intent-outcome/` | Is the pain execution ownership, or reviewable batch intent/outcome/failure policy? |
| Code snapshot and explicit record | `tests/fixtures/pain-discovery-code-snapshot-explicit-record/` | Is a simple code snapshot plus explicit run record enough before a code registry exists? |
| Measurement record and attachments | `tests/fixtures/pain-discovery-measurement-data-attachments/` | Which outputs should become system-managed measurement data, and which remain attached artifacts? |

## Grounding Labels

The fixture fields should be read with these support levels:

| Label | Meaning |
| --- | --- |
| `direct sample` | Visible in static sample source or artifacts. |
| `sample plus user clarification` | The sample shows the current pattern or pressure, while the user clarification supplies the future-state meaning. |
| `user clarification only` | Explicitly described by the user, but not visible in the sample. |
| `premature` | Useful as a design probe only; do not promote without a fixture, helper, or user validation. |

## Fixture 1: Batch Intent And Outcome

### Pain Tested

Notebook or IPython can already run multiple cells, but it gives weak support
for reviewing intended task order, continuing independent work after a failure,
recording failure or retry intent and observed outcomes, and using idle time
for lower-priority calibration.

Sample grounding: direct sample evidence supports sequential scans, sweep
intent, recording, interruption, failure/retry traces, and calibration
proposal/write-back pressure. Ordering constraints, mutual exclusion, priority
arbitration, independent continuation after failure, and idle backfill are
user-clarified or premature unless a later helper fixture proves them.

The batch fixture should avoid an expansive status vocabulary. Use a small set
such as `pending`, `succeeded`, `failed`, `blocked`,
`waiting_for_review`, `skipped`, and `canceled`, then attach context fields for
why a task continued, waited, was blocked, or was skipped. Use
`waiting_for_review` for the task or output that needs a human decision. Use
`blocked` for a downstream task that cannot start because a required input,
dependency, or resource is unavailable. This keeps product validation focused
on useful review semantics rather than a runner-specific state machine.

The fixture should also model task dataflow. In real Python/notebook workflows,
later tasks often depend on earlier results through Python variables, files, or
sidecar records. Represent that as declared `inputs` and `outputs`, while
keeping `ordering.not_before` for non-data ordering such as warmup, operator
preference, or conservative sequencing. A future executor can derive ordering
from data dependencies, but the pain-discovery fixture should keep both concepts
visible so users can say why one task waits for another.

Inputs and outputs can also name logical states of the same mutable artifact at
different stages, such as `parameters-before-readout-cal` and
`parameters-after-readout-cal-proposal` for a shared `parameters.json`. In that
case, `mutual_exclusion_keys` should express the shared mutable resource, while
`inputs` and `outputs` express which state a later task depends on. The fixture
does not require Scopecat to diff, write, snapshot, or rollback the file.

### Current Workaround

Users queue notebook cells, write loops manually, copy parameters into side
files, and decide after the fact which outputs correspond to which planned
task.

### Input Artifacts

- `batch-intent.json`: declared task list, priorities, dependencies, failure
  policy, review gates, inputs, and outputs.
- `outcome-log.json`: actual task statuses and links to produced records.
- `records/*.json`: tiny measurement or proposal records produced by tasks.

### Expected Scopecat Output

Scopecat should show intended versus actual execution, which failure did not
block later work with no `not_before` dependency, which task waited for human
review, which calibration result is only a proposal, and which later task
needed an unavailable prior output. The output should identify which parts are
observed sample patterns, user-clarified desired behavior, or proposed
managed-runner semantics.

### Explicit Unknowns

The fixture does not prove Scopecat must own scheduling, retries, resource
locking, hardware execution, or priority arbitration. It only tests whether the
manifest and outcome record are useful enough before those capabilities exist.

### Success Criteria

The user can review the batch before leaving the lab and later understand which
tasks ran, failed, continued, waited for review, or produced proposals.

## Fixture 2: Code Snapshot And Explicit Record

### Pain Tested

Non-git users manage experiment code through copied folders, renamed files,
comments, and notebook copies. The pain may be code identity and selected
entrypoint, not a full code registry.

### Current Workaround

Users copy whole notebooks beside data, but a long notebook does not tell which
cell or function actually produced a result.

### Input Artifacts

- inert text-only code files;
- two code snapshot manifests with hashes and version notes;
- one run record that explicitly names the selected template and snapshot;
- notebook-cell evidence that is marked ambiguous unless explicitly recorded.

### Expected Scopecat Output

Scopecat should show which template snapshot was explicitly used, what helper
files were included, and what remains unknown because it was not recorded.

### Explicit Unknowns

Scopecat should not infer arbitrary notebook state, import code, execute code,
resolve a full dependency graph, or decide which copied file is canonical.

### Success Criteria

The user can decide whether code snapshot and explicit entrypoint recording
solve most provenance pain before designing a code registry or managed runner.

Sample grounding: copied folders, backup variants, duplicated helpers, mutable
notebooks, path hacks, and weak canonical identity are direct sample evidence.
Explicit selected entrypoints, hash-based snapshots, and dependency summaries
are user-clarified desired records. Code registry, bare git management,
`uv.lock`, temp run folders, and managed runners remain future hypotheses.

## Fixture 3: Measurement Record And Attachments

### Pain Tested

Legacy Data Vault-like constraints force raw-ish measurement sidecars into
nearby files. Future Scopecat records may need a cleaner system-managed
measurement table plus metadata, while cross-run analysis outputs may remain
attachments.

### Current Workaround

Users write extra files next to `NNNNN - <name>` style folders or attach
derived files without a stable source relation.

### Input Artifacts

- one primary dataframe-like measurement CSV;
- metadata with axes, units, task relation, and context refs;
- attached derived summary and inert plot placeholder;
- attachment roles and source-run relations.

### Expected Scopecat Output

A review view should show the proposed split between primary system-managed
measurement data and cataloged attachments, while preserving which parts are
legacy workaround evidence. The fixture should not imply a final storage
format, reader API, GUI contract, or source-relation schema.

Sample grounding: the sample directly supports Data Vault-like tables,
independent/dependent columns, row capture, CSV exports, run-adjacent parameter
sidecars, JSON/NPZ sidecars, derived arrays, notebooks, PDFs, workbooks, and
decks. The desired system-managed primary measurement format comes from user
clarification.

### Explicit Unknowns

The fixture does not validate universal parsing for arbitrary binary files,
publication workflows, analysis reruns, or a final storage/API schema.

### Success Criteria

The user can separate "measurement data format Scopecat should own" from
"artifact attachments Scopecat should catalog and link."

## Review Questions

Use these prompts when reviewing the fixtures:

1. Which fixture reflects a real experiment episode most closely?
2. Which fixture still smuggles in a solution you are not confident about?
3. Which fields are necessary before leaving the lab, and which are only useful
   after something goes wrong?
4. Which fields should be produced by user code explicitly rather than inferred?
5. Which behavior would make Scopecat too close to a runner, code registry,
   deployment manager, or report generator too early?
