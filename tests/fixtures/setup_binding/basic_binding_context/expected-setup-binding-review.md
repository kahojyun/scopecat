# Expected Setup Binding Review

## Fixture Wrapper

- expected output id: `setup-binding-basic-context.expected`
- status: `expected_validation_output`
- source fixture: `setup-binding-input.json`
- guard: This expected output is not a final station registry schema,
  setup-binding schema, physical wiring ontology, hardware-control contract,
  generator contract, or shared snapshot framework.

## Candidate Summary Review

### Measurement Inputs

Measurement `measurement-04001` records run-start context as a list of named
input snapshots:

| Input | Snapshot | Role |
| --- | --- | --- |
| `parameter_state` | `param-state-0002` | calibrated values |
| `setup_binding` | `setup-binding-0002` | logical-to-physical mapping |
| `station_registry` | `station-registry-mmcs2-redacted` | station context |

The list shape keeps the future generalization visible while avoiding a shared
snapshot framework. Each input family can still keep separate lifecycle, diff,
review, and authority rules.

### Registry And Binding

- station registry: `station-registry-mmcs2-redacted`
- registry scope: station configuration
- selected setup binding: `setup-binding-0002`
- sample: `sample-alpha`
- cooldown: `cooldown-2026-05`

The station registry is referenced as separate context. Setup binding does not
own registry connection payloads, raw hostnames, driver credentials, or
hardware-control behavior.

### Logical Bindings

| Logical entity | Kind | Role | Physical resource |
| --- | --- | --- | --- |
| `qA` | qubit | `drive_line` | `drive_dac_A_ch04` |
| `qA` | qubit | `z_line` | `bias_dac_A_ch02` |
| `cAB` | coupler | `z_line` | `bias_dac_A_ch05` |
| `qA_ro` | readout line | `readout_dac` | `readout_dac_A_ch00` |
| `qA_ro` | readout line | `readout_adc` | `readout_adc_A_ch00` |
| `qA_ro` | readout line | `readout_lo_group` | `readout_lo_group_A` |

### Generated Views

- `line-info-qA-0002`: line-info view for runtime line selection.
- `readout-view-qA-0002`: readout-group view for readout position selection.

These views are included because real setup binding often appears through
generated runtime line/readout artifacts. The fixture treats generator and
converter identity as black-box provenance; it does not execute or validate
project code.

### Binding Diff

Diff `setup-binding-diff-0002` compares `setup-binding-0001` to
`setup-binding-0002`.

| Kind | Logical entity | Role | Old | New |
| --- | --- | --- | --- | --- |
| changed | `qA` | `z_line` | `bias_dac_A_ch01` | `bias_dac_A_ch02` |
| added | `cAB` | `z_line` | none | `bias_dac_A_ch05` |

The qA Z-line change is attention-worthy because it changed since earlier
calibration context. This fixture does not claim that the selected parameter
state is invalid.

### Measurement Reference

- measurement: `measurement-04001`
- experiment: qA chevron check
- logical targets: `qA`, `cAB`
- runtime context refs: `line-info-qA-0002`, `readout-view-qA-0002`
- hardware state claim: `not_recorded`

The measurement reference records selected run-start context. It does not
claim current hardware state.

## Boundary Notes

- setup binding is adjacent to parameter state but not part of parameter state;
- station registry context is separate and redacted;
- generated line/readout views are fixture pressure, not a generator contract;
- binding diffs can support review without defining a full wiring ontology;
- hardware control, resource arbitration, automatic retuning, and scientific
  comparability remain out of scope.

## Reviewer Questions

A reviewer should be able to answer:

- which named input snapshots the measurement used;
- which station registry context was referenced;
- which setup-binding snapshot was selected;
- how qA, cAB, and qA_ro map to physical resource labels;
- which generated runtime views were carried for context;
- which binding assignments changed;
- that binding change attention does not automatically invalidate parameter
  state;
- that no current hardware state or hardware-control claim is made.
