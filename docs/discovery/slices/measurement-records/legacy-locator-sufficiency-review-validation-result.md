# Legacy Locator Sufficiency Review Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Records slice:
**Legacy Locator Sufficiency Review**.

It does not accept a final locator schema, backend-specific locator parser,
legacy source openability check, file observation, legacy import acceptance,
storage mutation, reference repair workflow, or GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/legacy_locator_sufficiency_review/basic_review/`](../../../../tests/fixtures/legacy_locator_sufficiency_review/basic_review)

Implementation candidate:
[`../../implementation_candidates/legacy_locator_sufficiency_review/`](../../../../implementation_candidates/legacy_locator_sufficiency_review)

The fixture consumes the validated legacy-run sidecar manifest summary and
reviews two locator targets:

- the measurement-level legacy source locators;
- the primary-data legacy source locators.

The review treats locators as declared user-navigation hints. A locator may be
a legacy record id, path, URI, session/record pair, operator note, or other
backend-specific handle. Scopecat does not parse the value or prove that the old
system can resolve it.

## What This Earned

The implementation candidate shows that Scopecat can:

- consume legacy-run sidecar summaries without replaying sidecar validation;
- summarize measurement-level and primary-data locator sufficiency;
- classify locator targets as ready, ready with unavailable alternatives,
  operator-note-only, or unavailable for review;
- surface review findings without claiming the legacy record is missing,
  deleted, invalid, or repairable;
- preserve locator kind, display, authority, and reference state while keeping
  the display opaque;
- reject policy claims that cross into backend lookup, path parsing, file
  observation, legacy import acceptance, storage mutation, reference repair, or
  GUI behavior.

## Boundary

This slice validates review sufficiency only.

It does not:

- connect to the legacy backend;
- parse IDs, paths, URIs, session labels, or operator notes;
- open files, check existence, calculate checksums, or observe byte size;
- import or normalize legacy data;
- decide if a locator is globally unique or semantically correct;
- repair moved references or discover alternate references;
- write storage, mutate sidecar records, or refresh read models;
- define GUI behavior or final locator taxonomy.

## Result

This slice aligns the sidecar workflow with the reference-only legacy import
posture: Scopecat preserves enough declared information for a user to find the
old data, but does not bind itself to one legacy system's record-reference
scheme.

The useful distinction is between:

- **locator sufficiency review**: do declared locators look adequate for human
  navigation?
- **source observation**: does a specific reference resolve under a caller root?
- **legacy import**: should normalized data be copied or accepted into durable
  measurement storage?

Those boundaries should remain separate.

## Follow-Up

Likely follow-up slices should stay separate:

- route-local GUI projection for locator review findings;
- reference repair or moved-reference review, without automatic discovery by
  default;
- source observation for a specific file-backed locator;
- adapter-authored legacy import when a user wants normalized data preview or
  durable import.
