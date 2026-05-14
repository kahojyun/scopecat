# JC-002 Analysis Handoff Journey

## Status

Draft journey seed for selected-run analysis handoff. Not accepted scope,
prototype scope, implementation plan, UI spec, API contract, storage model, or
export format.

## Purpose

Describe the current-state and future-state journey for moving selected
experiment data from a control computer to an analysis computer.

This journey depends on the handoff snapshot definition in
[`jc-002-handoff-snapshot-definition.md`](jc-002-handoff-snapshot-definition.md).

## Actor And Situation

The actor is an experiment user who has already run measurements on a control
computer and now needs to analyze promising data elsewhere.

The user may have found valuable data through a plotting browser, Data Vault
or LabRAD-style paths, numeric dataset IDs, quick plots, filenames, run names,
or memory from the measurement session. The existing sample evidence does not
show a native star/favorite UI; star or selected-run behavior remains a
future-state interaction pressure.

## Current-State Journey

| Step | Current behavior | Pain |
| --- | --- | --- |
| 1 | User finds promising data through a browser, plot, path, or numeric ID. | Selection intent is not durable; the reason a run mattered may live only in memory or a notebook comment. |
| 2 | User writes a path, Data Vault path, or ID into a notebook or helper script. | The identifier often depends on local machine paths or directory conventions. |
| 3 | User reads data into analysis code and may export local CSV, NPY, NPZ, or pickle snapshots. | Derived files can become detached from source run identity. |
| 4 | User makes plots, fit results, PDFs, or slides from the copied data. | The report artifact may not explain which source run, sidecar, context, or correction was used. |
| 5 | Later, the user or a collaborator tries to reuse the analysis on another computer. | Missing axis labels, units, sample labels, parameters, or companion sidecars make the package harder to understand. |

## Future-State Journey

| Step | Future behavior | Outcome |
| --- | --- | --- |
| 1 | User opens post-run history and finds high-value runs by name, time, simple preview, label, or selection mark. | Valuable runs are recoverable without relying on memory or latest-file conventions. |
| 2 | User selects one or more runs like files. | The selection set becomes explicit before export. |
| 3 | Scopecat shows a low-ceremony handoff prompt with auto-filled context and visible missing fields. | Users can add purpose, sample/device label, selected reason, or important parameters without blocking export. |
| 4 | Scopecat creates an immutable handoff snapshot by packaging already-known artifacts and context. | Data, source identity, read guidance, required sidecars, context slots, and missing warnings travel together without generating new analysis outputs. |
| 5 | User moves the snapshot to an analysis computer and opens it with personal analysis code or tools. | Data can be read and plotted without the original control machine's local paths. |
| 6 | User produces figures, fit results, PDFs, slides, or notes outside the snapshot. | Derived outputs can later be linked back as append-only analysis records, but do not redefine the original handoff. |

## Snapshot Prompt Shape

The first future-state prompt should stay small:

```text
Selected runs: auto-filled
Snapshot title: user-provided or suggested
Sample/device: suggested when available, editable, may be not_provided
Purpose or note: optional
Important parameters: suggested, user can pin or edit
Include required read sidecars: default yes
Include internal verification references: optional
Include user-attached derived inputs: advanced optional
```

This prompt shape is not a UI spec. It records the expected information
pressure for the journey.

## Acceptance Checks

A drafted `JC-002` fixture should show:

- selected data has stable source identity;
- primary data and required sidecars can be found in the snapshot;
- axes, units, shape, and labels are present or explicitly missing;
- sample/device, purpose, and important parameters are present or explicitly
  `not_provided` or `unknown`;
- original control-computer path evidence is preserved as provenance, not as a
  required portable read path;
- snapshot export does not create new CSV, NPY, PNG, PDF, fit, deck, or report
  artifacts;
- included non-primary artifacts are justified by recorded roles such as
  required read sidecar, handoff context, or user-attached derived input;
- generated PDFs, decks, reports, fit outputs, and publication arrays remain
  outside the initial snapshot boundary.

## Non-Goals

This journey does not accept:

- full publication workflow;
- generic export-format-first design;
- complete work-bundle export/import;
- generation of new derived artifacts during export;
- live-monitor semantics;
- managed analysis-script execution;
- permission systems;
- reader API, storage, package manifest, or UI details;
- automatic scientific comparison or equivalence judgment.

## Reopening Triggers

Reopen this journey boundary if fixture or user validation shows that:

- generated analysis outputs must travel with the first snapshot for the user
  to trust or use it;
- Tier 3 verification context is routinely required before ordinary analysis
  handoff succeeds;
- users cannot make useful plots from snapshots without a stable reader API
  being specified earlier;
- star/favorite behavior is not the right selection metaphor for the target
  workflow.
