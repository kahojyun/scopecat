# Scopecat documentation

Scopecat is a local-first Python toolkit for laboratory experiment workflows.
It connects notebooks, typed experiment authoring, instrument control, live
visibility, and durable results without requiring a lab to replace its existing
Python projects.

## Start here

New users should follow the [source preview quickstart](getting-started/quickstart.md).
It creates a hardware-free project, starts its daemon and project console, and
runs the smallest experiment through the complete durable workflow.

Continue according to what you want to accomplish:

- [Tour the reference lab](tutorials/reference-lab.md) for a runnable gallery of
  instrument, experiment, data, and quantum workflows.
- [Control configured instruments](how-to/control-instruments.md) for direct and
  experiment-time device access.
- [Author experiments](concepts/experiment-dataflow.md) for point plans, compute
  placement, and durable results.
- [Use measurement data](how-to/use-measurement-data.md) for selection, Xarray,
  Arrow, pandas, Polars, and GUI projections.
- [Publish analysis](concepts/analysis-publication.md) for derived datasets,
  facts, artifacts, views, and parameter proposals.

## Reference

- [Command-line interface](reference/cli.md)
- [Project layout and manifest](reference/project-layout.md)
- [Python API](reference/python/index.md)

## Extend or develop Scopecat

Instrument and quantum integrations are product extensions and use public
Scopecat contracts. Start with the [instrument extension guide](extensions/instruments.md)
or [quantum extension guide](extensions/quantum.md).

Contributors changing Scopecat itself should use the
[development guide](development/index.md). Compiler, daemon, scalability, and
repository details live there so an experiment author does not need to learn
them before completing a first run.

The [project charter](development/project-charter.md) is the authority for
current product priorities and scope. These documents describe the present
system, not a compatibility promise or roadmap.
