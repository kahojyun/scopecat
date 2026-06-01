# Measurement Context Candidate Backlog

## Status

Discovery backlog, not an ADR.

This document collects recurring candidate slices for context records attached
to or selected for measurements. It is a planning aid for validation work, not
an accepted shared schema, storage model, lifecycle model, diff engine, GUI
contract, write-back contract, or execution framework.

## Why This Exists

Several discovery routes are currently split by domain:

- parameter state;
- setup binding and station-registry context;
- experiment code context;
- declared environment context;
- recorded analysis choices;
- attachments, artifacts, and handoff context;
- selected-reference comparison context.

These are not the same domain, but they repeat the same product shape: a
measurement or calibration step can reference named, point-in-time context
records that may later be selected, compared, reviewed, exported, or checked.

The shared backlog prevents every route from carrying a separate copy of the
same candidate list. It does not mean the families share internal payloads,
version semantics, storage authority, restore behavior, or write-back rules.

## Scope

This backlog applies when a slice is about measurement context rather than
primary measurement data.

In scope:

- context record identity, provenance, family name, and declared summary;
- measurement, calibration-step, export, or handoff references to context;
- named run-start input sets;
- same-family or selected-reference comparison findings;
- reviewable context changes;
- readiness or status summaries;
- selected parameter-state snapshots as parameter context;
- explicit attachment/debug artifact references when a user supplies them.

Out of scope:

- primary measurement data storage, preview, import, export, and writer
  semantics;
- final relation graph, recursive traversal, or analysis-DAG inference;
- final shared context schema or storage model;
- domain-specific payload interpretation unless a slice earns it;
- generated compatibility files or objects as normal measurement context when
  a selected managed parameter-state snapshot already records the parameter
  context;
- hardware write-back, dependency sync, code import, code execution, notebook
  execution, managed runners, or GUI ownership.

Generated compatibility files, adapter requests, adapter receipts, stdout,
stderr, and adapter diagnostics are derivative operational artifacts by
default. They should enter this backlog only through a generic
debug/attachment route, or when a later accepted decision says a specific
artifact family has become real context. The active parameter route should
prefer the managed parameter-state snapshot as the canonical context.

## Choosing A Validation Slice

Do not treat this backlog as the owner of active sequencing. The slice under
active work should be chosen in the implementation or PR plan. This backlog
only helps classify the slice once that plan chooses a concrete user pressure.

Use
[`measurement-context-workflow-review-strategy.md`](measurement-context-workflow-review-strategy.md)
when reviewing accumulated measurement-context slices. It summarizes the
intended gradual adoption path and the rule that review findings are passive
visibility by default unless a local policy explicitly turns them into gates.

When the goal is to test whether the shared context vocabulary is useful,
**Named Run-Start Input Set** is usually the smallest cross-family validation
slice because it assembles existing selected context references, such as
parameter state, setup binding, code context or managed code version, and
measurement intent, into one run-preparation summary.

That fixture should stop at selection, labels, provenance, and missing-context
findings. It should not introduce a universal context schema, hardware control,
code import, environment sync, runnable-readiness claims, or execution.

Use the experiment-code backlog instead when the next question is about code
capture state, comparable code surfaces, workspace materialization, editable
folders, or environment readiness.

## Candidate Slice Backlog

### 1. Context Snapshot Record

Validation question: can Scopecat record a point-in-time context record with
identity, provenance, declared summary, and family-specific payload boundary?

Applies to: parameter state, setup binding, station registry context, code
context, declared environment context, and analysis choices.

Attachments, debug logs, compatibility outputs, and ordinary artifacts are
supporting evidence by default, not context records. They should enter this
context-snapshot slot only if a later accepted slice promotes a specific
artifact family into real context.

First fixture: one family-specific context record with explicit authority,
declared summary fields, references, and opaque or family-owned payload.

Boundary: no universal context schema, final storage identity, recursive graph,
write-back, restore, import, execution, or GUI.

### 2. Measurement Or Step Context Link

Validation question: can a measurement, calibration step, export, or handoff
package reference selected context records without absorbing their domain
models?

Applies to: parameter state, setup binding, code context, environment context,
analysis choices, promoted artifact-family context, and selected-reference
packages. Derivative compatibility artifacts apply only when explicitly
supplied as debug/attachment evidence; they are not implied by selecting
parameter state.

First fixture: a measurement or step with explicit context links, family names,
roles, include state, and missing or unavailable context findings.

Boundary: no recursive relation traversal, automatic inclusion of adjacent
records, shared relation graph, restore, execution, or cause attribution.

First direct result:
[`measurement-context-link-validation-result.md`](../slices/measurement-context/measurement-context-link-validation-result.md)
validates measurement records with zero, resolved, and missing optional
context links while keeping context reference-only and optional for primary
measurement-record validity.

First intent-resolution result:
[`measurement-intent-resolution-validation-result.md`](../slices/measurement-context/measurement-intent-resolution-validation-result.md)
validates the subcase where a prospective measurement intent carries moving
context selectors, run-start resolution freezes those selectors to concrete
context records, and the measurement record keeps only the resolved optional
context links.

First supporting-evidence result:
[`supporting-evidence-reference-validation-result.md`](../slices/measurement-context/supporting-evidence-reference-validation-result.md)
validates the subcase where a user explicitly supplies debug, audit, handoff,
or review evidence related to measurement, running-measurement, prepared-run,
operator-approval, parameter-state, or calibration-step targets while keeping
the evidence reference optional, reference-only, and outside primary data,
canonical context authority, and artifact provenance. Supporting evidence
references are lifecycle explicit; during-run diagnostic evidence should not be
implied by run-start context review.

First supporting-artifact provenance result:
[`supporting-artifact-provenance-validation-result.md`](../slices/measurement-context/supporting-artifact-provenance-validation-result.md)
validates the subcase where artifact-labeled supporting evidence carries
declared direct producer and source links without making provenance required
for ordinary attachments, importing payloads, observing files, validating
checksums, generating artifacts, inferring analysis DAGs, judging fit quality,
deciding measurement validity, or producing export/package behavior.

First supporting-artifact observation result:
[`supporting-artifact-observation-validation-result.md`](../slices/measurement-context/supporting-artifact-observation-validation-result.md)
validates the subcase where an artifact-labeled supporting evidence reference
with prior provenance is checked for file availability, sha256, and byte size
under a caller-provided artifact root without importing payloads, parsing
artifacts, generating previews, observing source payloads, mutating storage,
generating artifacts, inferring analysis DAGs, validating fits, deciding
measurement validity, or producing export/package behavior.

First running-record evidence result:
[`running-record-supporting-evidence-update-validation-result.md`](../slices/measurement-context/running-record-supporting-evidence-update-validation-result.md)
validates the subcase where explicit during-run supporting evidence is attached
to a running-record review surface by target continuity while avoiding payload
import, file observation, durable record append, runner ownership, log
streaming, artifact provenance, and measurement-validity claims.

Adjacent legacy-run sidecar result:
[`legacy-run-sidecar-manifest-validation-result.md`](../slices/measurement-records/legacy-run-sidecar-manifest-validation-result.md)
validates the brownfield composition where externally executed legacy code
declares measurement identity, flexible legacy source locators, optional
run-start context links, primary-data references, supporting evidence
references, and lifecycle events in one local review summary without importing
payloads, controlling runners, writing storage, writing parameters, accepting
legacy import, binding to one legacy reference scheme, or defining a final
workflow schema.

Adjacent locator review result:
[`legacy-locator-sufficiency-review-validation-result.md`](../slices/measurement-records/legacy-locator-sufficiency-review-validation-result.md)
validates review-only classification of those declared legacy locators as
human-navigation hints, without backend lookup, path parsing, file observation,
legacy import acceptance, storage mutation, reference repair, or a final
locator schema.

Adjacent sidecar post-run review result:
[`legacy-sidecar-post-run-review-validation-result.md`](../slices/measurement-records/legacy-sidecar-post-run-review-validation-result.md)
validates a local post-run projection over prior legacy sidecar and locator
review summaries, carrying lifecycle, locator, primary-data, and supporting
evidence sections without fresh observation, legacy import acceptance, storage
mutation, record write, reference repair, parameter write-back, measurement
validity decisions, or GUI behavior.

Adjacent sidecar GUI-state result:
[`legacy-sidecar-review-gui-state-validation-result.md`](../slices/measurement-records/legacy-sidecar-review-gui-state-validation-result.md)
validates the subcase where that sidecar post-run review is projected into
passive local cards, visible findings, and action labels for GUI, CLI, or
notebook surfaces without executing actions, observing files, querying
backends, accepting imports, mutating storage, repairing references, writing
parameters, deciding measurement validity, or making review state run-blocking.

Adjacent legacy file-locator observation result:
[`legacy-file-backed-locator-observation-validation-result.md`](../slices/measurement-records/legacy-file-backed-locator-observation-validation-result.md)
validates the subcase where a user explicitly selects one declared
`legacy_path` locator from sidecar review, supplies an external root and
relative path, and observes file-level availability plus optional sha256 and
byte-size facts without inferring paths from redacted displays, querying
legacy backends, parsing data, verifying previews, accepting imports, mutating
storage, repairing references, writing parameters, deciding measurement
validity, or defining GUI behavior.

Adjacent legacy locator-observation review-bundle result:
[`legacy-locator-observation-review-bundle-validation-result.md`](../slices/measurement-records/legacy-locator-observation-review-bundle-validation-result.md)
validates the subcase where sidecar post-run review and optional prior
file-backed locator observations are composed into one local review summary,
surfacing no-observation, observed, unavailable, mismatch, and sidecar
attention states without fresh observation, backend lookup, legacy parsing,
preview verification, import acceptance, storage mutation, reference repair,
parameter write-back, measurement-validity decisions, or GUI behavior.

Adjacent reviewed legacy append-intent result:
[`reviewed-legacy-sidecar-append-intent-validation-result.md`](../slices/measurement-records/reviewed-legacy-sidecar-append-intent-validation-result.md)
validates the subcase where an operator explicitly approves carrying reviewed
sidecar and locator-observation facts forward as review/debug evidence for a
later measurement-record append, while still avoiding storage mutation,
record writes, primary-data import, legacy payload parsing, preview
verification, reference repair, parameter write-back, measurement-validity
decisions, or GUI behavior.

Adjacent reviewed legacy evidence append-receipt result:
[`reviewed-legacy-sidecar-evidence-append-receipt-validation-result.md`](../slices/measurement-records/reviewed-legacy-sidecar-evidence-append-receipt-validation-result.md)
validates the subcase where that approved intent writes one review-evidence
receipt under an existing measurement record with manifest identity preflight,
no-overwrite behavior, and a record-local lock guard, while still avoiding
primary-data import, legacy payload parsing, preview verification, reference
repair, parameter write-back, measurement-validity decisions, manifest
replacement, read-model refresh, or GUI behavior.

Adjacent legacy evidence receipt read-view result:
[`legacy-evidence-receipt-read-view-validation-result.md`](../slices/measurement-records/legacy-evidence-receipt-read-view-validation-result.md)
validates the subcase where declared review-evidence receipt paths are read
back from an existing measurement record, surfacing receipt identity, source
intent, locator-observation evidence, and receipt findings without storage
scan, storage mutation, primary-data read/import, legacy payload parsing,
preview verification, reference repair, parameter write-back,
measurement-validity decisions, read-model refresh, or GUI behavior.

Adjacent legacy brownfield adoption backbone result:
[`legacy-brownfield-adoption-backbone-validation-result.md`](../slices/measurement-records/legacy-brownfield-adoption-backbone-validation-result.md)
validates the post-run-first composition across prior legacy sidecar,
post-run review, locator-observation review, append-intent, review-evidence
receipt, and receipt-read summaries, while keeping lifecycle events compatible
with a later during-run event writer and avoiding fresh observation, new
storage mutation, primary-data import, legacy parsing, reference repair,
parameter write-back, measurement-validity decisions, runner ownership, or GUI
behavior.

Adjacent legacy calibration handoff bridge result:
[`legacy-calibration-handoff-parameter-state-bridge-validation-result.md`](../slices/measurement-records/legacy-calibration-handoff-parameter-state-bridge-validation-result.md)
validates an explicit operator-approved bridge from a legacy brownfield
adoption summary to calibration accepted-write handoff and calibration
parameter-state intake summaries, requiring measurement/provenance continuity
while keeping legacy sidecar facts as review/debug evidence and avoiding fresh
observation, primary-data import, legacy parsing, parameter-state storage
mutation, legacy parameter write-back, hardware write-back, reference repair,
measurement-validity decisions, or GUI behavior.

First post-run review result:
[`post-run-review-bundle-validation-result.md`](../slices/measurement-context/post-run-review-bundle-validation-result.md)
validates a local post-run review composition over completed measurement
identity, reference-only context links, context-status findings, and carried
during-run supporting-evidence findings without storage mutation,
primary-data observation, evidence import, artifact provenance, fit validation,
measurement-validity decisions, or package/export behavior.

First post-run artifact-provenance review result:
[`post-run-artifact-provenance-review-validation-result.md`](../slices/measurement-context/post-run-artifact-provenance-review-validation-result.md)
validates the subcase where prior supporting-artifact provenance summaries are
surfaced inside local post-run review only when they match artifact evidence
already present in the post-run bundle, while still avoiding storage mutation,
primary-data observation, evidence import, artifact/source observation,
checksum validation, artifact generation, analysis-DAG inference, fit
validation, measurement-validity decisions, or package/export behavior.

First post-run artifact-observation review result:
[`post-run-artifact-observation-review-validation-result.md`](../slices/measurement-context/post-run-artifact-observation-review-validation-result.md)
validates the subcase where prior supporting-artifact observation summaries are
surfaced inside local post-run review only when they match already-reviewed
artifacts, while still avoiding fresh artifact observation, checksum
validation, payload import, artifact parsing, preview generation, source
payload observation, storage mutation, artifact generation, analysis-DAG
inference, fit validation, measurement-validity decisions, or package/export
behavior.

### 3. Named Run-Start Input Set

Validation question: can Scopecat assemble selected context records as named
inputs for a run-start or run-preparation surface?

Applies to: parameter state, setup binding, station registry context, code
context, declared environment context, and measurement intent.

First fixture: one run-start input set with selected parameter state, setup
binding, code context or managed version, and declared intent.

Boundary: no universal lifecycle model, hardware control, write-back,
dependency sync, code import, runnable-readiness claim, or execution.

First result:
[`named-run-start-input-set-validation-result.md`](../slices/measurement-context/named-run-start-input-set-validation-result.md)
validates this as a side-effect-free implementation candidate with missing
declared environment context reported as a review finding.

### 4. Context Comparison Findings

Validation question: can Scopecat report objective comparison findings between
two context records or between current and selected-reference context?

Applies to: parameter state, setup binding, station registry context, code
context, declared environment context, preview metadata, and selected-reference
review.

First fixture: one family-specific comparison with explicit authority and
findings such as same-observed, changed, missing, unverified, redacted,
unlinked, or not-compared.

Boundary: no user judgment, scientific interpretation, cause attribution,
semantic source review, setup truth, parameter invalidation, raw-data
comparison, or universal diff engine.

First resolved-link result:
[`resolved-context-link-comparison-validation-result.md`](../slices/measurement-context/resolved-context-link-comparison-validation-result.md)
validates selected-reference comparison over actual measurement-record context
links, explicitly excluding prospective measurement intent selectors, context
payload diff, primary-data comparison, fit-quality comparison, readiness
claims, and cause attribution.

### 5. Reviewable Context Change

Validation question: can Scopecat represent a proposed, accepted, rejected, or
applied context change for review without taking authority to perform it?

Applies to: parameter writes, setup-binding edits, calibration writes, selected
configuration updates, and external compatibility-file updates.

First fixture: one proposed change set against a known context record, with
review status and before/after summary.

Boundary: no hardware mutation, rollback, automatic correction, durable branch
semantics, scheduler, executor, or write-back authority.

### 6. Context Readiness Or Status

Validation question: can Scopecat summarize readiness, trust, freshness,
validity, or blocked state for a context record without claiming deeper
execution authority?

Applies to: parameter trust/readiness, setup-binding validity, declared
environment inventory, running measurement context, and calibration
continuation state.

Code workspace readiness belongs to the experiment-code backlog because it
depends on managed-code, materialization, editable-folder, and environment
authority that this generic backlog does not earn.

First fixture: one context record with declared or observed readiness facts and
attention findings.

Boundary: no hardware readiness check, dependency sync, code import, setup
truth, autonomous advice, or execution unless a narrower slice earns it.

First result:
[`context-readiness-status-validation-result.md`](../slices/measurement-context/context-readiness-status-validation-result.md)
validates a read-only local review projection over explicit family-owned
context status facts, distinguishing ready, attention-needed, and blocked
context-review states without claiming run blocking, runnable readiness,
hardware readiness, setup truth, measurement validity, restore, execution, or a
shared status schema.

### 7. External Materialization Or Compatibility Output

Validation question: can Scopecat prepare an external representation of a
context record after review while keeping Scopecat's authority explicit?

Applies to: compatibility JSON files, setup import or validation reports,
export package context manifests, and handoff bundles.

Code workspace materialization plans belong to the experiment-code backlog
because they depend on managed-version and workspace authority.

First fixture: one reviewed context record that produces an external output
plan or materialized review artifact with source identity and skipped,
degraded, or unavailable findings.

Boundary: no importer, package writer, final external-file authority, hardware
mutation, dependency install, code import, or execution unless separately
validated.

## Domain-Specific Backlogs

Some domains need their own backlog after the common context shape is clear:

- experiment code context needs managed versions, content capture state,
  comparable code surfaces, workspace materialization, editable-folder
  observation, and environment readiness boundaries;
- parameter state needs lineage purposes, trusted versus seeded state,
  reviewable parameter writes, drift views, and optional compatibility-file
  outputs;
- setup binding needs station-registry references, setup imports, generated
  line/readout summaries, opaque project-defined payloads, and setup-truth
  deferral;
- calibration continuation needs episode context, review gates, blocked steps,
  proposed writes, targeted remeasurement intent, and possible executor
  boundaries;
- measurement records need primary-data preview, import, export, running
  inspection, writer lifecycle, and data-shape boundaries separate from
  context records.

Use this backlog to avoid duplicate slice lists. Use domain-specific backlogs
only when the validation question depends on family-specific semantics.

## Extraction Boundary

This backlog is evidence for shared vocabulary, not shared implementation.

Do not extract a shared measurement-context model until at least two validated
slices need the same behavior with matching user-visible semantics, tests, and
failure handling. Until then, each fixture may keep its own fields while using
this backlog to name the validation question it is answering.
