# Native Experiment Kernel Detail

Status: accepted subsystem detail
Date: 2026-06-24

This note defines the experiment-kernel details behind the accepted
architecture. It is a companion to [Scopecat Architecture](architecture.md), not
a second top-level architecture document.

The core decision is that an experiment is a declarative plan recipe:

1. build point rows
2. apply point-local parameter patches
3. derive desired logical state
4. acquire measurements

Everything else is outside the experiment definition. Analysis, candidate
review, registry activation, run comparison, and legacy adapter translation are
workflow concerns.

The stable output is the plan shape and boundary contracts now covered by
production tests.

## Public Shape

The authoring API should have four primary fields:

```python
experiment(
    id="readout-frequency-calibration",
    kind="readout.frequency_scan",
    points=grid(
        readout=table("readout_devices").filter(col("enabled")),
        readout_frequency=linspace(5.90, 6.00, 101, unit="GHz"),
        readout_power=values([-31, -29, -27], unit="dBm"),
    ),
    params=[
        update_param_rows(
            "readout_devices",
            key={"device_id": col("readout.device_id")},
            values={
                "frequency": col("readout_frequency"),
                "power": col("readout_power"),
            },
        ),
    ],
    state=[
        set_state(
            resource=col("readout.resource_id"),
            field="pulse.frequency",
            value=param("readout_devices", key={"device_id": col("readout.device_id")}, column="frequency"),
        ),
    ],
    acquire=acquisition(kind="iq", shots=240, repetitions=1024),
)
```

The durable model should mirror this shape:

- `kind`: domain-owned experiment kind.
- `points`: a relation expression that yields one row per acquired point.
- `params`: parameter patches evaluated for each point row.
- `state`: desired-state bindings evaluated from point columns and resolved
  parameters.
- `acquire`: acquisition shape and record granularity.
- `assets`: optional referenced waveforms, schedules, or other content-addressed
  artifacts.

There is no durable `target` field. A target-like value is a column in
`points`, such as `readout.device_id`, `qubit_id`, `line_id`, or `sample_id`.
Template functions may accept ergonomic arguments, but they must lower to the
same model before validation.

If a use case only makes sense by binding pseudo-resources such as
`resource-scheduler`, `campaign-orchestrator`, `resume.policy`, or
`monitor.every`, it is not an experiment definition problem. Model the ordinary
experiment as context and move the policy input/output to a workflow, executor,
storage, or config boundary case. This keeps `ExperimentSpec` readable and
prevents boundary mechanics from masquerading as desired instrument state.

## Relation Expressions

Scopecat should own one small relation-expression IR and reuse it for:

- parameter derivations
- experiment point construction
- variable-key parameter references
- repeated desired-state bindings
- validation previews and dry-run diagnostics

The authoring surface can look Polars-like:

```python
grid(
    lo_frequency=linspace(4.9, 5.1, 101, unit="GHz"),
).with_columns(
    lo_id=lit("xy_shared"),
)
```

and:

```python
table("drive_channels").filter(col("enabled")).select(
    "resource_id",
    "fixed_if_frequency",
)
```

The durable IR should stay smaller than Polars:

- relation roots: `literal_rows`, `range`, `linspace`, `points`, `table`,
  `parameter_table`
- relation ops: `select`, `filter`, `join`, `cross`, `with_columns`, `sort`
- expression terms: `col`, `param`, `literal`, arithmetic, comparison,
  boolean logic, selected pure functions

The planner may use Polars internally later, but the core contract is the
Scopecat IR and its diagnostics.

## Parameter Patches

Experiment-time parameter changes are patches against a resolved parameter
view, not mutations of accepted `ParameterState`.

Use row-oriented patch operations as the core shape:

```python
set_param("readout.demod_frequency", col("demod_frequency"))

update_param_rows(
    "readout_devices",
    key={"device_id": col("readout.device_id")},
    values={
        "frequency": col("readout_frequency"),
        "power": col("readout_power"),
    },
)
```

Cell helpers can exist as authoring sugar, but the model should store patches:

- `set_scalar(parameter_id, value)`
- `update_rows(table_id, key, values)`
- `insert_rows(table_id, rows)`
- `delete_rows(table_id, key_or_filter)` only for proposals, not for ordinary
  experiment execution unless a domain package has a clear reason

Patch evaluation rules:

1. evaluate point rows
2. resolve patch keys from point columns and literals
3. validate table/key cardinality
4. validate units, types, and safety bounds
5. apply patches to an internal per-point parameter view
6. evaluate affected parameter derivations

The full per-point parameter view is planner state. `PlanSnapshot` may store
sampled previews and diagnostics, but it should not commit to embedding a full
copy of every patched table for every point.

## Desired State

Desired state is the contract native instruments consume. It is not a driver
call and it is not a parameter table.

Single-resource binding:

```python
set_state(
    resource="xy_shared_lo",
    field="frequency",
    value=col("lo_frequency"),
)
```

Repeated binding over a relation:

```python
bind_each(
    table("drive_channels").filter(col("enabled")),
    resource=col("resource_id"),
    fields={
        "if_frequency": col("fixed_if_frequency"),
        "carrier_frequency": outer("lo_frequency") + col("fixed_if_frequency"),
    },
)
```

`bind_each` is the public helper because it describes the author intent:
evaluate another relation for every point row and emit repeated desired-state
records. The lower-level kernel IR may still use `for_each` internally, but it
does not need to be the main authoring concept.

The shared-LO fixed-IF scan becomes:

```python
experiment(
    id="shared-lo-fixed-if-scan",
    kind="drive.shared_lo_scan",
    points=grid(lo_frequency=linspace(4.9, 5.1, 101, unit="GHz")),
    params=[
        update_param_rows(
            "lo_sources",
            key={"lo_id": "xy_shared"},
            values={"frequency": col("lo_frequency")},
        ),
    ],
    state=[
        set_state("xy_shared_lo", "frequency", col("lo_frequency")),
        bind_each(
            table("drive_channels").filter(col("enabled")),
            resource=col("resource_id"),
            fields={
                "if_frequency": col("fixed_if_frequency"),
                "carrier_frequency": outer("lo_frequency") + col("fixed_if_frequency"),
            },
        ),
    ],
    acquire=acquisition(kind="iq", shots=240, repetitions=1024, record="point"),
)
```

This covers simultaneous multi-device control without a special target system.

## Planning

Planning produces execution records from a config snapshot and an
`ExperimentSpec`:

- `PointPlan`: evaluated point rows and coordinate ids.
- `ParameterPatchPlan`: evaluated parameter patches and diagnostics.
- `DesiredStatePlan`: desired logical resource state per point.
- `StatePatchPlan`: changes between adjacent desired states.
- `AcquisitionPlan`: record granularity, dimensions, channels, shots,
  repetitions, and estimated counts.
- `PlanSnapshot`: durable aggregate with hashes, diagnostics, and artifact
  refs.

The planner should not expose mutable registry/session objects, raw
spreadsheets, or private runner dictionaries. It reads a resolved
`ParameterBuildSnapshot`, evaluates parameter patches for each point, and
resolves desired state from the patched view.

Variable-key parameter lookup is a join:

1. project key columns from the current point or repeated relation row
2. join keys against the parameter table
3. require exactly one matching row unless the API explicitly asks for many
4. project the requested columns

This avoids a dynamic `parameters[path][target]` language while still handling
swept subjects and shared-resource scans.

## Boundaries

`ExperimentSpec` owns:

- point construction
- parameter patches local to the run
- desired-state bindings
- acquisition shape
- experiment assets
- expected measurement schema when useful

`ExperimentSpec` does not own:

- analysis or promoted analysis automation
- candidate config decisions
- registry activation
- accepted parameter mutation
- operator/run metadata
- brownfield compatibility behavior
- retry loops, active reset stop conditions, or decoder feedback loops
- cross-instrument barrier schedules
- large artifact chunk assembly
- online early-stop decisions
- crash recovery and resume point selection
- multi-run calibration campaign orchestration
- resource lease scheduling
- shot-level classifier training or model selection
- artifact availability and downstream processing eligibility
- parameter invalidation and cache dirtying
- mixed host/hardware backend strategy selection
- monitor/background calibration row insertion

Native instruments consume desired-state patches and acquisition context.
Adapters may translate plans to legacy runner calls at the boundary, but that
translation must not shape the core model.

## Relationship To Architecture

The package split and durable boundaries live in
[Scopecat Architecture](architecture.md) and the focused contract documents.
This document should stay focused on relation expressions, parameter patches,
desired-state bindings, and planning records.
