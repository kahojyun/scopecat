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
review, which calibration update path was used or left open, and which later
task needed an unavailable prior output. The output should identify which parts
are observed sample patterns, user-clarified desired behavior, or proposed
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

## User Review Notes

These notes record the first user critique of the pain-discovery fixtures. They
are validation inputs, not accepted architecture or product commitments.

### Batch Intent Needs A Minimal Local Executor

The user does not see a batch intent record alone as sufficient. A complex
intent that users must parse and execute themselves does not solve the pain.
The early boundary should therefore test a **minimal local executor** or a
small standalone package that can interpret the intent.

This does not automatically promote a full managed runner. The validation
ladder becomes:

1. helper-generated intent around ordinary Python;
2. local executor for simple sequential and dataflow cases;
3. outcome report;
4. later reliability features such as retry, resume, priority scheduling,
   resource leases, and richer DAG translation.

The intended user-facing shape should feel like builder code or decorated
functions, not hand-authored manifest files. The manifest is a serialized
record and interchange format, not the first authoring surface.

### Intent Declaration Comes From Users First

Early fixtures should assume users or helper APIs declare task order, inputs,
outputs, and mutual exclusion. Later, a fuller system may derive some of this
from recorded experiment context, parameter memory, templates, or code
snapshots. Arbitrary code inference is still out of scope.

### Dataflow Is Logical, Not Transport

Inputs and outputs are logical task products or state IDs. The concrete
transport may still be Python variables, files, notebook state, or Scopecat
records in existing workflows. Early validation should test whether logical
dataflow is enough for review and simple local execution without requiring a
full artifact routing system.

### Measurement Data Should Not Be Too Narrow

The user's preferred direction is an Arrow-table-like data model plus a custom
manifest for complex structures. IQ data, shots, traces, and VNA-like data are
ordinary measurement needs and should not be deferred. `ndarray` support is
less certain for measurement plotting, but may matter for analysis outputs.

This note does not decide storage, reader API, or export format. It does mean
the measurement fixture should avoid implying that simple scalar CSV examples
are enough to validate the measurement data model. Measurement validation needs
ordinary complex cases such as IQ, shots, traces, VNA-like records, and possibly
analysis `ndarray` payloads.

### Calibration Proposal Apply Is Still Open

The current fixture keeps calibration proposals as review-only with no
write-back. The user questioned whether a non-applying proposal will be adopted:
in real experiments, calibration updates are often directly applied with
variable-assignment-like code. A proposal-only path may require extra code
without obvious benefit unless parameter memory automatically records and
displays diffs around existing update code.

So the open question is not "should Scopecat apply calibration now?" but:

- Can users keep their direct update style while Scopecat records parameter
  memory and diffs?
- Is explicit proposal useful as an optional higher-safety path?
- What is the smallest fixture that compares direct apply with proposal/review
  without accepting autonomous calibration?

### Code Snapshot Minimum

The most important code provenance field is the entrypoint. Recording it is
simple and high value. For user-owned code, folder selection plus an ignore
mechanism may be enough initially. Third-party dependency capture affects full
reproducibility, but it is less central to experiment intent and can remain a
lower-priority readiness detail.

### First User-Visible Outputs

The likely first visible outputs are:

| Fixture | First useful output |
| --- | --- |
| Batch intent/outcome | Run report from the minimal local executor. |
| Code snapshot | Exported snapshot folder with entrypoint and selected code evidence. |
| Measurement data/attachments | Reader API or export path over recorded data plus attachments. |

### Prioritization

The user did not choose one fixture as the only next prototype; all three are
valuable. Prioritization should therefore be by cost-to-learning ratio:

- Batch fixture tests whether a minimal local executor can solve immediate
  unattended/sequential workflow pain without full orchestration.
- Code snapshot fixture tests whether explicit entrypoint plus selected folder
  capture solves most no-git provenance pain.
- Measurement fixture tests the recording substrate needed by both batch
  reports and later analysis/handoff.
