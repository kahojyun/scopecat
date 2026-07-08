# Scopecat Experiment Core

Status: active design notes

These notes describe the experiment core currently being designed. They are
not a contract for internal schemas, record names, storage layout, diagnostic
codes, or Python APIs. During the redesign, breaking changes are expected when
they make the model simpler.

## Shape

The structured experiment path is:

```text
ExperimentModule + ExperimentTemplate + RunRequest
  -> ExperimentAssembly
ExperimentAssembly + ConfigProfileSnapshot
  -> ExperimentSpec
  -> PlannerSnapshot          transient planner IR
  -> RuntimeGraph            transient runtime graph
  -> RuntimeExecutor
  -> InstrumentDriver(s)
```

The core idea is to separate authoring intent, operator input, accepted
configuration, planning output, and runtime side effects.

`ExperimentModule` is reusable experiment library code. It should primarily
declare input ports, resource ports, output products, parameter derivations,
state fragments, compute nodes, and product declarations. A module should not
decide whether an input is a coordinate, sweep axis, identity column,
auxiliary column, fixed value, or adaptive decision. Those are entrypoint and
run-level interpretations.

`ExperimentTemplate` is a runnable entrypoint. It exposes inputs and calls
module-level components. It wires module input ports to experiment-level
symbols, declares point sources, assigns coordinate/identity/auxiliary roles,
chooses which module products become experiment records, and provides default
values or default scans. Templates should stay thin enough that repeated logic
can move back into modules.

There is no core `subject` concept. A subject may appear as a domain example
name, but core authoring should use ordinary typed entity inputs such as
`qubit`, `coupler`, `sample`, or `site`; templates and runs decide whether
those entity values are fixed inputs, point coordinates, identity columns, or
output axes.

`RunRequest` is the normalized invocation evidence for one run or segment. It
is produced by template/workspace/run facades from user inputs, sweep options,
tags, description, operator metadata, overrides, seeds, extra records,
execution flags, config source, and segment lineage. Notebook users should not
need to construct it directly. It should not contain materialized point
tables, device routing, dataset layouts, analysis decisions, or runtime order.

`ConfigProfileSnapshot` is the accepted configuration input for planning. It
may include parameter state, topology, routing, environment, and registry
metadata. It is not live device state and should not be mutated by instruments,
analysis, notebooks, or legacy registries during a run.

`ExperimentAssembly` is an internal source-level IR produced by compiling a
template invocation. It keeps module/template fragments and request inputs
together without reading accepted configuration, resolving resources, or
materializing parameter views. It is not run evidence.

`ExperimentSpec` is the closed input for a structured run segment. Reusable
intent lives in modules/templates, normalized operator input lives in
`RunRequest`, and accepted configuration lives in `ConfigProfileSnapshot`. The
spec binds those inputs into a concrete segment before side effects.

`PlannerSnapshot` is the planner output for the current implementation. It may
materialize point rows, point-local patches, desired logical state, output
records, artifact refs, diagnostics, and compiler metadata. It is an
execution-time intermediate, not run evidence. Its shape may change
aggressively while the core settles, and stored runs should not depend on
being able to reload it. It should not expose a stable content hash; content
addressing belongs to durable inputs and evidence, not transient planner IR.

`RuntimeGraph` is the runtime-facing dependency graph. It is built from the
plan, program artifacts, routing, instrument capabilities, and runtime policy.
Its current implementation is still eager, but the graph boundary is the place
where point rows, point-local parameter patches, route bindings, pure compute
nodes, desired-state fields, collect requests, record bindings, payloads, and
diagnostics meet before side effects. Runtime may re-layer, optimize, batch,
stream, or discard it without changing the durable run contract.

## Experiment Model

The working calculation graph is:

```text
point_source / points
  -> params
  -> state
  -> records
  -> outputs
```

`point_source / points` describes the logical point space for a segment.
Small runs may materialize points directly. Larger, streaming, or adaptive
runs may keep a point source description plus an append-only decision log.

`params` are point-local configuration patches derived from point rows, run
overrides, and accepted config. A parameter sweep is syntax for a point column
plus a patch evaluated for each point.

Reusable parameter calculations live on `ExperimentModule` as deterministic
derivation graphs. Resolving a template evaluates the module graph against the
accepted configuration into an in-memory parameter view for authoring and
planning. That view is not a `ConfigProfileSnapshot` field, not a run evidence
record, and not a compatibility surface. Composing modules composes their
derivation graphs in order, with later graph nodes seeing earlier derived
values in memory.

The authoring boundary follows a compile/link split. Compile turns
module/template source plus a facade-generated `RunRequest` into
`ExperimentAssembly` without configuration access. Link takes that assembly
plus `ConfigProfileSnapshot`, resolves symbols such as entities, resources,
capabilities, parameter-derived defaults, and dataset dimensions, then emits
the closed `ExperimentSpec`.

`state` is desired logical instrument state. Controls such
as integration time, readout length, average count, demod frequency, trigger
delay, and backend program selection belong here or in config-derived views,
not in a parallel record-control system.

Pure compute nodes are point-local calculation nodes declared by modules and
lowered by runtime before instrument commands are built. They are suitable for
ordinary user functions that build gate sequences, render waveform bundles, or
perform backend-specific compilation while Scopecat does not yet have a native
quantum IR. Compute nodes may consume point rows, point-local parameter views,
previous compute results, and route bindings. User functions return ordinary
Python objects; runtime wraps each result as a typed in-memory command payload
only when a state binding consumes it. Instrument drivers receive only the
resulting payload references, in-memory payloads needed by the command, and
device-local commands; they do not call user functions or reconstruct
experiment intent. Writing pulse programs or waveform arrays to files is
optional, not part of the core contract. Compute results are transient and do
not carry durable media types or content hashes.

There is no experiment-authoring asset input in the core model. External files,
reports, or backend handles should enter as run evidence or attachments when a
real workflow needs them, not as desired-state inputs. Runtime-generated Python
objects are `CommandPayload`s, produced during lowering and omitted from
persistent experiment specs.

`records` are declarations for values or artifacts the run should produce.
Sources may include instrument products, readbacks, expressions, point
columns, backend-decoded results, and generated artifacts. Module product
ports describe reusable outputs; they become experiment records only when an
entrypoint selects them.

For dense per-point data such as single-shot IQ captures, one logical
experiment point should remain one record. The shot axis belongs to the
observable value shape, for example an array field, not to extra record rows.

`outputs` are persisted measurements, artifacts, events, diagnostics, and
analysis inputs. The storage shape should be chosen by current needs rather
than frozen as a public layout.

## Point Identity

The current design distinguishes three concepts:

```text
point_index       dense logical row index for the segment
point_uid         logical identity derived from identity columns
execution_index   runtime order, retry order, or backend return order
```

`point_uid` should be derived from meaningful identity inputs such as
coordinates, entity refs, logical repeat, seed, and adaptive decision identity.
It should not include randomized execution order, backend batch id, operator
notes, transient runtime state, or local file paths.

Core point-column roles should stay small until repeated workflows prove the
need for stronger vocabulary:

```text
role: coordinate | auxiliary
identity: bool
ref: EntityRef | null
tags: list[str]
```

Concepts such as target, randomization, repeat, carry, and entity type can use
`identity`, `ref`, and tags for now.

## Entities And Topology

Entities are generic domain objects referenced by experiments. Core does not
special-case qubits, channels, resonators, samples, chips, or couplers. An
entity reference carries an id, optional kind, and metadata. An ordered entity
array represents simultaneous operations over multiple entities without
splitting one logical point into multiple records.

Accepted topology contains an explicit entity catalog. Devices, channels, and
links may describe physical or logical topology, but they are not the implicit
source of authoring entities. Link-time resolution validates entity ids against
the catalog and can fill in catalog kind/metadata when source code only names
an id.

Entity sweeps are point sources. For example, sweeping `qubit` over `q0`,
`q1`, and `q2` creates three logical points whose coordinate value is an
entity reference. A simultaneous readout over `[q0, q1, q2]` should normally be
one logical point with an entity-shaped record axis, not three point rows.

Resource ports declare which capabilities and entity inputs they need, but
module source does not name concrete resources. Link preserves symbolic route
intents in `ExperimentSpec`; planning materializes point-local entity values;
`RuntimeGraph` compilation resolves each point through the internal
`RoutingView` over accepted configuration. This keeps modules reusable across
fixed entity inputs, entity sweeps, and entity arrays, and keeps instruments
from knowing experiment coordinates or record names.

The current routing view is graph-first. Accepted config may declare a
`RoutingGraph` of logical resources with capabilities, served entities,
channels, metadata, and explicit edges from resources to served entities or
channels. Resource-level `served_entities` is a shortcut; edge-level channel
bindings are the cleaner shape. `InstrumentRegistry` does not imply routing;
configs must declare routing resources explicitly. The router can resolve
point-local entity sweeps and ordered entity arrays, record the selected
product-axis order in point programs, and attach entity-to-channel bindings
for route-aware compute functions.

Routing declarations should narrow consistently as they move from resource to
edge to binding. If a resource declares served entities, channels, or
capabilities, its edges and bindings must stay within those sets. If an edge
declares entities, channels, or capabilities, its bindings must stay within
those sets. Omitting the broader set leaves it unconstrained; repeating it
turns the value into a validation assertion.

Channel topology is the source of line and shared-group facts. A routing
channel binding may name the selected entity, channel, and capability, but it
should not carry an independent copy of the channel's line or shared groups.
Runtime and preview enrich bindings from accepted channel topology. If a
config still repeats line or group ids on a binding, validation treats those
values as assertions and reports an error when they disagree with the channel.
Shared resource group membership is also a topology assertion: when both a
channel and a group explicitly name each other, they must agree. A group may
name either the concrete channel or the channel's logical line. `Device.channels`
is not the same kind of ownership assertion; domain configs may use it to show
logical device reachability, while `Channel.device_id` can point at the
instrument-side device that owns the physical port. If a channel names both a
line and an instrument-side device, and the line has endpoints, the line should
include that device endpoint so wiring views can explain the route path.

User-facing preview may lower route intents against the accepted config and
show high-level resolved route summaries: point index, port, resource,
ordered entities, product-axis order, and entity-to-channel/line/group
bindings. This is monitor and review information, not a durable runtime IR.
Implementation should keep this boundary explicit: planner/runtime details may
be adapted into an internal preview snapshot, but preview APIs should consume
only high-level summary data. Preview results should not expose `RunRequest`
or resolved authoring objects; they may show template id, materialized inputs,
points, records, state summaries, routes, payload summaries, and diagnostics.

Topology remains domain-neutral, but it now has enough vocabulary for
lab-facing wiring views to compile into core config: entities, devices,
logical lines, physical/logical channels, links, and shared resource groups
such as local oscillators. Domain packages should expose editable terms such
as qubit, coupler, readout line, flux line, and shared LO, then compile them
to core topology and routing channel bindings. The quantum examples follow
that boundary with a local `quantum_wiring()` builder: it validates qubit,
coupler, line, channel, and shared-LO references before producing the
domain-neutral core config. Runtime lowering performs a conservative
route-constraint pass for duplicate route bindings, shared-group resource
conflicts, channels selected by multiple route ports, and conflicting state
field values. A fuller router should add richer simultaneous service policies
beyond "one logical resource serves all entities". The current generic service
policy lives on topology: shared resource groups can declare
`max_resources_per_point`, and channels can declare
`max_route_ports_per_point`. These are point-local routing constraints, not
instrument-driver responsibilities. Background resources that are maintained
while foreground records are acquired and richer domain-specific fan-out/fan-in
rules should build on the same topology-owned policy model.

## Configuration

Accepted configuration, run-time overrides, point-local patches, analysis
outputs, candidate changes, and live device readbacks are different things.

The working model is:

```text
accepted ConfigProfileSnapshot
  + RunRequest overrides
  + point-local ParameterPatch
  -> planning/runtime views
```

The accepted snapshot stores source configuration only. Derived parameter
views are rebuilt when authoring, validating, previewing, or executing the
current experiment, and may be discarded after planning.

Reusable modules can declare background state materialization from parameter
tables. These modules do not produce records; they turn complete, point-local
parameter tables into desired state such as flux bias, readout idle settings,
or shared LO outputs. Planning applies point-local parameter patches first,
refreshes derived parameter views, and only then materializes foreground and
background desired state. Other entities are therefore maintained by explicit
state declarations, not by implicit runtime carry.

Candidate configuration changes come from analysis or adapters:

```text
analysis output
  -> ParameterChangeSet / ConfigPatch
  -> candidate ConfigProfileSnapshot
  -> preview / follow-up run / review
  -> explicit activation
```

Activation creates a new accepted configuration snapshot. Analysis,
instruments, instrument providers, and online decisions should not silently
mutate accepted configuration.

Importers for CSV, XLSX, JSON, registry trees, and private runner inputs are
anti-corruption tools. They should convert external formats into Scopecat
configuration or artifacts without making those external formats core design.

## Runtime

Runtime lowers a plan into a runtime graph and performs side effects. Runtime
owns:

- routing from logical resources to instrument drivers;
- capability checks;
- desired-state diff and patch generation;
- uploads, arms, triggers, barriers, collect commands, readbacks, cleanup, and
  abort;
- retry, resume, failure handling, and backend point mapping.

`PlannerSnapshot` and `RuntimeGraph` are implementation details, not public
runtime models. The cleaner runtime shape is a transient dependency graph plus
an execution cursor:

```text
ExperimentSpec + ConfigProfileSnapshot
  -> RuntimeGraph
  -> ExecutionCursor
  -> RuntimeEvent stream + measurement evidence
```

`RuntimeGraph` should describe point rows, point-local parameter patches,
route bindings, pure compute nodes, desired-state fields, collect requests,
and record bindings as dependency edges. It may be eager for small runs or
lazy/streamed for large, adaptive, or optimized runs. `ExecutionCursor` then
advances points or batches, evaluates only dirty pure compute nodes, diffs
desired state against runtime state cache, sends only changed device fields,
collects readback, and emits records. This lets runtime optimize without
changing authoring, linked specs, or persisted data.

The current implementation has started this split by building an internal
`RuntimeGraph` and running an execution cursor over it. The graph is still
eager, but it is the boundary where later lazy point sources, batching, dirty
compute evaluation, and finer state diffing should land.

Runtime lowering normalizes desired state before drivers see commands. For one
point, repeated declarations of the same concrete resource, capability, field,
and value collapse into one field update. Multiple values for the same
concrete field and channel target produce a blocking diagnostic. Background
state and foreground state use the same desired-state model; any
domain-specific origin label is preview or diagnostic metadata, not driver
semantics. Parameter-table materialization may produce multiple field updates
for one logical instrument field when each update carries a different resolved
channel binding, such as per-coupler parking flux outputs. Preview should
expose high-level normalized state summaries with resource, capability, field,
and route channel context instead of exposing planner/runtime IR.

Runtime optimization should use explicit input versions and dirty dependency
sets, not hashes of transient planner/runtime graphs or large Python payloads.
If a waveform node depends on a changed sweep input, route binding, parameter
row, or upstream compute result, runtime may recompute it and resend the
affected state. The result object is an in-memory command payload; it does not
need a durable media type, content hash, or file path.

Runtime events are transient observability data. They may report run start and
finish, point start, compute boundaries, state patches, collect boundaries,
record emission, progress counts, diagnostics, and compact payload summaries
such as dtype, shape, or preview ranges. GUI monitors can subscribe to these
events and optionally inspect in-memory payloads through monitor hooks.
Events should not expose `PlannerSnapshot` or `RuntimeGraph`, and a complete
event log should not be required to analyze a stored run.

Drivers may receive resolved channel bindings on state and collect commands.
Those bindings are device-local context: entity id, line id, channel id,
capability, and shared groups such as LO groups. They let a driver address the
right hardware channel without learning experiment coordinates, record names,
or dataset layout.

The current event stream emits compact compute-completion summaries for
in-memory command payloads, including Python type names and array-like shape
or dtype metadata where available. Preview and runtime summaries can also
report declared compute dependencies such as point columns, parameter tables,
route ports, and upstream compute nodes. These dependency summaries are
metadata for inspection and future dirty evaluation; they are not yet a cache
or scheduling contract. The current `RuntimeGraph` carries point-local compute
steps with these dependency summaries and deferred payload ids; the execution
cursor evaluates the Python functions for the active point and passes the
resulting in-memory payloads to state commands. This keeps large generated
objects out of the graph while preserving the preview boundary needed for
later dirty evaluation. The cursor now performs a conservative dirty check for
compute nodes and may reuse a previous result when declared point, parameter,
route, and upstream compute dependencies are unchanged. This is an internal
optimization, not a durable scheduling contract.

An `Instrument` is a logical instrument from the user's point of view. It may
wrap one physical device or coordinate multiple physical devices. Runtime code
talks to it through an `InstrumentDriver`.

An `InstrumentDriver` should stay thin. It declares capabilities, executes
device-local commands, and reports readbacks, products, events, and
diagnostics. It does not receive a measurement sink, global record indices,
the full experiment, the config registry, analysis policy, candidate review
policy, or GUI state.

Collect commands are device-facing acquire/readback requests for
instrument-native product ids. The driver SDK model is `CollectCommand`: its
role is collect-time device I/O, not dataset or record declaration. Runtime owns
the mapping from collected product ids to experiment record ids and dataset
schema variables.

There is no core `InstrumentGroup` split for now. A coordinated AWG, ADC, LO,
trigger, clock, or virtual-lab stack is just one logical instrument driver with
a richer connection profile and provider-internal implementation.

## Data And Analysis

Structured runs and legacy capture should both produce inspectable evidence
under a run identity. The exact storage backend is an implementation choice.
JSON, JSONL, Parquet, Arrow, Zarr, HDF5, object storage, or content-addressed
storage can be introduced when they remove real friction.

Useful run evidence includes:

- request, accepted config snapshot, and linked experiment spec;
- events, diagnostics, attachments, and operator context;
- result tables, arrays, readbacks, backend payloads, figures, reports, and
  external files;
- analysis records, candidate config patches, comparisons, and reviews.

Planner and runtime products such as `PlannerSnapshot`, `RuntimeGraph`, route
views, parameter views, state diffs, backend batches, retry queues, live
readback caches, and temporary upload
handles are optimization surfaces. User preview APIs should expose high-level
summaries derived from those products, such as point count, coordinates,
records, route ports, state changes, and
transient payload boundaries, rather than the planner/runtime objects
themselves. Planner IR can be rebuilt from the persisted spec plus config when
useful, but it should not be a required durable artifact. Persist only a
compact execution snapshot or diagnostics when that helps audit what actually
happened. The current execution snapshot records compact point-local counts
for compute evaluation, compute reuse, state patches, payload references, and
captured records, plus run-level compute totals, without storing runtime
graphs or generated payload objects.

Data analysis should depend on data evidence, not planner evidence. Dataset
schema and dataset metadata carry coordinates, observable ids, dimensions,
units, dtypes, and record counts for both structured runs and legacy capture.
Analysis code that needs a sweep coordinate should read the measurement
dataset schema rather than an experiment preview.

Analysis should be able to start as manual notebook interpretation and later
be promoted into reusable steps. Manual analysis and promoted analysis should
share enough lineage that follow-up candidate configs and comparisons remain
auditable.

## Legacy Capture

`RunScope` / `TraceScope` is the low-intrusion path for existing notebooks and
scripts. The legacy code keeps execution control while Scopecat captures run
identity, inputs, config files or snapshots, generated artifacts, events,
measurements, notes, analysis, and a provenance level.

Capture records are evidence. They do not imply that Scopecat can replay the
run, and they should not pretend to have a structured spec, plan, or device
program unless those objects were actually produced.

Legacy hardware setup, upload, play, collect, registry mutation, Data Vault
writes, GUI state, and background side effects should not shape the core model.

## Domain And GUI Deferral

Core should not encode one lab's qubit, pulse, device, registry, file naming,
or runner vocabulary. Domain vocabulary, compiler policy, pulse/circuit
semantics, instrument drivers, and private legacy behavior belong in examples,
private adapters, or future packages once a smaller useful boundary exists.

GUI/workbench work should present the same objects available from Python:
workspace, template, run request, run, data, analysis, candidate config,
comparison, and review. It should not invent GUI-only workflow state while the
experiment core is still changing.

## Current Bias

- Prefer a simpler internal shape over preserving old internal names.
- Keep structured execution and legacy capture visibly separate.
- Validate before side effects where practical.
- Treat local paths as storage details, not workflow identity.
- Promote abstractions only after real workflows repeat.
- Let tests and type checks identify everything that must move together after
  a breaking design change.
