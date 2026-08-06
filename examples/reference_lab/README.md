# Scopecat Reference Lab

This is the single runnable gallery for Scopecat. A coupled virtual RF source,
DC source, temperature monitor, VNA, quantum drive stack, and quantum readout
stack all belong to one `q0` laboratory project. Every recipe uses the same
daemon, immutable configuration history, instrument inventory, and two
reviewable parameter tables: `qubits` and `readout_resonators`.

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

## Golden path

Run these scripts in order, or execute their `# %%` cells in an editor:

1. `notebooks/10_direct_control.py` reserves the flux source, temperature
   monitor, and VNA together, exercises their live typed clients, and releases
   them without creating an experiment run.
2. `notebooks/20_flux_spectroscopy.py` previews and runs a DC-bias scan, records
   complex S21 traces and temperature, fits the resonator, saves table and
   figure evidence, and creates a candidate update to the
   `readout_resonators` row for `q0`.
3. `notebooks/30_drag_calibration.py` runs the two-dimensional DRAG experiment,
   analyzes it, checks the candidate without changing the default, accepts the
   reviewed `qubits` row update, uses it in a production run, and undoes the
   activation while retaining the audit trail.

```sh
uv run python examples/reference_lab/notebooks/10_direct_control.py
uv run python examples/reference_lab/notebooks/20_flux_spectroscopy.py
uv run python examples/reference_lab/notebooks/30_drag_calibration.py
```

The virtual instrument world is deterministic: enabled flux bias moves the VNA
notch and changes mixing-chamber telemetry. The experiment declarations use
logical resources and interface contracts rather than concrete driver classes,
so the same workflows can be routed to compatible real devices.

## Source map

| Path | Responsibility |
|---|---|
| `config/system-infrastructure.json` | One six-device inventory, routing graph, topology, and quantum target. |
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
