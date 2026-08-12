# User-facing glossary

These terms form the vocabulary that Scopecat should present consistently in
Python, the CLI, diagnostics, and the project console. Implementation terms such
as worker, lease, wire record, compiler IR, and SQLite entry are intentionally
excluded from ordinary workflows.

| Term | User-facing meaning | User manages it when |
| --- | --- | --- |
| Project | Version-controlled lab code and its discoverable `scopecat.toml`. | Creating or opening a lab project. |
| Lab | The connected operational view of one project and its accepted state. | Running work, controlling instruments, or inspecting history. |
| Configuration source | User-owned Python that describes the intended initial lab configuration. | Reviewing configuration changes in source control. |
| Accepted configuration | One immutable, daemon-owned configuration revision available to runs. | Applying, accepting, selecting, or undoing a change. |
| Instrument | A configured or temporary physical/virtual device available through typed capabilities. | Controlling a device or diagnosing its availability. |
| Capability | Typed state and operations that describe what compatible instruments can do. | Authoring direct control or experiment work independent of a driver. |
| Route | Accepted configuration that connects a logical purpose to physical capability endpoints. | Integrating a lab or diagnosing why a resource cannot be selected. |
| Entity | A logical experimental subject, such as a sample or qubit, retained in provenance. | Selecting or comparing work by subject. |
| Experiment | Reusable authored work that declares inputs, points, effects, and results without executing them. | Defining or composing a measurement procedure. |
| Run | One admitted execution of an experiment with concrete inputs and configuration. | Previewing, executing, cancelling, or inspecting work. |
| Point | One logical coordinate row in a run's authored point domain. | Selecting, grouping, or interpreting measurements. |
| Measurement | Immutable recorded data produced by a run, with declared identity, type, unit, shape, and availability. | Inspecting or analyzing acquired results. |
| Result | The authored return structure that determines the ordinary durable output of an experiment. | Defining what downstream users should receive from a run. |
| Analysis | One immutable publication of derived facts, datasets, artifacts, views, and proposals attached to a source run. | Preserving conclusions from ordinary numerical Python. |
| Proposal | An analysis output that describes a reviewable parameter change and its evidence. | Evaluating a candidate configuration. |

## Vocabulary design checks

A core workflow should not require users to translate between several names for
the same object. When a term above has different meanings across Python, CLI,
GUI, or diagnostics, record that difference as design feedback.

Internal identities may appear in advanced reference and diagnostics, but the
ordinary workflow should carry them through typed handles and links. Asking a
user to copy an entry ID, generation, daemon URL, or database key is evidence
that a product boundary is leaking.
