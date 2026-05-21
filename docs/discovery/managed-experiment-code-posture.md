# Managed Experiment-Code Posture

## Status

Discovery posture, not an ADR.

This note records the intended product direction for experiment-code
management. It does not accept a final storage backend, Git replacement,
workspace layout, package manager, environment manager, execution service,
workflow/DAG model, merge model, sync protocol, GUI design, or code registry.

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

Git and directory structure are import evidence, not user-facing authority.

Many existing lab folders may have stale commits, dirty working trees, nested
repositories, backup folders, notebook checkpoints, copied helper packages,
generated files, and unclear entrypoints. Scopecat should be able to capture
that messy state without pretending it is well managed.

The near-term product boundary is:

- selected code context from a messy external folder;
- a candidate captured version that Scopecat could later manage;
- visible ambiguity and readiness information;
- explicit links from measurements or calibration steps to selected code
  context.

The long-term direction is:

- Scopecat-managed code workspaces that can be expanded into editable folders;
- user edits happen in ordinary files and notebooks;
- Scopecat records saved versions and diffs;
- measurements reference the selected code version at run start;
- selected code versions can be materialized on another machine or environment
  when storage and environment support are earned.

## First Boundary

The first supported path should be whole selected workspace or selected root
plus named entrypoints.

This means the first record can say:

- which root or folder was selected;
- which notebook, script, function, or template is the intended entrypoint;
- which helper roots or generated companions are included;
- which files are excluded or classified as checkpoints, caches, backups,
  archives, generated artifacts, or external references;
- what observed version state exists, such as Git commit, dirty state, file
  checksums, or snapshot timestamp;
- what environment, service, private package, local path, and hardware-active
  assumptions are visible;
- whether the entrypoint is analysis-only, parameter-mutating,
  hardware-active, or unknown.

This boundary does not require users to divide the codebase into independently
versioned workflow nodes.

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

- version the selected workspace first;
- name important entrypoints inside that version;
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
boundary should record them as observed or selected companions.

Scopecat should not silently regenerate circuit JSON, chip/line info, registry
views, waveform-adjacent state, or derived analysis arrays as part of selected
code capture. Regeneration, build pipelines, and transformation validation are
later questions.

## Current Questions

- Is whole selected workspace plus named entrypoints enough for the first
  managed-code version boundary?
- What should Scopecat store for a captured version first: file contents,
  checksums, Git identity when present, an archive, or a content-addressed
  snapshot?
- Which ignore/classification rules are product policy, and which should be
  user-editable?
- How should users see dirty Git state when Git is not the product authority?
- When should environment readiness become active validation rather than
  recorded hints?
- What conditions would earn workflow/DAG nodes as first-class records?

## Current Recommendation

Validate a first selected-code context fixture before designing a managed
workspace store or workflow/DAG model.

The first fixture should represent a messy external folder being selected and
captured into a Scopecat-managed version candidate. It should make code
selection, entrypoint choice, helper scope, observed version state, exclusions,
mutation capability, generated companions, and environment assumptions visible
without executing or importing user code.
