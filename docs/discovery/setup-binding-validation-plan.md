# Setup Binding Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a first fixture boundary for setup binding. It does not
accept final station registry schema, setup-binding schema, physical wiring
ontology, hardware-control behavior, importer design, GUI design, or parameter
validity rules.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `setup-binding-registry-station-config.md`;
- `setup-binding-sample-cooldown-mapping.md`;
- `setup-binding-measurement-usage.md`.

These notes show that setup binding is a chain, not one artifact:

1. wiring workbook or `_wiring.json`;
2. registry generation code;
3. registry `Device`/`Instrument`/`connection` records;
4. runtime config for LO/readout groupings;
5. generated `chip_info` and `line_info`;
6. readout-position bindings produced by pulse/runtime code;
7. measurement run-start context.

The first fixture should use this chain for realism without making every step
part of the product contract.

User/project transformation code is black-box provenance for this slice.
Scopecat records declared or generated setup-binding artifacts and references;
it does not execute, inspect, or validate the generator, converter, waveform,
or runner code that produced or consumed them.

## Validation Question

Can Scopecat represent the sample/cooldown-specific binding between logical
experiment entities and physical wiring/device channels, separately from both
station registry and calibrated parameter values?

## Concept Boundary

The first setup-binding boundary should distinguish:

| Concept | Meaning In This Plan |
| --- | --- |
| Station registry | Relatively stable station/lab configuration: devices, instruments, connections, drivers, timing, and data/session fields. |
| Setup-binding snapshot | Sample/cooldown/session-specific mapping from logical entities to physical resources, generated views, and selected registry context. |
| Parameter state | Calibrated or seed values for qubits, couplers, lines, readout, and related entries. |
| Measurement reference | Run-start selection of parameter state, setup-binding snapshot, logical targets, and derived readout timing. |
| Hardware control | Runner/server behavior that turns registry and binding context into instrument commands. |
| Transformation provenance | User/project code identity or source artifact reference for generated binding/runtime views; recorded as provenance, not executed or validated. |

Setup binding may reference registry and parameter-state identifiers, but it
should not own registry connection payloads, calibrated parameter values, or
hardware-control execution.

## First Fixture Shape

The first fixture should stay small:

- one station registry summary with redacted connection identity;
- one setup-binding snapshot for one sample/cooldown;
- one logical qubit, one coupler, and one readout line;
- a mapping from logical roles to physical resource labels, such as drive line,
  Z line, readout ADC, readout DAC, and LO group;
- one generated line/readout view enough to show runtime binding pressure;
- generator/converter provenance as a label or source reference only;
- one prior binding snapshot with a simple changed assignment;
- one measurement referencing both the selected parameter state and selected
  setup-binding snapshot at start;
- one attention item that says binding changed since an earlier calibration,
  without claiming parameter invalidity.

## Input Boundary

Fixture input may include:

- station registry summary ID and public-safe resource labels;
- setup-binding snapshot ID, source, sample/cooldown/session label, and
  selected registry reference;
- generator or converter provenance for declared/generated binding artifacts;
- logical entity bindings for qubit, coupler, and readout roles;
- generated line/readout labels or readout-position hints;
- simple binding diff entries;
- measurement reference to selected setup binding and selected parameter state.

Fixture input should not include:

- raw hostnames, IP addresses, driver credentials, or private paths;
- full station registry payloads;
- full wiring workbook payloads;
- executable transformation code or code-derived payloads that require running
  user Python;
- calibrated numeric parameter values;
- hardware commands, waveforms, trigger RAM entries, or driver calls;
- automatic retuning or invalidation decisions.

## Expected Output

Expected review output should let a reviewer answer:

- which station registry was selected;
- which setup-binding snapshot was active;
- which sample/cooldown/session the binding belongs to;
- how logical entities map to physical resource labels;
- which binding assignment changed relative to a prior binding;
- which measurement referenced the binding at start;
- that binding changes may require attention but do not automatically invalidate
  parameter state;
- that hardware control remains out of scope.

## Out Of Scope

This plan does not earn:

- final station registry schema;
- final setup-binding schema;
- physical wiring ontology;
- full wiring workbook importer;
- execution, static analysis, validation, or ownership of user/project
  generator, converter, waveform, or runner code;
- LabRAD, QCoDeS, or hardware-control replacement;
- driver connection management;
- resource arbitration;
- automatic parameter retuning or invalidation;
- selected-reference comparison semantics;
- GUI design;
- shared domain model extraction.

## Current Recommendation

Create one fixture and expected output before writing any implementation
candidate. The first goal is to validate the separation between station
registry, setup binding, parameter state, measurement reference, and hardware
control.
