# Expected Multi-Measurement Export Review

## Status

Expected reviewer-facing output for the synthetic multi-measurement export
fixture. This is not a product UI, package format, schema contract, or UX
design.

## Selected Export Set

- selection mode: `multi_measurement`
- selected measurements: `1001`, `1002`
- traversal policy: `non_recursive`

Selecting these measurements exports their default bundles. It does not
recursively include linked source measurements, notebooks, derived arrays,
reports, or workbooks.

## Included By Default

| Measurement | Experiment | Included items |
| --- | --- | --- |
| `1001` | `qA Rabi amplitude sweep` | Run 1001 Rabi source data (`source/session-alpha/01001_qA_rabi_20260518_101500.csv`); Run 1001 parameter snapshot (`snapshots/run-01001-parameters.json`) |
| `1002` | `qA T1 decay` | Run 1002 T1 source data (`source/session-alpha/01002_qA_t1_20260518_104500.csv`); Run 1002 parameter snapshot (`snapshots/run-01002-parameters.json`) |

Shared included context:

- Session wiring note (`attachments/session-alpha-wiring-note.md`):
  user-declared attachment linked to measurements `1001` and `1002`.

## Optional Linked Context

| Label | Kind | Path | Relation | Authority | Linked measurements | Include status |
| --- | --- | --- | --- | --- | --- | --- |
| qA summary candidate | artifact | `artifacts/qA-summary-candidate.csv` | summarizes | user_declared | `1001`, `1002` | optional |

The optional artifact is visible so a user can decide whether to include it
later. This fixture does not treat it as proof of analysis lineage.

## Missing Context

- Run 1002 fit note (`attachments/run-01002-fit-note.md`): user-declared
  companion for measurement `1002` is absent from the fixture.

## Source Recovery

- legacy session: `session-alpha`
- public-safe source location:
  `LAB_LOCAL:/redacted/datavault/session-alpha`
- local source path is redaction-sensitive and not portable.

## Warnings

- `local_only_path`: original local source path is redaction-sensitive and not
  portable.
- `missing_companion`: a user-declared companion for measurement `1002` is
  absent.

## Boundary Notes

- The shared artifact is visible but not part of the default measurement export
  bundle.
- Export does not recursively include linked source measurements, notebooks,
  derived arrays, reports, or workbooks.
- Selected measurements and declared links indicate export intent only, not fit
  validity, analysis lineage, or scientific reproducibility.

## Reviewer Questions

A reviewer should be able to answer:

- which measurements were intentionally selected;
- which primary data and metadata are included by default;
- which human-facing labels correspond to exported file paths;
- which shared context is included;
- which artifact is optional rather than silently included;
- which relation authority is user-declared;
- which context is missing;
- that Scopecat is not claiming a downstream analysis DAG.
