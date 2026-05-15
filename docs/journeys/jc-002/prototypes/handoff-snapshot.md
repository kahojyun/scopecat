# JC-002 Handoff Snapshot Prototype

## Status

Fixture-backed draft prototype. It validates a fixture-scale handoff boundary
only; it is not an accepted decision, stable manifest schema, reader API,
storage format, or final GUI spec.

## Purpose

Test whether a selected-run handoff snapshot can be copied away from the
experiment-control computer, opened locally, inspected for missing context,
loaded through a Python-reader-like path, and plotted without depending on
original local paths.

This prototype depends on:

- [`../selection.md`](../selection.md)
- [`../snapshot-boundary.md`](../snapshot-boundary.md)
- [`../journey.md`](../journey.md)

Current validation artifacts:

- [`../../../../tests/fixtures/jc002-handoff-snapshot/`](../../../../tests/fixtures/jc002-handoff-snapshot/)
- [`../../../../prototypes/jc002_handoff_snapshot.py`](../../../../prototypes/jc002_handoff_snapshot.py)
- [`../../../../tests/test_jc002_handoff_snapshot.py`](../../../../tests/test_jc002_handoff_snapshot.py)

## Prototype Question

Can a user take a small selected-run snapshot to an analysis computer and,
without network access, cloud login, control-PC access, local Data Vault paths,
or managed script execution:

- identify included runs and selection intent;
- see source identity, artifact roles, warnings, exclusions, and missing
  context;
- load one run and the selected group with data, axes, units, labels, and
  required sidecars;
- hand plot-ready data to an external plotter;
- understand which derived inputs, verification references, or report artifacts
  were included, excluded, or only referenced?

## Fixture Shape

The fixture should stay synthetic and public-safe. It should exercise:

- one selected-run group with two or three runs;
- source IDs, acquisition timestamps, measurement labels, and redacted original
  path evidence;
- group order and condition labels;
- primary data plus at least one required read sidecar;
- axes, units, shape, and value labels;
- explicit `not_provided`, `unknown`, and `redacted` statuses;
- one calibration or correction reference;
- one user-attached derived input included as an explicit export decision;
- one unknown-role artifact excluded with a warning;
- one report artifact deliberately excluded from the snapshot.

The fixture may use JSON and CSV for cheap validation. That is a prototype
convenience, not a product export-format decision.

## Validated Behavior

The current prototype checks:

- included artifact paths are portable relative paths confined to the snapshot;
- required status objects use the allowed status vocabulary;
- artifact `source_run_relation` values refer to selected runs;
- primary data columns, axes, units, and shapes agree;
- required sidecar metadata applies to declared primary data columns;
- included derived input records are visible through reader-like run and group
  objects without parsing attached payloads;
- reader output includes plot-ready specs with declared title, axis labels,
  series labels, and series data;
- excluded unknown-role and report artifacts remain visible as warnings or
  exclusions;
- reader validation does not perform redaction audits.

## Boundary Lessons

The hardening loop showed that reader-side redaction is the wrong place to
guarantee public safety. Once a snapshot exists on disk, a user can bypass the
reader and inspect the files directly. Export or publish flows must own
redaction and publishability.

The prototype also keeps consumer-side generated plots and summaries outside
the snapshot created by export. They validate that the snapshot is usable, but
they are not part of the exported package.

## Non-Goals

This prototype does not accept:

- safe export creation on a real control computer;
- stable package manifest schema;
- stable Python reader API;
- final GUI behavior;
- storage model;
- arbitrary CSV or user-file parsing;
- generated plots, arrays, fits, PDFs, reports, or decks during export;
- public/reference packaging;
- permission systems;
- managed analysis execution;
- live monitor semantics;
- full work-bundle export/import.

## Reopening Triggers

Reopen this prototype scope if validation shows that:

- users cannot get to a basic plot without a stable reader API being specified
  earlier;
- another realistic fixture needs context or artifact roles not represented
  here;
- generated analysis outputs must travel in the first snapshot for the user to
  trust or use it;
- Tier 3 verification context is routinely required for ordinary handoff;
- local GUI and Python-reader validation pull the design toward conflicting
  manifest needs.
