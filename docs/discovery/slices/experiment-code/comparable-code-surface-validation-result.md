# Comparable Code Surface Validation Result

## Status

Implementation candidate validated.

This result validates the first Experiment Code Context backlog slice:
**Comparable Code Surface**.

It does not accept a universal diff model, semantic source review, Git
diagnostics, environment readiness contract, restore contract, workspace
materialization contract, code import, code execution, workflow/DAG model, or
GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/comparable_code_surface/recorded_to_managed/`](../../../../tests/fixtures/comparable_code_surface/recorded_to_managed)

Implementation candidate:
[`../../implementation_candidates/comparable_code_surface/`](../../../../implementation_candidates/comparable_code_surface)

The fixture compares one recorded external-folder code context against one
Scopecat-managed code version from explicit code facts:

- declared file paths and roles;
- recorded forms;
- capture states;
- sha256 integrity hints for content-captured files;
- source authority for each code surface.

The fixture intentionally includes same-observed, changed, missing,
unverified, redacted, and not-compared findings so the candidate can keep
content-comparison limits visible.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- compare two authority-explicit code surfaces without reading source files;
- preserve recorded-context versus managed-version authority;
- use declared digest equality only for `same_observed`;
- use declared digest difference only for `changed`;
- distinguish absent paths from reference-only, redacted, and excluded paths;
- report comparison findings without claiming semantic source meaning,
  runnable readiness, Git state, import behavior, or execution behavior.

## Boundary

This slice validates declared-fact comparison only.

It does not:

- inspect Git state;
- read or diff file contents;
- parse, import, load, or execute code;
- infer semantic source differences;
- explain cause, safety, scientific impact, or reproducibility;
- check dependencies, lockfiles, interpreters, or environment readiness;
- materialize, restore, or mutate an editable workspace;
- define a universal diff model across all future code surfaces.

## Result

Comparable code surface is useful as the first stronger authority slice after
recording and managed code version records.

The result supports the sequence in
[`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md):
comparison can be validated before workspace materialization intent,
workspace creation, editable-folder observation, prepared run context,
reference-based rerun preparation, or environment readiness.

## Follow-Up

Stop this slice at recorded-to-managed declared-fact comparison unless the next
workflow needs another authority case.

Likely follow-up slices should stay separate:

- managed-version inventory comparison;
- capture-state edge cases that need a second fixture;
- workspace materialization, after intent planning and only with approved
  writes;
- additional editable-folder observation cases, after the first
  post-materialization observation result;
- declared environment inventory, still without dependency sync or runnable
  readiness claims.
