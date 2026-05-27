# Reference-Only Source Observation Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Records slice:
**Reference-Only Source Observation**.

It does not accept a stable public adapter or import API, LabRAD, DataVault,
Labber, or lab-specific reader, data-level observation, row-count checks,
preview verification, schema inference, reference repair, moved-reference
discovery, primary-data copy, storage mutation, linked-context payload import,
recursive relation traversal, package integrity contract, or GUI workflow.

Artifact posture: `internal_validation_summary`. The fixture and expected
output are repository-safe discovery artifacts; they are not portable/public
or export artifacts.

## Fixture

Fixture:
[`../../tests/fixtures/reference_only_source_observation/basic_observation/`](../../tests/fixtures/reference_only_source_observation/basic_observation/)

Implementation candidate:
[`../../implementation_candidates/reference_only_source_observation/`](../../implementation_candidates/reference_only_source_observation/)

The fixture starts after reference-only legacy import has produced reviewed
facts that preserve one external source reference. The observation input adds:

- an explicit `scopecat.reference_only_source_observation.v0` request;
- file-level-only observation policy;
- the consumed reviewed reference-only import facts;
- a caller-provided external root fixture;
- expected sha256 and byte-size facts for the preserved external source path.

The candidate validates continuity with the preserved reference id, external
root label, and adapter-declared source path before reading the file.

The fixture source CSV intentionally uses legacy column names that do not match
the declared preview columns; this slice observes bytes only and does not
compare headers with preview metadata.

## What This Earned

The implementation candidate shows that Scopecat can safely observe a
reference-only imported external source at the file level:

- require an explicit file-level observation request;
- consume reviewed reference-only legacy import facts without replaying import
  acceptance;
- require reference id, external root label, and source path continuity;
- reject policy claims that cross into data observation, row counting, preview
  verification, schema inference, storage mutation, copy behavior, or repair;
- read only the declared relative source path under a caller-provided external
  root;
- reject symlink roots, symlink parents, and symlink targets;
- report unavailable, digest mismatch, and size mismatch findings;
- keep declared preview metadata as an adapter assertion, not an observed
  preview contract;
- keep storage mutation and copying explicitly not performed.

## Boundary

This slice validates file-level observation only.

It assumes the caller-provided external root is not concurrently mutated during
observation. The symlink checks cover normal prototype operation, not
adversarial race safety.

It does not:

- parse LabRAD, DataVault, Labber, or lab-specific legacy records in Scopecat
  core;
- count rows, infer schema, inspect columns, verify preview metadata, generate
  plots, or expose dataframe-like rows;
- decide whether the external file is normalized Scopecat-readable data;
- copy primary data, write storage, write manifests, or accept imports;
- repair moved references or discover alternate paths;
- protect against concurrent external-root mutation or adversarial filesystem
  races;
- import linked-context payloads or traverse relations recursively;
- accept Scopecat-authored export or handoff packages;
- define final storage architecture, import API, package-integrity semantics,
  or GUI behavior.

## Result

Reference-only source observation closes the narrow follow-up from
reference-only legacy import without weakening the boundary clarified in
[`measurement-data-reference-boundary.md`](measurement-data-reference-boundary.md).
Scopecat can check whether a preserved external source reference still resolves
and matches declared file facts, while still not claiming to understand,
preview, plot, repair, copy, or import that source.

This keeps three levels separate:

- reference-level acceptance records the external source reference;
- file-level observation checks availability, sha256, and byte size;
- data-level observation or preview still requires normalized data or an
  explicitly validated adapter authority.

## Follow-Up

Stop this slice at file-level observation unless a later workflow needs one of
these separate boundaries:

- data-level open/read of normalized adapter output;
- reference repair or moved-reference review without automatic discovery;
- adapter package or drop-folder validation;
- existing-record append/update behavior with lock and crash-recovery pressure;
- GUI display of reference-observation findings without previewing legacy data.
