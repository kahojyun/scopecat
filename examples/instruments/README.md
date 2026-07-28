# Scopecat Virtual Instrument Lab

This project is a hardware-free tour of both direct instrument control and a
complete measurement workflow. Its RF source, DC source, temperature monitor,
and VNA use the same interface contracts as the first-party real drivers. They
share one deterministic virtual world, so enabled bias and RF power affect
temperature and the VNA response.

## Start the GUI

Build the workspace UI once, then start this project:

```sh
cd apps/scopecat-ui
pnpm install --frozen-lockfile
pnpm run build
cd ../..
uv run scopecat start examples/instruments --static-dir apps/scopecat-ui/dist
uv run scopecat open examples/instruments
```

Open **Instruments**, choose a device, and explicitly connect it. Changes stay
staged until **Apply staged** is selected. The daemon owns the exclusive
session until disconnect. A later GUI client can disconnect a session left by
a closed browser.

## Try the notebook API

With the daemon still running:

```sh
uv run python examples/instruments/notebooks/01_direct_control.py
```

The script reserves three devices together, enables a virtual flux bias, reads
the resulting mixing-chamber telemetry, collects a complex VNA trace, and then
disables the bias output. It does not create an experiment run: direct
interaction is an independent daemon-owned workflow.

## Run resonator flux spectroscopy

The second notebook uses the normal experiment API:

```sh
uv run python examples/instruments/notebooks/02_flux_spectroscopy.py
```

It calls `lab.prepare(flux_spectroscopy_template()).run()`, scans eleven DC-bias
points, and stores a VNA frequency axis, complex S21 trace, and mixing-chamber
temperature at every point. Its analysis extracts the resonance frequency and
loaded linewidth, saves fit tables and a flux-map figure descriptor, and
creates a reviewable configuration proposal for
`readout_resonance_frequency` and `readout_resonator_linewidth`. The notebook
does not accept that proposal automatically.

The experiment declares only the logical resources `flux-source`,
`mixing-chamber`, and `readout-vna` plus their interfaces. It has no driver or
vendor imports, so the same experiment can be routed to compatible real
instruments. The intended path explicitly disables the flux output after each
acquisition. The demo provider also enforces bias-off during abort, which covers
an acquisition failure before the final experiment effect runs.

Run the example-level checks with:

```sh
uv run pytest examples/instruments/tests
uv run ruff check examples/instruments
uv run basedpyright examples/instruments
```

Connection edits in the GUI publish a new immutable configuration revision.
The four defaults use `virtual` connections; change one to a supported real
driver and `tcpip_socket` address only when the corresponding hardware is safe
to operate.
