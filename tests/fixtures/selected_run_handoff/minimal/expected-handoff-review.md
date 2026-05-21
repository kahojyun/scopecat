# Expected Selected Run Handoff Review

## Status

Expected reviewer-facing output for the synthetic minimal fixture. This is not
a product UI, package format, or public documentation contract.

## Selection

Selected run: legacy data ID `42`.

Source reference:

- session: `selected-rabi-demo-session`
- encoded filename: `selected-rabi-source.csv`
- fixture source file:
  `source/selected-rabi-demo/selected-rabi-source.csv`
- export source:
  `LAB_LOCAL:/redacted/datavault/selected-rabi-demo/selected-rabi-source.csv`

Selection rationale:

Run `42` was chosen as the candidate to hand off for downstream contrast
analysis. This is a handoff choice, not a claim that the run is scientifically
validated.

## Figure Readiness

Status: partial.

Experiment:

- label: `qA Rabi amplitude sweep`
- type: `rabi_amplitude_sweep`
- target: `qA`
- run started at: `2026-05-18T10:15:00`
- session: `selected-rabi-demo-session`
- setup: `redacted-fixture-fridge`
- sample: `redacted-fixture-sample`

Relevant parameter context:

- readout frequency: `6.101 GHz`
- drive frequency: `4.802 GHz`
- Rabi amplitude parameter: `0.025`
- held bias condition: `0.100 V`

Source columns:

| Column | Role | Unit |
| --- | --- | --- |
| `bias_v` | held condition | `V` |
| `drive_amp` | sweep axis | `arb` |
| `iq_i` | measured response | `arb` |
| `iq_q` | measured response | `arb` |

Candidate figure panels:

| Panel | X | Y | Source | Caution |
| --- | --- | --- | --- | --- |
| qA Rabi response | `drive_amp` | `iq_i` | `source/selected-rabi-demo/selected-rabi-source.csv` | plot hint only; no fit or quality claim |

Missing for group-meeting interpretation:

- calibration notes;
- fit result;
- uncertainty estimate.

## Linked Context

Present:

- source record for run `42`;
- copied parameter snapshot: `snapshots/selected-rabi-parameter-snapshot.json`;
- companion artifact: `companions/selected-rabi-iq-companion.json`;
- derived artifact: `derived/selected-rabi-analysis-summary.csv`.

No Silent Transform:

- source record for run `42` should not be silently compressed, converted,
  filtered, or otherwise transformed during export:
  `source/selected-rabi-demo/selected-rabi-source.csv`.

Missing:

- `companions/selected-rabi-calibration-notes.md`.

## Warnings

- `local_only_path`: the original source path is redaction-sensitive and not
  portable. Use `LAB_LOCAL:/redacted/datavault/selected-rabi-demo` as the public-safe
  display value.
- `missing_companion`: a referenced calibration-notes companion is absent.
- `figure_readiness_partial`: the handoff includes experiment label, measured
  columns, context, and plot candidates, but calibration notes, fit results,
  uncertainty, and scientific selection rationale are missing.

## Boundary Notes

- Selected source data should not be silently compressed, converted,
  filtered, or otherwise transformed during export. This fixture does not
  define a final checksum or package contract.
- The handoff preserves where the selected data was exported from using a
  public-safe source reference.
- Source data, copied parameter context, companion artifact, and derived
  artifact are represented as distinct handoff material.
- Derived artifact relations are linked by fixture declaration; this fixture
  does not recompute the analysis.
- Selected means handed off for later work, not proven good, reproducible,
  or reference-worthy.

## Reviewer Questions

A reviewer should be able to answer:

- selected run: `42`;
- preserved source identity: session, encoded filename, numeric ID, and fixture
  source file;
- export trust: the output says where the selected data was exported from and
  which source file should not be silently transformed during export;
- figure readiness: the output names the experiment type, target, source
  columns, candidate plot axes, relevant parameter context, and missing
  scientific annotations;
- parameter context: `snapshots/selected-rabi-parameter-snapshot.json`;
- companion context: one present IQ summary and one missing calibration note;
- derived context: `derived/selected-rabi-analysis-summary.csv`;
- portability issue: local-only path is redacted;
- trust boundary: no scientific validation, reanalysis, storage, sync, or
  package-format decision is earned.
