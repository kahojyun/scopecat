# Handoff Package Writer Validation Result

## Status

Implementation candidate validated.

Document role: historical discovery validation result. It records what this
slice earned and what it did not establish. Current handoff implementation
boundaries are owned by
[`handoff.md`](../../../../architecture/boundaries/handoff.md);
do not update this result to mirror live API or package-writer hardening.

## Fixture

[`../../tests/fixtures/handoff_package_writer/basic_package/`](../../../../../tests/fixtures/handoff_package_writer/basic_package)

The fixture writes one directory-shaped handoff package from explicit package
writer input. It includes both the local write-receipt expected output and the
expected portable package files:

- one selected measurement primary CSV copied from caller-provided storage;
- one deterministic package manifest written at
  `{package_id}/package-manifest.json`;

The manifest also includes one linked context preserved as a visible
reference-only manifest entry; its payload is not packaged.

## Candidate

[`../../implementation_candidates/handoff_package_writer/`](../../../../../implementation_candidates/handoff_package_writer)

The candidate validates managed package paths, generated package
directory/manifest topology, separation between measurement storage and package
roots, non-empty selected-measurement input, no-overwrite destination topology,
source sha256/size preflight, managed identifiers and schema-binding column
names, preview plot-source continuity, unique linked measurement targets,
reference-only linked-context alignment, allowlisted manifest projection,
manifest compatibility with the handoff package contents preview candidate,
and best-effort rollback for ordinary write failures.

Repeated low-level checks for managed identifiers, syntax-only relative path
checks, generated package primary-data paths, reference targets, redacted
display references, sha256 digests, and package-root separation are supplied by
the narrow contract-primitives candidate. The writer remains responsible for
the package write workflow, manifest projection, file preflight, no-overwrite
behavior, and rollback.

The generated package directory is the portable/package boundary for this
slice. Its `package-manifest.json` is the portable contract/index inside that
directory, and the copied primary CSV is a package member. The manifest includes
package-relative paths and manifest-declared package facts in the same shape
accepted by the handoff package contents preview candidate, but it does not
include the storage source paths used to copy primary data or local display
paths.

The returned `artifact_posture: local_write_receipt` summary is a local
engineering review receipt. It may include the storage-relative source path and
redacted local display identity used for copy review, but it is not part of the
portable package artifact and should not be carried away as the package
contract.

The writer treats schema-binding names, roles, units, relation names, and
record/package identities as managed identifiers. Human-facing labels,
display names, and reasons remain reviewed free text; this slice does not add a
broad runtime redaction or DLP surface for those fields.

This prototype assumes the caller-provided storage and package roots are not
concurrently mutated during the write call. It validates and avoids symlink
roots, parents, and leaf targets during normal operation, but does not claim
adversarial race safety or atomic publish semantics.

## Result

The candidate shows that Scopecat can materialize a minimal handoff package
directory from already-declared selected-measurement package facts. That
directory is the portable artifact for this slice:

- copy selected primary data into
  `measurements/{measurement_record_id}/primary.csv`;
- write a deterministic `{package_id}/package-manifest.json`;
- refuse existing package targets, overlapping package outputs, path traversal,
  source digest/size mismatches, empty selected-measurement packages,
  package roots equal to or inside measurement storage, unapproved writes,
  symlink source/target parents, and linked-context payload packaging;
- perform best-effort rollback for ordinary late write failures;
- return a local write receipt with write results and boundary deferrals.

The candidate does not accept arbitrary nested package member paths. Additional
package members or package layout categories remain future explicit contracts,
not fixture-driven path passthrough.

This remains a candidate directory-manifest shape, not the final Scopecat
package format.

## Not Earned

This result does not accept:

- archive or zip package creation;
- package import acceptance;
- full package integrity beyond declared source/write digest checks for
  materialized files;
- adversarial concurrent filesystem mutation or atomic publish semantics;
- recursive relation traversal or linked-context payload capture;
- final package format;
- shared measurement schema;
- GUI workflow;
- schema inference or scientific validation.
