# Run Preparation Workflow Boundary Validation Result

## Status

Boundary documentation validated.

Artifact boundary posture: `internal_validation_summary`.

This result is not an ADR, adapter API, reusable template language, shared
run-context schema, run lifecycle model, storage model, GUI workflow,
hardware-control contract, environment manager, executor, or run-start
permission contract.

## Why This Exists

The context-inclusion slices can be confusing without the surrounding
experiment-start workflow. In particular, "absence" means a context role has
no resolved record in a normalized run-preparation input. It does not mean a
caller supplied a context ID and Scopecat silently ignored lookup failure.

The boundary is:

- `include_state=selected` with `context_id` means the caller has selected a
  specific context record; that ID must resolve in the declared preparation
  surface, or the input is invalid;
- `include_state=unavailable` with `context_id=null` means the preparation
  step considered a role but has no resolved context record;
- `include_state=optional_not_selected` with `context_id=null` means the role
  was possible, but the preparation step did not include it;
- `required=true` controls the severity of a missing role, not whether a
  selected ID is recorded.

## Workflow Map

The validated slices sit in the middle of a broader user workflow:

```text
user or lab code decides to run
  -> adapter or preparation UI collects available context
  -> normalized run-input context refs
  -> family-specific summaries and read views
  -> manual prepared-run review composition
  -> user or lab system starts the experiment
  -> measurement record links selected context
```

Scopecat has validated only selected parts of this chain. The actual
experiment start remains owned by the user or lab system in the current
boundary.

## Two Adoption Routes

### Legacy Or Passive Recording Route

In this route, users keep existing experiment code and do not immediately move
all context management into Scopecat.

Typical flow:

1. Existing lab code, notebook code, or operator practice decides what to run.
2. A user adapter, preparation helper, or recording step emits any context refs
   it can identify.
3. Scopecat records selected refs with IDs and optional unavailable refs
   without requiring the missing roles to be filled.
4. The lab system still starts and controls the run.

This route should favor optional context recording. It should reject dangling
selected IDs, but it should not turn every unrecorded context family into a
required input.

### Template Or Prepared Route

In this route, a user has intentionally defined a reusable preparation surface
or experiment template that declares required inputs.

Typical flow:

1. User selects a reusable preparation surface.
2. The surface declares local required inputs, such as a `parameter_state`
   context role.
3. The preparation step normalizes supplied and missing inputs into context
   refs.
4. Missing required roles become review findings for manual prepared-run
   review.
5. The final run start still remains outside this boundary unless a later
   slice earns run-start authority.

This is the natural place for `required=true`. The current work has not
validated a reusable template language; it has only preserved the semantics
needed for a later template slice.

## Current Slice Placement

| Stage | Current validated slices | Boundary |
| --- | --- | --- |
| Context collection or adapter output | Not yet validated as a stable API | User adapters or preparation helpers may produce normalized refs, but Scopecat does not understand arbitrary legacy JSON, XLSX tables, notebooks, or lab-specific formats by default. |
| Normalized run-input refs | Named run-start input set, prepared run context, context inclusion semantics | Validate selected IDs, optional unavailable roles, required absence severity, and family-owned reference metadata. |
| Family summaries and read views | Parameter state storage read view, setup binding, managed code version, editable-folder observation, declared environment inventory | Validate family-owned facts without forcing a shared context payload schema. |
| Prepared-run review composition | Prepared-run parameter consumption, parameter gate, scope alignment, prepared-run review gate, environment review bundles | Compose prior summaries into manual review surfaces without run-start permission, hardware control, write-back, import, or execution. |
| Experiment start | Not validated | Remains user or lab-system authority. |
| Measurement record linkage | Measurement records and linked-context slices | Records what context was associated with the measurement without proving restoration or reproducibility. |

## What This Clarifies

- A selected context ID is not optional absence; unresolved selected IDs are
  invalid references.
- Optional unavailable context is a recordable condition after normalization.
- Required inputs belong to a local policy, manual-preparation policy, or
  future template surface, not to every context family globally.
- The current prepared-run and run-start fixtures model normalized
  preparation inputs, not legacy import/parsing from arbitrary prior formats.
- User adapters own legacy-format interpretation unless a later adapter slice
  validates a narrower handoff boundary.

## How To Use This Document

Use this result as a placement and boundary map for later slices, not as a
schema source. Future work should preserve these cautions:

- Do not infer a stable normalized context-ref schema from this document.
  Existing field names are carried from validated fixtures only.
- Do not redesign `required` inside prepared-run or run-start consumers.
  Revisit it only when validating the producer side: template inputs,
  adapter-produced normalized refs, or another explicit preparation surface.
- Do not make every missing context family required. Required inputs need a
  local policy source, such as a future reusable template or a narrow
  manual-preparation policy.
- Do not treat normalized refs as legacy import support. Parsing old parameter
  JSON, XLSX tables, notebooks, or lab-specific experiment code remains owned
  by user adapters unless a separate adapter slice earns a narrower boundary.
- Do not let manual review composition become run readiness. Prepared-run
  review can surface findings, but it does not start runs, control hardware,
  write parameters, sync environments, import code, or execute code.
- Do not retrofit the parameter-state lifecycle into this workflow by
  implication. Parameter-state slices have their own coherent lifecycle; a
  later slice should explicitly decide how selected parameter state enters a
  measurement or experiment-start workflow.

## Not Earned

This boundary result does not earn:

- a reusable template language;
- a stable adapter API;
- parsing semantics for legacy parameter JSON, XLSX tables, notebooks, or
  project-specific experiment code;
- automatic context discovery;
- run-start permission;
- hardware control;
- parameter write-back;
- setup mutation;
- environment sync;
- code import or execution;
- GUI workflow;
- shared run-context schema.

## Recommended Next Work

Do not redesign the normalized context-ref shape in this boundary document.
The `required` field remains a carried normalized-ref fact for existing
validated slices. Whether it should become absence-only, move into a separate
requirement object, or be replaced by explicit absence severity belongs to a
later producer-stage slice.

Do not add producer-side required-input semantics, or new fixtures that imply
producer-side required-input authority, until that stage is explicit. The
highest-value later implementation slice is either:

- a minimal reusable preparation-template input contract, if we need to show
  where required inputs such as `parameter_state` come from; or
- a narrow adapter-produced normalized-context-ref boundary, if the immediate
  need is to connect legacy experiment code or lab-specific parsers to the
  existing prepared-run summaries.
