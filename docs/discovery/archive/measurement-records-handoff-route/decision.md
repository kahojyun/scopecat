# Handoff Package Route Decision Consolidation

## Status

Retired discovery route decision.

Decision status: retired.

This note closed the handoff-package discovery pass before the engineering
prototype and durable Measurement Records import route became the live owners.
It remains historical route memory for the decisions earned by validated
handoff package slices and the triggers that justified more handoff work at
that time. It does not accept final production architecture, a public SDK, a
GUI framework, a package archive format, signatures, final storage import
behavior, or a shared measurement-record domain model.

For current implementation boundaries, use
[`handoff.md`](../../../engineering/prototype-boundaries/handoff.md),
[`handoff-durable-import-storage.md`](../../../engineering/prototype-boundaries/handoff-durable-import-storage.md),
and [`src/scopecat/handoff/README.md`](../../../../src/scopecat/handoff/README.md).

## Historical Decision

The validated discovery handoff route was **open before import**:

```text
write package
  -> carry package directory
  -> preview manifest
  -> open/read package locally
  -> inspect plot/table/context locally
  -> optionally observe integrity
  -> optionally adapt one reviewed package measurement into durable Measurement Records import
```

The package directory is the portable artifact. `package-manifest.json` is the
portable contract/index inside that directory. Writer receipts, inspection
receipts, visual artifacts, SDK/view objects, and review summaries are local
review or runtime surfaces unless a future slice explicitly promotes them.

Primary measurement data is first-class package data. The current writer and
reader route use the canonical topology
`measurements/{measurement_record_id}/primary.csv`. Additional packaged member
layouts need their own contract; fixtures must not create arbitrary nested path
semantics by accident.

The current package purpose is analysis/review, not offline execution
migration.
Use
[`policies/package-purpose-boundary.md`](../../policies/package-purpose-boundary.md)
to distinguish current handoff packages from shared lab references such as NAS
paths and future restorable execution-context artifacts or workflows.
Offline execution migration should open a separate migration boundary or route.
It should change this handoff route only when an analysis/review package needs
to expose references to that future migration context.

Declared preview metadata is the preview authority. Reader-side preview,
visual-review, GUI-state, and SDK projections consume declared preview facts.
They do not infer scan shape, table schema, scalar types, scientific meaning,
or plot candidates from raw files.

Python/package use is **table-first and plot-ready**. Notebook and script users
should be able to discover measurements and get useful table/plot facts without
importing the package into Scopecat storage. Dataframe-like tables, arrays,
optional pandas/numpy adapters, hard dataframe dependencies, and final public
SDK names remain deferred SDK/notebook pressure. Current implementation
baseline details live in
[`handoff.md`](../../../engineering/prototype-boundaries/handoff.md).

GUI/local review use is **plot-first when a plot is declared**. Experimental
users commonly orient by the primary plot and structured context first, with
table drilldown available for table-only or deeper inspection cases. The GUI
should consume structured facts rather than generated caption prose.

Linked context is currently reference-only. The route should keep visible
context references and findings near the measurement, but should not package,
open, recursively traverse, or import linked-context payloads until a concrete
payload use case appears.

Integrity observation is separate from acceptance and authenticity. The route
can compare declared package-local digest/size facts when asked, but signatures,
archive authenticity, trust policy, concurrent package-root mutation, and
concurrent storage-root mutation are separate authority questions.

Receiving-side storage mutation requires explicit approval and stays after
read-only review. Acceptance/import is a distinct mutation step, not part of
preview, open, SDK access, visual review, or integrity observation.

Route-local contracts are justified for repeated handoff semantics that already
recur across slices: managed identifiers, exact package primary-data topology,
selected-measurement continuity, and preview-ready metadata binding.
Receiving-workflow fact continuity may stay as provisional route-local
composition support while review pressure settles. This does not promote a
shared measurement domain model.

## Deferred Decisions

Keep these out of the current route until a named user workflow requires them:

- final public SDK object names, module layout, and dataframe dependency
  policy;
- numeric dtype conversion, unit conversion, plotting helpers, and
  publication-grade rendering;
- live GUI components, interaction design, routing, and production plotting
  framework;
- full scan/data-shape schema, automatic shape inference, array API, trace
  opening, or schema inference from package members;
- analysis/fit result model, fit execution, ROI selection, outlier rejection,
  uncertainty display, write-back, or import of externally produced analysis;
- linked-context payload packaging, opening, recursive traversal, or import;
- attachments beyond simple opaque carried files, unless their semantic
  category affects SDK or GUI use;
- archive extraction, compressed package format, signatures, authenticity,
  trust policy, and adversarial package-root race handling;
- offline execution migration behavior, including code workspace
  restore, environment restore, dependency sync, managed-runner inputs, or
  runnable readiness;
- final storage import API, existing-record update behavior, storage schema,
  import conflict policy, and storage concurrency semantics;
- shared measurement-record domain models or cross-route object lifecycles.

## Reopen Triggers

Do more handoff work only when one of these concrete triggers appears:

- External sharing needs a single-file or trust-bearing artifact:
  validate archive format, signatures, authenticity, and extraction rules.
- Notebook users hit real friction getting useful computation inputs:
  validate numeric dtype conversion, unit handling, or a plotting-helper API.
- GUI review needs inspectable context content:
  validate one concrete linked-context payload category and how it appears
  beside the measurement.
- Users need durable/final local records beyond the implemented
  single-measurement new-record path:
  reopen from the accepted durable import path in
  [`handoff-durable-import-storage.md`](../../../engineering/prototype-boundaries/handoff-durable-import-storage.md).
  The current trigger is satisfied for reviewed handoff package to
  single-measurement new durable record import, receipt summary, retry review,
  and CLI receipt summary. Existing-record update, batch import, conflict
  handling beyond no-overwrite, stronger recovery/concurrency, linked-context
  payload import, package trust/archive handling, public adapter transport, and
  GUI durable review state still need separate decisions. The older candidate
  mutation boundary is recorded in
  [`handoff-candidate-storage-acceptance.md`](../../../engineering/archive/handoff-candidate-storage-acceptance.md).
- Analysis or fit results need first-class display:
  validate a read-only analysis-result model before executing fits or
  accepting write-back.
- Multiple routes need the same behavior with the same lifecycle and failure
  semantics:
  reconsider shared model extraction with a narrower accepted decision.

## Stop Rule

Do not add another handoff slice to restate package identity, portable vs local
artifact boundaries, preview-metadata authority, dataframe deferral, GUI
deferral, redaction boundaries, or reference-only linked context. Future
handoff work should name the missing user workflow and the authority boundary
it changes.
