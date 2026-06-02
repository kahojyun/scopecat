# Selected Record Handoff Export Branch Plan

## Status

Active branch plan for the next engineering prototype seam.

Supersession: replace this plan with updates to the accepted handoff boundary,
module README, tests, fixtures, and expected outputs when the implementation
lands.

## Workflow Question

Validate the missing legacy portable handoff seam:

```text
selected stored Measurement Record
  -> single-measurement handoff package export
  -> read-only package preview
  -> receiving-side durable import
```

The workflow map owns the user workflow and gap:
[`../workflow-validation-map.md`](../workflow-validation-map.md).

## Ownership Split

`scopecat.handoff` should own the new export adapter because the output is a
portable handoff package. The adapter should live under
[`../../../src/scopecat/handoff/`](../../../src/scopecat/handoff/) and reuse the
existing package writer shape where possible.

`scopecat.measurement_records` remains the source-record authority. It should
provide read-only source facts and record-local primary data through its
accepted route-local surfaces; it should not learn package writing or package
manifest rules.

The seam adapter owns:

- selecting exactly one stored Measurement Record for export;
- adapting accepted Measurement Records read facts into a handoff package write
  request;
- preserving identity continuity from source record to package measurement;
- enforcing portable/export artifact-boundary checks for the package output;
- returning a local export receipt or summary that is review evidence, not
  receiving-side import authority.

## Authoritative Inputs

Use these active docs for contracts:

- [`../implementation-register.md`](../implementation-register.md)
- [`../prototype-boundaries/handoff.md`](../prototype-boundaries/handoff.md)
- [`../prototype-boundaries/handoff-durable-import-storage.md`](../prototype-boundaries/handoff-durable-import-storage.md)
- [`../prototype-boundaries/measurement-records-creation-lifecycle.md`](../prototype-boundaries/measurement-records-creation-lifecycle.md)
- [`../prototype-boundaries/measurement-records-legacy-run-storage.md`](../prototype-boundaries/measurement-records-legacy-run-storage.md)
- [`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md)
- [`../../../src/scopecat/measurement_records/README.md`](../../../src/scopecat/measurement_records/README.md)

Use discovery and candidate docs only as evidence. In particular, do not copy
`implementation_candidates/selected_measurement_export`,
`spikes/selected_measurement_export`, or the old handoff route candidates into
live code without adapting them to this branch plan and the accepted module
boundaries.

## Proposed First Slice

The first implementation should accept one explicit selected source record and
one caller-declared package destination:

```text
approved selected-record export request
  -> read selected Measurement Record view and primary-data facts
  -> build one handoff package write request
  -> write package through the handoff package writer
  -> reopen package read-only
  -> return local selected-record export receipt
```

The first slice should support one selected stored record and one package
measurement. Batch export, multi-measurement packages sourced from storage,
archive output, signatures, linked-context payload packaging, and receiving
import should remain separate decisions.

## API Shape To Decide

Prefer a narrow handoff entrypoint such as:

```text
run_selected_record_handoff_export(request, storage_root=..., package_root=...)
```

The request should be explicit rather than discovery-driven. Likely fields:

- `approval_state`
- source `record_id` or record directory facts
- package id or package directory facts
- selected package measurement id
- expected source primary-data digest, size, format, and row count when
  available from the record read view
- label, experiment type, and preview metadata to carry into the package
- optional reference-only linked context selected for package review

The implementation can choose typed route-local request/result objects plus a
raw dictionary edge adapter, matching the current handoff module pattern.

## Identity And Mapping

The package measurement should preserve explicit source continuity:

| Package Fact | Source |
| --- | --- |
| package measurement id | caller-declared selected package measurement id, normally derived from the source record id only when the request says so |
| source record id | selected Measurement Record read facts |
| primary data path | copied from the selected record's accepted primary CSV bytes into package topology |
| digest and size | Measurement Records primary-data facts rechecked before package write |
| row count and format | Measurement Records read-view or projected read-model facts |
| label and experiment type | source record read-model or caller-reviewed export request |
| linked context | reference-only recorded references selected for review |

The first slice should not invent missing source facts silently. If preview
metadata is missing, the package may still be exportable only when the result
records an explicit degraded-preview or review-needed finding.

## Artifact And Redaction Boundary

The handoff package directory and `package-manifest.json` are portable/export
artifacts. Package paths must be package-relative and managed-reference fields
must be validated at the package boundary.

Local source paths, storage-root paths, hostnames, usernames, and other
machine-local details should not leak into the package output. A local export
receipt may retain caller-rooted diagnostic references only as local review
surface data.

Linked context remains reference-only unless a later workflow explicitly
promotes payload packaging.

## Failure Shape

The first slice should block before package mutation when:

- the export request is not approved;
- the selected source record cannot be read through accepted Measurement
  Records surfaces;
- the selected primary data is missing, changed, or disagrees with declared
  digest, size, format, or row-count facts;
- the destination package already exists under no-overwrite rules;
- required portable/export package fields cannot be validated.

If package writing starts and then fails, the result should report whether
best-effort cleanup ran or whether a partial package directory needs review.

## Tests And Fixtures

Add focused tests under
[`../../../tests/prototypes/handoff/`](../../../tests/prototypes/handoff/).
Use small repository-safe fixtures, preferably under
[`../../../tests/fixtures/prototypes/handoff/`](../../../tests/fixtures/prototypes/handoff/)
unless an existing fixture family is the clearer source.

The first test set should prove:

- approved selected stored record writes one previewable handoff package;
- source record id, package measurement id, digest, size, row count, and format
  continuity are visible in the package or local receipt as appropriate;
- unapproved export blocks before package mutation;
- stale or mismatched primary-data facts block before mutation;
- destination collision follows no-overwrite behavior;
- machine-local storage paths do not appear in portable package output;
- linked context remains reference-only.

Run:

```sh
uv run python -m unittest discover -s tests/prototypes/handoff
uv run ruff check .
uv run ruff format --check .
```

## Stop Condition

Stop this branch when the narrow composition prototype proves:

```text
stored record -> single-measurement package -> read-only preview
```

and the docs, tests, fixtures, and expected outputs agree on the accepted
boundary. After implementation lands, update the handoff module README and the
accepted handoff prototype boundary instead of keeping this branch plan as
current truth.
