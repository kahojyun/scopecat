# Chips and physical samples

A sample is the stable identity of a physical experimental subject: a chip,
wafer piece, material coupon, packaged device, biological specimen, or another
object that can participate in several runs. It is not a synonym for a run,
configuration, or entity.

Scopecat separates the identity from its changing description:

- `SampleRecord` gives the physical object a stable project-local ID and kind.
- `SampleRevision` is an immutable descriptive snapshot of that object.
- `SampleSelector` expresses which sample and role an operator wants for a run.
- `SampleBinding` records the exact revision resolved when the run is admitted.

This lets a chip keep one identity while its lifecycle, annotations, map, and
design references evolve. An old run still points to the revision it actually
used instead of silently inheriting a newer description.

## Relationship to existing concepts

| Concept | Relationship to a sample |
| --- | --- |
| Project | Owns the sample registry and its immutable revision history. Sample IDs are stable within this boundary. |
| Configuration | Describes accepted lab configuration, instruments, routes, and execution topology. A sample revision describes the physical subject. Its topology does not override or automatically merge into accepted configuration. |
| Entity | Names one part of a sample topology, such as `q0`, `sensor-a`, or `site-3`. Interpret that identity within the containing sample; the same entity ID on another sample is a different physical subject. |
| Run | Binds zero or more samples in named roles, such as `subject`, `reference`, or `control`. Admission resolves selectors and freezes exact sample revision hashes in run provenance. |
| Measurement | Remains owned by a run. It acquires sample provenance through the run's immutable bindings instead of duplicating mutable sample metadata into every record. |
| Analysis | Can belong to one run, the project, or one stable sample. A sample analysis may combine completed runs only when every input run binds that sample in the `subject` role. Reference and control bindings remain context, not scientific ownership. |
| Calibration | Can qualify a target by `sample_id` and optional `context_id`, so state for two physical chips or two operating contexts cannot collide. That scope is inherited by procedure child runs. |
| Procedure | May select samples for its experiment runs and consume sample-scoped published analysis explicitly. |

The registry is therefore a provenance and longitudinal-analysis boundary, not
an inventory-management system and not a second configuration system.

Sample IDs are URL-safe stable keys: 1–128 ASCII letters, digits, `.`, `_`, `:`,
or `-`, beginning with a letter or digit. Put hierarchical or vendor-facing
labels that contain spaces or slashes in aliases, tags, `design_ref`, or
properties instead of the identity. One run role may select one sample, and the
same sample cannot fill several roles in one run; use relations or explicit
context metadata when one physical object has several descriptive meanings.

The word “sample” in a measurement dimension means a sampling point or record
axis, not a `SampleRecord`. Likewise, configuration entities are logical
addresses. A physical sample is established only by the registry identity and
its exact run binding.

## What belongs on a sample revision

Use typed fields for information that drives navigation or interpretation:

- `display_name`, `kind`, aliases, and tags for discovery;
- lifecycle status: `received`, `available`, `mounted`, `retired`, or `damaged`;
- `design_ref` for a layout, mask, drawing, or external design identity;
- typed relations to other samples, such as parent wafer, diced-from, mounted-in,
  or reference/control relationships;
- a domain-neutral entity topology and optional two-dimensional geometry;
- external artifact references for photographs, reports, datasheets, and maps;
- JSON `properties` for domain-specific, revisioned descriptors that do not yet
  justify a core field.

Measurements, fitted values, run outcomes, and accepted instrument settings do
not belong in `properties`. Keep those in run data, analysis publications, and
accepted configuration so their provenance and lifecycles remain explicit.

## Register, revise, and bind a sample

The Python API deliberately requires a complete revision draft. Revising a
sample creates a new immutable snapshot; it does not edit history in place.

```python
from scopecat.kernel.entity import EntityRef
from scopecat.records.config import Topology, TopologyConnection
from scopecat.records.sample import (
    SampleArtifactRef,
    SampleGeometry,
    SampleGeometryPoint,
    SampleRevisionDraft,
)

chip = lab.samples.create(
    "chip-a17",
    kind="chip",
    content=SampleRevisionDraft(
        display_name="Chip A17",
        tags=("fridge-2", "generation-4"),
        design_ref="mask:g4-r3",
        topology=Topology(
            entities=[
                EntityRef(id="q0", kind="qubit"),
                EntityRef(id="q1", kind="qubit"),
            ],
            connections=[
                TopologyConnection(
                    id="q0-q1",
                    kind="coupling",
                    endpoints=("q0", "q1"),
                )
            ],
        ),
        geometry=SampleGeometry(
            unit="mm",
            width=10,
            height=10,
            points=(
                SampleGeometryPoint(entity_id="q0", x=3, y=5),
                SampleGeometryPoint(entity_id="q1", x=7, y=5),
            ),
        ),
        artifacts=(
            SampleArtifactRef(
                id="die-photo",
                title="Inspection photo",
                uri="https://example.invalid/chip-a17/photo",
                media_type="image/jpeg",
            ),
        ),
    ),
    note="Registered after room-temperature inspection",
)

run = lab.run(ramsey(), sample=chip)
assert run.samples[0].sample_id == "chip-a17"
```

Passing `sample=chip` is shorthand for the ordinary `subject` role and the
active revision at admission. Use an explicit selector for multiple roles,
operating contexts, or a historical revision:

```python
run = lab.run(
    comparison(),
    samples=(
        chip.selector(role="subject", context_id="mount-2026-08"),
        reference_chip.selector(role="reference", revision=3),
    ),
)
```

The resulting `run.samples` contains exact `sample_id`, revision, content hash,
kind, display name, role, and context. Changing the active sample revision later
does not change that binding.

Browse history independently from the active detail so long-lived samples are
never silently truncated:

```python
page = chip.revisions(limit=100)
registered = chip.revision(1)
bound_runs = lab.runs(sample=chip)
```

## Publish longitudinal sample analysis

Use a sample owner when a conclusion describes the physical sample across
multiple completed runs:

```python
published = lab.analyze(drift_summary, sample=chip)
history = lab.analysis_summaries(sample=chip)
latest = lab.published_analysis("drift-summary", sample=chip)
```

The publication still carries explicit immutable run inputs. Scopecat rejects
an input run that does not bind the selected sample as its `subject`, preventing a
project-level cohort from being mislabeled as a sample conclusion.

## Project-console experience

The **Samples** workspace treats physical subjects as a top-level way to enter
the project:

- registry search and lifecycle filters answer “which object?” before “which
  run?”;
- the sample header exposes stable identity, active revision, design reference,
  aliases, tags, and relations;
- the sample map projects topology through supplied geometry, or uses a
  deterministic automatic layout when geometry is absent;
- selecting an entity reveals its kind and connections without pretending that
  the map is an execution schematic;
- run history, sample analyses, artifacts, properties, and revision history are
  visible in one longitudinal view;
- sample-to-run and run-to-sample links preserve context in both directions.

The UI shows lifecycle and metadata from the active revision, while every run
badge and detail link shows the exact revision bound to that run. This visual
distinction is important: “what we currently know about the chip” and “what
this run actually used” are related views, not the same fact.
