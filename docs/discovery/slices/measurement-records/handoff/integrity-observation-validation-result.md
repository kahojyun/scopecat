# Handoff Package Integrity Observation Validation Result

## Status

Implementation candidate validated.

Document role: historical discovery validation result. It records what this
slice earned and what it did not establish. Current handoff implementation
boundaries are owned by
[`handoff.md`](../../../../architecture/boundaries/handoff.md);
do not update this result to mirror live API, integrity, or workflow changes.

This result validates a read-only receiving-side integrity observation for an
already expanded directory-shaped handoff package. It compares package-local
files against manifest-declared digest and size facts where those facts are
present. It is not accepted architecture, an authenticity model, archive
validation, signature validation, import acceptance, final package format, GUI
workflow, or stable SDK API.

## Fixture

Fixture:
[`../../tests/fixtures/handoff_package_opener/basic_package/package/handoff-package-legacy-rabi-001/`](../../../../../tests/fixtures/handoff_package_opener/basic_package/package/handoff-package-legacy-rabi-001)

Implementation candidate:
[`../../implementation_candidates/handoff_package_integrity_observation/`](../../../../../implementation_candidates/handoff_package_integrity_observation)

The candidate reuses the existing openable handoff-package fixture so the
question stays focused on file observation and declared integrity comparison,
not on adding a new package shape.

## What This Earned

The candidate shows that a receiver can inspect package-local member state
before import or acceptance:

- read `package-manifest.json` from an existing package directory;
- validate the manifest through the existing handoff package contents-preview
  contract;
- require the package directory name to match the manifest package id;
- collect manifest-declared packaged members with package-relative paths;
- read package-local regular files without following symlink targets or
  symlink parents;
- compute observed sha256 and byte size for available members;
- compare observed facts to manifest-declared digest and size when declared
  together;
- reject partial digest/size declarations on packaged members;
- report verified, mismatched, unavailable, blocked, or not-declared member
  states as local review facts.

Artifact posture: local review summary. The output is useful before package
acceptance, but it is not a portable package member or public artifact.

## Boundary

This candidate deliberately keeps integrity observation narrower than a trust
or import system. It does not:

- accept or import package contents;
- mutate local Scopecat storage;
- extract archives or validate archive contents;
- validate signatures, publishers, transport provenance, or authenticity;
- infer schemas, load CSV preview rows, or render plots;
- recursively import linked-context payloads;
- support adversarial concurrent package-root mutation;
- define a GUI workflow, final SDK names, final package format, or shared
  measurement-record model.

Digest and size comparison are local observations of bytes currently present
in the directory package. A verified comparison means the observed member
matches its manifest-declared facts; it does not prove who created the package
or whether the manifest itself is trusted.

## Result

At this checkpoint, the handoff package route had a separate read-only
integrity-observation step that can sit between package preview/open/review and
later acceptance. This keeps package acceptance explicit while allowing the
receiver to catch missing or modified package members before storage mutation.
