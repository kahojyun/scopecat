# JC-002 Handoff Snapshot Prototype Scope

## Status

Fixture-backed draft prototype scope. The first synthetic fixture and read-only
prototype validate this scope at fixture scale. This is not an
accepted boundary, manifest schema, reader API contract, storage format, or
final GUI spec.

## Purpose

Define the smallest fixture and prototype checks that can test whether
`JC-002` is attractive enough to continue: a selected-run handoff snapshot can
be copied away from the experiment-control computer, opened locally, inspected
for missing context, read through a Python-reader-like path, and plotted
without depending on original local paths.

The adoption test is intentionally concrete: after export, a lab member should
be able to copy the snapshot to a different path, open it offline, understand
what was selected and why, load the selected group in Python, reproduce a
sanity plot in minutes, and see which context is missing, excluded, redacted,
or only referenced. The reader explicitly does not scan for redaction or
certify that an already-created snapshot is safe to publish.

This scope depends on:

- [`jc-002-journey-selection-note.md`](jc-002-journey-selection-note.md)
- [`jc-002-handoff-snapshot-definition.md`](jc-002-handoff-snapshot-definition.md)
- [`jc-002-analysis-handoff-journey.md`](jc-002-analysis-handoff-journey.md)

Current validation artifacts:

- [`../../tests/fixtures/jc002-handoff-snapshot/`](../../tests/fixtures/jc002-handoff-snapshot/)
- [`../../prototypes/jc002_handoff_snapshot.py`](../../prototypes/jc002_handoff_snapshot.py)
- [`../../tests/test_jc002_handoff_snapshot.py`](../../tests/test_jc002_handoff_snapshot.py)

## Hardening Pass Result

The first bounded hardening pass tightened the fixture-scale prototype without
expanding `JC-002` into a richer lab-data fixture or export workflow.

The prototype now checks:

- included artifact paths are portable relative paths confined to the snapshot;
- required status objects use the allowed status vocabulary and preserve the
  difference between concrete values, explicit absence, unknowns, and
  redaction;
- artifact `source_run_relation` values refer to selected runs;
- Scopecat-managed primary data columns, declared axes and values, units, and
  shape agree;
- required sidecar metadata applies to the declared primary data columns;
- included derived input manifest records are exposed through the reader-like
  run and group objects without parsing their attached payloads;
- reader output includes plot-ready specs with manifest-declared title, axis
  labels, series labels, and series data for an external plotter;
- redaction lessons are preserved as export and publish guidance, not reader
  checks or gates.

This hardening pass does not prove:

- safe export creation on an experiment-control computer;
- a stable manifest schema, package format, reader API, or GUI;
- realistic multi-run analysis with repeats, excluded runs, ragged data, IQ or
  complex data, 2D sweeps, trace-valued records, or large-file pressure;
- meeting-ready figure or slide workflows.

## Prototype Question

Can a user take a small selected-run snapshot to an analysis computer and,
without network access, cloud login, control-PC access, local Data Vault paths,
or managed script execution:

- identify what runs are included;
- understand the user selection intent, group order, and condition labels;
- see source identity, roles, warnings, and missing context;
- load one run and the whole selected group with data, axes, units, labels,
  and required sidecars;
- hand the loaded data to a plotter-like consumer with title, axis labels, and
  series labels;
- understand which optional derived inputs, verification references, or report
  artifacts were included or excluded?

## Fixture Boundary

Use a synthetic fixture derived from the observed role pattern, not from exact
private data.

The fixture should contain:

- one selected-run group with two or three runs;
- an explicit selection record: who or what selected the runs, selected reason,
  group title, group order, and optional per-run notes;
- per-run source IDs namespaced by source system or station, acquisition
  timestamps, measurement labels, and original path evidence using redacted
  values;
- group-level order and condition labels, such as baseline and sample;
- one primary data artifact per run with simple coordinates and values;
- one required read sidecar for at least one run;
- axis names, units, shape, and value labels;
- one intentionally messy but common context case, such as a missing sample
  label, redacted source path, required sidecar, unknown-role artifact, or
  ambiguous source field;
- sample or device label when available and a small important-parameter
  summary;
- at least two explicit missing statuses, such as `not_provided` and
  `unknown`;
- one calibration or correction reference kept as a reference by default;
- one user-attached derived input that is visible as an export decision and has
  source-run relation, size or checksum evidence, lossy-or-processed status
  when known, and human production note when known;
- one unknown-role artifact that is excluded with a warning;
- one report artifact that is deliberately excluded from the snapshot.

The fixture may use simple JSON and CSV files to make validation cheap. That is
a prototype convenience, not a product export-format decision. The reader
prototype does not attempt to be a general CSV parser or handle arbitrary CSV
edge cases supplied by users; it only demonstrates checks for the small
Scopecat-managed fixture format.

## Source-Map Summary

The source evidence behind this fixture is internal and full-fidelity. Public
docs should preserve only role-stable facts:

| Fixture role | Source evidence shape | Public-safe lesson |
| --- | --- | --- |
| Selected data by ID/path | Analysis notebooks and helpers preserve Data Vault paths, numeric IDs, and local source paths. | Snapshot identity must not depend on fragile local path conventions. |
| Primary data plus sidecars | Legacy reads often pair data files with sidecar metadata needed for columns, axes, and labels. | Required read sidecars should travel with selected data. |
| Derived input | Some intermediate arrays are practical inputs to later analysis rather than final report artifacts. | User-attached derived inputs need explicit role and provenance. |
| Report artifact | PDFs, plots, and decks often appear after analysis. | Report artifacts are excluded from the default snapshot and belong to later lineage. |
| Missing context | Sample labels, important parameters, and selection intent may be absent or only user-declared. | Missing-value statuses should be explicit, not silent. |

## Prototype Outputs

The prototype may produce:

- a fixture snapshot directory or archive;
- a fixture-local manifest or index used only for validation;
- a local GUI-like summary or static report listing runs, roles, warnings, and
  missing context;
- a Python-reader-like smoke test that returns notebook-ready objects for one
  run and for the selected group, including data, axes, units, condition
  labels, sidecar status, and warnings;
- a mock plotter smoke test that consumes plot-ready data after reading the
  snapshot on the analysis side;
- a support/debug summary with stable sections for identity, openability,
  missing fields, exclusions, and export-provided redaction status.

The plots and summaries generated after reading the copied snapshot are
consumer-side validation artifacts. They are not part of the handoff snapshot
created by export, and the prototype does not treat caller-chosen output paths
as a reader API safety boundary.

## GUI Summary Checks

The local GUI-like summary or static report should answer ordinary lab-user
questions without requiring the user to inspect raw manifest files:

- What snapshot is this?
- Which runs are included?
- Why were these runs selected?
- What order and condition labels should I use for first-pass plotting?
- What data or sidecar should I load first?
- Which fields are missing, unknown, not provided, or redacted?
- Which artifacts were excluded and why?
- Which included artifacts need special caution, such as user-attached derived
  inputs or advanced internal references?
- What redaction status was recorded by export?

This is a validation shape, not a final GUI specification.

## Acceptance Checks

The prototype passes this draft scope when:

- the snapshot can be copied to a path unrelated to the source fixture and
  still opened;
- no test depends on original local source paths as portable read paths;
- the local GUI-like summary can list selected runs, selection reason, group
  order, condition labels, artifact roles, source identity, missing fields,
  export-provided redaction status, and excluded artifacts;
- each run ID is scoped by source system or station, or explicitly marked
  ambiguous or unknown;
- the Python-reader-like smoke test can load one run's primary data, axes,
  units, shape, labels, and required sidecar status as a notebook-ready object;
- the Python-reader-like smoke test can enumerate and load the whole selected
  group with per-run labels, condition labels, shared context, and per-run
  overrides;
- the reader can provide plot-ready specs for one run and for the selected
  group, and a mock plotter can consume those specs;
- the user-attached derived input is visible as an included optional artifact
  with role, provenance, source-run relation, size or checksum evidence, and
  known processed-or-lossy status, without reader-side payload parsing;
- the report artifact remains excluded, but its existence, role, and exclusion
  reason are reported;
- the unknown-role artifact is excluded or requires explicit classification;
- advanced or internal-only artifacts are excluded by default, and any copied
  advanced artifact has role, provenance, and warning text;
- reader validation does not perform redaction audits; redaction and
  publishability are owned by export or publish flows because users can bypass
  the reader and inspect snapshot files directly;
- control-PC safety invariants are preserved: no source mutation, no code
  execution, no notebook execution, no generated artifacts during export, no
  network or cloud dependency, and no instrument or setup access;
- the support/debug summary has stable sections for: what is this snapshot,
  can it open, what is missing, what was excluded, and what redaction status
  export recorded.

## Redaction Lessons For Export

The hardening loop showed that reader-side redaction is the wrong place to
guarantee public safety. Once a snapshot exists on disk, a user can bypass the
reader and inspect CSV, JSON, sidecars, arrays, or attached files directly.

Use the project-level structured redaction boundary in
[`../jc-analysis-operating-standard.md`](../jc-analysis-operating-standard.md)
for path handling, keyword tables, arbitrary payloads, and publish/export
ownership. `JC-002` adds only this fixture-specific lesson: the snapshot reader
should pass through export-produced redaction status and must not scan or
redact already-created snapshots.

## Non-Goals

This prototype scope does not accept:

- final package layout;
- stable manifest schema;
- stable Python reader API signature;
- final GUI behavior;
- storage model;
- export adapter commitments;
- managed analysis-script execution;
- generated report, fit, PDF, slide, or publication workflow;
- protection against intentional misuse of caller-selected output paths;
- parsing edge cases for arbitrary user-provided CSV or sidecar file formats;
- permission system;
- scientific-comparison or equivalence judgment.

## Reopening Triggers

Reopen this scope if validation shows that:

- users cannot get to a basic plot without committing to a stable reader API
  earlier than expected;
- the role model cannot distinguish primary data, required sidecars, derived
  inputs, and report artifacts clearly enough for export decisions;
- multi-run group labels are too weak for real analysis handoff;
- excluded report artifacts are needed for trust in the first slice;
- local GUI and Python-reader validation pull the design toward conflicting
  manifest needs.
