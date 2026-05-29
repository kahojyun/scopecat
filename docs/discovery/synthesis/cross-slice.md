# Cross-Slice Discovery Synthesis

## Status

Discovery synthesis, not an ADR.

This document compares validated route and slice evidence to identify
recurring candidate concepts, stable separations, and remaining design
pressure. It does not accept a final schema, storage model, workflow model, GUI
contract, export package format, executor design, relation graph, or warning
taxonomy.

## Evidence Owners

This synthesis compares recurring pressure across the current discovery corpus.
It intentionally points to owner indexes rather than repeating every slice or
route inventory.
Individual validation-result evidence is owned by
[`../slices/README.md`](../slices/README.md) and linked route indexes; the
recurring-concepts table below uses route and slice shorthand only.

| Owner | Use For |
| --- | --- |
| [`../slices/README.md`](../slices/README.md) | Current slice inventory and maturity by route. |
| [`../routes/README.md`](../routes/README.md) | Route owners and route-specific sequencing. |
| [`../routes/measurement-records/README.md`](../routes/measurement-records/README.md) | Measurement-record import, export, storage, source observation, handoff, and shape pressure. |
| [`../routes/measurement-records/handoff/README.md`](../routes/measurement-records/handoff/README.md) | Handoff package route map, artifact boundary, stable route concepts, and next work. |
| [`../routes/measurement-records/handoff/decision.md`](../routes/measurement-records/handoff/decision.md) | Current handoff route decisions, deferrals, reopen triggers, and stop rule. |
| [`../routes/measurement-records/import-source-decision.md`](../routes/measurement-records/import-source-decision.md) | Current import/source decisions, deferrals, reopen triggers, and stop rule. |
| [`../routes/experiment-code/README.md`](../routes/experiment-code/README.md) | Experiment-code recording, managed code versions, workspace materialization, editable observation, and prepared-run context. |
| [`../routes/environment-operation/README.md`](../routes/environment-operation/README.md) | Environment-operation review around manifest preflight, manager intent, declared external result, and local operation review. |
| [`measurement-context-backlog.md`](measurement-context-backlog.md) | Shared backlog for context-shaped validation work across routes. |
| [`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md) | Why shared model extraction remains deferred. |
| [`../policies/README.md`](../policies/README.md) | Cross-route boundary vocabulary, artifact boundaries, and product posture. |

## Route Evidence Summary

Current route evidence is strong enough to compare recurring concepts, but not
strong enough to promote a shared architecture package. Route-local sequencing
and stop rules belong in route owners; this document only records cross-route
pressure.

| Evidence area | Current synthesis posture | Owner |
| --- | --- | --- |
| Measurement records | The strongest implementation-shaped boundary for primary recorded data, selected export, import/source separation, storage writing, source observation, running inspection, declared preview metadata, and package-facing handoff pressure. | [`../routes/measurement-records/README.md`](../routes/measurement-records/README.md) |
| Handoff packages | A route-local open-before-import model has emerged: write/carry package, preview manifest, open/read package, inspect locally, optionally observe integrity, then optionally accept into local storage. Its package and field decisions remain route-local. | [`../routes/measurement-records/handoff/README.md`](../routes/measurement-records/handoff/README.md) |
| Import/source | Adapter-normalized primary data, preserved external source references, reference-only observation, copy acceptance, storage writing, and existing-record append receipts are distinct authority boundaries. | [`../routes/measurement-records/import-source-decision.md`](../routes/measurement-records/import-source-decision.md) |
| Experiment code | Current evidence supports record -> promote -> materialize -> observe -> prepare as adjacent responsibilities around code context, without accepting Git semantics, environment restoration, code loading, or execution. | [`../routes/experiment-code/README.md`](../routes/experiment-code/README.md) |
| Environment operation | Current evidence supports approve intent -> record result -> review locally for uv-specific operations. Discovery candidates validated declared external result recording; the route-local engineering prototype now covers one approved `uv sync` subprocess boundary without accepting verified package state, runtime readiness, code execution, or a shared manager abstraction. | [`../routes/environment-operation/README.md`](../routes/environment-operation/README.md) |
| Parameter state, setup binding, calibration, selected reference, and measurement context | These slices add repeated pressure for named point-in-time context records, selected references, comparison findings, proposed writes, and run-start inputs, but have not earned a shared context framework. | [`../slices/README.md`](../slices/README.md) and [`measurement-context-backlog.md`](measurement-context-backlog.md) |

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

## Route Relationship Model

Current measurement-route evidence, experiment-code consolidation, and
environment-operation consolidation should be read as route-level
interpretations of validated slices, not new contract sources. The
relationship among measurement, experiment code, and environment is:

| Route surface | Current role | Current non-claim |
| --- | --- | --- |
| Measurement record | User-facing evidence, selection, export, import, handoff, inspection, and selected-reference anchor for comparison or rerun work. | Does not own code recording, environment sync, runtime readiness, or execution. |
| Experiment code context | Linked run/step context describing recorded code, managed code version, materialized workspace, or editable observation. | Does not own environment restoration, runnable readiness, Git semantics, import, or execution. |
| Declared environment or environment operation record | Linked runtime/manager context describing declared environment facts, approved manager intent, declared external result, route-local approved `uv sync` execution result, and local operation review. | Does not own package-state truth, general manager execution, code loading, measurement storage, or run readiness. |
| Prepared run context | Local composition surface joining selected code/workspace, parameter/setup/station context, measurement intent, declared environment context, and separately validated environment review findings for manual run preparation. | Does not become a shared run-context schema, runner, restore contract, hardware-control contract, or reproducibility claim. |

This keeps the current architecture reference-based: measurement explains why
context is selected, experiment code and environment records explain selected
facts around a run, and prepared-run or review bundles compose those facts for
local review without turning them into execution authority.

## Recurring Candidate Concepts

These concepts recur across more than one slice and are becoming useful
analysis vocabulary. They are still candidate concepts, not accepted product
schema.

| Candidate concept | Slice pressure | Current meaning |
| --- | --- | --- |
| Measurement record | Export, incoming-record import preview, handoff package contents preview, legacy import acceptance, reference-only legacy import, reference-only source observation, running inspection, new-run writer, storage writer, existing-record update, source observation, calibration continuation | The ordinary user-facing unit for primary recorded experiment data, created from writer events, written to storage, given separately recorded append evidence under a bounded existing-record update, accepted from reviewed legacy adapter manifests, preserved as external references, observed after storage or at the file level while still external, selected for export, previewed before external import, handoff package read-only open, or later package acceptance, inspected while running, or referenced as calibration output. |
| Source identity | Export, incoming-record import preview, legacy import acceptance, reference-only legacy import, running inspection, new-run writer, calibration continuation | Recoverable provenance for where a record came from, distinct from current read path, package-relative fixture path, writer-declared primary data path, external current reference, or final storage identity. |
| Primary data reference | Export, incoming-record import preview, handoff package contents preview, adapter output boundary, normalized primary table, legacy import acceptance, running inspection, new-run writer, storage writer, existing-record update, source observation, measurement boundary | A Scopecat-readable or adapter-normalized data item users expect to inspect, preview, export, import, package, store, associate with separately recorded append evidence, observe, or later plot; may be fixture path-shaped now but should not imply durable path identity. Original legacy files preserved without normalized data should be modeled as external source references, not previewable primary data. |
| External source reference | Storage-transition export, incoming-record import preview, adapter-authored legacy import, reference-only legacy import, reference-only source observation, measurement boundary | A declared pointer to original or lab-managed external data for provenance, transition, or later observation. It can carry source identity, reference state, redacted display facts, and file-level observations, but does not imply Scopecat can parse, preview, or plot the referenced data. |
| Declared preview metadata | Export, incoming-record import preview, handoff package contents preview, adapter output boundary, normalized primary table, legacy import acceptance, reference-only legacy import, running inspection, new-run writer, storage writer, source observation, scan/data-shape | Shape, roles, labels, units, axis order, row order, and plot candidates supplied explicitly enough to support preview without schema inference when paired with Scopecat-readable or adapter-normalized data. For external source references, preview metadata remains a declared adapter/manifest assertion until normalized data or data-level observation is validated. |
| Observed table fact | Handoff package opener, handoff package read view, normalized primary table | String-valued rows and columns read from a normalized table source after malformed table shapes are rejected. This currently proves table shape and declared-column binding, not scalar types, dtypes, scan shape, plotting semantics, streaming, or query behavior. |
| Linked context | Export, incoming-record import preview, handoff package contents preview, adapter output boundary, legacy import acceptance, reference-only legacy import, derived artifact source links, calibration continuation, measurement boundary | Snapshots, attachments, artifacts, fit previews, notes, or derived outputs connected to a measurement, package, or step with explicit relation and authority. Adapter output boundary currently observes linked-context file facts only; it does not import or interpret payloads. |
| Include state | Export, handoff package contents preview, measurement boundary | Whether linked context is default-included, user-included, visible-but-excluded, visible-but-not-packaged, missing, or local-only; this is not recursive graph traversal. |
| Lifecycle or progress state | Running inspection, new-run writer, calibration continuation | Current status of a measurement or step, such as running, complete, partial, review-needed, failed, or blocked. |
| Intervention or operation | Running inspection, calibration continuation, future GUI pressure | A user-facing item that needs attention or can be acted on, without implying autonomous execution. |
| Reviewable change | Calibration continuation, parameter-state pressure | A user-authored or Scopecat-computed diff from a known state that can be reviewed before committing or applying; not durable history unless accepted. |
| Warning or attention state | Export, incoming-record import preview, handoff package contents preview, legacy import acceptance, reference-only legacy import, reference-only source observation, running inspection, new-run writer, existing-record update, source observation, calibration continuation | A degraded, missing, stale, uncertain, risky, unavailable, mismatched, failed, blocked, or review-needed condition. Normal policy and boundary disclaimers should not become warnings. |
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
| Materialized code workspace | Experiment code, prepared-run context support | A concrete folder expanded from a selected managed code version after approval. The first candidate writes declared content into a caller-provided workspace root only; it remains separate from recorded code context, Git checkout behavior, environment readiness, import, execution, and prepared run context. |
| Editable workspace observation | Experiment code, prepared-run context support | A read-only observation of a selected editable folder against a managed code version. The first candidate records size and sha256 facts for observed files and reports drift or non-authoritative extras while using ignored-directory guardrails for workspace internals, without accepting semantic source diff, Git diagnostics, environment readiness, import, execution, or prepared run context. |
| Prepared run context | Experiment code, measurement context support | A manual run-preparation summary that groups selected managed code/workspace observation, parameter state, setup binding, station registry, and measurement intent while surfacing missing environment context, workspace drift, or workspace limitations as review findings, without claiming restore, runnable readiness, hardware control, import, or execution. |
| Reference-based rerun preparation | Experiment code, selected reference, measurement context support | A proposed manual rerun context seeded from a user-selected reference measurement and its linked context records. The first candidate validates reference-linked selection and review findings without claiming reference goodness, reproducibility, automatic cause attribution, drift correction, hardware control, environment sync, import, or execution. |
| Environment readiness plan | Declared environment, prepared run context support | A reviewable plan for what checks would be needed for a selected declared modern `uv`/`pyproject.toml` environment context. The first candidate treats lab-managed drivers and legacy dependency concerns as review notes while avoiding package-manager runs, code import, code execution, hardware probes, or runnable-readiness claims. |
| Environment comparison finding | Declared environment, selected reference, prepared run context support | A declared-fact comparison result such as same-declared, changed, missing, unverified, or unsupported for selected environment context. It is not dependency resolution, runtime compatibility, hardware readiness, runnable readiness, or reproducibility. |
| Environment file observation | Declared environment, prepared run context support | A read-only observation of explicitly declared environment files under a caller-provided workspace root. The first candidate records availability, sha256, byte size, malformed-manifest review findings, and narrow `pyproject.toml` declared summary fields without workspace discovery, lockfile graph parsing, dependency resolution or sync, runtime probes, hardware checks, code import, execution, or runnable-readiness claims. |
| Environment review bundle | Declared environment, selected reference, prepared run context support | A composition of prepared/rerun context, declared environment comparison, file observation, and readiness-plan summaries into one review surface. It validates alignment and aggregates review findings without fresh observation, dependency resolution, dependency sync, package installation, runtime probes, hardware checks, code import, execution, shared environment schema, managed-runner behavior, run-blocking decisions, or runnable-readiness claims. |
| Modern manifest preflight | Environment operation, declared environment support | An optional `uv`/`pyproject.toml` review projection over one approved manifest under a caller-provided workspace root. It summarizes declared manifest facts, derives `default` only from list-shaped `[project].dependencies`, and reports missing or malformed `requires-python`, read failures, malformed dependency-group values, normalized dependency-group-name collisions, and missing dependency-group review findings, using normalized dependency-group comparison without defining a general manager abstraction, lockfile parsing, dependency resolution, dependency sync, package installation, runtime probes, hardware checks, code import, execution, shared environment schema, managed-runner behavior, run-blocking decisions, manager-operation authority, or runnable-readiness claims. |
| UV sync intent | Environment operation, prepared run context support | A bounded `uv sync` command-intent projection over one approved request. It constructs exact argv from structured fields, including `--locked`, `--no-default-groups`, and selected declared uv dependency groups while modeling project dependencies separately, leaving filesystem inspection, manifest reads, lockfile reads, dependency resolution, process execution, dependency sync, package installation, runtime probes, hardware checks, code import, execution, shared environment schema, general manager abstraction, managed-runner behavior, run-blocking decisions, and runnable-readiness claims out of scope. |
| UV sync result | Environment operation, prepared run context support | A declared external `uv sync` result record checked against a prior command intent. It records execution state, exit code, timestamp/duration consistency, observer, nullable local execution cwd, bounded stdout/stderr summaries, and command mismatch findings while leaving process execution, filesystem inspection, manifest reads, lockfile reads, dependency-output parsing, verified dependency sync, verified package installation, runtime probes, hardware checks, code import, execution, shared environment schema, general manager abstraction, managed-runner behavior, run-blocking decisions, and runnable-readiness claims out of scope. |
| Environment operation review bundle | Environment operation, prepared run context support | A local `review_summary` composition over prior modern manifest preflight, `uv_sync_intent`, and `uv_sync_result` summaries. It validates selected identity and command continuity and aggregates child findings, non-success result status, and cross-summary mismatches without producing a portable/export artifact, fresh filesystem inspection, manifest reads, lockfile reads, process execution, dependency-output parsing, verified dependency sync, verified package installation, runtime probes, hardware checks, code import, execution, shared environment schema, general manager abstraction, managed-runner behavior, run-blocking decisions, or runnable-readiness claims. |

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
- Analysis/review packages, shared lab references such as NAS paths, and future
  offline execution migration are separate product purposes. A package that
  helps someone inspect data does not automatically become a shared-storage
  deployment model or a code/environment migration artifact; use
  [`../policies/package-purpose-boundary.md`](../policies/package-purpose-boundary.md)
  before adding package behavior that crosses those purposes.
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
- External parameter files can be public-safe relative compatibility targets
  without becoming the source of parameter authority. Planning a compatibility
  output from accepted parameter state is still separate from writing files,
  applying hardware parameters, flattening schema-limited values, or tracking
  live JSON state.
- External legacy data references can be preserved for provenance and
  transition, but plotting and dataframe-like preview require normalized
  Scopecat-readable data or a supported previewable data item.
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
- Prepared run context can group selected code/workspace, parameter, setup,
  station, and intent records for manual preparation without becoming a shared
  run lifecycle, readiness, restore, execution, or hardware-control framework.
- Environment readiness can be represented as check planning before dependency
  resolution, sync, runtime probes, code import, execution, or hardware checks
  are authorized, with legacy/lab-managed environment facts kept as record-only
  review evidence rather than sync inputs.
- Environment review bundles can compose prior declared comparison,
  file-observation, and readiness-plan summaries for manual rerun review
  without becoming dependency resolution, dependency sync, package
  installation, runtime compatibility result, shared environment schema,
  managed-runner contract, run-blocking decision, or runnable-readiness claim.
- Modern manifest preflight can support environment review/comparison when raw
  file hashes or text diffs are too weak, but should remain optional for
  manager execution and separate from a general manager abstraction, lockfile
  parsing, dependency resolution, dependency sync, package installation,
  runtime compatibility, managed-runner behavior, run-blocking decisions, and
  runnable-readiness.
- UV sync intent can express a bounded external manager operation without
  becoming that operation's executor. Exact argv construction should remain
  manager-specific until multiple operation-intent slices earn a shared
  manager abstraction.
- UV sync result can record an external manager outcome without turning that
  outcome into verified package state, runtime readiness, managed-runner state,
  or run-start permission. Result recording should remain manager-specific
  until multiple operation-result slices earn a shared manager abstraction.
- Environment operation review bundles can compose uv-specific preflight,
  intent, and result summaries into one local review surface without becoming
  the manager executor, portable/export output, shared manager abstraction,
  environment verifier, runtime readiness result, managed-runner state, or
  run-start permission.

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
The first measurement record handoff flow reinforces that posture: composition
currently needs narrow, test-local adapters around selected explicit candidate
facts, not a shared model package.

The second strongest pressure is preview readiness. Export, incoming-record
import preview, handoff package contents preview, and running inspection need
explicit shape and role metadata. Calibration continuation also references
measurements and fit previews that may later benefit from the same
preview-ready record shape, but that reuse is not yet earned. Handoff package
contents preview now validates adjacent pressure over selected measurement
export output while staying separate from incoming-record import preview.

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
- final existing-record update model, manifest replacement, segment
  compaction, read-model refresh, distributed locking, lock identity,
  stale-lock cleanup, or crash recovery;
- checksum, archive, importer, or package integrity contract;
- checksum, observed-file-state, file-watcher, backup, or restore contract;
- export, handoff-package contents, incoming-record import GUI, live monitor
  GUI, or calibration resume GUI;
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
  environment restoration, selected-version loading, dependency sync,
  runtime readiness, managed runners, code execution, workflow/DAG nodes,
  component-level code versioning, or generated artifact regeneration;
- publication-grade plotting or multi-run plotting GUI;
- fit quality, uncertainty, reproducibility, or user/domain scientific
  conclusions.

## Use This Synthesis

Use this document as the comparison point before promoting shared architecture.
It should answer whether a concept is recurring cross-slice pressure, a stable
separation, a route-local decision, or still only slice-local vocabulary.

For route sequencing, next-work choices, stop rules, and reopen triggers, use
the route owners instead of this synthesis:

- [`../routes/measurement-records/README.md`](../routes/measurement-records/README.md)
- [`../routes/measurement-records/handoff/README.md`](../routes/measurement-records/handoff/README.md)
- [`../routes/measurement-records/handoff/decision.md`](../routes/measurement-records/handoff/decision.md)
- [`../routes/measurement-records/import-source-decision.md`](../routes/measurement-records/import-source-decision.md)
- [`../routes/experiment-code/README.md`](../routes/experiment-code/README.md)
- [`../routes/environment-operation/README.md`](../routes/environment-operation/README.md)

The next useful synthesis change should do one of three things:

- record pressure from more than one validated route or slice;
- clarify a stable separation that keeps route contracts from collapsing into
  each other;
- name a shared-model extraction trigger with an immediate implementation need.

Do not consolidate slice-local builders into shared domain code just because
their vocabulary overlaps. Consolidation becomes justified when the next
implementation task would otherwise duplicate behavior, tests, and boundary
rules that have already been validated in multiple slices.
