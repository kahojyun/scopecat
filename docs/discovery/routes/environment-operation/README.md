# Environment Operation Route Consolidation

## Status

Discovery consolidation note, not an ADR.

This note harvests the current environment-operation validation work into one
route-level view. It does not accept a final environment schema, shared
environment-manager interface, process executor, runtime probe, managed-runner
contract, dependency resolver, package installer, workflow/DAG model,
portable/export package projection, or GUI contract.

## Route Shape

The validated environment-operation posture is **approve intent, record
external result, review locally**:

```text
optional manifest preflight
  -> bounded manager operation intent
  -> declared external manager result
  -> local operation review bundle
```

The route is currently uv-specific. `uv` remains authoritative for lockfile
semantics, dependency resolution, synchronization, and package installation.
Scopecat owns the local review records around the operation: explicit approval,
bounded argv construction, declared external result recording, and composition
of prior summaries into one `review_summary` surface.

In the wider route model, environment operation records support selected
prepared-run and declared-environment identity references. They can explain
what manager command was approved, what external result was recorded, and how
that result aligns with selected code/environment context, but they do not make
environment state the anchor record. Measurement records and prepared-run
context still explain why this environment operation matters for a user
workflow.

## Current Track Map

| Track | Current slices | Earned responsibility |
| --- | --- | --- |
| Optional manifest projection | Modern manifest preflight | Read one explicitly approved `pyproject.toml` path under a caller root and project declared manifest facts plus review findings. |
| Operation intent | UV sync intent | Construct one bounded `uv sync --locked --no-default-groups` argv from declared context and approval fields without reading files or running uv. |
| External result recording | UV sync result | Record a declared external uv outcome, bounded summaries, command facts, and result status without executing uv or verifying package state. |
| Operation review composition | Environment operation review bundle | Compose prior manifest preflight, uv sync intent, and uv sync result summaries into one local review surface with alignment findings and explicit non-claims. |
| Edge-case pressure | Operation review edge cases | Confirm manifest findings, uv failure, uv not-run, and deliberately inconsistent command projections remain review findings, not run blockers or readiness claims. |

## Boundary Map

| Surface | Boundary posture | Responsibility |
| --- | --- | --- |
| Manifest preflight summary | Local `review_summary` | Optional structured manifest facts for comparison/review; not required before manager intent. |
| UV sync intent summary | Local `review_summary` | Approved command intent and exact argv; no process execution or environment observation. |
| UV sync result summary | Local `review_summary` | Declared external outcome and bounded output summaries; no verified dependency sync or installed package truth. |
| Operation review bundle | Local `review_summary` | Aligns selected prior facts and aggregates review findings; does not become runtime readiness, run permission, or portable output. |
| Handoff/package references | Future reference-only package entries unless separately validated | May reference code/environment records, but does not own code packaging, environment restoration, sync, or runnable readiness. |
| Future execution receipt | Not yet validated | Must be a separate authority boundary if Scopecat runs manager commands. |

## Scopecat Owns

These concepts have enough repeated pressure to carry forward inside this
route:

- explicit operation approval and managed request/result identifiers;
- declared prepared-run and declared-environment continuity;
- relative command working directory for command-fact comparison;
- bounded manager-specific argv construction rather than arbitrary flags;
- declared external result status, execution state, exit code, observer, and
  bounded stdout/stderr summaries as review facts;
- optional manifest preflight as structured review/comparison support, not as
  a prerequisite for manager execution;
- local operation review bundles that aggregate child findings and
  cross-summary mismatches without creating run-blocking decisions.

## External Managers Own

Keep these outside Scopecat until a separate slice explicitly earns authority:

- lockfile semantics and dependency graph interpretation;
- dependency resolution, sync, installation, update, and removal;
- package state truth and virtual-environment state truth;
- manager-specific command semantics beyond the bounded argv Scopecat
  constructs;
- Conda/Pixi semantics, channels, platforms, and non-Python package behavior.

## Still Candidate-Local

Keep these concepts local to current candidates or future manager-specific
slices:

- uv-specific command policies such as `--locked` and
  `--no-default-groups`;
- the current `pyproject.toml` manifest projection shape;
- operation review finding wording and status vocabulary;
- local execution cwd review facts;
- future Pixi intent/result/preflight shapes;
- any helper contracts until at least a second manager-specific family proves
  the same lifecycle shape.

## Future Boundaries

These are not cleanup tasks for the current route. They are separate product
authority questions:

1. **Execution wrapper**: if Scopecat runs `uv`, validate approval, cwd,
   environment variables, timeout, cancellation, output capture, and failure
   classification in a new execution-authority slice.
2. **Runtime probe**: if users need "can this run now?", validate interpreter
   and package-state observation separately from sync result recording.
3. **Pixi/Conda pressure test**: if Conda-capable manager support becomes
   near-term, validate Pixi-specific preflight/intent/result/review slices
   before extracting shared manager contracts.
4. **Portable/package projection**: if handoff packages need experiment
   code/environment context, validate a package projection that carries
   references or safe artifacts without implying environment restoration or
   runnable readiness.
5. **Managed runner**: if Scopecat coordinates run lifecycle, validate runner
   state after execution, runtime, hardware, and run lifecycle boundaries are
   separately earned.

## Cross-Route Relationship

Current cross-route coupling should stay reference-based:

- measurement records and prepared-run context explain the user workflow that
  needs environment review, but they do not make the environment-operation
  route own measurement storage, code loading, or run execution;
- prepared run context and declared environment records provide identity and
  scope references;
- handoff package work may eventually carry references to managed code,
  prepared-run context, declared environment, or operation review records;
- package import/export does not currently restore environments, run managers,
  or claim runnable readiness;
- measurement and handoff routes provide general posture around local review
  summaries, portable artifact boundaries, and explicit mutation approval, but
  they do not define environment-operation contracts.

## Test And Fixture Posture

Future tests should harden route behavior without restating every child
contract:

- keep focused route fixtures for operation status and finding combinations
  that affect review wording or product decisions;
- keep one negative test per new boundary vocabulary or alignment class;
- prefer edge-case matrices for review-only combinations when full duplicate
  fixtures would add noise;
- add richer fixtures only when they pressure a real user workflow, such as a
  failed sync followed by runtime probe planning or package-reference review;
- keep repository fixtures small and repository-safe; local review summaries
  are not automatically portable/public/export artifacts.

## Recommended Next Work

The current route is ready to pause broad slice expansion. The next work should
depend on the product question being answered:

1. **If execution is the priority**, validate a minimal manager execution
   wrapper as its own authority boundary.
2. **If multi-manager support is the priority**, validate Pixi-specific
   operation intent/result slices before extracting shared manager contracts.
3. **If run readiness is the priority**, validate a post-sync runtime probe
   separate from operation result recording.
4. **If handoff continuity is the priority**, validate a reference-only
   experiment context package projection before packaging code or environment
   artifacts.

Do not add another environment-operation slice merely to restate uv ownership,
local `review_summary` posture, dependency-sync non-claims, or shared-manager
deferral. Those are now route-level conclusions unless a new user workflow
challenges them.
