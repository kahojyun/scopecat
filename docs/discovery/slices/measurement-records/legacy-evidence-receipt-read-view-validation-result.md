# Legacy Evidence Receipt Read View Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Records slice:
**Legacy Evidence Receipt Read View**.

It reads an existing measurement-record manifest plus explicitly declared
review-evidence receipt paths. It does not scan storage, mutate storage, read
primary data, import legacy payloads, parse legacy data, verify previews,
repair references, write parameters, decide measurement validity, refresh read
models, or define GUI behavior.

## Fixture

Fixture:
[`../../tests/fixtures/legacy_evidence_receipt_read_view/basic_read/`](../../../../tests/fixtures/legacy_evidence_receipt_read_view/basic_read)

Implementation candidate:
[`../../implementation_candidates/legacy_evidence_receipt_read_view/`](../../../../implementation_candidates/legacy_evidence_receipt_read_view)

The fixture reads a synthetic existing record containing one receipt written by
[`reviewed-legacy-sidecar-evidence-append-receipt-validation-result.md`](reviewed-legacy-sidecar-evidence-append-receipt-validation-result.md).

## What This Earned

The implementation candidate shows that Scopecat can:

- read a declared existing-record manifest and validate record identity;
- read declared legacy review-evidence receipt paths without scanning storage;
- surface receipt identity, source intent, locator-observation evidence, and
  receipt-level review findings;
- classify missing, malformed, mismatched, or effect-claiming receipts as
  review findings;
- reject path and symlink hazards;
- keep primary data, legacy payloads, preview verification, reference repair,
  parameter write-back, measurement validity, read-model refresh, and GUI
  behavior out of scope.

## Boundary

This slice validates read-only receipt visibility only.

It does not:

- discover receipt files by scanning storage;
- open primary data or legacy payloads;
- parse legacy data, count rows, infer schema, or validate previews;
- discover moved receipt paths or repair references;
- mutate storage or write records;
- replace manifests or refresh read models;
- apply parameter or calibration updates;
- decide measurement validity, scientific quality, run safety, or
  continuation behavior;
- define a GUI workflow.

## Result

This slice closes the durable review-evidence loop for the brownfield path:

1. reviewed legacy sidecar evidence is written as a small receipt;
2. a read-only view can surface that receipt again from declared paths;
3. missing or malformed receipts become review findings rather than repair
   actions.

The result keeps durable review evidence visible without promoting legacy
locators into primary data or validity state.

## Follow-Up

Likely follow-up slices should stay separate:

- adapter-authored import review when normalized primary data is needed;
- locator repair or moved-reference review without automatic discovery by
  default;
- product GUI projection over the read view;
- data-level preview verification only after adapter-normalized primary data
  exists.
