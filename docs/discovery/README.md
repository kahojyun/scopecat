# Discovery

## Purpose

Discovery owns current problem framing, adoption routes, validation
artifacts, implementation-shaped exploration results, synthesis, and explicit
deferrals.

These documents are not user documentation and are not accepted architecture
unless a narrower document says so. Use them to decide the next validation or
implementation slice without promoting slice-local vocabulary into shared
product contracts too early.

## Read First

| Document | Use For |
| --- | --- |
| [`adoption-routes.md`](adoption-routes.md) | Compare current evidence-backed adoption routes by durable user workflow. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Start from evidence-backed problem framing before choosing a validation question. |
| [`cross-slice-synthesis.md`](cross-slice-synthesis.md) | See recurring candidate concepts across validated slices. |
| [`measurement-context-candidate-backlog.md`](measurement-context-candidate-backlog.md) | Shared discovery backlog for context records attached to or selected for measurements, without accepting a shared schema. |
| [`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md) | Understand why shared domain models are intentionally deferred. |
| [`external-file-reference-policy.md`](external-file-reference-policy.md) | Candidate policy vocabulary for external files, latest state, observed file state, and non-backup boundaries. |
| [`managed-experiment-code-posture.md`](managed-experiment-code-posture.md) | Product posture for Git-like managed experiment-code versions without requiring users to operate Git. |

## Validation Slices

Validation slices are grouped by adoption route. A route can contain several
slices at different maturity levels; a slice should stay narrow even when it
tests part of a broader route.

The route tables below include problem briefs, plans, validation results, and
supporting policy notes. The current validated slice inventory is:

| Slice | Route | Current maturity | Boundary |
| --- | --- | --- | --- |
| Preview-ready selected measurement export | Measurement records | Implementation candidate validated | Pure summary for explicit selected measurement sets, default bundles, linked context, declared preview metadata, degraded-preview warnings, and non-recursive traversal. |
| Storage-transition export | Measurement records | Fixture validated | Source identity, current reference, package materialization, and external-reference policy pressure without accepting storage, checksum, backup, package writer, importer, or GUI behavior. |
| Running measurement inspection | Measurement records | Implementation candidate validated | Side-effect-free state summary for already-recorded data from still-running measurements, including progress, completeness, freshness, declared preview metadata, and non-durable monitor ergonomics without live-service, GUI, plotting, storage, import/export, or hardware-control authority. |
| Incoming measurement record import preview | Measurement records | Implementation candidate validated | Side-effect-free preview and classification for explicit incoming-record manifests, including source identity, current-reference state, declared preview metadata, linked context, and review findings without import acceptance, storage mutation, selected-measurement export package preview, schema inference, package integrity, recursive traversal, or GUI behavior. |
| Handoff package contents preview | Measurement records | Implementation candidate validated | Side-effect-free preview and classification for Scopecat-authored selected-measurement export package manifests, including package identity, selected measurements, packaged contents, declared preview metadata, visible-but-not-packaged artifacts, and missing context without import acceptance, storage mutation, archive extraction, package integrity, schema inference, recursive traversal, or GUI behavior. |
| Adapter-authored legacy import manifest | Measurement records | Implementation candidate validated | Side-effect-free validation and summary for normalized manifests emitted by user-owned legacy adapters, including adapter identity, external source identity, primary-data reference, declared preview metadata, linked context, and adapter findings without stable public API, LabRAD/DataVault/Labber reader behavior, import acceptance, storage mutation, schema inference, package format, recursive traversal, or GUI behavior. |
| Legacy import acceptance | Measurement records | Implementation candidate validated | Approved copy-into-new-record mutation for one reviewed adapter-authored manifest, including source sha256/size preflight, no-overwrite targets, copied primary data, deterministic imported-record manifest, preserved external source identity, and reference-only linked context without stable import API, legacy readers in core, export-package acceptance, existing-record update, schema inference, recursive traversal, package integrity, or GUI behavior. |
| Reference-only legacy import | Measurement records | Implementation candidate validated | Side-effect-free reference-only acceptance summary for one reviewed adapter-authored manifest, including lab-managed current-reference facts, public-safe redacted display validation, preserved source identity, unobserved openability/checksum/size state, and reference-only linked context without copying primary data, storage mutation, source observation, repair, stable import API, legacy readers in core, export-package acceptance, schema inference, recursive traversal, package integrity, or GUI behavior. |
| New-run measurement writer semantics | Measurement records | Implementation candidate validated | Side-effect-free summary from explicit writer events, including lifecycle, progress, declared primary data reference, and preview metadata without storage mutation, source observation, schema inference, live service, hardware control, scan execution, or GUI behavior. |
| Append-only measurement storage writer | Measurement records | Implementation candidate validated | Approved filesystem mutation for one new measurement record directory from declared append chunks, including sha256/size preflight, no-overwrite targets, stored primary data, and deterministic manifest without final storage architecture, schema inference, import/export packages, live service, GUI, or hardware-control authority. |
| Derived artifact source links | Measurement records | Implementation candidate validated | Side-effect-free summary for an explicit derived-artifact manifest, including artifact identity, direct source measurement roles, relation states, and review findings without artifact parsing, source observation, checksum validation, storage mutation, recursive traversal, analysis-DAG inference, scientific validity review, or GUI behavior. |
| Measurement source observation | Measurement records | Implementation candidate validated | Read-only observation for one declared primary-data file under a caller-provided storage root, including sha256, size, row-count, unavailable, and mismatch findings without schema inference, repair, recursive storage inspection, import/export packages, live service, GUI, or hardware-control authority. |
| Declared scan/data-shape fixtures | Measurement records support | Spike/fixtures validated | Declared 1D table, rectangular 2D grid table, and sidecar-declared weak-table pressure for preview readiness, not a final data-shape schema or importer. |
| Parameter state management | Parameter state | Implementation candidate validated | Side-effect-free summary for parameter-state lineage, purpose labels, seeded/trusted state, reviewable diffs, committed states, and measurement references without hardware write-back, instrument state tracking, external JSON authority, or branch/tag/commit semantics. |
| Parameter write compatibility output | Parameter state | Implementation candidate validated | Side-effect-free compatibility-output plan for accepted committed parameter state, including trusted scalar emits and skipped untrusted or schema-limited entries without file writes, hardware write-back, schema migration, or external JSON authority. |
| Experiment code recording | Experiment code context | Summary candidate validated | Recorded run/step code context and code snapshot record from explicit include policy and capture-state posture without Git inspection, dependency discovery, environment restore, loading, execution, or workflow/DAG semantics. |
| Managed code version | Experiment code context | Summary candidate validated | Managed record shape for a code snapshot record, including stable identity, inclusion-aligned file inventory, integrity hints, and materialization intent without workspace creation or environment restore. |
| Comparable code surface | Experiment code context | Implementation candidate validated | Declared-fact comparison between a recorded code context and managed code version, including same-observed, changed, missing, unverified, redacted, and not-compared findings without Git inspection, semantic source diff, import, execution, environment readiness, or workspace materialization. |
| Workspace materialization intent | Experiment code context | Implementation candidate validated | Side-effect-free destination planning for a selected managed code version, including planned, collision, redacted, and unavailable findings without filesystem inspection, file writes, overwrite, merge, environment restoration, import, execution, or GUI behavior. |
| Workspace materialization | Experiment code context | Implementation candidate validated | Approved file materialization from declared managed content into a caller-provided workspace root, including digest/size preflight, no-overwrite writes, explicit existing-target skips, and redacted/unavailable findings without Git, environment restoration, import, execution, or GUI behavior. |
| Editable-folder observation | Experiment code context | Implementation candidate validated | Read-only observation of a selected editable workspace against a managed code version, including same-observed, changed-observed, missing-expected, redacted, unavailable, and non-authoritative extra-file findings without Git inspection, semantic source diff, workspace mutation, environment readiness, import, or execution. |
| Prepared run context | Experiment code context | Implementation candidate validated | Side-effect-free manual run-context summary for selected managed code/workspace observation, parameter state, setup binding, station registry, measurement intent, and missing declared environment context without shared schema, hardware control, restore, environment sync, code import, execution, or readiness claims. |
| Declared environment inventory | Experiment code context | Implementation candidate validated | Side-effect-free summary for declared runtime hints, dependency-source references, package declarations, and external-tool hints without reading environment files, resolving dependencies, installing packages, checking runtime readiness, importing code, or executing code. |
| Reference-based rerun preparation | Experiment code context | Implementation candidate validated | Side-effect-free manual rerun preparation from a selected reference measurement and its linked context without reproducibility guarantees, cause attribution, automatic drift correction, hardware control, environment sync, code import, or execution. |
| Environment readiness planning | Experiment code context | Implementation candidate validated | Side-effect-free check plan from a declared modern `uv`/`pyproject.toml` environment context, with lab-managed drivers and legacy dependency concerns as record-only review notes rather than sync inputs, without reading dependency files, resolving or syncing dependencies, installing packages, probing runtime or hardware, importing code, executing code, or claiming runnable readiness. |
| Environment comparison findings | Experiment code context | Implementation candidate validated | Side-effect-free comparison of selected-reference and current declared environment facts, including same-declared, changed, missing, unverified, and unsupported findings without reading manifests or lockfiles, resolving or syncing dependencies, probing runtime or hardware, importing code, executing code, or claiming runnable readiness. |
| Environment file observation | Experiment code context | Implementation candidate validated | Read-only observation for explicitly declared environment files under a caller-provided workspace root, including sha256, size, unavailable, mismatch, malformed-manifest, and narrow `pyproject.toml` summary facts without workspace discovery, lockfile parsing, dependency resolution or sync, runtime probes, code import or execution, hardware checks, or runnable-readiness claims. |
| Setup binding | Setup binding | Implementation candidate validated | Side-effect-free setup-binding summary for explicit setup-binding snapshots, simple diffs, station-registry references, generated line/readout views, and measurement input references while keeping parameter state, station management, generator execution, and hardware control separate. |
| Calibration work continuation | Calibration continuation | Assembler candidate validated | Continuation-state assembly for planned steps, observed outputs, review gates, proposed writes, blocked steps, and interventions without executor, scheduler, write-back, or GUI ownership. |
| Selected reference comparison | Selected reference comparison | Implementation candidate validated | Side-effect-free context-comparison summary against a user-selected reference, including declared preview metadata, named input snapshots, selected artifacts, declared facts, and recorded-code context without user judgment, raw-data comparison, fit-quality comparison, setup truth, restore, execution, semantic source diff, or cause attribution. |
| Named run-start input set | Measurement context support | Implementation candidate validated | Side-effect-free run-preparation summary for selected parameter state, setup binding, station registry, managed code version, measurement intent, and missing declared environment context without shared schema, hardware control, write-back, environment sync, code import, execution, restore, or GUI ownership. |

Future slice candidates should each answer one primary validation question. Do
not combine import/export, storage, GUI, execution, redaction, write-back,
restore, or shared-framework decisions just because the same fixture mentions
more than one of them.

Validation result and plan documents may include slice-local recommendations
for what their fixture earned or deferred. They should not be treated as the
owner of active sequencing. Sequencing belongs in the implementation or PR
plan, using these discovery docs as supporting context.

### Measurement Context Backlog

The canonical shared backlog for context records attached to or selected for
measurements lives in
[`measurement-context-candidate-backlog.md`](measurement-context-candidate-backlog.md).
Use it for context-shaped work across parameter state, setup binding,
experiment code context, declared environment context, analysis choices,
attachments, artifacts, and selected-reference review.

In compact form, the common candidate slices are:

1. context snapshot record;
2. measurement or step context link;
3. named run-start input set;
4. context comparison findings;
5. reviewable context change;
6. context readiness or status;
7. external materialization or compatibility output.

This backlog is discovery vocabulary only. It should reduce duplicated
route-local slice lists without accepting a shared context schema, lifecycle,
storage model, diff engine, write-back contract, or execution framework.

The first cross-family implementation candidate for this backlog is
[`named-run-start-input-set-validation-result.md`](named-run-start-input-set-validation-result.md).
It validates a side-effect-free run-preparation summary without making
Measurement Records the owner of context-support behavior.

### Measurement Records

| Document | Use For |
| --- | --- |
| [`problem-briefs/selected-run-handoff.md`](problem-briefs/selected-run-handoff.md) | Problem framing for selected-run handoff and export pressure. |
| [`problem-briefs/measurement-record-boundary.md`](problem-briefs/measurement-record-boundary.md) | Boundary pressure around primary measurement data, context, attachments, and artifacts. |
| [`selected-run-handoff-spike-summary.md`](selected-run-handoff-spike-summary.md) | Narrow spike summary before the preview-ready export consolidation. |
| [`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md) | Decision-ready discovery summary for preview-ready selected measurement export. |
| [`preview-ready-selected-measurement-export-plan.md`](preview-ready-selected-measurement-export-plan.md) | Planning boundary for the source/metadata-first export slice. |
| [`preview-ready-selected-measurement-export-implementation-plan.md`](preview-ready-selected-measurement-export-implementation-plan.md) | Code-facing plan for the pure selected measurement export summary builder. |
| [`preview-ready-selected-measurement-export-validation-result.md`](preview-ready-selected-measurement-export-validation-result.md) | Result of the first implementation-shaped export candidate. |
| [`storage-transition-export-fixture.md`](storage-transition-export-fixture.md) | Fixture note for managed storage, external references, source identity, and export materialization pressure. |
| [`storage-transition-export-validation-result.md`](storage-transition-export-validation-result.md) | Result of the storage-transition fixture and domain review. |
| [`external-file-reference-policy.md`](external-file-reference-policy.md) | Candidate external-file policy modes that affect export, import, inspection, and provenance. |
| [`../../spikes/scan_data_shapes/README.md`](../../spikes/scan_data_shapes/README.md) | Spike boundary for declared scan/data-shape fixture generation. |
| [`../../tests/fixtures/scan_data_shapes/`](../../tests/fixtures/scan_data_shapes/) | Public-safe fixtures for rectangular 2D grid and sidecar-declared weak-table pressure. |
| [`problem-briefs/running-measurement-inspection.md`](problem-briefs/running-measurement-inspection.md) | Problem framing for inspecting already-recorded data from a still-running measurement. |
| [`running-measurement-inspection-validation-plan.md`](running-measurement-inspection-validation-plan.md) | First fixture-validation boundary for running inspection. |
| [`running-measurement-inspection-validation-result.md`](running-measurement-inspection-validation-result.md) | Result of the running-inspection implementation candidate. |
| [`measurement-record-import-preview-validation-result.md`](measurement-record-import-preview-validation-result.md) | Result of the first side-effect-free incoming-record import preview implementation candidate. |
| [`handoff-package-contents-preview-validation-result.md`](handoff-package-contents-preview-validation-result.md) | Result of the first side-effect-free Scopecat-authored handoff package contents preview implementation candidate. |
| [`adapter-authored-legacy-import-validation-result.md`](adapter-authored-legacy-import-validation-result.md) | Result of the first normalized adapter-authored legacy import manifest candidate. |
| [`legacy-import-acceptance-validation-result.md`](legacy-import-acceptance-validation-result.md) | Result of the first approved copy-into-new-record acceptance candidate for a reviewed adapter-authored legacy manifest. |
| [`reference-only-legacy-import-validation-result.md`](reference-only-legacy-import-validation-result.md) | Result of the first side-effect-free reference-only acceptance candidate for a reviewed adapter-authored legacy manifest. |
| [`new-run-measurement-writer-validation-result.md`](new-run-measurement-writer-validation-result.md) | Result of the first side-effect-free writer-event implementation candidate. |
| [`measurement-storage-writer-validation-result.md`](measurement-storage-writer-validation-result.md) | Result of the first approved append-only storage writer implementation candidate. |
| [`derived-artifact-source-links-validation-result.md`](derived-artifact-source-links-validation-result.md) | Result of the first explicit derived-artifact source-link implementation candidate. |
| [`measurement-source-observation-validation-result.md`](measurement-source-observation-validation-result.md) | Result of the first read-only source observation implementation candidate. |

Candidate next slices in this route should stay separate:

- existing-record append or update pressure: validate locks, crash recovery,
  and in-progress record behavior separately from the new-record writer and
  legacy import acceptance;
- source observation for reference-only imported records: validate explicit
  checks against lab-managed shared-storage references without automatic
  repair, discovery, or schema inference.

The first reference-only legacy import candidate is validated in
[`reference-only-legacy-import-validation-result.md`](reference-only-legacy-import-validation-result.md).
It preserves one reviewed adapter-authored legacy record as an external
lab-managed primary-data reference, validates public-safe display facts, and
leaves primary-data copy, storage mutation, source observation, repair,
export-package acceptance, schema inference, package integrity, and GUI
behavior out of scope.

The first legacy import acceptance candidate is validated in
[`legacy-import-acceptance-validation-result.md`](legacy-import-acceptance-validation-result.md).
It copies one reviewed adapter-authored legacy record into new storage after
source sha256 and size preflight, preserves external source identity and
linked context as reference-only facts, and leaves stable import APIs,
legacy readers in core, export-package acceptance, existing-record update,
schema inference, package integrity, and GUI behavior out of scope.

The first append-only storage writer candidate is validated in
[`measurement-storage-writer-validation-result.md`](measurement-storage-writer-validation-result.md).
It writes one new record directory under a caller-provided storage root from
declared append chunks, after sha256 and size preflight, while refusing
existing targets and leaving final storage architecture, import/export package
behavior, schema inference, live service, GUI, and hardware control out of
scope.

The first derived artifact source-link candidate is validated in
[`derived-artifact-source-links-validation-result.md`](derived-artifact-source-links-validation-result.md).
It connects one derived artifact to explicit source measurements with source
roles, relation states, and review findings, while leaving artifact parsing,
source observation, checksum validation, storage mutation, recursive traversal,
analysis-DAG inference, scientific validity review, and GUI behavior out of
scope.

The first source observation candidate is validated in
[`measurement-source-observation-validation-result.md`](measurement-source-observation-validation-result.md).
It checks one declared primary-data file under a caller-provided storage root
against declared sha256, size, and row-count facts, while reporting
unavailable or mismatched data as review findings and leaving schema
inference, repair, package validation, import/export behavior, live service,
GUI, and hardware control out of scope.

The first handoff package contents preview candidate is validated in
[`handoff-package-contents-preview-validation-result.md`](handoff-package-contents-preview-validation-result.md).
It summarizes a Scopecat-authored selected-measurement export package manifest
before opening, accepting, or organizing it, while leaving archive extraction,
package integrity, import acceptance, storage mutation, schema inference,
recursive traversal, GUI behavior, and final package format out of scope.

Context-shaped work such as recorded analysis choices and handoff context
should use the Measurement Context Backlog above unless the slice is about
primary measurement data or this direct artifact-to-measurement source-link
boundary.

### Parameter State

| Document | Use For |
| --- | --- |
| [`problem-briefs/parameter-state-management.md`](problem-briefs/parameter-state-management.md) | Problem framing for first-class calibrated parameter state, lineages, trust/readiness state, reviewable diffs, and write-back boundaries. |
| [`parameter-state-management-validation-plan.md`](parameter-state-management-validation-plan.md) | First fixture-validation boundary and fixture pointer for parameter state lineage, purpose labels, reviewable diffs, and committed states. |
| [`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md) | Result of the first parameter-state fixture, domain review, and summary candidate. |
| [`parameter-write-compatibility-output-validation-plan.md`](parameter-write-compatibility-output-validation-plan.md) | First compatibility-output boundary for accepted committed parameter state without writing files or applying hardware parameters. |
| [`parameter-write-compatibility-output-validation-result.md`](parameter-write-compatibility-output-validation-result.md) | Result of the first parameter write compatibility-output fixture and summary candidate. |

The first parameter-state summary candidate is validated in
[`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md).
It summarizes copied seed state, accepted reviewable diff, committed parameter
state, and run-start measurement selection while leaving hardware write-back,
instrument state tracking, external JSON authority, branch/tag/commit
semantics, rollback automation, drift plotting, and shared domain models out
of scope.

Most next parameter-state slices are instances of the Measurement Context
Backlog: context links, named run-start inputs, comparison findings,
reviewable changes, readiness or trust state, and external compatibility
outputs. Parameter-specific validation should stay narrow around lineage
purposes, trusted versus seeded state, drift views, reviewable parameter-write
records, and compatibility output planning without applying changes to
hardware.

The first parameter write compatibility-output candidate is validated in
[`parameter-write-compatibility-output-validation-result.md`](parameter-write-compatibility-output-validation-result.md).
It plans trusted scalar output entries from an accepted committed parameter
state while reporting skipped untrusted or schema-limited entries. It does not
write files, apply parameters to hardware, claim external JSON authority, or
perform schema migration.

### Experiment Code Context

| Document | Use For |
| --- | --- |
| [`problem-briefs/experiment-code-recording.md`](problem-briefs/experiment-code-recording.md) | Copied folders, entrypoint/helper ambiguity, recorded run/step code context, environment readiness, and future code snapshot selection. |
| [`managed-experiment-code-posture.md`](managed-experiment-code-posture.md) | Direction for messy external-folder recording, Scopecat-managed code versions, named entrypoints, and workflow/DAG deferral. |
| [`experiment-code-recording-validation-plan.md`](experiment-code-recording-validation-plan.md) | First fixture-validation boundary for recorded code context that defines code snapshot records. |
| [`experiment-code-recording-validation-result.md`](experiment-code-recording-validation-result.md) | Result of the first code snapshot fixture and summary candidate. |
| [`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md) | What the code-recording slice has earned, what remains deferred, the user adoption route, and the candidate validation-slice backlog. |
| [`managed-code-version-validation-plan.md`](managed-code-version-validation-plan.md) | First fixture-validation boundary for turning a code snapshot record into a managed code version record. |
| [`managed-code-version-validation-result.md`](managed-code-version-validation-result.md) | Result of the first managed code version fixture and summary candidate. |
| [`comparable-code-surface-validation-result.md`](comparable-code-surface-validation-result.md) | Result of the first recorded-to-managed declared-fact comparison candidate. |
| [`workspace-materialization-intent-validation-result.md`](workspace-materialization-intent-validation-result.md) | Result of the first side-effect-free workspace materialization intent candidate. |
| [`workspace-materialization-validation-plan.md`](workspace-materialization-validation-plan.md) | First write-bounded validation boundary for creating an editable workspace from a selected managed code version. |
| [`workspace-materialization-validation-result.md`](workspace-materialization-validation-result.md) | Result of the first approved workspace materialization fixture and implementation candidate. |
| [`editable-folder-observation-validation-result.md`](editable-folder-observation-validation-result.md) | Result of the first read-only editable-folder observation fixture and implementation candidate. |
| [`prepared-run-context-validation-result.md`](prepared-run-context-validation-result.md) | Result of the first prepared run context fixture and implementation candidate. |
| [`declared-environment-inventory-validation-result.md`](declared-environment-inventory-validation-result.md) | Result of the first declared environment inventory fixture and implementation candidate. |
| [`reference-based-rerun-preparation-validation-result.md`](reference-based-rerun-preparation-validation-result.md) | Result of the first reference-based rerun preparation fixture and implementation candidate. |
| [`environment-readiness-validation-result.md`](environment-readiness-validation-result.md) | Result of the first environment readiness planning fixture and implementation candidate. |
| [`environment-comparison-validation-result.md`](environment-comparison-validation-result.md) | Result of the first declared environment comparison fixture and implementation candidate. |
| [`environment-file-observation-validation-result.md`](environment-file-observation-validation-result.md) | Result of the first explicit declared environment file observation fixture and implementation candidate. |

The canonical Experiment Code Context candidate-slice backlog lives in
[`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md).
In compact form, the validation slices should be ordered by authority level.
This order is not the user adoption route; it is the order in which Scopecat
should earn stronger claims:

1. comparable code surface: compare two authority-explicit code fact sets over
   known captured, reference-only, missing, redacted, or excluded surfaces,
   without accepting a universal diff model;
2. workspace materialization intent: plan where a selected managed version
   would be materialized, without creating an editable workspace;
3. workspace materialization: create an editable workspace from a selected
   managed version, without environment sync, code import, Git semantics, or
   execution;
4. editable-folder observation: compare an observed editable folder against a
   selected managed version or materialized workspace, without claiming
   environment readiness or semantic source correctness;
5. prepared run context: assemble selected code or workspace, selected
   parameter state, setup binding, and measurement intent so a user can run
   existing lab code outside Scopecat, without claiming execution or hardware
   control;
6. declared environment inventory: record declared environment files,
   lockfiles, interpreter hints, or package-manager hints, without syncing,
   importing, or checking runnable readiness;
7. reference-based rerun preparation: start from a selected reference
   measurement and prepare the matching run context for manual rerun, without
   claiming reproducibility or automatic cause attribution;
8. environment readiness planning: plan checks from declared modern Python
   environment context without running resolution, sync, probes, or execution;
9. environment comparison findings: compare selected-reference and current
   declared environment facts without reading manifests or lockfiles, resolving
   dependencies, syncing packages, probing runtimes or hardware, importing
   code, executing code, or claiming runnable readiness;
10. environment file observation: observe explicitly declared environment files
    under a caller-provided workspace root without workspace discovery,
    lockfile parsing, dependency resolution or sync, runtime probes, code
    import or execution, hardware checks, or runnable-readiness claims.

The comparison work is a fixture family, not one slice. The first
recorded-to-managed declared-fact comparison is validated in
[`comparable-code-surface-validation-result.md`](comparable-code-surface-validation-result.md).
Future fixtures should add one authority case at a time: managed-version
inventory comparison, capture-state edge cases, or additional editable-folder
observation cases. Add materialized-directory comparison or semantic source
diff only when a separate validation question needs that stronger authority.

The first workspace materialization intent candidate is validated in
[`workspace-materialization-intent-validation-result.md`](workspace-materialization-intent-validation-result.md).
It plans destination paths and review findings for a selected managed version
without inspecting the filesystem or writing files.

The first workspace materialization candidate is validated in
[`workspace-materialization-validation-result.md`](workspace-materialization-validation-result.md).
It writes declared content-available files into a caller-provided workspace
root after approval, while refusing overwrites and leaving environment, Git,
import, execution, and GUI behavior out of scope.

The first editable-folder observation candidate is validated in
[`editable-folder-observation-validation-result.md`](editable-folder-observation-validation-result.md).
It observes one selected editable workspace root against a managed code version
with size and sha256 facts only. The selected managed-version inventory remains
the strong include list; extra workspace files are bounded, non-authoritative
observations, and declared workspace-internal directories are ignored. Semantic
diff, Git diagnostics, workspace mutation, environment readiness, import,
execution, and prepared-run context remain out of scope.

The first prepared run context candidate is validated in
[`prepared-run-context-validation-result.md`](prepared-run-context-validation-result.md).
It assembles selected managed code version, declared editable-workspace
observation, parameter state, setup binding, station registry, measurement
intent, and missing declared environment context for manual run preparation.
Workspace drift and missing environment context are review findings, not
runnable-readiness, safety, restore, import, execution, or hardware-control
claims.

The first declared environment inventory candidate is validated in
[`declared-environment-inventory-validation-result.md`](declared-environment-inventory-validation-result.md).
It summarizes explicit runtime hints, dependency-source references, package
declarations, and external-tool hints without reading files, resolving or
installing dependencies, checking runtime readiness, importing code, or
executing code.

The first reference-based rerun preparation candidate is validated in
[`reference-based-rerun-preparation-validation-result.md`](reference-based-rerun-preparation-validation-result.md).
It starts from a user-selected reference measurement and seeds a proposed
manual rerun context from explicit reference-linked context records. Workspace
and declared-environment findings remain review facts, not reproducibility,
cause-attribution, drift-correction, readiness, execution, or hardware-control
claims.

The first environment readiness planning candidate is validated in
[`environment-readiness-validation-result.md`](environment-readiness-validation-result.md).
It plans checks from a declared modern `uv`/`pyproject.toml` environment
context, treating lab-managed drivers and legacy dependency concerns as review
or migration notes rather than equal dependency declaration sources or sync
inputs. It does not read files, resolve or sync dependencies, install packages,
import code, execute code, probe hardware, or claim runnable readiness.

The first declared environment comparison candidate is validated in
[`environment-comparison-validation-result.md`](environment-comparison-validation-result.md).
It compares selected-reference and current declared environment facts without
reading manifests or lockfiles, resolving dependencies, syncing packages,
probing runtimes, importing code, executing code, probing hardware, or claiming
runnable readiness.

The first environment file observation candidate is validated in
[`environment-file-observation-validation-result.md`](environment-file-observation-validation-result.md).
It observes explicitly declared `pyproject.toml` and `uv.lock` files under a
caller-provided workspace root with sha256 and size facts, while parsing
`pyproject.toml` only for declared manifest summary fields and reporting
malformed manifests as review findings without losing observed file facts. It
does not scan workspaces, parse lockfiles into dependency graphs, resolve or
sync dependencies, install packages, probe runtimes or hardware, import code,
execute code, or claim runnable readiness.

Do not validate "select a code version at run start" by itself. Selection
becomes useful only when it prepares a run context, supports a reference-based
rerun, or checks an editable folder against the selected version.

### Setup Binding

| Document | Use For |
| --- | --- |
| [`problem-briefs/setup-binding.md`](problem-briefs/setup-binding.md) | Problem framing for sample/cooldown binding between logical entities and physical wiring/device resources. |
| [`setup-binding-validation-plan.md`](setup-binding-validation-plan.md) | First fixture-validation boundary for setup-binding snapshots, diffs, and measurement references. |
| [`setup-binding-validation-result.md`](setup-binding-validation-result.md) | Result of the first setup-binding fixture, measurement-input context review, and implementation candidate. |

The first setup-binding implementation candidate is validated in
[`setup-binding-validation-result.md`](setup-binding-validation-result.md).
It builds a side-effect-free summary from explicit setup-binding fixture input,
validates selected station-registry references, carries declared generated
line/readout views, keeps user/project-defined inner payloads opaque, and
reports binding changes as review attention without claiming parameter
invalidation. Station management, hardware control, generator/converter
execution, setup-truth decisions, GUI behavior, shared snapshot framework, and
payload interpretation remain out of scope.

Most next setup-binding slices are instances of the Measurement Context
Backlog: context links, named run-start inputs, comparison findings,
readiness/status summaries, and selected-reference setup findings.
Setup-specific validation should stay narrow around station-registry
references, setup-import validation reports, generated line/readout summaries,
opaque project-defined payloads, and setup-truth deferral.

### Calibration Continuation

| Document | Use For |
| --- | --- |
| [`problem-briefs/calibration-work-continuation.md`](problem-briefs/calibration-work-continuation.md) | Problem framing for calibration continuation, review gates, and executor pressure. |
| [`calibration-work-continuation-validation-plan.md`](calibration-work-continuation-validation-plan.md) | First fixture-validation boundary for continuation-state assembly. |
| [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md) | Result of the continuation assembler candidate and domain review. |

Calibration continuation overlaps the Measurement Context Backlog for context
links, reviewable changes, readiness/status summaries, and selected parameter
or setup references. Its domain-specific backlog should stay focused on
review/resume usefulness, calibration-write review, targeted remeasurement
intent, and a possible local sequential executor boundary after the read model
proves useful but insufficient.

### Selected Reference Comparison

| Document | Use For |
| --- | --- |
| [`problem-briefs/selected-reference-comparison.md`](problem-briefs/selected-reference-comparison.md) | Problem framing for selected references, user marks, setup reality, objective comparison findings, and user-interpretation boundaries. |
| [`selected-reference-comparison-validation-plan.md`](selected-reference-comparison-validation-plan.md) | Fixture-validation boundaries for selected-reference context comparison. |
| [`selected-reference-comparison-validation-result.md`](selected-reference-comparison-validation-result.md) | Result of selected-reference context comparison fixtures, including the basic named-input fixture and declared code-context comparison fixture. |

Most selected-reference work is a cross-family instance of the Measurement
Context Backlog, especially context comparison findings over parameter state,
setup binding, code context, environment context, and preview metadata.
Selected-reference-specific validation should stay narrow around explicit user
anchors, objective findings, preview compatibility, support-package review
boundaries, and the continued separation from user judgment, raw-data
comparison, fit-quality comparison, setup truth, semantic source review,
restore, execution, or cause attribution.

## Promotion Discipline

Do not promote a validation result directly into shared architecture.

Before moving a concept into accepted schema, shared implementation, or
`docs/architecture/`, make sure there is:

- pressure from more than one validated slice;
- a concrete implementation need;
- explicit tests or contracts that would otherwise be duplicated;
- a narrower decision or ADR that names the ownership and what remains out of
  scope.
