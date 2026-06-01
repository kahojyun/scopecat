# Legacy Brownfield Adoption Backbone Validation Result

## Status

Implementation candidate validated.

This result validates one narrow brownfield adoption composition:
**Legacy Brownfield Adoption Backbone**.

It does not accept a final sidecar manifest schema, live legacy-storage
adapter, during-run sidecar writer, legacy import acceptance flow, storage
writer, hardware-control contract, notebook execution contract, parameter
write-back contract, GUI design, or shared workflow model.

## Fixture

Composition test:
[`../../tests/test_legacy_brownfield_adoption_backbone_summary_candidate.py`](../../../../tests/test_legacy_brownfield_adoption_backbone_summary_candidate.py)

Implementation candidate:
[`../../implementation_candidates/legacy_brownfield_adoption_backbone/`](../../../../implementation_candidates/legacy_brownfield_adoption_backbone)

The test composes existing repository-safe synthetic candidate summaries:

- legacy run sidecar manifest;
- legacy sidecar post-run review;
- legacy locator observation review bundle;
- reviewed legacy sidecar append intent;
- reviewed legacy sidecar evidence append receipt;
- legacy evidence receipt read view.

The fixture remains generic. It uses synthetic legacy runtime, measurement,
locator, context, and receipt identifiers. It does not reference local sample
paths, host names, instrument identifiers, notebook names, or lab-specific
labels.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- validate one measurement identity across the legacy sidecar, post-run review,
  locator-observation review, append intent, receipt write summary, and receipt
  read view;
- classify the adoption chain as post-run-first while keeping lifecycle events
  compatible with a later during-run incremental event writer;
- carry run-start context links as optional reference posture unless a caller
  declared one required;
- treat existing receipt writes as prior summaries while the backbone itself
  performs no fresh storage mutation;
- verify that the read view includes the written review-evidence receipt path
  and matching receipt id;
- preserve review/debug evidence posture without primary-data import, legacy
  payload parsing, reference repair, parameter write-back, measurement-validity
  decisions, or GUI behavior.

## Boundary

This slice validates a local composition over prior summaries.

It does not:

- execute legacy notebooks, scripts, runners, or hardware calls;
- write sidecar events during a run;
- observe files, connect to legacy backends, stream logs, or inspect live
  services;
- read, parse, normalize, checksum, preview, or import primary data;
- perform the review-evidence receipt write;
- replace record manifests or refresh read models;
- repair references or discover moved legacy files;
- apply parameter or calibration updates back to legacy files;
- define final sidecar transport, API, GUI behavior, or shared workflow schema;
- decide scientific validity, fit quality, hardware safety, or run-blocking
  policy.

## Result

The composition validates the preferred adoption posture:

```text
post-run first, during-run compatible
```

The current low-intrusion path can be:

```text
external legacy run
-> declared sidecar facts
-> post-run review
-> optional locator-observation review
-> explicit append intent
-> review-evidence receipt
-> read-only receipt view
```

Lifecycle events are currently declared as batch facts after the run. A future
slice can validate during-run event append or a thin wrapper hook, but that
would be a new authority boundary. This slice deliberately does not make
Scopecat a legacy runner adapter.

## Follow-Up

Likely follow-up slices should stay separate:

- during-run sidecar event append, if users need lower-latency lifecycle or
  debug evidence capture;
- post-run adoption comparison against real operator workflow, if current
  synthetic stages do not match how users review old runs;
- parameter-state handoff composition, if a legacy sidecar needs to carry a
  calibration accepted-write handoff into later managed parameter state;
- durable record lifecycle integration, if review-evidence receipts should
  become visible through the active measurement-record read model.
