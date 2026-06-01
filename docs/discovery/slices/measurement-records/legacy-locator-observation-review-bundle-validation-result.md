# Legacy Locator Observation Review Bundle Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Records slice:
**Legacy Locator Observation Review Bundle**.

It does not perform fresh file observation, query legacy backends, parse legacy
data, verify previews, accept imports, mutate storage, write records, repair
references, write parameters, decide measurement validity, or define GUI
behavior.

## Fixture

Fixture:
[`../../tests/fixtures/legacy_locator_observation_review_bundle/basic_bundle/`](../../../../tests/fixtures/legacy_locator_observation_review_bundle/basic_bundle)

Implementation candidate:
[`../../implementation_candidates/legacy_locator_observation_review_bundle/`](../../../../implementation_candidates/legacy_locator_observation_review_bundle)

The fixture consumes:

- an already-built
  [`legacy-sidecar-post-run-review-validation-result.md`](legacy-sidecar-post-run-review-validation-result.md)
  summary;
- one prior
  [`legacy-file-backed-locator-observation-validation-result.md`](legacy-file-backed-locator-observation-validation-result.md)
  summary.

The bundle groups sidecar review state and optional locator-observation facts
into one local review summary.

## What This Earned

The implementation candidate shows that Scopecat can:

- validate that locator-observation summaries match locators already visible
  in sidecar post-run review;
- allow zero locator observations because file observation remains optional;
- classify ready, ready-without-observation, unavailable-locator,
  file-fact-mismatch, sidecar-attention, and generic attention states;
- carry observation findings with locator and target ids;
- preserve declared preview metadata as unverified by file-level observation;
- reject policy or child-summary claims that cross into fresh observation,
  backend lookup, data observation, row-count checks, schema inference, preview
  verification, legacy parsing, import acceptance, storage mutation, record
  writes, reference repair, parameter write-back, measurement validity, or GUI
  behavior.

## Boundary

This slice validates local review composition only.

It does not:

- open files or re-run locator observation;
- infer paths from redacted display values;
- discover moved files or repair references;
- connect to LabRAD, DataVault, Labber, or another legacy backend;
- parse primary data, count rows, infer schema, or validate preview metadata;
- normalize, import, or copy legacy data;
- append durable measurement-record state;
- apply parameter or calibration updates;
- decide measurement validity, scientific quality, run safety, or
  continuation behavior;
- define a GUI workflow.

## Result

This slice gives the brownfield review chain a stable review checkpoint before
durability or import:

1. sidecar post-run review establishes local review facts;
2. optional file-backed locator observation adds file-level availability and
   checksum/size facts;
3. locator observation review bundle composes those facts without turning them
   into storage, import, repair, or validity decisions.

That keeps early migration useful for users who only want review/debug
visibility, while leaving durable append and adapter-normalized import as
separate explicit choices.

## Follow-Up

Likely follow-up slices should stay separate:

- durable append of reviewed sidecar and locator-observation facts to
  measurement-record storage;
- adapter-authored import review when normalized primary data is needed;
- locator repair or moved-reference review without automatic discovery by
  default;
- data-level preview verification only after adapter-normalized primary data
  exists.
