# Legacy Calibration Handoff Parameter-State Bridge Validation Result

## Status

Implementation candidate validated.

This result validates one narrow cross-route composition:
**Legacy Calibration Handoff Parameter-State Bridge**.

It does not accept a final sidecar manifest schema, calibration schema,
parameter-state schema, live legacy-storage adapter, legacy parameter-file
writer, hardware-control contract, notebook execution contract, storage model,
GUI design, or shared workflow model.

## Fixture

Composition test:
[`../../tests/test_legacy_calibration_handoff_parameter_state_bridge_summary_candidate.py`](../../../../tests/test_legacy_calibration_handoff_parameter_state_bridge_summary_candidate.py)

Implementation candidate:
[`../../implementation_candidates/legacy_calibration_handoff_parameter_state_bridge/`](../../../../implementation_candidates/legacy_calibration_handoff_parameter_state_bridge)

The test composes existing repository-safe synthetic candidate summaries:

- legacy brownfield adoption backbone;
- calibration accepted-write handoff;
- calibration parameter-state intake.

The test deliberately declares the bridge between the legacy measurement id
and the calibration handoff/intake provenance. It does not infer the bridge
from sample paths, notebook names, file names, debug artifacts, primary-data
payloads, or legacy backend semantics.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- validate that the legacy sidecar measurement id is referenced by the
  calibration accepted-write handoff and the parameter-state intake provenance;
- require an explicit operator-approved bridge from reviewed legacy sidecar
  evidence to parameter-state intake;
- preserve the accepted calibration handoff as `not_applied`;
- keep parameter-state intake as the authority for the managed parameter-state
  summary;
- classify copied legacy snapshots and debug artifacts as supporting evidence,
  not canonical context;
- report the managed parameter-state snapshot as the canonical parameter
  context after intake;
- avoid fresh observation, primary-data import, legacy payload parsing,
  parameter-state storage mutation, legacy parameter write-back, hardware
  write-back, reference repair, measurement-validity decisions, and GUI
  behavior.

## Boundary

This slice validates an explicit review bridge. It does not:

- discover calibration handoffs from legacy files, notebook state, paths,
  timestamps, or labels;
- inspect supporting evidence, artifacts, logs, or primary-data payloads;
- import or preview legacy data;
- write parameter-state storage or durable history;
- write accepted values back to legacy `parameters.json`-style files;
- apply values to instruments or record current hardware state;
- repair moved references;
- execute calibration, fitting, measurement, notebooks, or runners;
- decide scientific validity, fit quality, hardware safety, or run-blocking
  policy;
- define final sidecar, calibration, parameter-state, context, evidence, or
  workflow schemas.

## Result

The validated bridge connects two previously closed trunks without expanding
either route's authority:

```text
legacy brownfield adoption backbone
  -> explicit operator-declared calibration handoff bridge
  -> calibration accepted-write handoff
  -> parameter-state intake summary
  -> managed parameter-state snapshot as canonical parameter context
```

The bridge is review/debug evidence on the legacy side and parameter-state
intake provenance on the parameter-state side. It does not make Scopecat write
legacy files or control hardware.

## Follow-Up

Likely follow-up slices should stay separate:

- parameter-state storage visibility, if the managed state created by intake
  must be stored and read back through active parameter-state storage;
- later prepared-run selection, if the legacy-calibration-derived managed
  state should be selected for a future run;
- legacy parameter-file write-back, only if users explicitly need Scopecat to
  produce or apply legacy compatibility output;
- during-run sidecar event append, if users need lower-latency calibration
  evidence capture before post-run review.
