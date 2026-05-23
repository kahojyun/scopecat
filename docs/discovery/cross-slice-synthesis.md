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
- [`managed-experiment-code-posture.md`](managed-experiment-code-posture.md)
- [`experiment-code-recording-validation-result.md`](experiment-code-recording-validation-result.md)
- [`managed-code-version-validation-result.md`](managed-code-version-validation-result.md)
- [`comparable-code-surface-validation-result.md`](comparable-code-surface-validation-result.md)
- [`workspace-materialization-intent-validation-result.md`](workspace-materialization-intent-validation-result.md)
- [`workspace-materialization-validation-result.md`](workspace-materialization-validation-result.md)
- [`problem-briefs/measurement-record-boundary.md`](problem-briefs/measurement-record-boundary.md)
- [`adoption-routes.md`](adoption-routes.md)
- [`measurement-context-candidate-backlog.md`](measurement-context-candidate-backlog.md)

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
parameter state versions. It has not earned final branch/tag/commit semantics,
schema migration, drift plotting, setup binding, hardware write-back, or an
implementation candidate.

Setup binding has fixture-level validation for sample/cooldown binding
snapshot versions, simple binding diffs, station-registry references, generated
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
artifacts, recorded code context, code snapshot record identities,
include-list file inventory, and precise finding vocabulary. It has not earned
a comparison engine, user-judgment engine, fit-quality comparison, raw-data
comparison, setup truth, publication-grade plotting, user-provided analysis
conclusion model, Git-state comparison, dependency discovery, environment
readiness, selected-version loading, code execution, semantic source diff, or
GUI design.
The first reference-selection model can start from ordinary user marks on
measurement records.

Experiment code recording has a slice-local summary candidate for a run/step
code context from a messy external folder and a code snapshot record. The
product concept is a point-in-time code snapshot for a declared recording
scope; later selection can choose, promote, or restore
one of those records. It uses minimal explicit include recording, strips
notebook outputs before recording, validates recorded-root, step-input, and
code snapshot record references, and does not inspect internal Git state or
analyze unrecorded files. Code records should carry explicit capture-state
posture for included items, such as content-captured, reference-only, missing,
redacted, or excluded, before any comparison surface claims content equality or
difference. It has not earned Git replacement implementation, internal Git
analysis, default record-all tracking, package management, environment
ownership, environment restoration, selected-version loading, execution,
workflow/DAG nodes, component-level versioning, generated artifact
regeneration, or GUI design.

Managed code version has a slice-local summary candidate for turning a code
snapshot record into a Scopecat-managed record with stable identity, exact
inclusion-aligned file inventory, content-integrity hints, and materialization
intent. Promotion to managed code version should not pretend that every prior
recorded snapshot becomes part of one continuous managed-version history;
reference-only prior records remain context until recaptured or otherwise
observed. It does not read source files, inspect Git state, create archives,
restore environments, materialize workspaces, import code, execute code, or
accept final storage, archive, content-addressed store, restore, sync,
selected-version loading, workflow/DAG, or GUI semantics.

Comparable code surface has a slice-local summary candidate for comparing
authority-explicit recorded and managed code fact sets without reading source
files. It uses declared capture states and integrity hints to report
same-observed, changed, missing, unverified, redacted, and not-compared
findings. It does not accept a universal diff engine, semantic source review,
Git diagnostics, environment readiness, restore, workspace materialization,
code import, code execution, or workflow/DAG semantics.

Workspace materialization intent has a slice-local summary candidate for
planning where a selected managed code version would be materialized before
writing files. It preserves selected-version identity, destination path plans,
provenance labels, declared collision findings, redacted-file skips, and
unavailable-file findings. It does not inspect the filesystem, create
directories, write files, overwrite or merge destinations, restore
environments, import code, execute code, or accept final managed-workspace or
GUI semantics.

Workspace materialization has a slice-local implementation candidate for
approved writes from declared managed content into a caller-provided workspace
root. It validates content size and sha256 digest hints, creates target
directories, writes content-available files, refuses overwrites, and reports
redacted or unavailable files without placeholders. It does not accept final
managed workspace storage, Git checkout or merge semantics, dependency sync,
environment restoration, code import, code execution, workflow/DAG behavior,
prepared run context, or GUI semantics.

## Version Terminology

The slices are converging on a shared distinction without yet earning a shared
snapshot framework:

- A version or snapshot is a point-in-time record inside a family of context
  records, such as parameter state, setup binding, station registry context, or
  experiment code.
- Selection is the user or workflow action that chooses one such record for a
  measurement, calibration step, comparison, restore, or handoff.
- Candidate means the validation or storage contract is still provisional. It
  should not make experiment code conceptually different from parameter state
  or setup binding.

Parameter state currently emphasizes management because it validates lineage,
review, and committed state. Setup binding currently emphasizes run-start
snapshots because it validates measurement context. Experiment code currently
emphasizes recording because the first slice starts from messy external folders
and preserves an explicit run/step code context before selection. These are
different entry points into the same broader pressure:
Scopecat needs named, point-in-time context records that can be selected,
compared, restored, exported, or later managed according to each family's own
semantics.

This shared vocabulary does not accept common lifecycle, diff, storage,
restore, or integrity semantics across the families. Each family still owns its
own boundary until implementation pressure earns extraction.

The measurement-context candidate backlog now gives that shared vocabulary a
single planning home. It collects recurring validation slices such as context
snapshot records, measurement or step context links, named run-start input
sets, context comparison findings, reviewable context changes, readiness or
status summaries, and external materialization or compatibility outputs. That
backlog is still discovery vocabulary: it reduces duplicated route-local slice
lists without accepting shared schema, storage, lifecycle, restore, write-back,
diff, or execution behavior.

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
| Named input snapshot | Parameter state, setup binding, experiment code, measurement reference pressure | A measurement or step context entry that references a point-in-time context record by family name, such as parameter state, setup binding, station registry, or code context, without making those families share lifecycle, diff, storage, or restore semantics. |
| Outer envelope with opaque payload | Setup binding, export, external-file pressure | A Scopecat-owned record boundary around identity, provenance, references, declared summaries, and attention state while leaving user/project-defined internal payloads opaque until a later slice earns deeper interpretation. |
| Selected reference | Selected reference comparison | A user-chosen comparison anchor, such as last-working, notable, best-observed, or simply relevant. These can start as ordinary user marks on measurement records; export, parameter state, and setup binding provide supporting context for comparison. |
| Comparison finding | Selected reference comparison, export, running inspection | A precise context-comparison result such as changed, missing, unverified, redacted, unlinked, same-observed, or not-compared. It is not automatic cause attribution. |
| Preview compatibility | Selected reference comparison, export, running inspection, scan/data-shape | Declared preview metadata that suggests compatible quick browsing or overlay across measurements. It does not imply publication-grade plotting or user interpretation. |
| Code context | Experiment code, calibration continuation, selected reference | The root or workspace reference, entrypoint, included files or source observations, notebook recording policy, and declared context refs associated with a run or step. `Recorded code context` is the audit state of this context, not a future active workspace. |
| Code snapshot record | Experiment code, export/handoff, selected reference | A point-in-time code snapshot record that Scopecat may later manage. It can describe recording/snapshot scope and capture state, supporting declared context or manifest comparison only for facts actually captured or observed, without accepting storage, restore, sync, environment, loading, execution, merge, Git inspection, or managed workspace semantics. |
| Code capture state | Experiment code, selected reference, future managed-version comparison | Whether a code item is content-captured, reference-only, missing, redacted, or excluded. This should drive same-observed, changed, missing, unverified, redacted, or not-compared findings instead of implying one universal diff. |
| Materialized code workspace | Experiment code, future prepared-run pressure | A concrete folder expanded from a selected managed code version after approval. The first candidate writes declared content into a caller-provided workspace root only; it remains separate from recorded code context, Git checkout behavior, environment readiness, import, execution, and prepared run context. |

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
  metadata. A measurement may reference the parameter state version selected at
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
- Experiment code-context mismatch is a real selected-reference comparison
  dimension. Selected-reference comparison can compare declared recorded code
  context, code snapshot record identities, include-list inventory, recorded
  source observations, and declared refs without claiming Git diff, semantic
  source comparison, environment readiness, restore, loading, or execution.
- Code comparison should grow as a fixture family, not as one catch-all
  selected-version comparison. Recorded context comparison, snapshot
  capture-state comparison, managed-version inventory comparison, and
  editable-folder observation can share finding vocabulary only after their
  authority and capture-state behavior match.
- Early code recording is explicit-include-based. Internal Git state,
  directory-name heuristics, unrecorded backups, caches, checkpoints, and
  generated files are not analyzed or surfaced as warnings unless the user
  records them or a later slice earns that behavior.
- Recorded root plus included files and named entrypoints is the first
  code-recording boundary. Workflow/DAG nodes, component-level versioning,
  and compatibility contracts remain deferred until repeated stable experiment
  functions earn inputs and outputs.

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
  comparison, user-provided analysis conclusion model, semantic source diff
  behavior, or automatic cause attribution;
- final managed experiment-code workspace storage, archive or
  content-addressed store contract, Git replacement implementation,
  branch/merge/sync semantics, package management, environment ownership,
  environment restoration, selected-version loading, code execution,
  workflow/DAG nodes, component-level code versioning, or generated artifact
  regeneration;
- publication-grade plotting or multi-run plotting GUI;
- fit quality, uncertainty, reproducibility, or user/domain scientific
  conclusions.

## Recommended Next Step

Use this synthesis as the comparison point before promoting shared
architecture.

Shared model extraction is currently deferred in
[`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md).

The next useful work is one of:

- choose another validation slice and build a similarly narrow fixture or
  implementation candidate;
- add one early-adoption fixture only where it pressures a recurring concept
  without assuming mature Scopecat ownership;
- draft a small decision only for a concept that now has pressure from at least
  two validated slices and an immediate implementation need.

Do not consolidate the slice-local builders into shared domain code just
because their vocabulary overlaps. Consolidation becomes justified when the
next implementation task would otherwise duplicate behavior, tests, and
boundary rules that have already been validated in multiple slices.
