# Handoff Package Route Decision Consolidation

## Status

Discovery decision consolidation, not an ADR.

This note closes the current handoff-package discovery pass. It records the
route decisions earned by the validated handoff package slices and names the
triggers that would justify more handoff work. It does not accept final
production architecture, a public SDK, a GUI framework, a package archive
format, signatures, final storage import behavior, or a shared
measurement-record domain model.

Artifact posture: `internal_validation_summary`. This document is internal
project memory. It creates no portable package output and no new redaction
rules. Use
[`artifact-boundary-and-redaction-policy.md`](artifact-boundary-and-redaction-policy.md)
for artifact-boundary classification.

## Accepted For Now

The current handoff route is **open before import**:

```text
write package
  -> carry package directory
  -> preview manifest
  -> open/read package locally
  -> inspect plot/table/context locally
  -> optionally observe integrity
  -> optionally accept into local storage
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

Declared preview metadata is the preview authority. Reader-side preview,
visual-review, GUI-state, and SDK projections consume declared preview facts.
They do not infer scan shape, table schema, scalar types, scientific meaning,
or plot candidates from raw files.

Python/package use is **table-first and plot-ready**. Notebook and script users
should be able to discover measurements, get dataframe-like primary tables,
and get declared plot records or arrays without importing the package into
Scopecat storage. Optional pandas/numpy adapters are useful pressure, but hard
dataframe dependencies and final public SDK names remain deferred.

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
archive authenticity, trust policy, and concurrent package-root mutation are
separate authority questions.

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
- final storage import API, existing-record update behavior, storage schema,
  import conflict policy, and concurrency semantics;
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
- Users need accepted packages to become durable local records:
  design final storage import behavior, conflict handling, and existing-record
  update policy.
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
