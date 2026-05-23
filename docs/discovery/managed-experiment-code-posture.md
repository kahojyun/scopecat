# Managed Experiment-Code Posture

## Status

Discovery posture, not an ADR.

This note records the intended product direction for experiment-code
management. It does not accept a final storage backend, Git replacement,
workspace layout, package manager, environment manager, execution service,
workflow/DAG model, merge model, sync protocol, GUI design, or code registry.
The durable product direction lives in
[`product-direction.md`](../strategy/product-direction.md); this note owns the
slice-specific discovery boundary.

## Direction

Scopecat should eventually manage experiment-code workspaces with Git-like
versioning hidden behind lab-native actions.

The user-facing model should be closer to:

- save this code version;
- restore or materialize this version;
- compare these changes;
- mark this version as useful for a lab purpose;
- use this version for a measurement, calibration step, analysis, or handoff;
- run or inspect readiness under this environment profile when execution
  support is earned.

It should not require ordinary lab users to understand Git commit, branch,
merge, push, pull, rebase, stash, or submodule workflows before Scopecat can
record useful code context.

## Current Posture

Git and directory structure should not be early-adoption authority.

Many existing lab folders may have stale commits, dirty working trees, nested
repositories, backup folders, notebook checkpoints, copied helper packages,
generated files, and unclear entrypoints. Scopecat should be able to record
useful run/step code context without pretending the folder is well managed.

The earliest adoption path should be deliberately minimal:

- record only files or references the user explicitly includes;
- do not inspect internal Git state;
- do not recursively analyze every file in the recorded folder;
- do not turn unrecorded backup, cache, checkpoint, or generated files into
  noisy warnings;
- strip notebook outputs before recording `.ipynb` files;
- avoid dependency discovery, import-time inspection, and mutation-capability
  inference unless a later validation earns them.

The near-term product boundary is:

- code context recorded from a messy external folder;
- a code snapshot record that Scopecat could later manage;
- explicit include policy and notebook recording policy;
- explicit links from measurements or calibration steps to recorded code
  context.

This keeps `recorded` on the audit side. A future active path can choose a
code snapshot or managed code version, materialize it into a workspace, and
then record which code context was actually associated with the run or step.

This is an adoption route, not a retreat from managed code. The first useful
step is to record the experiment code context associated with the run:
entrypoints, notebooks, helper files, declared context references, and linked
generated companions. That already covers the code most directly tied to
experiment workflow and intent while avoiding legacy-codebase analysis.

Selection can later choose, promote, or restore one of these records. The
record Scopecat is trying to earn first is a point-in-time code snapshot,
analogous to parameter-state or setup-binding snapshots at the
measurement-context level while retaining code-specific storage, restore,
environment, and execution boundaries.

The long-term direction is:

- Scopecat-managed code workspaces that can be expanded into editable folders;
- user edits happen in ordinary files and notebooks;
- Scopecat records saved versions and diffs;
- measurements or calibration steps may reference recorded code context as
  provenance, while later run-preparation workflows may select managed code
  versions as intended inputs;
- code snapshot records can be materialized on another machine or environment
  when storage and environment support are earned.
- environment restoration may later include loading a selected code snapshot and
  running an approved modern-manifest sync, such as a `uv` lockfile workflow,
  but only after managed workspace storage and environment authority are
  earned; legacy or lab-managed environment facts remain record-only migration
  evidence, not sync paths.

## First Boundary

The first supported path should be code context recording: root or source
reference plus an explicit include policy. That context defines the code
snapshot scope; choosing a managed version can come later.

This means the first record can say:

- which root or folder was recorded;
- which notebook, script, function, or template is the recorded entrypoint;
- which specific files or declared references were explicitly included;
- whether included notebooks were recorded as source without outputs;
- which broad non-recording policy applies to unrecorded files;
- which environment profile or setup context the user linked explicitly;
- that execution, dependency discovery, Git inspection, and mutation analysis
  were not performed.

This boundary does not require users to divide the codebase into independently
versioned workflow nodes.

It also does not require Scopecat to analyze a legacy repository before it can
be useful. Scopecat records the run/step code context, makes its limits
visible, strips notebook outputs when recording notebooks, and links that code
context to measurements or calibration steps. Users can later promote or select
those records for restore, comparison, or managed workspace migration.

## Adoption Route

The intended user adoption route is value-driven:

- start with explicit-include code contexts and code snapshot records for the
  files and references associated with a run or step, while code still lives in
  normal lab folders;
- use those records to connect measurements, calibration steps, handoff
  packages, and comparison workflows to the code context users actually used
  or observed;
- promote captured or recaptured snapshots into managed code versions when
  stable identity, inventory, restore, compare, or selection becomes valuable;
- branch from managed versions into comparison, materialization,
  editable-folder observation, run preparation, rerun preparation, or
  environment help only when those workflows solve a concrete lab problem;
- reserve lockfile-driven modern-manifest dependency sync, execution readiness
  checks, and managed runners for labs that want Scopecat to help prepare
  runnable managed contexts, while legacy/lab-managed facts stay review
  evidence.

This route keeps early adoption practical for messy labs while preserving the
later path toward structured code management.

The validation order is stricter than the adoption route. Comparable code
surfaces, materialization intent, workspace materialization, editable-folder
observation, prepared run context, declared environment inventory,
reference-based rerun preparation, and environment readiness planning now each
have first validation results. Actual dependency resolution,
modern-manifest dependency sync, runtime probes, execution readiness, and
managed runners still need separate authority boundaries.

## Workflow And DAG Deferral

Workflow/DAG structure is future pressure, not the first code recording
boundary.

DAG-like structure may become useful when repeated experiment functions have
stable inputs, outputs, review gates, and compatibility expectations. Examples
include calibration routines, setup generation, analysis input assembly, or
multi-step continuation.

It is too early to require DAG structure because:

- exploratory notebooks often do not have stable boundaries;
- helper modules are shared across many tasks;
- function-level versioning would require compatibility rules between nodes;
- users may not know which helper changes affect which experiment step;
- forcing boundaries too early can turn code capture into schema work.

The safer intermediate model is:

- record the user-included code snapshot scope first;
- name important entrypoints inside that capture;
- let measurements and calibration steps reference those entrypoints;
- promote repeated, stable entrypoints into workflow steps only when a later
  validation slice earns input/output contracts.

## Separations To Preserve

Code version should remain separate from:

- parameter state;
- setup binding;
- station registry;
- environment profile;
- measurement record;
- selected reference;
- export package;
- generated companion artifact;
- runtime execution or hardware-control authority.

A measurement may reference several of these as named input or context records
at run start. That does not make them one shared version-control model.

## Generated Artifacts

Generated code-derived artifacts can be important context, but the first
boundary should record them only when the user explicitly includes or links
them.

Scopecat should not silently regenerate circuit JSON, chip/line info, registry
views, waveform-adjacent state, or derived analysis arrays as part of code
recording. Regeneration, build pipelines, and transformation validation are
later questions.

## Current Questions

- Is recorded root plus explicit include policy enough for the first
  code-recording and code snapshot record boundary?
- What should Scopecat store for a code snapshot record first: file contents,
  checksums, stripped notebooks, an archive, or a content-addressed snapshot?
- Which include-list helpers should exist for common notebook/script workflows
  without defaulting to record-all behavior?
- When, if ever, should Git state become an optional diagnostic rather than
  ignored early-adoption noise?
- When should dependency resolution, runtime probes, or active environment
  readiness operations become validation rather than user-declared references
  and readiness planning?
- What conditions would earn workflow/DAG nodes as first-class records?

## Slice Recommendation

Use the validated code-recording fixture and
[`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md)
as the stop point for this slice.

The validated boundary represents a messy external folder being recorded with a
small explicit include list as a candidate for a future Scopecat-managed
version. It makes the recorded root, entrypoint, included files,
notebook-output stripping, declared context references, and non-recording
policy visible without inspecting Git, scanning unrecorded files, executing
code, importing code, or inferring dependencies. Start a later
managed-workspace slice only when restore, compare, materialization, or
prepared-run-context behavior creates concrete implementation pressure.
