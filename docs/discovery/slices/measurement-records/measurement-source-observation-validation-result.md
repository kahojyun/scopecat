# Measurement Source Observation Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Records slice: **Measurement Source
Observation**.

It does not accept final measurement-record storage architecture, recursive
storage inspection, source schema inference, import acceptance, export package
writing, package integrity, live service, callback API, hardware control, scan
execution, GUI workflow, or a shared measurement-record schema.

## Fixture

Fixture:
[`../../tests/fixtures/measurement_source_observation/basic_observation/`](../../../../tests/fixtures/measurement_source_observation/basic_observation)

Implementation candidate:
[`../../implementation_candidates/measurement_source_observation/`](../../../../implementation_candidates/measurement_source_observation)

The fixture observes one stored Rabi measurement primary-data file that is
already in the small normalized CSV/table shape used by the storage-writer
pressure:

- one explicit observation request with a storage-root-relative primary-data path,
  expected sha256 digest, expected byte size, and expected row count;
- one caller-provided storage root containing the declared primary CSV;
- declared 1D table preview metadata for the observed primary-data path.

The candidate reads only the declared primary-data file under the caller root.
It does not scan the storage root, read a manifest, infer columns, repair
files, accept imports, or write export packages. Sha256 and byte size are
file-level observations; CSV row count is a data-level check for this
validated normalized fixture only.

## What This Earned

The implementation candidate shows that a bounded source observer can:

- keep observation authority explicit through one declared primary-data path;
- keep storage-root authority explicit through a caller-provided root plus
  relative paths;
- validate relative primary-data paths before reading;
- refuse symlink targets rather than following them;
- report unavailable primary data as a review finding instead of performing
  repair or import acceptance;
- compare observed sha256 and byte size with declared file facts;
- compare CSV row count with the declared row-count fact for this normalized
  fixture;
- report digest, size, and row-count mismatches as review findings without
  cause attribution;
- preserve declared preview metadata without inferring schema from source rows;
- return deterministic observed-file facts, review findings, preview summary,
  and boundary attention items.

## Boundary

This slice validates one read-only source observation.

It does not:

- define a final storage schema, database layout, object store, package format,
  retention model, or migration strategy;
- inspect full storage roots, watch for staleness, manage locks across
  processes, or define crash recovery;
- infer source columns, units, row semantics, array shapes, plot candidates,
  fit quality, uncertainty, or scientific validity from stored primary data;
- repair, overwrite, merge, update, rename, delete, or materialize files;
- accept import packages or write export packages;
- define package-integrity, archive-validation, backup, or checksum contracts
  beyond this explicit observation request;
- add runtime redaction, DLP scanning, or label sanitization; public fixture
  labels and display text are reviewed free text for this slice;
- define live event transport, callbacks, websockets, monitor refresh, or GUI
  behavior;
- control hardware, run scans, mutate parameters, retry failed measurements,
  or make safety decisions.

## Result

Measurement source observation closes one loop after the append-only storage
writer: a stored or writer-produced primary-data file can be checked later
against declared digest, size, and row-count facts without granting Scopecat
schema inference, repair, import acceptance, package validation, or broader
storage ownership.

The fixture intentionally uses the same small Rabi primary-data shape as the
storage writer pressure, but this result is read-only. It should be compared
with writer, incoming-record import preview, adapter-manifest, export, and
running-inspection work without being promoted into a final storage schema.

## Follow-Up

Stop this slice at explicit read-only observation unless the next workflow
needs a stronger storage or package contract.

Likely follow-up slices should stay separate:

- stronger update behavior for existing records, such as manifest replacement,
  read-model refresh, stale-lock cleanup, crash recovery, and conflict policy;
- adapter-authored import review-to-acceptance, with explicit copy/reference
  storage mutation and no-overwrite policy;
- harder data-shape observation cases, such as ragged scans, trace-per-point
  data, or array-valued responses, without automatic schema inference;
- package or archive validation, without treating this fixture as a final
  integrity contract.
