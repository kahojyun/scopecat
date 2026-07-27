# Instrument Control

Scopecat treats direct instrument interaction as a first-class lab activity,
not as an experiment with one point. The GUI and notebook API use renewable
sessions owned by the lab daemon, while experiments and interactive sessions
compete for the same exclusive instrument leases.

The design borrows Labber's useful separation between a background Instrument
Server, manual instrument controls, and measurement tooling. It does not adopt
a flat, vendor-shaped quantity tree as Scopecat's experiment model. Logical
resource ports and capabilities remain the experiment-facing contract.

## Four distinct layers

```mermaid
flowchart LR
    C["InstrumentSpec<br/>immutable connection config"]
    D["InstrumentDescription<br/>capabilities, fields, products"]
    S["InstrumentSession<br/>live daemon driver + lease"]
    R["ResourcePort<br/>logical experiment requirement"]

    C --> D
    C --> S
    D --> S
    R -->|"planning and routing"| C
```

`InstrumentSpec` answers what physical device is configured and how a provider
can reach it. It contains a stable instance id, a model/category hint,
`driver_id`, and a typed connection. It is versioned with the complete
`ConfigProfileSnapshot`; editing a connection publishes a new immutable config
entry instead of mutating a live run's inputs.

`InstrumentDescription` is the pure driver contract used without opening
hardware. It declares vendor-neutral capabilities, state fields, field access,
types, units, labels, descriptions, and collectable products. Both GUI controls
and experiment validation are derived from it.

`InstrumentSession` is temporary live authority. The daemon pins the active
config revision, exclusively leases all requested instruments, provisions the
drivers, and returns a fencing token with a TTL. A heartbeat renews the lease.
A clean close releases it. A missed heartbeat expires the live authority,
aborts and closes the daemon drivers, and retains the resources in
`attention_required` until an operator confirms the hardware state. A write or
acquisition with an ambiguous outcome follows the same reconciliation path.

`ResourcePort` remains a logical experiment requirement such as RF output or
network sweep. Planning routes it to a physical instrument. Experiment
definitions therefore do not depend on addresses, vendors, or GUI concepts.

## Connection configuration

The core configuration schema distinguishes:

- `virtual`: an in-process simulated device selected by `driver_id`;
- `tcpip_socket`: host, port, and timeout for line-oriented SCPI;
- `visa`: VISA resource, optional backend, and timeout;
- `serial`: port, baud rate, and timeout.

Every connection also has an opaque `credential_ref` and driver-specific
`options`. Credentials themselves never belong in a config snapshot or GUI
form. The first-party driver package initially provides virtual devices and raw
TCP SCPI. VISA and serial are typed configuration contracts for providers that
add those transports.

Example:

```json
{
  "id": "readout-vna",
  "kind": "vna",
  "driver_id": "scopecat.keysight.e5080b",
  "connection": {
    "kind": "tcpip_socket",
    "host": "192.0.2.20",
    "port": 5025,
    "timeout_seconds": 10,
    "credential_ref": null,
    "options": {}
  }
}
```

The GUI's connection editor follows the same immutable workflow as other
configuration: load the active complete snapshot, edit the selected
instrument, review, publish a new entry, and activate it. Editing is disabled
while the instrument is leased. A “Test connection” action, when added, should
open and immediately close a normal session so it exercises identity checks,
leases, and auditing rather than creating a second connection path.

## Instruments workspace

Instruments are a top-level workspace beside Runs and Configuration. The list
shows:

- friendly label, stable id, driver, and non-secret connection summary;
- availability: `available`, `active`, `quarantined`, or `unavailable`;
- current owner kind, actor or run id, and lease expiry;
- provider or configuration problems.

Opening an instrument does not connect automatically. The operator explicitly
selects **Connect**, after which the detail view:

1. reads a fresh state snapshot;
2. renders capability groups and field controls from
   `InstrumentDescription`;
3. disables `read_only` fields and never tries to read `write_only` values;
4. stages edits locally, showing current and proposed values separately;
5. submits all staged fields in one **Apply** operation;
6. offers **Collect** only for declared products and previews returned values
   or arrays;
7. maintains a heartbeat and closes the session on explicit disconnect or
   workspace teardown.

This is intentionally not a raw SCPI terminal. Driver capabilities preserve
units and validation, make changes auditable, and keep the same semantics in
GUI, notebooks, and experiments. A diagnostic command console can be designed
later as a separately permissioned expert tool.

Output enable, source level, heater control, and similar consequential fields
must never be “apply on change”. Staging makes a multi-field transition
intentional and lets a driver order dependent device commands safely. The
initial Lake Shore driver is read-only because generic heater controls need
additional lab-specific safety policy.

## Notebook API

The normal project connection exposes the same daemon-owned path:

```python
import scopecat as sc

with sc.open_project(".").connect(operator="alice") as lab:
    for item in lab.instruments.list().items:
        print(item.spec.id, item.availability, item.owner_actor)

    with lab.instruments.open("readout-vna") as vna:
        print(vna.describe())
        print(vna.read_state())

        receipt = vna.apply(
            "network_sweep",
            start_frequency=sc.Quantity(4.8, "GHz"),
            stop_frequency=sc.Quantity(5.2, "GHz"),
            points=401,
        )
        trace = vna.collect(
            "network_sweep",
            "frequency",
            "s_parameter",
        )
```

Values with physical units may be passed as Scopecat `Quantity` values. Plain
numbers remain valid only where the declared field type accepts them. A
multi-instrument session is available when an operation must reserve a coherent
set:

```python
with lab.instruments.open("flux-source", "readout-vna") as session:
    session.apply(
        "dc_output",
        {
            "voltage_level": sc.Quantity(0.05, "V"),
            "output_enabled": True,
        },
        instrument_id="flux-source",
    )
    trace = session.collect(
        "network_sweep",
        "s_parameter",
        instrument_id="readout-vna",
    )
```

The handle is synchronous to match the existing notebook API. It generates a
new operation id for every apply or collect unless the caller supplies one,
heartbeats in the background, and closes or aborts through the daemon when
leaving the context. If an HTTP response is lost, retry with the same
`operation_id`: the daemon returns the recorded receipt instead of touching the
device again. The daemon client automatically retries one transport failure
with the same complete command; callers can supply an id when they need to
continue that retry explicitly. Open and end operations retain their retry ids
on the handle, and the GUI does the same while a mutation is unresolved.

## Concurrency and failure semantics

Runs and direct sessions lease the same resource key, so an instrument cannot
be manually adjusted while an experiment owns it. Multi-instrument acquisition
is all-or-nothing. The daemon acquires the durable lease before contacting
hardware.

Reads are observational: a failed read reports an error but does not by itself
claim the physical state changed. Apply and collect are consequential:

- `applied` or `collected` means the driver confirmed the outcome;
- `not_applied` or `not_collected` proves it did not happen;
- `unknown` means the command may have reached the instrument.

The last case aborts and closes the live drivers, retains quarantined resource
leases, and requires operator resolution. Automatic retry would be unsafe.
Operation ids provide session-local de-duplication, and durable started/finished
events provide an audit trail around consequential calls.
Successful close/abort receipts are currently replayable for the lifetime of
the daemon process; making that small terminal-receipt ledger durable and
bounded is a later control-plane refinement.

The daemon is already the sole live driver host for interactive sessions.
Experiment execution still constructs its provider in the notebook process in
the current migration stage, but shared durable leases prevent simultaneous
access. The target architecture moves experiment driver calls behind the same
daemon session boundary, eliminating the remaining second driver-host path
without changing the capability or resource models.

## Initial superconducting-lab driver set

The first package deliberately implements narrow, documented subsets:

| Device | Capability | Initial boundary |
|---|---|---|
| Yokogawa GS200/GS210 | `dc_output` | source mode, range, level, protection, output, optional `/MON` reading |
| R&S SGS100A | `rf_output` | CW frequency, power, RF output, internal/external reference |
| Lake Shore 372 | `temperature_readout` | read-only scan channel, temperature, resistance, status, and sample-heater telemetry |
| Keysight E5080B | `network_sweep` | one linear two-port S-parameter sweep and complex trace |

These subsets follow the vendors' public programming documentation:

- [Yokogawa GS200/GS210 User's Manual](https://cdn.tmi.yokogawa.com/1/6218/files/IMGS210-01EN.pdf)
- [Rohde & Schwarz SGS100A User Manual](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/pdm/cl_manuals/user_manual/1173_9105_01/SGS100A_UserManual_en_13.pdf)
- [Lake Shore Model 372 User's Manual](https://www.lakeshore.com/docs/default-source/product-downloads/manuals/372_manual.pdf)
- [Keysight E5080B Programming Guide](https://helpfiles.keysight.com/csg/e5080b/Programming/Programming_Guide.htm)

Arbitrary waveform generators and oscilloscopes are the next useful pair, but
their waveform payload, memory ownership, trigger, acquisition, and array
contracts should be designed together rather than exposed as an unstructured
SCPI escape hatch.

## Virtual lab

Virtual instruments implement the same descriptions and receipts as real
drivers. They share one deterministic `VirtualLabWorld`: changing an enabled DC
source shifts the virtual resonance and adds heating; enabled RF power also
adds heating; the temperature monitor observes the resulting temperature; VNA
linewidth, depth, and trace noise respond to that world.

This coupling matters. Independent mocks can demonstrate buttons, but a shared
world lets a user learn the real workflow—connect, bias, observe temperature,
collect a trace, and see cause and effect—without hardware. A fixed seed keeps
tests reproducible while still producing realistic complex traces.
