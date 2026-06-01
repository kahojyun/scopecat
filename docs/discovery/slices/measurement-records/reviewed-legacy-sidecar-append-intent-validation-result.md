# Reviewed Legacy Sidecar Append Intent Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Records slice:
**Reviewed Legacy Sidecar Append Intent**.

It does not write storage, append records, import primary data, parse legacy
payloads, verify previews, repair references, write parameters, decide
measurement validity, or define GUI behavior.

## Fixture

Fixture:
[`../../tests/fixtures/reviewed_legacy_sidecar_append_intent/basic_intent/`](../../../../tests/fixtures/reviewed_legacy_sidecar_append_intent/basic_intent)

Implementation candidate:
[`../../implementation_candidates/reviewed_legacy_sidecar_append_intent/`](../../../../implementation_candidates/reviewed_legacy_sidecar_append_intent)

The fixture consumes an already-built
[`legacy-locator-observation-review-bundle-validation-result.md`](legacy-locator-observation-review-bundle-validation-result.md)
summary and an explicit local reviewer approval.

The intent selects:

- sidecar post-run review facts as review-summary references;
- legacy locator-observation review facts as review/debug evidence.

It explicitly excludes:

- primary data and legacy payloads;
- reference repair;
- measurement-validity state.

## What This Earned

The implementation candidate shows that Scopecat can:

- validate an explicit operator-approved intent before any durable append;
- require the source locator-observation review bundle to remain non-mutating;
- distinguish review/debug evidence from normalized primary data;
- carry source review findings without converting them into repair,
  import, write-back, or validity decisions;
- reject policies or requests that claim storage mutation, record writes,
  primary-data import, legacy payload inclusion, preview verification,
  reference repair, parameter write-back, measurement validity, or GUI
  behavior.

## Boundary

This slice validates append intent only.

It does not:

- create append files or write a measurement-record receipt;
- select storage paths, locks, or collision policy;
- copy, normalize, or import legacy primary data;
- read or parse legacy payloads;
- verify preview metadata;
- discover moved files or repair references;
- apply parameter or calibration updates;
- decide measurement validity, scientific quality, run safety, or
  continuation behavior;
- define a GUI workflow.

## Result

This slice creates a bridge from local brownfield review to a possible durable
append without implementing the append. It answers what the user approved to
carry forward: reviewed sidecar and locator-observation facts as
review/debug evidence, not primary data or validity state.

That keeps the next storage slice honest. A durable append can later consume
this intent, but it still needs its own storage-root, path, receipt, collision,
and rollback behavior.

## Follow-Up

Likely follow-up slices should stay separate:

- durable append of reviewed legacy sidecar evidence to measurement-record
  storage;
- adapter-authored import review when normalized primary data is needed;
- locator repair or moved-reference review without automatic discovery by
  default;
- data-level preview verification only after adapter-normalized primary data
  exists.
