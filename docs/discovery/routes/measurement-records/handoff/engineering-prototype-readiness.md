# Handoff Engineering Prototype Readiness

## Status

Engineering prototype readiness note, not an ADR.

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule. Use
[`policies/artifact-boundary-and-redaction.md`](../../../policies/artifact-boundary-and-redaction.md)
if any prototype output is promoted into a portable/export artifact.

## Readiness Judgment

The read-only handoff package engineering prototype is ready to stop broad
prototype expansion and move into a narrow promotion pass.

The recommended promotion target is the first accepted read-only vertical:

```text
package directory
  -> manifest validation and preview classification
  -> read-only package open
  -> package, measurement, table, declared plot, linked-context, and finding access
  -> local CLI or static HTML review surface
```

This does not promote final SDK names, package archive format, storage import,
GUI architecture, dataframe dependency, plotting dependency, linked-context
payload traversal, or a shared measurement-record domain model.

## Stop Criteria Check

| Criterion | Status | Assessment |
| --- | --- | --- |
| Usable local Python or CLI entrypoint | Met | `open_package(package_dir)` and `python -m scopecat.handoff <package-dir>` exist. |
| Representative regression coverage | Met | Tests cover basic opener, richer route-pressure package, multi-plot, table-only, shared context, degraded preview, CLI, HTML artifact, symlink guardrails, and typed manifest boundary behavior. |
| Documented contracts and non-claims | Met | The route plan, consolidation, decision note, and prototype README define read-only scope, artifact posture, dependency deferrals, and non-claims. |
| Green repository verification | Met | Current milestone verification uses `uv run python -m unittest discover -s tests` and `uv run prek run --all-files`. |
| Written promotion decision path | Met by this note | The next step is a narrow promotion pass, not additional broad discovery or GUI/dependency expansion. |

## Keep As Implementation Shape

These choices are strong enough to carry into the promotion pass:

- route-local `scopecat/handoff/` module boundary;
- raw JSON/dict validation at the package manifest boundary;
- typed route-local manifest fragments after validation;
- product-shaped `HandoffPackage`, `HandoffMeasurement`, `HandoffTable`,
  `HandoffPlotSeries`, `HandoffFinding`, and `HandoffLinkedContext`
  projections;
- manifest-only preview classification before package-local file reads;
- package-directory and package-id continuity;
- canonical primary data topology,
  `measurements/{measurement_record_id}/primary.csv`;
- declared preview metadata as the preview authority;
- string-valued table and declared plot projections without dataframe or
  numeric inference semantics;
- linked context as visible reference-only review state;
- static local HTML as the current review artifact.

## Keep Deferred

These are not blockers for promoting the read-only vertical:

- final public SDK naming and packaging metadata;
- hard pandas/numpy dependency;
- matplotlib or production plotting integration;
- live GUI components or routing;
- numeric dtype conversion, schema inference, unit conversion, scan-shape
  inference, trace opening, or array APIs;
- archive extraction, compressed package format, signatures, authenticity, or
  trust policy;
- storage import, acceptance, conflict handling, or existing-record update;
- linked-context payload packaging, opening, recursive traversal, or import;
- analysis/fit result model, execution, uncertainty, write-back, or import;
- shared measurement-record domain model or cross-route lifecycle model.

## Promotion Pass Scope

The promotion pass should be small and mechanical:

- keep leading-underscore modules in `scopecat/handoff/` route-private unless
  another concrete route needs the same behavior, lifecycle, and failure
  semantics;
- preserve the static HTML renderer as the first local review surface unless
  maintainability problems appear;
- document old implementation candidates as historical discovery evidence,
  not runtime dependencies;
- keep existing fixtures unless a cleaner regression fixture is needed for the
  promoted route;
- run the full repository test and hook commands before any promotion commit.

The pass should not add GUI, dataframe, plotting, import/acceptance, archive,
or cross-route domain work.

## Remaining Risks

- The static HTML renderer is acceptable for the first local review surface,
  but should not become a public report format by accident.
- `_contracts.py` still contains low-level validation primitives. This is fine
  while route-private, but promotion should avoid exporting it as a general
  domain library.
- The current primary table is string-valued by design. Notebook computation
  pressure should trigger a separate numeric/dataframe adapter decision.
- The package format remains the tested directory-shaped subset, not a final
  sharing/archive format.

## Recommendation

Promote the read-only handoff vertical after one narrow promotion cleanup and
no further broad prototype expansion. Future handoff work should be triggered
by the reopen conditions in [`decision.md`](decision.md), not by restating the
same route-level conclusions.

The promotion decision is recorded in
[`engineering-prototype-promotion-decision.md`](engineering-prototype-promotion-decision.md).
