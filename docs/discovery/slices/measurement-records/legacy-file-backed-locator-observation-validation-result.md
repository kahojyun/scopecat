# Legacy File-Backed Locator Observation Validation Result

## Status

Implementation candidate validated.

This result validates one narrow Measurement Records slice:
**Legacy File-Backed Locator Observation**.

It does not query legacy backends, parse legacy data, verify previews, accept
imports, mutate storage, write records, repair references, write parameters,
decide measurement validity, or define GUI behavior.

## Fixture

Fixture:
[`../../tests/fixtures/legacy_file_backed_locator_observation/basic_observation/`](../../../../tests/fixtures/legacy_file_backed_locator_observation/basic_observation)

Implementation candidate:
[`../../implementation_candidates/legacy_file_backed_locator_observation/`](../../../../implementation_candidates/legacy_file_backed_locator_observation)

The fixture consumes an already-built
[`legacy-sidecar-post-run-review-validation-result.md`](legacy-sidecar-post-run-review-validation-result.md)
summary, selects one declared `legacy_path` locator for the primary data
target, and observes a synthetic file under a caller-provided external root.

The observation request supplies:

- the sidecar measurement id;
- the target id and locator id;
- a public-safe external-root label;
- the relative source path under the caller-provided root;
- optional expected sha256 and byte-size facts.

## What This Earned

The implementation candidate shows that Scopecat can:

- validate that a request selects an existing declared `legacy_path` locator
  from prior sidecar review facts;
- preserve the redacted sidecar display rather than treating it as an
  executable filesystem path;
- observe one caller-provided relative path under one caller-provided external
  root;
- reject symlink roots, symlink parents, and symlink targets;
- classify observed, unavailable, and file-fact-mismatch states;
- compare optional sha256 and byte-size facts when supplied;
- keep declared preview metadata explicitly unverified by file-level
  observation;
- reject policy claims that cross into backend lookup, data observation,
  row-count checks, schema inference, preview verification, legacy parsing,
  import acceptance, storage mutation, record writes, reference repair,
  parameter write-back, measurement validity, or GUI behavior.

## Boundary

This slice validates explicit file-level locator observation only.

It does not:

- infer a path from a redacted display value;
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

This slice gives the previous GUI-state action label a concrete read-only
follow-up. A user can choose a declared file-backed locator, provide the local
root/path needed in their environment, and get file-level review facts without
making Scopecat own the legacy storage system or its reference semantics.

That keeps brownfield adoption flexible: legacy systems can use ids, paths, or
operator notes as navigation hints, while file observation remains an explicit
optional review step when a path-backed file can be checked.

## Follow-Up

Likely follow-up slices should stay separate:

- locator repair or moved-reference review without automatic discovery by
  default;
- adapter-authored import review when normalized primary data is needed;
- durable append of reviewed sidecar and locator-observation facts to
  measurement-record storage;
- data-level preview verification only after adapter-normalized primary data
  exists.
