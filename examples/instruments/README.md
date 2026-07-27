# Scopecat Virtual Instrument Lab

This project is a hardware-free tour of direct instrument control. Its RF
source, DC source, temperature monitor, and VNA use the same capability
contracts as the first-party real drivers. They share one deterministic virtual
world, so enabled bias and RF power affect temperature and the VNA response.

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
staged until **Apply staged** is selected. A session owns an exclusive lease
until disconnect or lease expiry.

## Try the notebook API

With the daemon still running:

```sh
uv run python examples/instruments/notebooks/01_direct_control.py
```

The script reserves three devices together, enables a virtual flux bias, reads
the resulting mixing-chamber telemetry, collects a complex VNA trace, and then
disables the bias output. It does not create an experiment run: direct
interaction is an independent daemon-owned workflow.

Connection edits in the GUI publish a new immutable configuration revision.
The four defaults use `virtual` connections; change one to a supported real
driver and `tcpip_socket` address only when the corresponding hardware is safe
to operate.
