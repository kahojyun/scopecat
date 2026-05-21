# Cross-Slice Discovery Synthesis

## Status

Discovery synthesis, not an ADR.

This document compares the currently validated slices to identify recurring
candidate concepts and remaining design pressure. It does not accept a final
schema, storage model, workflow model, GUI contract, export package format,
executor design, relation graph, or warning taxonomy.

## Inputs

- [`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md)
- [`preview-ready-selected-measurement-export-validation-result.md`](preview-ready-selected-measurement-export-validation-result.md)
- [`storage-transition-export-fixture.md`](storage-transition-export-fixture.md)
- [`storage-transition-export-validation-result.md`](storage-transition-export-validation-result.md)
- [`external-file-reference-policy.md`](external-file-reference-policy.md)
- [`running-measurement-inspection-validation-result.md`](running-measurement-inspection-validation-result.md)
- [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md)
- [`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md)
- [`problem-briefs/setup-binding.md`](problem-briefs/setup-binding.md)
- [`setup-binding-validation-plan.md`](setup-binding-validation-plan.md)
- [`setup-binding-validation-result.md`](setup-binding-validation-result.md)
- [`selected-reference-comparison-validation-result.md`](selected-reference-comparison-validation-result.md)
- [`problem-briefs/measurement-record-boundary.md`](problem-briefs/measurement-record-boundary.md)
- [`adoption-hypotheses.md`](adoption-hypotheses.md)

## Current Slice Positions

Selected measurement export has the strongest implementation-shaped boundary.
It earned a pure structured summary builder for explicit selected measurement
sets, default bundles, optional linked context, declared preview metadata,
degraded-preview warnings, and non-recursive traversal.

The storage-transition export fixture adds early-adoption and lab-policy
pressure without changing that implementation boundary. It separates source
identity, current reference, and package materialization for managed records
and lab-managed network references, and it treats missing or moved external
context as warning-worthy. It does not decide the final storage model or
external-reference policy.

The storage-transition validation result stops that slice at fixture
validation. It carries forward the source/current-reference/materialization
split and external-file policy vocabulary, while explicitly deferring storage,
checksum, backup, package writer, importer, and GUI behavior.

Running measurement inspection has fixture-level validation for state summaries
over already-recorded data from still-running measurements. It pressures
lifecycle state, progress, completeness, freshness, declared preview metadata,
and non-durable monitor ergonomics, but has not earned a generator or live
service.

Calibration work continuation has a tiny assembler candidate for continuation
state. It pressures episode context, planned steps, observed outputs, review
gates, user-authored proposed writes, blocked steps, and available
interventions, but has not earned executor, scheduler, write-back, or GUI
ownership.

Parameter state management has fixture-level validation for first-class
parameter state lineages, purpose labels, seeded versus trusted states,
reviewable diffs, committed states, and measurement references to selected
parameter state. It has not earned final branch/tag/commit semantics, schema
migration, drift plotting, setup binding, hardware write-back, or an
implementation candidate.

Setup binding has fixture-level validation for sample/cooldown binding
snapshots, simple binding diffs, station-registry references, generated
line/readout views, and measurement references while keeping parameter state
and hardware control separate. User/project transformation code is black-box
provenance for this slice: Scopecat records declared or generated binding
artifacts and references, not the render pipeline that produced them. The
fixture uses a measurement `inputs` list to group named input snapshots, but it
does not earn a shared snapshot framework. The fixture also allows
user/project-defined inner binding payloads, treated as opaque by default with
declared summary fields for review.

Scan/data-shape fixtures currently support declared 1D table, rectangular 2D
grid table, and sidecar-declared weak-table pressure. Harder shapes such as
ragged scans, trace-per-point data, and array-valued responses remain known
risks, not current requirements.

Selected reference comparison has fixture-level validation for comparing a
current measurement against a user-selected reference as recorded context. It
reuses selected measurement IDs, declared preview metadata, named input
snapshots, parameter state references, setup-binding references, selected
artifacts, and precise finding vocabulary. It has not earned a comparison
engine, user-judgment engine, fit-quality comparison, raw-data comparison,
setup truth, publication-grade plotting, user-provided analysis conclusion
model, experiment-code comparison, or GUI design. The first reference-selection
model can start from ordinary user marks on measurement records.

## Recurring Candidate Concepts

These concepts recur across more than one slice and are becoming useful
analysis vocabulary. They are still candidate concepts, not accepted product
schema.

| Candidate concept | Slice pressure | Current meaning |
| --- | --- | --- |
| Measurement record | Export, running inspection, calibration continuation | The ordinary user-facing unit for primary recorded experiment data, selected for export, inspected while running, or referenced as calibration output. |
| Source identity | Export, running inspection, calibration continuation | Recoverable provenance for where a record came from, distinct from current read path, package-relative fixture path, or final storage identity. |
| Primary data reference | Export, running inspection, measurement boundary | The data item users expect to inspect, preview, export, or later plot; may be fixture path-shaped now but should not imply durable path identity. |
| Declared preview metadata | Export, running inspection, scan/data-shape | Shape, roles, labels, units, axis order, row order, and plot candidates supplied explicitly enough to support preview without schema inference. |
| Linked context | Export, calibration continuation, measurement boundary | Snapshots, attachments, artifacts, fit previews, notes, or derived outputs connected to a measurement or step with explicit relation and authority. |
| Include state | Export, measurement boundary | Whether linked context is default-included, user-included, visible-but-excluded, missing, or local-only; this is not recursive graph traversal. |
| Lifecycle or progress state | Running inspection, calibration continuation | Current status of a measurement or step, such as running, complete, partial, review-needed, or blocked. |
| Intervention or operation | Running inspection, calibration continuation, future GUI pressure | A user-facing item that needs attention or can be acted on, without implying autonomous execution. |
| Reviewable change | Calibration continuation, parameter-state pressure | A user-authored or Scopecat-computed diff from a known state that can be reviewed before committing or applying; not durable history unless accepted. |
| Warning or attention state | Export, running inspection, calibration continuation | A degraded, missing, stale, uncertain, risky, or review-needed condition. Normal policy and boundary disclaimers should not become warnings. |
| Authority/provenance | All validated slices | A way to separate fixture-declared, observed, user-authored, external, materialized, and Scopecat-managed facts without settling final ownership. |
| Setup binding | Parameter state, selected reference, future measurement reference pressure | The sample/cooldown/session-specific mapping from logical experiment entities to physical wiring, channels, instruments, generated line/readout state, and selected registry context. |
| Named input snapshot | Parameter state, setup binding, measurement reference pressure | A measurement run-start context entry that references a specific snapshot family by name, such as parameter state, setup binding, or station registry, without making those families share lifecycle or diff semantics. |
| Outer envelope with opaque payload | Setup binding, export, external-file pressure | A Scopecat-owned record boundary around identity, provenance, references, declared summaries, and attention state while leaving user/project-defined internal payloads opaque until a later slice earns deeper interpretation. |
| Selected reference | Selected reference comparison, export, parameter state, setup binding | A user-chosen comparison anchor, such as last-working, notable, best-observed, or simply relevant. These can start as ordinary user marks on measurement records. |
| Comparison finding | Selected reference comparison, export, running inspection | A precise context-comparison result such as changed, missing, unverified, redacted, unlinked, same-observed, or not-compared. It is not automatic cause attribution. |
| Preview compatibility | Selected reference comparison, export, running inspection, scan/data-shape | Declared preview metadata that suggests compatible quick browsing or overlay across measurements. It does not imply publication-grade plotting or user interpretation. |

## Stable Separations

Several separations now appear repeatedly enough to keep carrying forward:

- Selected records are explicit. Adjacent IDs, rejected alternatives, linked
  artifacts, source runs, or relation graphs are not automatically included.
- Declared metadata is the first supported path for preview. Inference from
  notebooks, filenames, weak headers, sidecars, or legacy readers remains
  optional future help, not the trust base.
- Source identity, fixture paths, package-relative materialized files, external
  local paths, and future managed storage identities are different things.
- A current reference used before export is also separate from package
  materialization. Managed records may not need user-facing filesystem paths,
  while available lab-managed network references can still be materialized into
  export packages. Package materialization paths are output of export planning
  or packaging, not pre-export input.
- Normal policies belong in structured state. Warnings should be reserved for
  degraded, missing, uncertain, risky, stale, unavailable, or review-needed
  conditions.
- Markdown review output is fixture/reviewer support unless a later slice
  specifically validates a report or human-readable product artifact.
- In calibration continuation, proposed writes and applied writes are distinct.
  Recording a user-authored proposal does not imply Scopecat-decided mutation
  or write-back authority. In parameter-state work, start from reviewable
  change sets and committed states rather than assuming unapplied proposals are
  durable history.
- Parameter snapshots can be first-class lab state, not just measurement
  metadata. A measurement may reference the parameter state selected at
  measurement start, while the parameter state may also carry lineage,
  domain-purpose, readiness, trust, review, and committed-state meaning
  independently. Branch, tag, and commit remain analogies, not accepted
  semantics. Working point is one possible lineage purpose, not the generic
  lineage model.
- Partial running data can be visible as normal state. Incompleteness is not a
  warning unless it blocks a declared need.
- Linked artifacts and attachments need labels and relations, but recursive
  traversal, many-to-many ownership, and analysis-DAG inference remain deferred.
- Device registry, setup binding, and parameter state should remain separate
  until a later slice earns their relationship. Setup binding is adjacent to
  parameter state because it maps sample/cooldown logical entities to physical
  wiring, channels, and devices, may need snapshots/diffs, and may be
  referenced by measurements. A measurement may group these as named input
  snapshots at run start, but that does not make them one shared state model.
- User/project-defined inner payloads can remain opaque by default. Scopecat
  can still own the outer envelope and declared summary fields needed for
  review, export, and measurement context.
- Selected references are explicit user-chosen anchors. Same-observed setup
  context, matching preview metadata, and changed parameter state are
  comparison findings, not user interpretation or cause attribution.
- Last-working, notable, best-observed, or similar reference labels can start
  as user marks on measurement records. Scopecat does not need special
  semantics for each label before it can provide objective comparison.
- Experiment code/version mismatch is a real selected-reference comparison
  dimension, but it should stay deferred until experiment-code-selection
  validates the minimum code reference shape.

## Design Pressure

The strongest shared pressure is toward a structured record-oriented core that
can answer three questions before any final architecture decision:

- What did the user intentionally select, inspect, or continue?
- What data, context, preview metadata, and provenance are available?
- What is missing, degraded, blocked, stale, externally managed, or awaiting
  user intervention?

This pressure does not yet require a shared domain module. The current
implementation candidates should remain slice-local until another slice needs
the same code boundary rather than merely the same words.

The second strongest pressure is preview readiness. Export and running
inspection both need explicit shape and role metadata. Calibration continuation
also references measurements and fit previews that may later benefit from the
same preview-ready record shape, but that reuse is not yet earned.

The third pressure is externally managed context. Early adoption should assume
users may still own some snapshots, scripts, parameter files, local paths, and
analysis artifacts outside Scopecat. Scopecat can record provenance, relation,
warnings, and proposal state without claiming full storage, runtime, parameter,
or analysis authority.

The external-file policy note adds a narrower posture for this pressure:
Scopecat is not a general backup system, external references can default to the
latest external state, and original measurement data changes should not be
silent. Lightweight observed file state, such as checksum, size, mtime, and
observation time, is now candidate vocabulary but not an accepted integrity
contract.

## Not Yet Earned

The cross-slice comparison still does not earn:

- final measurement, artifact, attachment, relation, or data-shape schema;
- shared `core`, `domain`, or reusable model package;
- final storage identity, object ID, external-reference, or package path model;
- checksum, archive, importer, or package integrity contract;
- checksum, observed-file-state, file-watcher, backup, or restore contract;
- export/import GUI, live monitor GUI, or calibration resume GUI;
- rendered plotting, dataframe dependency, or interactive slicing API;
- automatic schema inference from legacy files or notebooks;
- recursive relation traversal or analysis-DAG inference;
- local executor, scheduler, retry policy, resource arbitration, or hardware
  control;
- Scopecat-decided parameter mutation, write-back, rollback, or calibration
  authority;
- device registry, setup binding schema, physical wiring model, or station
  configuration model;
- shared input-snapshot or run-context framework;
- deep interpretation of user/project-defined setup-binding payloads;
- selected-reference comparison engine, user-judgment engine, raw-data
  comparison, user-provided analysis conclusion model, experiment-code
  comparison, or automatic cause attribution;
- publication-grade plotting or multi-run plotting GUI;
- fit quality, uncertainty, reproducibility, or user/domain scientific
  conclusions.

## Recommended Next Step

Use this synthesis as the comparison point before promoting shared
architecture.

Shared model extraction is currently deferred in
[`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md).

The next useful work is one of:

- choose another adoption slice and build a similarly narrow fixture or
  implementation candidate;
- add one early-adoption fixture only where it pressures a recurring concept
  without assuming mature Scopecat ownership;
- draft a small decision only for a concept that now has pressure from at least
  two validated slices and an immediate implementation need.

Do not consolidate the slice-local builders into shared domain code just
because their vocabulary overlaps. Consolidation becomes justified when the
next implementation task would otherwise duplicate behavior, tests, and
boundary rules that have already been validated in multiple slices.
