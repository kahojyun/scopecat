# Reference-Based Rerun Preparation Validation Result

## Status

Implementation candidate validated.

This result validates the seventh Experiment Code Context backlog slice:
**Reference-Based Rerun Preparation**.

It does not accept a reproducibility guarantee, cause-attribution engine,
automatic drift correction, executor, hardware-control contract, parameter
write-back, setup mutation, dependency sync, code import, code execution,
shared context schema, workflow/DAG behavior, or GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/reference_based_rerun_preparation/basic_rerun/`](../../tests/fixtures/reference_based_rerun_preparation/basic_rerun/)

Implementation candidate:
[`../../implementation_candidates/reference_based_rerun_preparation/`](../../implementation_candidates/reference_based_rerun_preparation/)

The fixture records one user-selected last-working qA Rabi reference
measurement and uses its linked context to seed a proposed manual rerun
context:

- measurement intent;
- parameter state;
- setup binding;
- station registry context;
- managed code version;
- editable workspace observation;
- declared environment inventory.

The builder treats the selected reference as declared selection state. It does
not inspect measurement data, judge the reference as scientifically good,
compare raw data, check fit quality, inspect the filesystem, resolve
dependencies, import selected code, execute code, configure hardware, or apply
context changes.

## What This Earned

The implementation candidate shows that a side-effect-free summary can prepare
a manual rerun from a selected reference measurement without increasing
Scopecat's authority:

- preserve selected reference measurement identity, user selection reason, and
  linked context counts;
- validate that rerun-selected context records are seeded from the selected
  reference links rather than silently invented;
- preserve family-owned context records without defining a shared payload
  schema;
- validate editable workspace observation alignment to the selected managed
  code version;
- validate proposed run target alignment to the selected measurement intent;
- report workspace-observation and declared-environment review findings
  without turning them into run-blocking, readiness, reproducibility, or
  safety claims;
- keep hardware control, parameter write-back, setup mutation, dependency
  sync, code import, code execution, drift correction, and cause attribution
  out of scope.

## Boundary

This slice validates reference-based rerun preparation only.

It does not:

- decide that a selected reference is good, correct, representative, or
  reproducible;
- compare raw measurement data, fit quality, plots, analysis conclusions, or
  scientific outcomes;
- infer causes for differences between the reference and a future rerun;
- perform fresh filesystem observation or semantic source diff;
- resolve, install, sync, or verify runtime dependencies;
- import, load, or execute selected code;
- configure instruments, write parameters, mutate setup bindings, or start a
  run;
- automatically correct drift, missing files, environment gaps, parameter
  differences, or setup differences;
- define final run lifecycle, restore behavior, shared context schema,
  executor, scheduler, workflow/DAG, or GUI behavior.

## Result

Reference-based rerun preparation is useful after prepared run context and
declared environment inventory because it tests the user workflow that starts
from a prior measurement rather than from independently chosen context
records. It can propose a manual rerun context from explicit reference-linked
records while showing workspace and declared-environment review findings.

The selected reference remains a seed, not a truth source. Review findings
remain attention items, not automatic blockers or corrections. The output
helps a user gather matching context for a manual rerun while existing lab
systems still own environment setup, code execution, and hardware control.

## Follow-Up

Stop this slice at manual rerun preparation unless the next workflow needs a
sharper boundary around environment readiness or execution.

Likely follow-up slices should stay separate:

- environment readiness planning, still without dependency sync,
  hardware-active import, or experiment execution;
- comparison fixtures that add one reference-context authority case at a time;
- execution or managed-runner slices only after context selection,
  materialization, observation, and environment authority are separately
  validated.
