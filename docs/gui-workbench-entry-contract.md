# GUI Workbench Entry Contract

Status: accepted direction
Date: 2026-06-29

This note defines the GUI workbench entry model without adding a parallel GUI
workflow. The workbench should present the same objects notebook and script
users already use:

```text
Workspace -> Experiment -> Run -> Data -> Analysis -> CandidateConfig -> Comparison -> Overview
```

The GUI may add navigation, filtering, and review affordances, but it should
not add GUI-only workflow records or artifact indexes.

## Navigation Model

The first GUI version should map screens onto existing public objects:

| Screen | Backing object | Primary selectors |
| --- | --- | --- |
| Workspace overview | `Workspace` | workspace root, active config selector |
| Experiment setup | `Experiment` | experiment name, source builder, subject, sweeps |
| Runs | `Run` list | run id, status, created time, experiment id |
| Run details | `Run` | run id |
| Data artifacts | `Data` | artifact id, kind, metadata |
| Analysis artifacts | `Analysis` artifacts | artifact id, source artifact ids |
| Candidate configs | `CandidateConfig` artifacts | candidate artifact id, source run id |
| Comparisons | comparison artifacts | comparison id, baseline run id, candidate run id |
| Overview | `RunOverview` view | run id |
| Analysis reports | `analysis_report` artifacts | report artifact id, run id |

The GUI should resolve artifacts by `Artifact.id` first. Paths are display and
storage details, not navigation keys.

## Read-Only Entries

Workbench read paths should be thin wrappers around existing public readers:

- open workspace: `sc.open(...)`;
- list runs: `Workspace.runs()`;
- reopen a run by id: `Workspace.get_run(run_id)`;
- read run details: `Run`, `Run.data()`, and `Data.plan_preview()`;
- list data: `Run.data().list(kind=..., metadata=...)`;
- read measurements/tables/arrays/text/json/bytes through `Data`;
- read analysis artifacts through `Data.list(kind="analysis")` and analysis
  JSON payloads;
- read candidate configs through typed `candidate_config` artifacts;
- read comparisons through `Run.comparisons()` and comparison artifact ids;
- read system overviews through `Workspace.overview(run)` and `Run.overview()`;
- read user analysis reports through `Data.list(kind="analysis_report")` and
  report artifact ids.

Do not introduce a GUI artifact catalog. The run manifest artifact index is the
shared discovery surface.

## Write Entries

Keep GUI write actions small and reproducible from notebook code:

- save manual analysis as an `Analysis` artifact;
- review a `CandidateConfig`;
- run a follow-up `Experiment` with a reviewed candidate config;
- compare two runs;
- save user analysis reports as `analysis_report` artifacts.

Every GUI write should produce the same durable records as the equivalent
notebook call. If an action cannot be reproduced from `Workspace`, `Run`,
`Data`, `Analysis`, and `CandidateConfig`, it is not ready for the GUI.

## Explicit Non-Goals

- No GUI-only run index.
- No GUI-only analysis state.
- No GUI-specific candidate config record.
- No direct dependence on local filesystem layout.
- No storage mutation outside existing workspace APIs.

## Readiness Gate

The workbench entry contract is ready when:

- every planned screen maps to an existing public object or typed artifact;
- source data and analysis provenance are available through artifact ids;
- analysis reports and comparisons can cite analysis artifacts without scanning
  local paths;
- notebook and script workflows can reproduce GUI-visible state.

Current public read entries:

- `Workspace.runs()` returns public `Run` handles backed by workspace manifests;
- `Workspace.get_run(run_id)` reopens one public `Run` handle by id;
- `Run.comparisons()` lists comparison views for a run without exposing storage
  layout.
