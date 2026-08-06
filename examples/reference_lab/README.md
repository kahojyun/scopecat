# Scopecat Reference Lab

This is the single runnable gallery for Scopecat. A coupled virtual RF source,
DC source, temperature monitor, VNA, event digitizer, quantum drive stack, and
quantum readout stack all belong to one q0/q1 laboratory project. Every recipe
uses the same daemon, immutable configuration history, nine-device inventory,
and two reviewable parameter tables: `qubits` and `readout_resonators`.

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
5. `notebooks/22_multi_entity_routing.py` routes one symbolic thermometer group
   to the q0 and q1 sensors and records entity-aligned results.
6. `notebooks/30_drag_calibration.py` runs the two-dimensional DRAG experiment,
   analyzes it, checks the candidate without changing the default, accepts the
   reviewed `qubits` row update, uses it in a production run, and undoes the
   activation while retaining the audit trail.
7. `notebooks/31_adaptive_tuneup.py` runs a bounded tune-up, rediscovers its
   durable lineage, and resumes it to a measurement-dependent stop condition.
8. `notebooks/32_quantum_program_inspection.py` displays typed ports and the
   authored sequence/repeat/parallel structure without touching hardware.
9. `notebooks/40_measurement_workbench.py` demonstrates selection, filtering,
   grouping, Xarray grid restoration, Arrow export, and paged reads.
10. `notebooks/50_ragged_and_partial_data.py` records variable-length and
   unavailable arrays, slices available ragged data, and inspects the committed
   prefix of a deterministically failed run.

```sh
uv run python examples/reference_lab/notebooks/00_lab_tour.py
uv run python examples/reference_lab/notebooks/10_direct_control.py
uv run python examples/reference_lab/notebooks/20_flux_spectroscopy.py
uv run python examples/reference_lab/notebooks/21_scan_shapes.py
uv run python examples/reference_lab/notebooks/22_multi_entity_routing.py
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
| `config/system-infrastructure.json` | One nine-device inventory, routing graph, topology, and quantum target. |
| `src/reference_lab/parameters.py` | The `qubits` and `readout_resonators` schemas and bootstrap rows. |
| `src/reference_lab/provider.py` | Combined deterministic instrument provider and flux abort policy. |
| `src/reference_lab/workflows/` | Copyable experiment, analysis, and production workflows. |
| `notebooks/` | User-facing gallery recipes. |
| `tests/` | Real daemon, worker, storage, analysis, and configuration checks for the gallery. |

Configuration changes publish immutable revisions. Instrument connection and
startup state remain system configuration; reviewed scientific calibration
values live in the parameter tables; temporary scan axes remain invocation
inputs.

## Checks

```sh
uv run pytest examples/reference_lab/tests
uv run ruff check examples/reference_lab
uv run basedpyright examples/reference_lab
```
