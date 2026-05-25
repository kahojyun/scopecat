# Incoming Measurement Record Import Preview Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Records slice: **Incoming
Measurement Record Import Preview**.

It does not accept an importer, storage writer, package format, checksum or
archive contract, automatic schema inference, recursive relation traversal,
import review GUI, or shared measurement-record schema.

The slice name is intentionally specific. It previews externally supplied
incoming measurement candidates from an explicit manifest. It is not the
offline or receiving-side preview of a Scopecat-created selected-measurement
handoff package; that package-contents preview is validated separately because
the input authority is different.

## Fixture

Fixture:
[`../../tests/fixtures/measurement_record_import_preview/basic_preview/`](../../tests/fixtures/measurement_record_import_preview/basic_preview/)

Implementation candidate:
[`../../implementation_candidates/measurement_record_import_preview/`](../../implementation_candidates/measurement_record_import_preview/)

The fixture records two incoming measurement candidates from an explicit
incoming-record manifest:

- one declared-available Rabi CSV with preview-ready 1D table metadata and an
  operator note;
- one T1 candidate with unavailable source data, degraded preview metadata, and
  unavailable linked notebook context.

The builder treats source paths and linked-context references as declared facts.
It does not read source files, parse CSV headers, copy files, write storage,
accept imports, infer schemas, checksum content, render plots, or traverse
relations.

## What This Earned

The implementation candidate shows that a side-effect-free summary can preview
incoming measurement records before import authority exists:

- preserve incoming record identity, source kind, source label, redacted
  display path, current-reference state, and primary-data reference;
- summarize declared preview metadata and degraded-preview warnings from the
  manifest without source inspection;
- summarize explicitly listed linked context without recursive traversal;
- classify records as preview-ready for review, blocked pending source review,
  or needing metadata or linked-context review;
- report unavailable source data, missing preview metadata, and unavailable
  linked context as review findings;
- keep findings separate from importer validity, storage mutation,
  package-integrity, plotting, schema-inference, or relation-graph claims;
- reject fixture claims that cross into source observation, storage mutation,
  import acceptance, schema inference, package integrity, recursive traversal,
  GUI workflow, or shared schema.

## Boundary

This slice validates incoming-record import preview only.

It does not:

- accept, import, copy, move, archive, checksum, or write incoming records;
- preview a selected-measurement export package or define offline package
  viewer behavior;
- inspect whether referenced files exist outside the public-safe fixture;
- read source files to infer shape, columns, units, or plot candidates;
- define a final importer, storage model, package format, or acceptance flow;
- decide final measurement, attachment, artifact, relation, or data-shape
  schema;
- traverse relation graphs or infer analysis DAGs;
- decide source permanence, scientific validity, reproducibility, or plotting
  correctness;
- define GUI behavior.

## Result

Incoming-record import preview is a useful counterpart to selected measurement
export. It tests similar source identity, current-reference, declared preview
metadata, linked-context, and attention-state pressure from the external
candidate side without granting Scopecat import or storage authority.

The related receiving-side package preview is validated in
[`handoff-package-contents-preview-validation-result.md`](handoff-package-contents-preview-validation-result.md).
It starts from a Scopecat-authored selected-measurement export package manifest
and answers a different question: what contents, preview metadata, attachments,
artifacts, and degraded or missing context are present in this handoff package
before read-only package use or later acceptance/import/organization?

Unavailable source data blocks preview review for that record, but the finding
does not claim the source is permanently missing or invalid. Missing preview
metadata and unavailable linked context stay review findings, not importer,
package, relation-graph, or plotting failures.

## Follow-Up

Stop this slice at incoming-record import preview unless the next workflow
needs sharper legacy-source classification or import acceptance vocabulary.

Likely follow-up slices should stay separate:

- adapter-authored legacy import acceptance for one normalized source shape,
  with explicit storage mutation boundaries and no core legacy reader;
- package integrity or handoff package acceptance, starting from the
  separately validated package contents preview boundary rather than an
  external incoming-record manifest;
- source observation or checksum validation for a declared import package,
  without accepting a full package format;
- harder incoming-record data-shape preview cases, such as ragged scans or
  trace-per-point data, without automatic schema inference.
