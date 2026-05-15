# JC-002 Journey Selection Note

## Status

Promoted from candidate owner note to drafting `JC-002` journey record. Not an
accepted journey, implementation plan, API contract, export format, storage
design, UI spec, or prototype scope.

## Purpose

Record why `JC-002` is now a distinct drafting journey candidate and preserve
its boundary before writing detailed fixtures or technical contracts.

This note records the selection that lets `JC-002` test the provisional
`JC-001` capability owners before broadening ownership. The current `JC-002`
next decision is owned by [`README.md`](README.md); the project tracker carries
only the phase, links, and compact cross-journey coordination point.

## Selected Candidate

`JC-002`: starred or selected runs to an analysis handoff snapshot.

The selected pressure is internal analysis handoff, not cross-machine
scientific comparison. Users need to find high-value data after measurement,
inspect simple historical previews, mark or multi-select runs, and move a
pre-analysis data-plus-context snapshot from an experiment-control computer to
a personal analysis computer without losing source identity.

## Evidence Basis

- `EV-044`: analysis handoff from an experiment-control computer to a user's
  analysis computer is a high-priority adoption pressure distinct from
  cross-machine scientific comparison.
- `EV-045`: predecessor data-shape work provides validation coverage for
  handoff and durable-record journeys without defining Scopecat's storage,
  reader API, export format, or UI.
- `PN-004`: users need to find and take high-value data off the experiment
  computer for deeper analysis, figure making, and publication without losing
  source links, companion artifacts, corrections, or decisions.
- Full-fidelity sample review shows repeated current-state patterns where
  users preserve Data Vault paths, numeric dataset IDs, local file paths, and
  derived CSV or array snapshots inside analysis notebooks and plotting/report
  helpers. This is evidence for source-identity and context-loss pressure, not
  evidence that a star/favorite UI already exists.

## Current Fixture Direction

Use a small redacted fixture modeled on a selected-run handoff package:

```text
selected run or small run group
  -> primary readable data
  -> source IDs and original path evidence
  -> snapshot identity and selected-run group order
  -> axis names, units, shape, timestamp, and measurement label
  -> sample or device label when available
  -> important parameter summary or explicit missing warning
  -> visible user-attached derived input decision when present
  -> companion read sidecars required to open the data
```

The fixture should not start from a publication/report bundle. Existing
notebooks, PDFs, slides, fit outputs, and processed publication arrays are
useful evidence for what users later produce from a handoff, but they are not
part of the first handoff snapshot boundary.

## Validation Coverage

Predecessor data-shape work should challenge this candidate with:

- regular one-, two-, and N-dimensional sweeps;
- trace-valued records with explicit coordinate/value arrays or compact
  regular-coordinate descriptions;
- multiple traces in one outer sweep record;
- first-class complex values for magnitude/phase or I/Q views;
- IQ averages, I/Q channels, single-shot arrays, or labels;
- generic irregular or ragged step records for minimizer-like output.

This coverage validates historical plotting and read readiness. It does not
accept an internal storage model, first-contact reader view, API signature,
handoff manifest, export adapter, or UI behavior.

## Live Preview Boundary

Analysis handoff does not settle live-preview monitor semantics. A separate
durable-record or live-inspection journey would still need runtime hints for:

- active output;
- active axes;
- selected channel or trace;
- preferred line, heatmap, trace, or IQ view;
- stale, lagging, disconnected, or incomplete-view state.

Live preview remains adoption pressure, but it should not become a write
acknowledgement path or a full analysis viewer by default.

## JTBD Conversion

When I have found valuable experiment data on a control computer, help me move
the selected runs and enough context to my analysis computer so I can read,
plot, analyze, and explain the data later without relying on fragile local
paths, memory, or the original machine being available.

## Acceptance Pressure

| Pressure | How `JC-002` exercises it |
| --- | --- |
| `PN-004` | Selected data must leave the control computer with source identity, read guidance, and context warnings intact. |
| `PN-001` | Run or dataset identity anchors the snapshot and prevents derived local files from becoming anonymous data. |
| `PN-002` | Minimal selected context must travel with data, while missing or unknown context remains visible. |
| `PN-006` | Code references may explain how users read data, but Scopecat does not execute or manage analysis code. |
| `PN-007` | The package must be portable enough for personal analysis without requiring full-platform adoption. |

## Guardrails

`JC-002` should:

- prioritize internal full-fidelity analysis handoff before public or external
  export;
- keep user ceremony low by allowing explicit missing-value statuses;
- validate local offline GUI and Python-reader consumption without defining
  final UI or API details;
- treat export as packaging over already-known artifacts, not as derivation;
- separate pre-analysis handoff snapshots from derived analysis outputs;
- preserve source identity and original path evidence without treating local
  paths as portable truth;
- surface missing context as warnings instead of silently omitting fields.

`JC-002` should not:

- include generated PDFs, decks, reports, fit outputs, or publication arrays in
  the first snapshot definition;
- generate new CSV, NPY, plot, fit, PDF, deck, or report artifacts during
  export;
- require users to provide all context before export;
- commit to CSV, NPZ, HDF5, pandas, NumPy, xarray, or any other adapter as the
  first design center;
- accept full work-bundle export/import;
- manage or execute user analysis scripts;
- define live-monitor semantics, permission systems, reader API signatures,
  storage, final UI behavior, or package manifest details.

## Open Questions

- Which concrete fixture should exercise the first snapshot: VNA traces,
  IQ/readout data, irregular optimizer output, or a small selected-run group
  with companion sidecars?
- Which fields are needed for a useful group-meeting explanation versus only
  for internal debugging or verification?
- Which source IDs and read guidance are sufficient before a stable reader API
  is specified?
- Which later analysis outputs should become append-only derived analysis
  records linked back to a snapshot?
