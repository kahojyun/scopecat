# Expected Selected Reference Comparison Review

## Fixture Wrapper

- expected output id: `selected-reference-basic-context-compare.expected`
- status: `expected_validation_output`
- source fixture: `reference-comparison-input.json`
- guard: This expected output is not a final comparison engine,
  user-judgment engine, setup truth contract, raw-data comparison contract, or
  GUI design.

## Candidate Summary Review

### Selected Reference

- comparison: `reference-compare-0001`
- current measurement: `measurement-05002`
- reference measurement: `measurement-04001`
- reference selection source: `user_measurement_mark`
- reference mark: `last_working_reference`

The selected reference is user-chosen comparison context, supplied through an
ordinary measurement mark. The mark is selection context, not a special
Scopecat judgment.

### Measurement Pair

| Side | Measurement | Experiment | Sample | Cooldown | Start |
| --- | --- | --- | --- | --- | --- |
| reference | `measurement-04001` | qA chevron check | `sample-alpha` | `cooldown-2026-05` | `2026-05-20T09:30:00` |
| current | `measurement-05002` | qA chevron check | `sample-alpha` | `cooldown-2026-05` | `2026-05-21T11:15:00` |

### Named Input Comparison

| Input | Reference | Current | Finding |
| --- | --- | --- | --- |
| `parameter_state` | `param-state-0002` | `param-state-0003` | changed |
| `setup_binding` | `setup-binding-0002` | `setup-binding-0002` | same observed |
| `station_registry` | `station-registry-mmcs2-redacted` | `station-registry-mmcs2-redacted` | same observed, redacted |

The changed parameter state is an objective comparison finding.

### Preview Metadata

- shape: `rectangular_2d_grid_table`
- axes: `coupler_bias_v`, `drive_duration_ns`
- signal: `excited_state_probability`
- plot candidate: heatmap

Both measurements declare the same preview shape. A later GUI could use this
to quickly browse or overlay compatible measurements, without trying to produce
publication-grade plots or user interpretation.

### Findings

| Kind | Code | Subject |
| --- | --- | --- |
| same observed | `same_observed_preview_shape` | declared preview metadata |
| same observed | `same_observed_setup_binding` | setup binding |
| changed | `changed_parameter_state` | parameter state |
| missing | `missing_current_fit_summary` | fit summary |
| unlinked | `unlinked_reference_analysis_note` | analysis note |
| unverified | `unverified_mounted_sample_identity` | mounted sample identity |
| redacted | `redacted_station_connection_details` | station connection details |

These labels avoid using `gap` as a catch-all.

### Not Compared

- fit quality
- user interpretation
- raw waveforms
- hardware runtime state
- experiment code/version

These are explicit fixture boundaries, not missing facts.

## Boundary Notes

- selected reference means user-selected comparison context;
- last-working and similar labels can be ordinary user marks, not special
  Scopecat reference types;
- comparison findings do not imply cause attribution;
- preview compatibility supports quick browsing and comparison, not
  publication-grade plotting;
- unverified, redacted, missing, unlinked, same-observed, changed, and
  not-compared facts remain distinct;
- the fixture compares declared context only;
- raw data, fit quality, hardware runtime state, setup truth, equivalence
  scoring, user-provided analysis conclusions, and GUI behavior remain out of
  scope.

## Reviewer Questions

A reviewer should be able to answer:

- why the reference was selected;
- which named input snapshots changed or matched;
- whether preview metadata looks comparable enough for inspection;
- which supporting artifacts are missing or unlinked;
- which facts are unverified or redacted;
- which comparisons were intentionally not performed.
