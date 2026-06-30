# Next Development Plan

Status: current sequencing baseline
Date: 2026-06-29

Scopecat has completed the exploratory workflow switch. The next phase should
not add broad new feature families before the notebook-first workflow has been
exercised, documented, and hardened.

The stable public path is:

```text
Workspace -> Experiment -> Run -> Data -> Analysis -> CandidateConfig
```

The most important engineering goal is convergence. Users should see one
obvious path for notebook and script work, while internal execution records
stay behind that path.

## Completed Convergence

The initial convergence pass is implemented:

- root `scopecat` exports expose the notebook-first workflow facade;
- public-surface and user-facing-doc guards prevent retired session,
  lab-system, and old example-package entry points from returning to the main
  path;
- README and runnable examples use `sc.open -> experiment -> run -> data ->
  analysis`;
- manual `Analysis` artifacts persist source artifact ids in payloads and
  metadata for reports, comparisons, and future GUI readers;
- `Data` artifact selectors and `Analysis.artifact_ref(...)` are covered for
  missing artifacts, path escape attempts, kind mismatches, source-artifact
  de-duplication, and report rendering;
- notebook analysis payloads return stable diagnostics for invalid note,
  external-ref, and guess inputs;
- `Workspace.experiment(...)` is documented as the default authoring entry, with
  `ExperimentSpec` kept as durable IR;
- promoted demo `AnalysisStep`s use `AnalysisContext.data`,
  `AnalysisContext.config`, and `Analysis` outputs directly;
- GUI read entries have public notebook-equivalent APIs:
  `Workspace.runs()`, `Workspace.get_run(run_id)`, and `Run.comparisons()`;
- the notebook-facing `Run` facade no longer exposes low-level
  `process(...)`/`evaluate(...)`, candidate-accept handles, session helpers, or
  routine helpers;
- quantum examples include a copy-into-your-lab customization map and keep
  `quantum_lab_demo` under `examples/quantum/support`;
- completed migration notes and broad research backlogs have been folded into
  current contracts instead of kept as separate active docs;
- GUI workbench navigation is documented in
  [GUI Workbench Entry Contract](gui-workbench-entry-contract.md).

## Current Priorities

1. Align durable internals with the notebook-first model.

   The initial breaking cleanup is complete. Continue to prefer direct cleanup
   when `RunManifest`, artifact discovery, analysis records, or
   candidate-review records drift from the public workflow.

2. Stabilize `Data` and `Analysis` contracts.

   Prefer artifact ids over paths, readers over manifest traversal, and saved
   analysis records over ad hoc side files. Reports, comparisons, and future GUI
   readers should consume the same records.

3. Collapse parallel post-run concepts behind the same mental model.

   Reusable post-run logic should end in `AnalysisStep`. Manual and promoted
   analysis should produce equivalent output records. Candidate review should
   be the public configuration-change concept; lower-level proposal records can
   remain only as implementation artifacts while useful.

4. Split facade implementation by public concept.

   Keep the root public surface small, but stop letting one implementation file
   carry unrelated `Workspace`, `Run`, `Data`, `Analysis`, and candidate-review
   concerns.

5. Harden the notebook UX with executable examples after the model cleanup.

   Keep examples copyable and concrete. Each notebook should answer one user
   question and show where to change experiment inputs, analysis code, and lab
   adapters.

6. Keep GUI workbench work at entry-contract level until the notebook path is
   boring.

   GUI screens should map onto `Workspace`, `Run`, `Data`, `Analysis`,
   `CandidateConfig`, comparisons, and reports. Avoid GUI-only indexes or a
   parallel workflow model.

7. Clean internal vocabulary when it leaks.

   Lower-level automation records can remain while they carry useful
   persistence behavior. Remove or rename them when they shape public examples,
   docs, or authoring APIs.

## Sequencing Rules

- Prefer one public path over parallel advanced paths.
- Prefer artifact ids over paths for cross-references.
- Prefer `Data` and `Analysis` readers over manifest traversal in user code.
- Prefer breaking cleanup over compatibility layers while the project has no
  external compatibility contract.
- Add abstractions only when they simplify real repeated work.
- Keep GUI, routines, package extraction, and backend expansion behind the
  stable notebook workflow.

## Explicit Deferrals

Do not prioritize these until the convergence targets above are stable:

- optional Parquet, Arrow, Zarr, or HDF5 measurement backends;
- large `PlanSnapshot` preview artifact schema;
- relation function registry expansion;
- extracted domain package naming or publishing;
- broad GUI workbench implementation beyond entry contracts;
- campaign-level calibration records;
- automatic routine authoring as a primary workflow.

## Verification Gate

Every meaningful slice should leave these checks passing:

```sh
uv run --offline pytest packages/scopecat/tests examples/quantum/tests examples/quantum/support/tests
uv run --offline ruff check packages examples docs
uv run --offline basedpyright
```

For public workflow changes, also inspect:

- `README.md` basic shape;
- root `scopecat.__all__`;
- `packages/scopecat/tests/test_public_surface.py`;
- `packages/scopecat/tests/test_workspace.py`;
- runnable `examples/quantum/notebooks` and `examples/quantum/scripts`.
