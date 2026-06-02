# Handoff Package Contents Preview Validation Result

## Status

Implementation candidate validated.

Document role: historical discovery validation result. It records what this
slice earned and what it did not establish. Current handoff implementation
boundaries are owned by
[`handoff.md`](../../../../architecture/boundaries/handoff.md);
do not update this result to mirror live API or route changes.

This result validates a narrow Measurement Records slice: **Handoff Package
Contents Preview**.

The slice name is intentionally specific. It is the manifest-orientation step
for a Scopecat-authored selected-measurement export package: the receiving user
can see what the package says it contains before read-only package use or later
acceptance/organization. Incoming-record import preview remains a separate
slice because its input authority is an external candidate record.

## UX Position

The intended receiving-side experience is open-before-import:

1. Preview package contents from the manifest for quick orientation.
2. Open the package read-only to inspect selected measurements, load declared
   primary data, review metadata and linked context references, and make basic
   declared-preview plots.
3. Optionally accept, import, or organize the package into local Scopecat
   storage when the user wants mutation.

This slice validates only the first step. Read-only package open is validated
separately; GUI behavior and stable SDK surfaces remain future decisions. This
slice keeps the preview manifest-only so the receiving user can understand
package contents before file reads, package integrity checks, local storage
writes, or opener behavior are accepted.

## Fixture

Fixture:
[`../../tests/fixtures/handoff_package_contents_preview/basic_package/`](../../../../../tests/fixtures/handoff_package_contents_preview/basic_package)

Implementation candidate:
[`../../implementation_candidates/handoff_package_contents_preview/`](../../../../../implementation_candidates/handoff_package_contents_preview)

The fixture represents one Scopecat-authored selected-measurement handoff
package manifest:

- one package identity with a redacted display path linked to a
  selected-measurement export summary;
- two selected measurement records with packaged primary data;
- one preview-ready Rabi measurement and one T1 measurement with degraded
  preview metadata;
- default packaged parameter snapshots for both measurements;
- one packaged user-selected wiring note;
- one visible artifact reference that was not included in the package;
- one declared missing companion note preserved from the source export.

The builder treats all package paths and linked context as manifest-declared
references.

## What This Earned

The implementation candidate shows that Scopecat can summarize and classify a
Scopecat-authored handoff package before read-only open or later acceptance:

- preserve package identity, package-declared source export summary reference,
  selected measurements, primary-data references, default bundle contents, and
  linked context;
- reject empty selected-measurement package manifests;
- summarize declared preview metadata and degraded-preview warnings from the
  export manifest;
- summarize packaged, visible-but-not-packaged, and missing package content
  states;
- classify the package as needing review when preview metadata is degraded or
  linked context is not packaged;
- classify selected measurements separately from package-level review state;
- report degraded preview metadata, visible-but-not-packaged artifacts, and
  missing linked context as review findings;
- report those findings as preview review state rather than package-integrity,
  import-acceptance, storage-mutation, schema-inference, archive-extraction, or
  relation-graph claims.

## Boundary

This slice validates receiving-side package contents preview only.

Out of scope:

- provide the read-only package opener, SDK object model, GUI workflow, or
  plotting surface;
- read packaged files, extract archives, validate checksums, or inspect whether
  manifest-declared files exist;
- accept, import, organize, copy, move, archive, or write package contents;
- define final handoff package, archive, measurement, attachment, artifact,
  relation, or data-shape schemas;
- validate package integrity, signatures, or provenance beyond explicit
  manifest facts;
- traverse relation graphs or infer analysis DAGs;
- decide source permanence, scientific validity, reproducibility, or plotting
  correctness.

## Result

Handoff package contents preview is the receiving-side counterpart to selected
measurement export and incoming-record import preview. It answers a different
question from import preview: what does this Scopecat-authored package say it
contains before the user opens it read-only or later accepts/organizes it?

The slice validates package-orientation vocabulary without granting stronger
package authority. Degraded preview metadata remains a review finding, not a
claim that packaged data is unreadable. Visible-but-not-packaged artifacts and
missing linked context remain review findings, not package-integrity,
import-acceptance, relation-graph, or plotting failures.

## Follow-Up

Stop this slice at manifest-only package contents preview. The next
receiving-side step is now validated separately in
[`slices/measurement-records/handoff/opener-validation-result.md`](opener-validation-result.md):
read-only package use with package-local primary-data loading and declared
preview rows.

Before changing this route again, apply the route-local field-category checklist
in
[`archive/measurement-records-handoff-route/contract-checklist.md`](../../../archive/measurement-records-handoff-route/contract-checklist.md)
so managed identifiers, package paths, redacted display references, free text,
and declared manifest facts are reviewed by category rather than one field at a
time.

Likely follow-up slices:

- package integrity or archive validation for a declared package, without
  accepting import or storage mutation;
- source observation or checksum validation for packaged primary data, without
  accepting a final package format;
- handoff package acceptance, with explicit copy/reference storage mutation
  and no-overwrite behavior;
- harder packaged data-shape preview cases, such as ragged scans or
  trace-per-point data, without automatic schema inference.
