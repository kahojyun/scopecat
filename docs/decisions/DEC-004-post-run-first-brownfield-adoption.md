# DEC-004: Post-Run-First Brownfield Adoption

## Status

Decision status: accepted.

This note records the current low-intrusion brownfield adoption boundary for
legacy Measurement Records. It records what the validated legacy sidecar,
locator review, review-evidence append, receipt read-view, and brownfield
adoption backbone slices now support. It does not accept a final sidecar
manifest schema, live legacy-storage adapter, during-run sidecar writer,
legacy import acceptance flow, measurement storage model, hardware-control
contract, notebook execution contract, parameter write-back contract, GUI
design, or shared workflow model.

## Current Decision

The validated brownfield adoption boundary is **post-run first, during-run
compatible**:

```text
external legacy run
  -> declared sidecar facts
  -> legacy locator sufficiency review
  -> post-run review
  -> optional file-backed locator observation
  -> locator-observation review bundle
  -> explicit append intent
  -> review-evidence receipt write
  -> read-only receipt view
```

The boundary is useful for low-intrusion migration from old experiment workflows:
the legacy notebook, script, runner, storage system, and hardware-control path
can continue to execute outside Scopecat. Scopecat can receive declared facts
about the completed run, preserve flexible legacy locators, show local review
state, optionally observe one explicitly selected file-backed locator, and
carry reviewed sidecar facts forward as review/debug evidence under an
existing measurement record.

Legacy locators are user-navigation hints. They may be ids, paths, URIs,
session/record labels, operator notes, or other backend-specific handles.
Scopecat does not parse their backend semantics, query legacy backends, infer
paths, or repair references by default.

Primary data stays external unless another route imports normalized primary
data through an explicit adapter/storage boundary. A sidecar-declared primary
data reference is not previewable primary data merely because a locator exists.

Run-start context links remain optional and reference-only unless the caller
marks one required. Opaque legacy parameter snapshots, runtime logs, generated
execution inputs, and debug outputs are supporting evidence by default. When a
managed parameter-state snapshot exists, that snapshot remains the canonical
parameter context; copied legacy files remain review/debug evidence unless a
future accepted decision promotes a specific artifact family.

Lifecycle events are currently accepted as declared batch facts after the run.
The same event vocabulary can support a future during-run event writer, but
that would be a new authority boundary. This route does not make Scopecat a
legacy runner adapter.

## Validation Map

| Track | Current slices | Earned responsibility |
| --- | --- | --- |
| Sidecar declaration | Legacy run sidecar manifest | Wrap an externally executed legacy run with declared runtime identity, measurement identity, flexible locators, optional context links, primary-data refs, supporting evidence refs, and lifecycle events. |
| Locator review | Legacy locator sufficiency review | Classify whether declared locators are enough for human navigation without backend lookup, path parsing, file observation, import acceptance, storage mutation, or repair. |
| Post-run review | Legacy sidecar post-run review, legacy sidecar review GUI state | Project lifecycle, locator, primary-data, and supporting-evidence sections into local review or passive view state without fresh observation, action execution, import acceptance, storage mutation, or run blocking. |
| Optional locator observation | Legacy file-backed locator observation, legacy locator observation review bundle | Observe one explicitly selected `legacy_path` under a caller-provided root, then compose prior observation summaries without parsing data, verifying previews, accepting import, mutating storage, or repairing references. |
| Evidence append | Reviewed legacy sidecar append intent, reviewed legacy sidecar evidence append receipt | Let an explicit operator approval carry reviewed sidecar/locator facts forward as review/debug evidence, then write one no-overwrite receipt under an existing record without importing primary data or replacing manifests. |
| Readback | Legacy evidence receipt read view | Read declared review-evidence receipt paths without storage scan, primary-data read/import, read-model refresh, reference repair, parameter write-back, or measurement-validity decisions. |
| Route backbone | Legacy brownfield adoption backbone | Validate measurement and receipt continuity across the chain, while preserving post-run-first adoption and during-run compatibility without runner ownership. |
| Calibration handoff bridge | Legacy calibration handoff parameter-state bridge | Let an explicitly approved bridge carry reviewed legacy sidecar evidence to a calibration accepted-write handoff and parameter-state intake summary without legacy write-back, parameter-state storage mutation, hardware apply, payload import, or inferred links. |

## Boundary Decisions

Keep these boundaries explicit:

- Brownfield adoption is a review/evidence route, not a core legacy reader.
- Post-run sidecar ingestion is the default low-intrusion entry point.
- During-run lifecycle/event capture is future-compatible but not earned here.
- File-backed locator observation is file-level only. It does not inspect
  primary data, row counts, schemas, plots, previews, or scientific validity.
- Review-evidence receipts are evidence under an existing record. They do not
  replace manifests, merge primary data, refresh read models, or define final
  storage append semantics.
- Review findings are passive by default. They do not invalidate measurement
  data, block future work, repair references, or execute actions.
- Supporting evidence, attachments, and debug artifacts do not become
  canonical context by being present in a sidecar.
- Parameter write-back to legacy files remains outside this route.

## Deferred Decisions

Keep these out of the current route until a named workflow requires them:

- final sidecar manifest schema, transport, public API, or compatibility
  adapter;
- live sidecar emission, during-run event append, log streaming, or monitor
  integration;
- legacy backend lookup, source discovery, path inference, moved-reference
  discovery, or automatic repair;
- legacy payload parsing, normalized primary-data import, preview verification,
  plotting, or table/dataframe behavior;
- stronger durable storage integration such as manifest replacement,
  read-model refresh, canonical append visibility, lock identity, stale-lock
  cleanup, crash recovery, and conflict policy;
- further calibration handoff behavior beyond the explicit review bridge,
  such as storage visibility, prepared-run selection, or legacy write-back;
- parameter write-back, hardware apply, rollback, hardware control, or current
  instrument-state recording;
- GUI workflow, action execution, scheduler behavior, or run blocking;
- shared measurement-record, sidecar, context, evidence, or workflow schemas.

## Reopen Triggers

Do more brownfield adoption discovery only when one of these concrete triggers
appears:

- Users need lower-latency status or debug evidence before a run completes:
  validate a narrow during-run event or supporting-evidence append boundary
  without runner control.
- Users need a sidecar producer inside old notebooks/scripts:
  validate a thin wrapper/hook API and failure semantics without turning
  Scopecat into the legacy runner.
- Users need to open, preview, or import legacy data:
  route the work through adapter-normalized primary data or a separately
  accepted legacy reader/import boundary.
- Users need moved-reference recovery:
  validate operator-reviewed reference repair without automatic path discovery
  by default.
- Users need reviewed sidecar facts visible in the active durable record read
  model:
  validate read-model refresh or canonical append visibility separately from
  the first receipt read-view.
- Users need legacy-calibration-derived managed state to be stored, selected
  for a later prepared run, or written back to legacy files:
  validate each boundary separately from the current explicit review bridge.
- Real operator workflows show that the current post-run review stages or
  locator sufficiency labels do not match how users actually find and review
  old runs.

## Stop Rule

Do not add more brownfield sidecar slices merely to restate post-run-first
adoption, flexible legacy locators, optional context links, supporting evidence
posture, file-level observation limits, review-evidence receipt readback, or
no-runner/no-import/no-write-back boundaries. Future work should name the user
workflow and the authority boundary it changes.
