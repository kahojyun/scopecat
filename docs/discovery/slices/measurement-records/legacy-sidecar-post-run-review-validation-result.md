# Legacy Sidecar Post-Run Review Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Records slice:
**Legacy Sidecar Post-Run Review**.

It does not accept durable measurement-record updates, fresh source
observation, legacy import acceptance, storage mutation, reference repair,
parameter write-back, measurement-validity decisions, GUI behavior, or a shared
review schema.

## Fixture

Fixture:
[`../../tests/fixtures/legacy_sidecar_post_run_review/basic_review/`](../../../../tests/fixtures/legacy_sidecar_post_run_review/basic_review)

Implementation candidate:
[`../../implementation_candidates/legacy_sidecar_post_run_review/`](../../../../implementation_candidates/legacy_sidecar_post_run_review)

The fixture composes two prior summaries for the same legacy sidecar:

- a legacy-run sidecar manifest summary;
- a legacy locator sufficiency review summary.

The projection presents four local review sections:

- lifecycle facts for the completed sidecar measurement;
- legacy locator review targets and findings;
- declared primary-data references;
- declared supporting evidence references.

## What This Earned

The implementation candidate shows that Scopecat can:

- validate continuity between the sidecar and locator review summaries;
- carry sidecar lifecycle state into a post-run review projection;
- preserve locator sufficiency findings without performing backend lookup or
  reference repair;
- preserve declared primary-data references without observing or importing
  payloads;
- preserve supporting evidence references without importing payloads;
- classify completed, partial, failed, locator-unavailable, locator-review, and
  attention-needed sidecar states;
- reject policy claims that cross into fresh observation, import acceptance,
  storage mutation, record write, reference repair, parameter write-back,
  measurement validity, or GUI behavior.

## Boundary

This slice validates local post-run review projection only.

It does not:

- open primary data or supporting evidence files;
- connect to a legacy backend;
- parse, repair, or discover locator values;
- normalize, import, or copy legacy data;
- append durable measurement-record state;
- apply parameter or calibration updates;
- decide measurement validity, scientific quality, run safety, or continuation
  behavior;
- define a GUI workflow or shared post-run review schema.

## Result

This slice closes the first brownfield review loop:

1. Legacy run sidecar manifest records declared boundary facts.
2. Legacy locator sufficiency review checks whether declared locators are
   adequate for human navigation.
3. Legacy sidecar post-run review presents the sidecar lifecycle, locator
   review, primary references, and supporting evidence in one local review
   surface.

The result keeps the same reference-only posture as legacy import: enough
declared information for a user to find old data, without making Scopecat own
the old storage system or its reference semantics.

## Follow-Up

Likely follow-up slices should stay separate:

- route-local GUI projection for sidecar post-run review cards;
- source observation for a specific file-backed locator;
- reference repair or moved-reference review without automatic discovery by
  default;
- adapter-authored legacy import when normalized preview or durable import is
  needed;
- durable append of reviewed sidecar facts to measurement-record storage.
