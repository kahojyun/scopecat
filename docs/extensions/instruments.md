# Extend instruments

The `scopecat-instruments` package demonstrates the supported provider pattern:
interface declarations define typed capabilities, generated live and symbolic
clients expose them to notebooks and experiments, and drivers implement the
capability without receiving run or dataset concepts.

An interface author declares portable members directly on a Python `Protocol`
or abstract base class. A distinct acquisition names an explicit result schema:

```python
from typing import Protocol

from scopecat import Quantity
from scopecat.sdk.instruments import Member
from scopecat.sdk.instruments.declarations import (
    acquisition,
    array_result,
    axis,
    instrument_interface,
    member,
    result_schema,
)


@result_schema
class NetworkSweepResults:
    frequency = array_result(
        dtype="float64", role="coordinate", unit="Hz", axes=("frequency",)
    )
    s_parameter = array_result(dtype="complex128", unit="ratio", axes=("frequency",))


@instrument_interface("example.network_sweep/v1")
class NetworkSweep(Protocol):
    start_frequency: Member[Quantity] = member(
        access="read_write", restore=True, unit="Hz"
    )
    stop_frequency: Member[Quantity] = member(
        access="read_write", restore=True, unit="Hz"
    )
    points: Member[int] = member(access="read_write", restore=True, minimum=2)
    s_parameter: Member[str] = member(access="read_write", restore=True)

    @acquisition(
        results=NetworkSweepResults,
        axes={"frequency": axis(size=points, unit="Hz")},
    )
    def sweep(self) -> None: ...
```

Members are independently queryable and cacheable state facts. Generated sparse
patch and target carriers represent omission. `scalar_result(...)` and
`array_result(...)` explicitly own measurement dtype, role, unit, and axes;
the schema class is a declaration namespace rather than a runtime value carrier.
Generation produces the wire contract, typed clients, member references, state
projections, and measurement-valued driver observation carriers.

An acknowledged setting that the device cannot query is the narrow exception:
declare it with `write_only_member(...)`. It remains an independently
addressed sparse state command, but it cannot participate in observation,
baseline capture, or restoration. This is more honest than claiming a richer
read/write interface or fabricating cached readback.

A driver subclasses `ObjectInstrumentDriver` and binds typed methods to member
declarations with `@read`, `@write`, `@query`, or `@update`. The base class
handles dispatch and wire conversion; the driver owns command ordering, device
limits, temporary setup and restoration, and response interpretation. A true
operation or acquisition is attached to its interface declaration with
`@implements(...)`; acquisition methods return their generated class from
`scopecat_instruments.driver_observations`. Class creation rejects missing,
duplicate, or signature-incompatible behavior bindings.

When requested results affect hardware setup, override
`prepare_acquisitions(plan: DriverAcquisitionPlan)`. Scopecat calls this hook
before each hardware batch, and every `DriverAcquisition` exposes its selected
`results`. The driver can therefore enable raw retention, choose a capture
mode, or allocate buffers only when the experiment requests the corresponding
result. Aggregate demand across every acquisition sharing a physical resource
in the plan—for example, raw retention remains enabled if any acquisition on a
channel requests raw samples. `collect(...)` must return only the selected
results; preparation is batch-scoped and must not depend on the order of later
collection calls. Drivers that need no demand-dependent setup inherit the
no-op implementation.

When the values to record are already members, declare an `observation(...)`
on those members instead of repeating their schema. The framework performs a
fresh coherent state read and records it as acquisition
products. Reserve `@acquisition` for a distinct measurement procedure, arrays,
or acquisition-specific failure and evidence.

Model-specific background state belongs on the concrete driver as a
`device_member(...)`; it can be captured or restored without inventing a
single-device portable interface. A reader may return `observed(value,
source="configured_fixed")` or `source="derived"` to retain how that member was
known; plain values mean a hardware query. Keep such provenance on the member
it describes instead of duplicating it in every other observation. An operation
that disturbs persistent state lists the affected members in `invalidates`; a
later `ensure` establishes a new guarantee.

Concrete models may narrow a portable member's numeric range or string choices
with `member_constraint(...)`. This is an endpoint refinement, not a new
interface declaration. Relational constraints such as “remote sense requires a
voltage range of at least 1 V” remain explicit driver behavior because they
depend on several independently queryable members.

Configured providers distinguish physical connection from device protocol.
`tcpip_socket` supplies a line-oriented SCPI transport; `serial` supplies a
binary transport with explicit framing. `driver_managed` delegates construction
to a lazy factory only when a vendor SDK or composite controller owns multiple
physical resources: its `describe` path is side-effect-free, while `connect`
owns probing, partial-failure cleanup, and the returned driver's disconnect
lifecycle. Drivers use `send` when the protocol has no acknowledgement and
exact-size `exchange` when it does. A transport registration also chooses
identity or connection-only probing. Transport failures retire that generation:
never retry an unconfirmed write in a driver, because the command may already
have reached hardware.

Use the package's source-adjacent guides for the exact extension workflow:

- [driver authoring](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-instruments/README.md#driver-authoring)
- [typed client source generation](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-instruments/README.md#typed-client-source-generation)
- [configuration](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-instruments/README.md#configuration)
- [testing](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-instruments/README.md#testing)

The [instrument control guide](../how-to/control-instruments.md) shows the
resulting live and symbolic user experience. Keep driver-specific command and
transport details beside their code; only cross-cutting user concepts belong in
the main documentation site.
