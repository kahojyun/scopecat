# Progressive Adoption Progress Tracker

## Purpose

Track durable product and architecture progress for Scopecat without turning
early work into a premature subsystem scaffold.

This tracker is organized around progressive platform adoption:

```text
Journey-first discovery
  -> capability-first adoption ladders
  -> thin vertical migration wedges
  -> contract-first architecture
  -> subsystem specs only when needed
```

## Status Legend

| Status | Meaning |
| --- | --- |
| Not Started | No durable artifact exists yet. |
| Drafting | Early durable artifact exists, but confidence is low. |
| Validating | Being checked against evidence, interviews, or spikes. |
| Ready | Good enough to guide near-term implementation or downstream docs. |
| Deferred | Intentionally postponed. |

## Current Durable Inputs

| Input | Status | Notes |
| --- | --- | --- |
| Documentation policy | Ready | Captured in `README.md` and `AGENTS.md`. |
| Greenfield architecture notes | Drafting | Stored as research input; contains historical first-direction hypotheses that must be revalidated. |

## Workstreams

| ID | Workstream | Status | Durable Output | Exit Criteria |
| --- | --- | --- | --- | --- |
| W1 | Evidence and pain points | Not Started | Evidence registry or pain-point inventory | Major claims link back to interview notes, codebase observations, or explicit assumptions. |
| W2 | End-to-end journeys | Not Started | Journey documents | At least one current-state and future-state journey is written across capability boundaries. |
| W3 | Adoption ladders | Not Started | Capability adoption ladder document | Each major capability has a smallest useful standalone adoption step and upgrade path. |
| W4 | Migration wedges | Not Started | Wedge backlog | Candidate vertical slices are ranked by user value, migration cost, and architectural learning. |
| W5 | Capability map | Not Started | Architecture capability map | Capabilities, ownership, non-goals, and maturity targets are explicit. |
| W6 | Cross-capability contracts | Not Started | Contract notes or ADRs | Shared concepts and references have one owner and clear dependency direction. |
| W7 | Technical spikes | Not Started | Spike notes | Each spike has a question, result, decision impact, and follow-up. |
| W8 | Decision promotion | Not Started | ADRs or accepted architecture docs | Validated conclusions are promoted out of research notes. |

## Adoption Ladders To Define

Rows are unordered. This table does not choose the first adoption path.

| Capability | Starting User Pain | First Standalone Adoption Step | Later Composition Path | Status |
| --- | --- | --- | --- | --- |
| Measurement History | Data and run records are scattered or fragile. | Ordinary Python scripts write durable run and dataset records. | Scan points, parameter snapshots, code versions, execution records, and remote runs link into history. | Not Started |
| Scan Framework | Scan loops are ad hoc and hard to preview. | A standalone scan plan expands points and previews desired state without hardware. | Plans write scan-point records, bind parameter snapshots, and become frozen remote execution packages. | Not Started |
| Parameter Memory | Configs, calibrations, and notes drift across files. | Existing scripts read or export immutable parameter snapshots. | Calibration workflows propose updates and runs link exact snapshots. | Not Started |
| Code Asset Registry | Scripts and drivers are copied across experiments. | Existing repositories, commits, and entrypoints are registered without managed execution. | Managed execution and instrument runtime resolve exact code versions. | Not Started |
| Instrument Runtime | Shared instruments can be used concurrently by accident. | Old code acquires a simple resource lease before touching instruments. | Scan execution applies desired state and records actual state under leases. | Not Started |
| Managed Code Runner | Script execution is hard to reproduce or observe. | Old scripts run with captured logs, status, artifacts, and environment information. | Workflow and remote execution use runner records as provenance. | Not Started |

## Candidate Migration Wedges

Rows are unordered. Wedge priority should be decided from evidence, user value,
migration cost, and architectural learning.

| Wedge | User-Visible Outcome | Capabilities Involved | Main Learning Goal | Status |
| --- | --- | --- | --- | --- |
| Ordinary Python script to durable measurement record | A simple script writes data, supports live inspection, survives interruption, and reopens by stable ID. | Measurement History | Test whether measurement history is a strong early wedge. | Not Started |
| Legacy scan loop to previewable scan plan | A user replaces nested loops with a plan that can preview scan points before execution. | Scan Framework, Measurement History | Test scan semantics without requiring hardware control. | Not Started |
| Scattered config files to parameter snapshot | A script uses a frozen parameter snapshot instead of local config drift. | Parameter Memory, Measurement History | Separate durable parameters from scan-local variables. | Not Started |
| Copied scripts to code asset reference | A run records which external script, commit, and entrypoint were used. | Code Asset Registry, Measurement History | Separate code identity from execution identity. | Not Started |
| Manual instrument coordination to resource lease | Legacy code obtains an exclusive lease before controlling shared hardware. | Instrument Runtime | Validate the minimal live-resource model. | Deferred |
| Local script to managed execution record | A script runs under supervision with logs, artifacts, status, and environment capture. | Managed Code Runner, Code Asset Registry | Separate execution records from code identity. | Deferred |
| Local preview to remote dry run | A locally authored package validates remotely without touching hardware. | Scan Framework, Remote Execution, Code Asset Registry, Parameter Memory | Test immutable plan and validation contracts. | Deferred |

## Near-Term Execution Plan

| Step | Action | Expected Durable Output | Depends On |
| --- | --- | --- | --- |
| 1 | Distill the research note into current assumptions and open questions. | Research summary or project context document. | Existing research note. |
| 2 | Choose one concrete user journey to analyze first, based on evidence rather than subsystem preference. | Journey selection note. | Step 1. |
| 3 | Write the selected journey in current-state and future-state form. | Journey document. | Step 2. |
| 4 | Identify the capabilities touched by that journey and their standalone adoption steps. | Adoption ladder entries or capability note. | Step 3. |
| 5 | Shape one candidate migration wedge from the selected journey. | Wedge note with scope and non-goals. | Step 4. |
| 6 | Identify the minimum domain concepts and contracts needed for that wedge. | Concept notes or architecture section. | Step 5. |
| 7 | Run a technical spike only after the wedge scope is explicit. | Spike note and decision impact. | Step 6. |
| 8 | Promote validated decisions into ADRs or architecture docs. | Accepted decision records. | Step 7. |

## Review Cadence

Review this tracker whenever a durable product or architecture document is
created, removed, or promoted out of research.

During review:

- update statuses;
- add links to durable outputs;
- retire wedges that no longer match the product direction;
- avoid adding new workstreams unless they change how the project is managed.

## Guardrails

- Do not split product discovery by subsystem.
- Do not create subsystem specs before journeys, adoption ladders, and
  contracts justify them.
- Do not require full-platform adoption for the first useful slice.
- Do not let standalone adoption stories become incompatible mini-products.
- Keep each wedge narrow enough to validate with one concrete workflow.
