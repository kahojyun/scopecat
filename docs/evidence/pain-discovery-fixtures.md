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
| Parameter memory bad-state handling | `tests/fixtures/pain-discovery-parameter-memory-bad-state/` | Is retain-by-default history with yank/exclusion enough for bad parameter states before write-back exists? |
| Code version selection | `tests/fixtures/pain-discovery-code-version-selection/` | Does selecting a prior code version or branch variant need load-and-run behavior, or is provenance-only tracking enough? |
| Measurement record and attachments | `tests/fixtures/pain-discovery-measurement-data-attachments/` | Which outputs should become system-managed measurement data, and which remain attached artifacts? |
| Long-run watchdog and replay | `tests/fixtures/pain-discovery-long-run-watchdog/` | Can explicitly recorded partial slices produce useful, replayable advisory evidence before live control or autonomous calibration? |

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

The strongest target episode is a multi-step calibration flow like the one in
[`research/extracted/experimental-lab-workflow-reference.md`](research/extracted/experimental-lab-workflow-reference.md):
several calibration steps must run in order, individual steps may be split by
qubit group, groups on the same chip often must not run concurrently, each
group can produce its own fit and score, low-scoring fits may need human
review, other groups should continue when safe, and later steps such as gate
calibration should resume from the stopped point after review or mark only
selected groups for remeasurement. In many chip workflows, the chip/group
conflict and the instrument conflict are effectively the same resource
constraint; the fixture should not imply a separate chip scheduler when an
abstract instrument/resource key is enough.

Sample grounding: direct sample evidence supports sequential scans, sweep
intent, recording, interruption, failure/retry traces, and calibration
proposal/write-back pressure. Ordering constraints, mutual exclusion, priority
arbitration, independent continuation after failure, and idle backfill are
user-clarified or premature unless a later helper fixture proves them. The
multi-step calibration flow is user-clarified and domain-grounded, not yet
directly proven by static sample artifacts.

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

Scopecat should show intended versus actual execution, which failure or review
trigger did not block later work with no `not_before` dependency, which task
waited for human review, which calibration update path was used or left open,
and which later task needed an unavailable prior output. The output should
identify which parts are observed sample patterns, user-clarified desired
behavior, or proposed managed-runner semantics.

### Explicit Unknowns

The fixture does not prove Scopecat must own scheduling, retries, resource
locking, hardware execution, or priority arbitration. It only tests whether the
manifest and outcome record are useful enough before those capabilities exist.

### Success Criteria

The user can review the batch before leaving the lab and later understand which
tasks ran, failed, continued, triggered review, waited for review, or produced
proposals.

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

## Fixture 3: Parameter Memory Bad-State Handling

### Pain Tested

Users need to retry with prior parameter states, keep multiple working-point
branches, and exclude bad writes from drift analysis without deleting history
or accepting Scopecat-owned write-back.

### Current Workaround

Users keep multiple parameter files, copy old files back manually, or remember
which intermediate states were bad enough to ignore during later analysis.

### Input Artifacts

- `states/parameter-history.json`: tiny parameter timeline with active,
  yanked, and branch-moved states.
- `queries/drift-query.json`: example drift query that excludes a yanked bad
  state by default.
- `runs/run-links.json`: run-to-parameter-state links for retry and
  explanation.

### Expected Scopecat Output

Scopecat should show retained history, active branch heads, which run used
which parameter state, which bad state is excluded from default drift queries,
and why hard delete is cleanup-only.

### Explicit Unknowns

The fixture does not define parameter storage, schema evolution, write-back,
rollback automation, permission policy, or a universal parameter model.

### Success Criteria

The user can decide whether retain-by-default history plus yank/exclusion
semantics solves the bad-parameter-state pain before mutation ownership exists.

## Fixture 4: Code Version Selection

### Pain Tested

Code snapshot export improves retrospective provenance, but may not improve
experiment workflow if users still have to copy selected code versions back
into an experiment directory manually.

### Current Workaround

Users copy whole folders, rename files, keep exploratory variants, or manually
restore an older known-good script before running an experiment.

### Input Artifacts

- `versions/version-index.json`: prior known-good, current, and exploratory
  code-version choices.
- `selection/selection-plan.json`: comparison between `tracking_only` and
  `load_selected_version`.
- `records/run-record-loaded-version.json`: selected-version run record.
- `code/*.py`: inert public-safe code text; must not be executed by static
  analysis prototypes.

### Expected Scopecat Output

Scopecat should show which version was selected, why it was selected, which
entrypoint would run, and whether the path is provenance-only or a future
load-and-run capability hypothesis.

### Explicit Unknowns

The fixture does not accept a code registry, dependency-closure contract, temp
run folder, isolated process API, or managed runner.

### Success Criteria

The user can decide whether code-version selection is real experiment value and
whether tracking-only is too weak to drive adoption.

## Fixture 5: Measurement Record And Attachments

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
- tiny IQ and trace seed tables that show scalar CSV is not complete
  measurement-model coverage;
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
publication workflows, analysis reruns, or a final storage/API schema. It also
does not complete the measurement data model; shots, VNA-like data, and
analysis ndarray payloads remain missing validation cases.

### Success Criteria

The user can separate "measurement data format Scopecat should own" from
"artifact attachments Scopecat should catalog and link."

## Fixture 6: Long-Run Watchdog And Replay

### Pain Tested

Long-running measurements may need method-aware quality, anomaly, or decision
feedback before the full run finishes, but that feedback must be explicitly
recorded, replayable, and non-intrusive.

### Current Workaround

Users watch plots, callbacks, notebooks, or framework dashboards and may lose
the evidence behind stop, continue, repeat, zoom, or retune decisions.

### Input Artifacts

- `records/partial-sweep-record.json`: explicit partial-sweep data and
  lifecycle events.
- `data/partial-sweep.csv`: tiny public-safe partial sweep table.
- `records/decision-packet.json`: advisory quality/anomaly decision evidence.
- `records/replay-check.json`: expected replay result from recorded inputs.

### Expected Scopecat Output

Scopecat should show which slice was complete enough for analysis, the
quality/anomaly evidence, the advisory recommendation, and whether the same
decision can be replayed from recorded inputs.

### Explicit Unknowns

The fixture does not accept live control, scan-plan mutation, parameter
write-back, framework scraping, alerting UI, opaque AI advice, or autonomous
calibration.

### Success Criteria

The user can decide whether explicit partial-recording plus replayable decision
packets are useful before any live-advisory or automation surface exists.

## Source-Support Map

This table maps user-refined fixture claims back to support so they do not
become undocumented product commitments.

| Claim | Source family | Direct sample support | User clarification | Fixture path | Still hypothetical |
| --- | --- | --- | --- | --- | --- |
| Minimal local executor is needed because batch intent alone is not useful enough. | User clarification; workflow improvement case | Sequential scans, loops, interruptions, retry traces | Record-only intent would leave users parsing their own manifest. | `pain-discovery-batch-intent-outcome/` | Full managed runner, retry/resume engine, scheduler |
| Grouped calibration with review gates is the strongest batch episode. | User clarification; quarantined workflow reference | Calibration fit/update pressure only | Multi-step calibration, group-level fit scoring, review, continuation, resume/remeasure | `pain-discovery-batch-intent-outcome/` | Real resource leases, enforced concurrency, autonomous scheduling |
| Parameter bad states should be retained by default and excluded/yanked from drift. | User clarification; workflow improvement case | Mutable parameter files and copied snapshots | Do not delete by default; hard delete only for cleanup such as accidental large payloads | `pain-discovery-parameter-memory-bad-state/` | Write-back, rollback automation, permission model |
| Code-version selection may need load-and-run to improve experiment QoL. | User clarification; workflow improvement case | Copied folders, variants, weak canonical identity | Tracking-only helps provenance but may not drive adoption | `pain-discovery-code-version-selection/` | Code registry, process isolation contract, dependency closure |
| Measurement data model cannot be validated by scalar CSV only. | User clarification; sample artifact review | Data Vault-like tables, sidecars, arrays | IQ, shots, traces, VNA-like records are ordinary needs | `pain-discovery-measurement-data-attachments/` | Final Arrow/storage/API schema |
| Long-run advisory should be explicit, replayable, and non-intrusive. | User refinement; blind role-play; external baseline | Partial direct support from long-running scans and fit outputs | Measurement code should record decision-relevant data into Scopecat | `pain-discovery-long-run-watchdog/` | Live advisor UI, scan mutation, parameter apply, framework adapters |

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
2. local executor for simple sequential and dataflow cases that can run the
   declared plan to completion when no review gate blocks it;
3. outcome report;
4. later reliability features such as retry, resume, priority scheduling,
   resource leases, and richer DAG translation.

The intended user-facing shape should feel like builder code or decorated
functions, not hand-authored manifest files. The manifest is a serialized
record and interchange format, not the first authoring surface.

The batch feature should be tested as part of Scopecat rather than only as an
isolated manifest format. Early users may define tasks and dependencies
explicitly. A later integration hypothesis is that task intent could connect to
recorded experiment context, parameter memory, code snapshots, and templates,
but that should not be treated as accepted architecture from this fixture.

### Calibration Batch Episode

Use the calibration reference workflow as the highest-value batch validation
case:

- frequency or readout calibration split across qubit groups;
- same-chip or shared-instrument groups mutually exclusive even when logically
  independent;
- per-group fit score and user-script quality decision;
- low score causes human review for that group, not necessarily a global stop;
- other groups can continue when they have no dependency on the reviewed
  output and no active resource conflict;
- downstream gate calibration waits for accepted frequency or readout states;
- review should allow resume from the stopped point, or mark only selected
  groups for remeasurement.

This does not require accepting a rich DAG engine yet. It does mean the minimal
executor fixture should cover group-level continuation, review gates,
dependency-blocked downstream work, and resumable intent at a small scale.
`mutual_exclusion_keys` can be understood as lightweight resource hints, not
proof that Scopecat must own a real lease service.

Run status and analysis or health status should remain separate. A calibration
task can complete successfully while a user-script quality gate marks the fit as
low confidence and asks for review. This avoids treating scientific quality,
analysis confidence, and executor success as one state machine.

Reasonable first review decisions are accept, reject, remeasure selected group,
edit or replace the parameter state manually and continue, or mark the result as
excluded from later drift/quality analysis. A future hook or user-defined policy
could choose among these decisions, but the fixture should first show the
decision record and its downstream effect without requiring a plugin system.

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

The user's current clarification weakens controlled mutation as an early pain:
the primary value is parameter memory, not Scopecat-owned write-back. Users need
to pick a previous parameter version for retry, move a branch or working point
back to a better version, and avoid bad writes distorting drift analysis. It is
not acceptable to delete history by default. The better default is to keep bad
states with labels or exclusions so drift queries can omit them without losing
audit history. Hard delete is only a cleanup path for cases such as accidentally
writing large payloads; the useful distinction is closer to package-index
`yank` versus `delete`.

### Code Snapshot Minimum

The most important code provenance field is the entrypoint. Recording it is
simple and high value. For user-owned code, folder selection plus an ignore
mechanism may be enough initially. Third-party dependency capture affects full
reproducibility, but it is less central to experiment intent and can remain a
lower-priority readiness detail.

A snapshot-only export is probably not enough for the code-version pain. It
helps later provenance, but it can still leave users copying code back into an
experiment directory, creating more versions. The stronger user need is to
select a previous code version or branch variant for an experiment, run tests or
exploratory changes on a separate branch, and have Scopecat record which version
actually ran. A conservative tracking-only path improves retrospective analysis
but may not improve the experiment experience enough for users who do not
already care about provenance. Loading a selected version for execution is the
clearer quality-of-life improvement, likely with process isolation, but it
remains a capability hypothesis until the smaller entrypoint, selected-folder,
and minimal-executor paths prove insufficient.

The code-version-selection fixture now separates those two values:

- `tracking_only`: records selected code version and entrypoint for later
  analysis;
- `load_selected_version`: compares the stronger experiment workflow where
  Scopecat would load the selected entrypoint in an isolated process.

The second path is deliberately marked as a capability hypothesis, not an
accepted runner architecture.

### Scopecat Boundary Around Existing Control Systems

The intended mental model is a measurement function boundary: inside the
function is the existing lab stack; outside it is Scopecat's world of declared
intent, context, records, outcomes, and review. Early fixtures should preserve
that boundary. Later ambitions such as device-communication code version
management, automatic restarts, leases, and replacing unmaintained LabRAD-like
services may be valuable if they improve the integrated experience, but they
need separate validation and safety decisions.

### First User-Visible Outputs

The likely first visible outputs are:

| Fixture | First useful output |
| --- | --- |
| Batch intent/outcome | Run report from the minimal local executor. |
| Code snapshot | Exported snapshot folder with entrypoint and selected code evidence. |
| Parameter memory bad-state handling | Parameter history view or query showing active, yanked, and excluded states. |
| Code version selection | Selection report comparing provenance-only tracking with future load-and-run value. |
| Measurement data/attachments | Reader API or export path over recorded data plus attachments. |
| Long-run watchdog/replay | Replayable decision packet from explicitly recorded partial measurement input. |

### Prioritization

The user did not choose one fixture as the only next prototype; the fixture set
is valuable as a set of validation probes. Prioritization should therefore be
by cost-to-learning ratio:

- Batch fixture tests whether a minimal local executor can solve immediate
  unattended/sequential workflow pain without full orchestration.
- Code snapshot fixture tests whether explicit entrypoint plus selected folder
  capture solves most no-git provenance pain.
- Measurement fixture tests the recording substrate needed by both batch
  reports and later analysis/handoff.
- Parameter-memory and code-version-selection fixtures test whether recently
  clarified pains can be handled without accepting mutation ownership or a code
  registry too early.
- Long-run watchdog fixture tests whether the concrete `JC-011` shape needs
  fixture evidence before live advisory or automation scope is promoted.
