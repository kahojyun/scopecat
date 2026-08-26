# Tour the reference lab

The reference lab is Scopecat's runnable gallery: a deterministic four-qubit
project with virtual RF and DC sources, temperature monitor, VNA, shared LOs,
AWGs, digitizer, timing controller, and oscilloscope.

Complete the [source preview quickstart](../getting-started/quickstart.md) first
so the Python workspace and GUI are ready.

## Start the lab

From the repository root:

```sh
uv run scopecat config check examples/reference_lab
uv run scopecat start examples/reference_lab --static-dir apps/scopecat-ui/dist
uv run scopecat open examples/reference_lab
```

Every gallery script discovers this daemon through the project manifest.

Run the lab tour to establish the shared starting state:

```sh
uv run python examples/reference_lab/notebooks/00_lab_tour.py
```

Its summary should list the configured instruments, their availability, and the
reviewed parameter-table row counts. Users should not need daemon URLs or
database identities to establish this context.

Then run the physical-subject workflow:

```sh
uv run python examples/reference_lab/notebooks/05_sample_workflow.py
```

It registers and revises a stable chip, binds the active revision to a Ramsey
run, and publishes a sample-owned conclusion over that exact run. In the
**Samples** workspace, the run opens the historical revision it actually used,
while the active sample remains independently visible.

## Inspect and control instruments

Open the **Instruments** workspace, then run in another terminal:

```sh
uv run python examples/reference_lab/notebooks/10_direct_control.py
```

The script reserves typed virtual devices and changes their state outside an
experiment. The virtual world is coupled: enabled flux bias moves the VNA notch
and changes mixing-chamber telemetry. These clients use the same interfaces as
real providers.

Success means the summary contains successful temperature and trace receipts,
and the source output is disabled again even if acquisition fails. The GUI may
change, but it must make instrument availability and session failure attributable
to the affected device.

## Complete a calibration

Run the supported DRAG-beta workflow:

```sh
uv run python examples/reference_lab/notebooks/30_drag_calibration.py
```

In the project console, inspect the new runs, measurement data, analysis, and
configuration history. The workflow records a baseline, publishes a candidate,
runs the same scan with that candidate, and publishes a project-level
baseline/candidate verification. Only a passing verification accepts the
candidate; the workflow then uses the new default in production and demonstrates
undo. Durable revisions and decisions remain visible without exposing storage
identifiers in the ordinary notebook flow.

The structured summary verifies the design outcomes directly:

- the baseline run completes and records the previewed point count;
- analysis publishes outputs, evidence, a report, and one proposal;
- the candidate run identifies the analysis proposal as its config source;
- project analysis freezes both run datasets and records the acceptance metric;
- the production run uses the accepted default;
- undo resolves the previous distinct immutable entry and reactivates it through
  the same idempotent operation ledger without deleting history.

If users must manually transfer revision IDs between these steps, or cannot tell
which configuration a run used, treat that as workflow design feedback rather
than an explanation to add to the tutorial.

## Continue through the gallery

The [complete reference-lab gallery](https://github.com/scopecat-project/scopecat/blob/main/examples/reference_lab/README.md#gallery)
maps each tested script to its intended scenario. Useful next steps include:

- `20_flux_spectroscopy.py` for scan data, fitting, and parameter proposals;
- `21_scan_shapes.py` for point clouds, repeat, and traversal;
- `40_measurement_workbench.py` for selection, Xarray, Arrow, and paged reads;
- `50_ragged_scope_capture.py` for variable-length waveforms.

Stop the lab when finished:

```sh
uv run scopecat stop examples/reference_lab
```
