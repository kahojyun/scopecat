# Scopecat instrument drivers

`scopecat-instruments` contains a small, explicit instrument layer for direct
notebook work and for Scopecat's config-driven runtime. It separates
vendor-neutral capabilities from device-specific SCPI and provides matching
virtual devices for development without lab hardware.

The first version supports only:

- in-process virtual devices (`virtual`);
- newline-terminated SCPI over a raw TCP socket (`tcpip_socket`).

VISA and serial are valid core configuration shapes but are not implemented by
this package. Credential references are likewise not consumed in v1. Do not
configure these features for these drivers yet.

## Stable capabilities

| Capability ID | Purpose |
| --- | --- |
| `rf_output` | CW frequency, power, output, and reference source |
| `dc_output` | Voltage/current source mode, ranges, levels, protection, output, and optional monitor data |
| `temperature_readout` | Read-only temperature, resistance, scanner, and heater telemetry |
| `network_sweep` | Linear single-trigger complex S-parameter sweeps |

Every capability, field, and product includes label, description, and access
metadata suitable for a generated GUI. Drivers validate state commands and
collection requests before touching hardware and return structured receipts.

## Direct notebook use

Experiments are not required. Drivers expose ordinary synchronous Python
methods:

```python
from scopecat_instruments import RohdeSchwarzSGS100A, TcpScpiTransport

transport = TcpScpiTransport("192.0.2.10", 5025, timeout_seconds=5)
source = RohdeSchwarzSGS100A("readout-lo", transport)

try:
    identity = source.identify()  # performs *IDN? and validates SGS100A
    source.set_frequency(6.125e9)
    source.set_power(-25.0)
    source.set_reference_source("external")
    source.set_output(True)
    try:
        print(identity.raw, source.read_state())
    finally:
        source.set_output(False)
finally:
    source.close()  # closes the socket; it does not switch RF off
```

`cleanup()` releases run-scoped activity and deliberately does not change a
real source's output state. `close()` releases the transport. Applications must
make output shutdown an explicit, user-visible action.

For staged GS200 and SGS100A state commands, an explicit
`output_enabled=false` is sent before changing source settings; an explicit
`output_enabled=true` is sent only after all requested settings succeed.

The VNA also has a compact direct API:

```python
from scopecat_instruments import (
    KeysightE5080B,
    LinearSweepSettings,
    TcpScpiTransport,
)

vna = KeysightE5080B("readout-vna", TcpScpiTransport("192.0.2.20", 5025))
try:
    vna.identify()
    vna.configure_linear_sweep(
        LinearSweepSettings(
            start_frequency_hz=5.9e9,
            stop_frequency_hz=6.1e9,
            points=401,
            if_bandwidth_hz=1.0e3,
            source_power_dbm=-35.0,
            s_parameter="S21",
        )
    )
    trace = vna.acquire_trace()
finally:
    vna.close()
```

## Configured provider

`ConfiguredInstrumentProvider` creates only the instruments requested in its
`InstrumentProviderContext`. A real device is not returned ready until the
provider has sent `*IDN?` and validated the manufacturer and model. The raw
identity string is retained in provider metadata and subsequent state metadata.

Virtual configuration:

```json
{
  "id": "flux",
  "kind": "dc_source",
  "driver_id": "scopecat.virtual.dc_source",
  "connection": {
    "kind": "virtual"
  }
}
```

Raw TCP configuration:

```json
{
  "id": "readout-lo",
  "kind": "rf_source",
  "driver_id": "scopecat.rohde_schwarz.sgs100a",
  "connection": {
    "kind": "tcpip_socket",
    "host": "192.0.2.10",
    "port": 5025,
    "timeout_seconds": 5
  }
}
```

Connection `options` are intentionally narrow:

- Yokogawa GS200: `monitor_option` (`bool`, default `false`);
- Keysight E5080B: `channel` and `measurement` (positive integers, default `1`);
- all other v1 drivers: no options.

## Supported real instruments

| Driver ID | Device | Implemented boundary |
| --- | --- | --- |
| `scopecat.yokogawa.gs200` | Yokogawa GS200/GS210 | Voltage/current mode, active range and level, voltage/current protection, output, optional `/MON` scalar readback |
| `scopecat.rohde_schwarz.sgs100a` | R&S SGS100A | CW frequency, power, RF output, internal/external reference source |
| `scopecat.lakeshore.372` | Lake Shore Model 372 | Safe read-only K/R/status, scan state, and sample-heater telemetry |
| `scopecat.keysight.e5080b` | Keysight E5080B | One channel/measurement, linear S11/S21/S12/S22 setup, single trigger with continuous-trigger restoration, ASCII frequency and complex trace |

These are deliberately minimal drivers. They do not expose complete instrument
command sets, calibration workflows, option-dependent applications, arbitrary
binary transfers, or automated safety policy. Before using real hardware,
verify firmware behavior, installed options, limits, cabling, and interlocks for
the specific lab.

The SCPI transcripts are based on the manufacturers' public programming
manuals:

- [Yokogawa GS200/GS210 Communication Interface User's Manual](https://cdn.tmi.yokogawa.com/1/6218/files/IMGS210-01EN.pdf)
- [R&S SGS100A User Manual](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/pdm/cl_manuals/user_manual/1173_9105_01/SGS100A_UserManual_en_13.pdf)
- [Lake Shore Model 372 AC Resistance Bridge and Temperature Controller User's Manual](https://www.lakeshore.com/docs/default-source/product-downloads/manuals/372_manual.pdf)
- [Keysight E5080B help](https://helpfiles.keysight.com/csg/e5080b/Home.htm), including [standard setup commands](https://helpfiles.keysight.com/csg/e5080b/Programming/CF_Setup_Commands_-_Standard.htm), [measurement data](https://helpfiles.keysight.com/csg/e5080b/Programming/GP-IB_Command_Finder/Calculate/MeasureDATA.htm), and [stimulus values](https://helpfiles.keysight.com/csg/e5080b/Programming/GP-IB_Command_Finder/Calculate/MeasureX.htm)

## Virtual lab

The four reusable virtual devices mirror the stable capabilities:

- `scopecat.virtual.rf_source`;
- `scopecat.virtual.dc_source`;
- `scopecat.virtual.temperature_monitor`;
- `scopecat.virtual.vna`.

Drivers backed by the same `VirtualLabWorld` share state across sessions.
Seeding the world makes generated noise repeatable. Enabled DC bias shifts the
VNA notch, while DC/RF heating and the base temperature broaden it and reduce
its depth:

```python
from scopecat_instruments import (
    VirtualDcSource,
    VirtualLabWorld,
    VirtualNetworkAnalyzer,
)

world = VirtualLabWorld(seed=7)
flux = VirtualDcSource("flux", world)
vna = VirtualNetworkAnalyzer("readout", world)

flux.set_voltage_level(0.125)
flux.set_output(True)
biased_trace = vna.acquire_trace()

# A later driver session with the same world sees the same source state.
assert VirtualDcSource("flux", world).output_enabled()
```

## Test transports

`ScriptedTransport` asserts an exact ordered command/response transcript.
`RecordingTransport` records traffic around any `ScpiTransport`. Both are useful
for driver development and notebook demonstrations without a socket.

## Roadmap, not current support

Tektronix AWG70002B waveform generation and MSO64B oscilloscope acquisition are
candidate next drivers. They are not implemented or claimed as supported in
this version.
