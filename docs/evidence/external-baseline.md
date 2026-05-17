# External Framework Baseline

## Status

External reference note.

This document preserves external framework baseline references for
differentiation.

## Purpose

Use this note when interpreting evidence rows that cite external references.
The repeated lesson is not "no one stores measurements." Mature systems already
cover many acquisition, metadata, instrument, scheduler, and calibration
concerns. Scopecat's gap pressure should stay focused on cross-stack
explanation, readiness, comparison, handoff, and analysis-impact checks around
heterogeneous lab practice.

## Baseline Rows

| External baseline | What it already covers | Differentiation guidance |
| --- | --- | --- |
| [QCoDeS](https://microsoft.github.io/Qcodes/examples/basic_examples/15_minutes_to_QCoDeS.html) | Python instrument parameters, measurement loops, datasets, experiment/sample metadata, and station/instrument snapshots. | Focus on selected context, code selection, same-setup readiness, bounded protocol-transfer readiness, and legacy bundle explanation around existing scripts. |
| [Bluesky Event Model](https://blueskyproject.io/event-model/main/explanations/data-model.html) | Documented run/event schemas for data and metadata, event descriptors, run start/stop records, streaming, and callbacks. | Treat event/run records as a proven pattern, but preserve gaps around notebooks, generated artifacts, physical setup reality, handoff bundles, and scientific comparability outside one controlled stack. |
| [Keysight Labber](https://www.keysight.com/us/en/assets/3122-1301/technical-overviews/M5401LxxA-Labber.pdf) | Commercial instrument server, measurement editor, log browser, Python API, and quantum-measurement-oriented automation. | Emphasize low-intrusion explanation, comparison, and handoff for labs that already have local tools and copied scripts. |
| [labscript BLACS](https://docs.labscriptsuite.org/projects/blacs/en/latest/shot-management/) | Shot queues, connection-table compatibility checks, hardware programming flow, error handling, and analysis forwarding in that ecosystem. | Hardware compatibility checks are a known valuable pattern; Scopecat's early version should remain diagnostic and evidence-based across existing setups rather than claiming device-control authority. |
| [ARTIQ](https://m-labs.hk/artiq/manual/introduction.html) | Quantum experiment control, nanosecond-timing hardware execution, scheduling, GUIs, result visualization, and Windows/Linux availability. | Frame Scopecat as an explanation, readiness, comparison, and handoff layer around heterogeneous lab practice. |
| [Qiskit Experiments calibration management](https://qiskit-community.github.io/qiskit-experiments/stable/0.6/apidocs/calibration_management.html) and [Qibocal runcards](https://qibo.science/qibocal/stable/getting-started/runcard.html) | Specialized calibration schedules, parameter values, calibration experiments, declarative calibration runcards, and protocol libraries. | Calibration routines exist in specialized stacks; Scopecat's gap is cross-stack calibration context, dependency impact, proposal review, and downstream result/analysis trust. |
| [LabRAD](https://sourceforge.net/p/labrad/wiki/Introduction/) | Distributed modular instrument control and data acquisition/management for heterogeneous experimental setups. | Distributed modular control is an established approach; Scopecat should first complement existing distributed or local systems with explainability, diagnostics, and migration evidence. |

## Review Rule

These links are temporally unstable. Recheck versions, access dates, and
current documentation before using this note for high-stakes positioning,
published claims, or implementation decisions.
