# Selected Reference Code Comparison Review

## Selected Reference

- Reference measurement: `measurement-06001`
- Current measurement: `measurement-06002`
- Reference source: ordinary measurement mark `last_working_reference`

## Selected Code Context

The reference uses `code-context-readout-cali-0001` and the current measurement
uses `code-context-readout-cali-0002`. This is a
changed selected-code-context finding, not cause attribution.

Both selected code contexts use `readout_calibration_entrypoint.ipynb` as the
notebook entrypoint and record notebooks as source without outputs.

## File Inventory Findings

- `readout_calibration_entrypoint.ipynb`: changed recorded source observation.
- `helpers/record_measurement_context.py`: same observed recorded source
  observation.
- `helpers/readout_correction.py`: missing from the current selected code
  context.
- `helpers/readout_correction_v2.py`: missing from the reference selected code
  context.

## Declared Context

Both selected code contexts declare `env-profile-control-pc-redacted` as an
environment profile hint. Environment readiness is not compared.

The external code root display value is redacted for the public-safe fixture.

## Boundary

This fixture compares declared selected-code records only. It does not inspect
internal Git state, scan live files, resolve dependency closure, restore a
managed workspace, import code, execute notebooks, analyze hardware readiness,
or define a workflow DAG.

Recorded source observation IDs are fixture-level comparison tokens. They are
not a checksum, archive, content-addressed storage, or final integrity
contract.
