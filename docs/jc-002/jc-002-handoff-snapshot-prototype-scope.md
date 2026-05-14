# JC-002 Handoff Snapshot Prototype Scope

## Status

Draft prototype scope. Not fixture validated, not an accepted boundary, not a
manifest schema, not a reader API contract, not a storage format, and not a
final GUI spec.

## Purpose

Define the smallest fixture and prototype checks that can test whether
`JC-002` is attractive enough to continue: a selected-run handoff snapshot can
be copied away from the experiment-control computer, opened locally, inspected
for missing context, read through a Python-reader-like path, and plotted
without depending on original local paths.

This scope depends on:

- [`jc-002-journey-selection-note.md`](jc-002-journey-selection-note.md)
- [`jc-002-handoff-snapshot-definition.md`](jc-002-handoff-snapshot-definition.md)
- [`jc-002-analysis-handoff-journey.md`](jc-002-analysis-handoff-journey.md)

## Prototype Question

Can a user take a small selected-run snapshot to an analysis computer and,
without network access, cloud login, control-PC access, local Data Vault paths,
or managed script execution:

- identify what runs are included;
- see source identity, roles, warnings, and missing context;
- load one run's data, axes, units, and required sidecars;
- make a basic plot from the loaded data;
- understand which optional derived inputs, verification references, or report
  artifacts were included or excluded?

## Fixture Boundary

Use a public-safe synthetic fixture derived from the observed role pattern, not
from exact private data.

The fixture should contain:

- one selected-run group with two or three runs;
- per-run source IDs, acquisition timestamps, measurement labels, and original
  path evidence using redacted values;
- group-level order and condition labels, such as baseline and sample;
- one primary data artifact per run with simple coordinates and values;
- one required read sidecar for at least one run;
- axis names, units, shape, and value labels;
- sample or device label, selected reason, and a small important-parameter
  summary;
- at least two explicit missing statuses, such as `not_provided` and
  `unknown`;
- one calibration or correction reference kept as a reference by default;
- one user-attached derived input that is visible as an export decision;
- one unknown-role artifact that is excluded with a warning;
- one report artifact that is deliberately excluded from the snapshot.

The fixture may use simple JSON and CSV files to make validation cheap. That is
a prototype convenience, not a product export-format decision.

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
- a Python-reader-like smoke test that loads one run and prints or returns
  data, axes, units, sidecar status, and warnings;
- a basic plot generated after reading the snapshot on the analysis side;
- a support/debug summary.

The basic plot is a consumer-side validation artifact. It is not part of the
handoff snapshot.

## Acceptance Checks

The prototype passes this draft scope when:

- the snapshot can be copied to a path unrelated to the source fixture and
  still opened;
- no test depends on original local source paths as portable read paths;
- the local GUI-like summary can list selected runs, group order, artifact
  roles, source identity, missing fields, and excluded artifacts;
- the Python-reader-like smoke test can load one run's primary data, axes,
  units, shape, labels, and required sidecar status;
- the consumer-side basic plot can be produced from loaded snapshot data;
- the user-attached derived input is visible as an included optional artifact
  with role and provenance;
- the report artifact remains excluded and is reported as excluded;
- the unknown-role artifact is excluded or requires explicit classification;
- control-PC safety invariants are preserved: no source mutation, no code
  execution, no generated artifacts during export, and no instrument or setup
  access;
- the support/debug summary answers: what is this snapshot, can it open, what
  is missing, what was excluded, and can it be shared.

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
