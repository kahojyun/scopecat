# Analysis Handoff Candidate Note

## Status

Candidate owner note. Not an accepted journey, implementation plan, API
contract, export format, storage design, UI spec, or new `JC-###` folder.

## Purpose

Capture user-refined pressure around analysis handoff without expanding
`JC-001` beyond its accepted passive evidence-view boundary.

This note owns the current detail behind the `Starred runs to analysis handoff
package` candidate wedge in
[`progressive-adoption-progress-tracker.md`](progressive-adoption-progress-tracker.md)
and the `PN-004` handoff pressure in
[`evidence-and-pain-point-inventory.md`](evidence-and-pain-point-inventory.md).

## Evidence Basis

- `EV-044`: analysis handoff from an experiment-control computer to a user's
  analysis computer is a high-priority adoption pressure distinct from
  cross-machine scientific comparison.
- `EV-045`: predecessor Fricon data-shape work provides validation coverage for
  handoff and durable-record journeys without defining Scopecat's storage,
  reader API, export format, or UI.
- `PN-004`: users need to find and take high-value data off the experiment
  computer for deeper analysis, figure making, and publication without losing
  source links, companion artifacts, corrections, or decisions.

## Candidate Shape

The smallest useful candidate is:

```text
post-run browser
  -> find high-value runs by free-form names, time, quick previews, and stars
  -> multi-select runs like files
  -> create an immutable self-contained handoff snapshot
  -> preserve source IDs, read guidance, context evidence, and missing warnings
```

The handoff package should include data plus enough context to explain results:
source run or dataset identity, selected context evidence, calibration or
correction references where available, generated or companion artifacts,
code references or key script snapshots, evidence-handling labels, and explicit
missing-context warnings.

Analysis-result write-back is separate from the immutable handoff snapshot. If
it becomes part of a later slice, it should be user-approved append-only derived
evidence, such as fit results, figure references, notes, or stars. It must not
mutate source data, configuration, setup, parameter, or execution-state truth.

## Adoption Baseline

The adoption-critical path is not a generic export format. Users first need to:

- find valuable data after an experiment;
- inspect simple historical previews;
- mark promising data with simple star/favorite behavior;
- copy or open stable IDs through a usable read API;
- move selected data and context to a personal analysis computer;
- keep the experiment-control computer available for experiment work.

Analysis handoff should prioritize Scopecat's high-fidelity data model and a
usable read API before committing to CSV, NPZ, HDF5, pandas, NumPy, xarray, or
other adapters. Mainstream ecosystem adapters or guides can follow observed
use.

## Validation Coverage

Predecessor Fricon data-shape work should challenge this candidate with:

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

## Non-Goals

This candidate does not accept:

- complete work-bundle export/import;
- active setup, parameter, configuration, or execution-state import;
- generic export-format-first design;
- managed execution of analysis scripts;
- a permission or redaction system for ordinary internal handoff;
- a full ELN, report generator, or publication workflow;
- reader API, package manifest, storage, UI, or fit-result schema details.

## Open Questions

- Which concrete validation fixture should exercise the first handoff package:
  VNA traces, IQ/readout data, irregular optimizer output, or a report/figure
  source bundle?
- Which source IDs and read guidance are sufficient before a stable reader API
  is specified?
- Which fit results, figure references, notes, and star/favorite marks should
  user-run analysis scripts be allowed to write back without Scopecat managing
  or executing those scripts?
- Which code artifacts belong in a handoff snapshot as references, and which
  need key script snapshots?
