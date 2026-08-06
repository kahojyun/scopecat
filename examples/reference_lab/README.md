# Scopecat Reference Lab

This is the single runnable gallery for Scopecat. A coupled virtual RF source,
DC sources, temperature monitor, VNA, event digitizer, quantum drive stack, and
quantum readout stack all belong to one four-qubit laboratory project. Every recipe
uses the same daemon, immutable configuration history, nine-device inventory,
and three reviewable parameter tables: `qubits`, `readout_resonators`, and
`channel_calibrations`.

## Start the lab

From the repository root, build the source-checkout UI once and start the
project:

```sh
cd apps/scopecat-ui
pnpm install --frozen-lockfile
pnpm run build
cd ../..
uv run scopecat config check examples/reference_lab
uv run scopecat start examples/reference_lab --static-dir apps/scopecat-ui/dist
uv run scopecat open examples/reference_lab
```

The daemon chooses a loopback port and records it inside the project. Every
notebook discovers that same daemon automatically.

## Gallery path

Run these scripts in order, or execute their `# %%` cells in an editor:

1. `notebooks/00_lab_tour.py` inspects the shared inventory and parameter rows.
2. `notebooks/10_direct_control.py` reserves the flux source, temperature
   monitor, and VNA together, exercises their live typed clients, and releases
   them without creating an experiment run.
3. `notebooks/20_flux_spectroscopy.py` previews and runs a DC-bias scan, records
   complex S21 traces and temperature, fits the resonator, saves table and
   figure evidence, and creates a candidate update to the
   `readout_resonators` row for `q0`.
4. `notebooks/21_scan_shapes.py` runs an ordered point cloud with duplicate
   points and a repeated two-dimensional snake-traversed grid.
5. `notebooks/22_channel_map.py` shows four drive/demod routes, shared readout,
   and four flux routes spread across two two-channel devices.
6. `notebooks/23_q0_ramsey.py` introduces one Ramsey delay scan on q0.
7. `notebooks/24_flux_ramsey.py` composes q0 flux bias and Ramsey delay into one
   two-dimensional experiment.
8. `notebooks/25_entity_routed_ramsey.py` reuses the Ramsey workflow while
   point-locally switching between the q0 and q1 channel sets.
9. `notebooks/26_parallel_multiplexed_ramsey.py` runs independent q0/q1 drive
   channels concurrently, sums their shared readout waveform, and collects two
   demodulation channels.
10. `notebooks/27_channel_timing_candidate.py` proposes a reviewed q1 timing
    update and checks it with a pinned candidate config.
11. `notebooks/28_channel_conflict_diagnostic.py` shows the precise diagnostic
    for overlapping work on the q0 drive route.
12. `notebooks/29_channel_unavailable.py` keeps q0 IQ data available when the
    q1 demodulation channel reports a structured missing result.
13. `notebooks/30_multichannel_dc_bias.py` joins a named logical bias profile
    to per-qubit gain/polarity/offset calibration, applies the four resulting
    voltages through two physical DC sources, parks them, and disables every
    routed output.
14. `notebooks/30_drag_calibration.py` runs the two-dimensional DRAG experiment,
   analyzes it, checks the candidate without changing the default, accepts the
   reviewed `qubits` row update, uses it in a production run, and undoes the
   activation while retaining the audit trail.
15. `notebooks/31_adaptive_tuneup.py` runs a bounded tune-up, rediscovers its
   durable lineage, and resumes it to a measurement-dependent stop condition.
16. `notebooks/32_quantum_program_inspection.py` displays typed ports and the
   authored sequence/repeat/parallel structure without touching hardware.
17. `notebooks/40_measurement_workbench.py` demonstrates selection, filtering,
   grouping, Xarray grid restoration, Arrow export, and paged reads.
18. `notebooks/50_ragged_and_partial_data.py` records variable-length and
   unavailable arrays, slices available ragged data, and inspects the committed
   prefix of a deterministically failed run.

```sh
uv run python examples/reference_lab/notebooks/00_lab_tour.py
uv run python examples/reference_lab/notebooks/10_direct_control.py
uv run python examples/reference_lab/notebooks/20_flux_spectroscopy.py
uv run python examples/reference_lab/notebooks/21_scan_shapes.py
uv run python examples/reference_lab/notebooks/22_channel_map.py
uv run python examples/reference_lab/notebooks/23_q0_ramsey.py
uv run python examples/reference_lab/notebooks/24_flux_ramsey.py
uv run python examples/reference_lab/notebooks/25_entity_routed_ramsey.py
uv run python examples/reference_lab/notebooks/26_parallel_multiplexed_ramsey.py
uv run python examples/reference_lab/notebooks/27_channel_timing_candidate.py
uv run python examples/reference_lab/notebooks/28_channel_conflict_diagnostic.py
uv run python examples/reference_lab/notebooks/29_channel_unavailable.py
uv run python examples/reference_lab/notebooks/30_multichannel_dc_bias.py
uv run python examples/reference_lab/notebooks/30_drag_calibration.py
uv run python examples/reference_lab/notebooks/31_adaptive_tuneup.py
uv run python examples/reference_lab/notebooks/32_quantum_program_inspection.py
uv run python examples/reference_lab/notebooks/40_measurement_workbench.py
uv run python examples/reference_lab/notebooks/50_ragged_and_partial_data.py
```

The virtual instrument world is deterministic: enabled flux bias moves the VNA
notch and changes mixing-chamber telemetry. The experiment declarations use
logical resources and interface contracts rather than concrete driver classes,
so the same workflows can be routed to compatible real devices.

## Source map

| Path | Responsibility |
|---|---|
| `config/system-infrastructure.json` | One nine-device inventory, four-qubit quantum routes, and two two-channel DC sources. |
| `src/reference_lab/parameters.py` | Four shared calibration/profile schemas with four-qubit bootstrap rows; physical channel IDs are not duplicated here. |
| `src/reference_lab/provider.py` | Combined deterministic instrument provider, coherent two-channel bias ramps/readback, and flux abort policy. |
| `src/reference_lab/workflows/` | Copyable experiment, analysis, and production workflows. |
| `notebooks/` | User-facing gallery recipes. |
| `tests/` | Real daemon, worker, storage, analysis, and configuration checks for the gallery. |

Configuration changes publish immutable revisions. Instrument connection and
startup state remain system configuration; reviewed scientific calibration
values live in the parameter tables; temporary scan axes remain invocation
inputs.

The flux routes describe active DC source channels only. A passive bias tee is
part of the lab wiring assumption, not an instrument interface or config
record. Fast-flux pulses remain quantum signals on the routed pulse target;
they are not exposed as a DC-instrument capability.

The reference DACs additionally expose optional `scopecat.dc_bias/v1`: each
named profile transition becomes one scoped driver patch per physical DAC, and
the gallery records actual voltage plus settled status for every qubit. This is
slow bias control, not a fast-flux waveform interface. Hardware list memory and
external-trigger sequencing are intentionally not modeled until a concrete
driver and gallery workflow consume them; `ramp_duration` covers the present
park/operate/park UX without inventing a trigger abstraction.

Each physical DAC keeps one exclusivity key. Channel-level concurrent ownership
would conflict with shared device connection, trigger, and list-memory state, so
the current lab claims the whole device while still batching its routed channels.

## Checks

```sh
uv run pytest examples/reference_lab/tests
uv run ruff check examples/reference_lab
uv run basedpyright examples/reference_lab
```
