# Legacy Run Sidecar Manifest Validation Result

## Status

Implementation candidate validated.

This result validates one narrow brownfield measurement-record slice:
**Legacy Run Sidecar Manifest**.

It does not accept a final sidecar manifest schema, live legacy-storage adapter,
legacy import acceptance flow, storage writer, hardware-control contract,
notebook execution contract, parameter write-back contract, GUI design, or
shared workflow model.

## Fixture

Fixture:
[`../../tests/fixtures/legacy_run_sidecar_manifest/basic_sidecar/`](../../../../tests/fixtures/legacy_run_sidecar_manifest/basic_sidecar)

Implementation candidate:
[`../../implementation_candidates/legacy_run_sidecar_manifest/`](../../../../implementation_candidates/legacy_run_sidecar_manifest)

The fixture models a generic legacy measurement run where the old notebook/script/runner path
continues to own execution. Scopecat receives declared sidecar facts:

- legacy runtime identity and selected entrypoint;
- measurement-record identity and redacted legacy source locators;
- optional run-start context references for intent, parameter snapshot, setup
  binding, code context, and unavailable declared environment;
- declared primary-data reference to the legacy output;
- explicit supporting evidence references for a parameter snapshot and run log;
- sidecar lifecycle events from manifest start through completed legacy run.

The fixture is repository-safe and uses redacted labels rather than local
machine paths, host names, instrument identifiers, or lab-specific labels.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- wrap an externally executed legacy run without claiming runner or hardware
  authority;
- preserve redacted legacy source locators next to a Scopecat-facing
  measurement id without forcing one legacy record-id model;
- carry primary data as a declared legacy reference without opening,
  normalizing, importing, or validating the payload;
- carry supporting evidence references without promoting them to canonical
  context;
- count selected, required, and unavailable run-start context references;
- treat optional missing environment context as review-visible but not a
  finding;
- surface caller-required missing context as a local review finding without
  claiming the legacy run is blocked, unsafe, or invalid;
- classify partial and failed legacy runs as review states without root-cause
  or retry-policy claims;
- reject claims that cross into storage mutation, legacy import acceptance,
  hardware control, parameter write-back, schema inference, or GUI behavior.

## Boundary

This slice validates a local review summary around a legacy run.

It does not:

- execute notebooks, scripts, or runners;
- configure instruments, control hardware, stream logs, or observe live
  services;
- read, parse, normalize, checksum, preview, or import primary data;
- append durable measurement storage;
- apply parameter or calibration updates back to legacy files;
- materialize code workspaces or sync environments;
- infer schemas from legacy payloads;
- define final sidecar transport, API, GUI behavior, or shared workflow schema;
- decide scientific validity, fit quality, hardware safety, or run-blocking
  policy.

## Result

The legacy-run sidecar manifest is the missing bridge between the existing
run-start, writer, running-evidence, post-run review, and legacy-import
slices.

It is useful because it validates the first migration step for old experiment
code: keep the legacy workflow running, but record enough declared locator
facts for a user to find the corresponding data in the old system later. The
locator may be a legacy record id, path, URI, session/record pair, operator
note, or another backend-specific handle; Scopecat does not parse or validate
the backend semantics. This matches the sample-code pressure where
experiment wrappers, parameter snapshot copies, legacy storage metadata, dense
sidecars, and debug logs already exist but are not assembled into one explicit
review surface.

## Follow-Up

Likely follow-up slices should stay separate:

- a live legacy-storage observer or proxy, if current acquisition needs automated
  sidecar emission;
- offline import/read for declared legacy outputs, if payload preview becomes
  necessary;
- durable measurement-record storage, if sidecar summaries should become
  append-only records;
- parameter-state storage from accepted calibration handoff, if a sidecar
  points at a proposed/accepted update;
- route-local GUI projection for displaying sidecar review state.
