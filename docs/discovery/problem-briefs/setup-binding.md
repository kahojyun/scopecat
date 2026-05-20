# Setup Binding

## Status

Evidence-backed problem brief.

## User-Facing Failure

Experiment records can say which measurement ran and which parameter state was
selected, but still leave unclear how logical experiment entities were bound to
physical wiring, channels, instruments, readout groups, and generated runtime
line/readout state.

This matters when a user wants to understand whether a measurement used the
same physical setup as another run, whether a wiring or channel change may
require parameter retuning, or which setup context should be reused without
re-entering wiring details.

Setup binding is not the same as station registry, parameter state, or hardware
control. It is the sample/cooldown/session-specific middle layer that connects
logical entities such as qubits, couplers, readout lines, and line names to the
physical station resources they use.

## Observed Sample Evidence

Compact source notes live under `<sample>/_research/`:

- `setup-binding-registry-station-config.md`;
- `setup-binding-sample-cooldown-mapping.md`;
- `setup-binding-measurement-usage.md`.

Observed evidence includes:

- active full-station registries with `Device`, `Instrument`, `connection`,
  `master_name`, `period`, and path/session fields;
- subset, dated, and named `registry*.json` variants that look like
  sample/cooldown or setup-specific binding choices rather than one global
  station truth;
- wiring workbooks and older `_wiring.json` files that map physical boxes,
  PCIE boards, DAC/ADC channels, microwave sources, ports, and logical chip
  entities;
- registry generation code that converts wiring tables into registry
  `Device`/`Instrument`/`connection` records;
- project-authored generation and conversion code that encodes lab-specific
  wiring conventions rather than universal wiring inference;
- runtime config code that maps logical qubit groups to drive/readout LO
  groups;
- generated `chip_info` and `line_info` files that bridge parameter state into
  runtime line/chip views;
- measurement code that selects `setting_path`, `data_path`, copied registry
  context, parameter snapshots, logical `qidxs`, generated readout positions,
  and IQ dictionaries at run start;
- runner/server code that consumes registry and derived line/readout state to
  drive instruments, which is hardware-control implementation rather than the
  first setup-binding record boundary.

## Project-Owner Clarification

- Device registry should be separate from parameter state and closer to
  station or lab configuration.
- Setup binding should also be separate from parameter state because it
  concerns physical wiring/channel/device relationships, not calibrated values.
- Setup binding likely needs snapshots so measurements can reference the
  binding in effect at run start.
- Setup binding likely needs simple diffs so users can compare binding schemes
  and switch between them without re-entering wiring details.
- Binding changes may require attention because they can imply parameter
  retuning, but they do not automatically invalidate parameter state.
- Whether a binding change affects parameter validity should be judged by
  later sample/code evidence and domain review, not assumed by this brief.
- For the first setup-binding slice, user/project transformation code should be
  treated as black-box provenance. Scopecat records declared or generated
  binding artifacts and references; it does not execute, inspect, or validate
  the transformation logic.

## Derived Hypotheses

- A first setup-binding fixture should test whether Scopecat can represent a
  sample/cooldown binding snapshot separately from station registry and
  parameter state.
- Setup binding starts after user/project code has produced a binding artifact
  or declared binding record. Generator/converter identity can be recorded as
  provenance, but the render pipeline remains out of scope.
- A measurement may need to reference both a selected parameter state and a
  selected setup-binding snapshot.
- A setup-binding diff can be useful without becoming a full wiring model,
  station registry schema, or hardware-control model.
- Setup binding may later help selected reference comparison by making setup
  sameness, changed bindings, unverified bindings, and not-compared bindings
  explicit.

## Out Of Scope For This Brief

- Final station registry schema.
- Full LabRAD, QCoDeS, or hardware-control replacement.
- Driver connection management, server lifecycle, resource arbitration, or
  instrument execution.
- Full wiring workbook importer.
- Execution, static analysis, validation, or ownership of project-authored
  wiring generators, registry generators, parameter-to-runtime converters, or
  waveform builders.
- Final setup-binding schema, physical wiring ontology, or channel model.
- Automatic parameter invalidation after binding changes.
- GUI design for switching bindings.
- Scientific comparability claims.

## Possible Validation Questions

- Can a small fixture distinguish station registry, setup-binding snapshot,
  parameter state, and measurement reference without merging them?
- Can a measurement reference the setup-binding snapshot in effect at start
  without claiming current hardware state?
- Can a setup-binding diff show changed logical-to-physical assignments without
  deciding whether parameter state is invalid?
- Can setup binding carry enough labels and roles to support future selected
  reference comparison?
