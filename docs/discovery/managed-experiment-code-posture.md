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
generated files, and unclear entrypoints. Scopecat should be able to capture
useful selected code context without pretending the folder is well managed.

The earliest adoption path should be deliberately minimal:

- record only files or references the user explicitly whitelists;
- do not inspect internal Git state;
- do not recursively analyze every file in the selected folder;
- do not turn unselected backup, cache, checkpoint, or generated files into
  noisy warnings;
- strip notebook outputs before recording `.ipynb` files;
- avoid dependency discovery, import-time inspection, and mutation-capability
  inference unless a later validation earns them.

The near-term product boundary is:

- selected code context from a messy external folder;
- a candidate captured version that Scopecat could later manage;
- explicit whitelist and notebook recording policy;
- explicit links from measurements or calibration steps to selected code
  context.

This is an adoption route, not a retreat from managed code. The first useful
step is to let users name the experiment code that matters most to the run:
entrypoints, notebooks, helper files, declared context references, and selected
generated companions. That already covers the code most directly tied to
experiment workflow and intent while avoiding legacy-codebase analysis.

The long-term direction is:

- Scopecat-managed code workspaces that can be expanded into editable folders;
- user edits happen in ordinary files and notebooks;
- Scopecat records saved versions and diffs;
- measurements reference the selected code version at run start;
- selected code versions can be materialized on another machine or environment
  when storage and environment support are earned.
- environment restoration may later include loading a selected code version and
  running a declared environment sync, such as a `uv` lockfile workflow, but
  only after managed workspace storage and environment authority are earned.

## First Boundary

The first supported path should be selected root plus a user whitelist.

This means the first record can say:

- which root or folder was selected;
- which notebook, script, function, or template is the intended entrypoint;
- which specific files or declared references the user whitelisted;
- whether whitelisted notebooks were recorded as source without outputs;
- which broad non-recording policy applies to unwhitelisted files;
- which environment profile or setup context the user linked explicitly;
- that execution, dependency discovery, Git inspection, and mutation analysis
  were not performed.

This boundary does not require users to divide the codebase into independently
versioned workflow nodes.

It also does not require Scopecat to analyze a legacy repository before it can
be useful. File selection remains user-owned in the first slice; Scopecat
records the selection, makes its limits visible, strips notebook outputs when
recording notebooks, and links the selected code context to measurements or
calibration steps.

## Adoption Route

The intended route is:

- start with whitelist-based records for the files and references the user
  considers experiment-relevant;
- use those records to connect measurements, calibration steps, handoff
  packages, and comparison workflows to the code context users actually meant;
- let users gradually move from external folders into Scopecat-managed
  workspaces when they want restore, compare, and version-selection behavior;
- only then consider loading selected code versions, environment restoration,
  lockfile-driven dependency sync, execution readiness checks, or managed
  runners.

This route keeps early adoption practical for messy labs while preserving the
later path toward structured code management.

## Workflow And DAG Deferral

Workflow/DAG structure is future pressure, not the first code-versioning
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

- version the user-whitelisted capture scope first;
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
boundary should record them only when the user explicitly whitelists or links
them.

Scopecat should not silently regenerate circuit JSON, chip/line info, registry
views, waveform-adjacent state, or derived analysis arrays as part of selected
code capture. Regeneration, build pipelines, and transformation validation are
later questions.

## Current Questions

- Is selected root plus explicit whitelist enough for the first selected-code
  and captured-version-candidate boundary?
- What should Scopecat store for a captured version first: file contents,
  checksums, stripped notebooks, an archive, or a content-addressed snapshot?
- Which whitelist helpers should exist for common notebook/script workflows
  without defaulting to record-all behavior?
- When, if ever, should Git state become an optional diagnostic rather than
  ignored early-adoption noise?
- When should environment readiness become active validation rather than
  user-declared references?
- What conditions would earn workflow/DAG nodes as first-class records?

## Current Recommendation

Use the validated selected-code fixture and
[`experiment-code-selection-next-boundary.md`](experiment-code-selection-next-boundary.md)
as the stop point for this slice.

The validated boundary represents a messy external folder being selected with a
small explicit whitelist and captured as a candidate for a future
Scopecat-managed version. It makes the selected root, entrypoint, whitelisted
files, notebook-output stripping, declared context references, and
non-recording policy visible without inspecting Git, scanning unselected files,
executing code, importing code, or inferring dependencies. Start a later
managed-workspace slice only when restore, compare, materialization, or
selected-version-at-run-start behavior creates concrete implementation
pressure.
