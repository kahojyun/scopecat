# Domain Package Extraction Contract

Status: accepted boundary baseline
Date: 2026-06-29

This note records the current domain-package decision after the examples
reorganization. Scopecat currently has one product package:
`packages/scopecat`. Quantum-flavored lab code used for examples lives under
`examples/quantum/support` as the local `quantum_lab_demo` support package.

That support package is copyable teaching and UX validation code. It is not a
domain extension boundary to freeze or publish.

## Current Baseline

Repository ownership is now:

- `packages/scopecat`: domain-neutral core.
- `examples/quantum/notebooks`: the user-facing notebook-first learning path.
- `examples/quantum/scripts`: thin command-line wrappers around the same demo
  workflows.
- `examples/quantum/support`: local demo lab package containing experiment
  builders, virtual providers, promoted analysis steps, fixtures helpers, and
  support tests.
- `fixtures/quantum`: repository-local fixture assets consumed by the demo
  package and examples.

Core must remain independent of the demo package. Import guard tests should
continue to fail if core imports `quantum_lab_demo` or quantum vocabulary leaks
into the public core surface.

## Extraction Decision

Do not extract a quantum domain package yet.

The demo support package intentionally mixes several concerns that are useful
for examples but wrong for a stable domain package:

- readout calibration workflows;
- IQ quality analysis;
- sample Rabi, readout, single-qubit RB, and CZ RB templates;
- virtual lab providers and fixture response models;
- notebook UX helpers;
- candidate review and update-loop examples.

Those pieces should stay local to examples until there is evidence that a
smaller reusable domain package boundary is worth freezing.

## Future `scopecat-quantum` Scope

When a real `scopecat-quantum` package is introduced, start with foundational
building blocks only:

- lightweight target identifiers such as qubit and coupler ids;
- gate and gate-sequence records;
- pulse, envelope, channel, and pulse-sequence records;
- serializers or artifact helpers for gate and pulse sequence payloads;
- validation helpers that are independent of any lab workflow.

Do not put these in the first extracted package:

- readout-frequency calibration workflows;
- IQ-quality analysis;
- virtual lab providers;
- fixture response models;
- notebook examples;
- candidate review policy;
- update loops or calibration campaigns.

The example support package may later import `scopecat_quantum` building
blocks. `scopecat_quantum` must not import examples.

## Compatibility Policy

There is still no external compatibility contract for this repository.
Local breaking changes remain preferred over compatibility layers while the
project is single-user and local.

Creating a real domain package would create a compatibility obligation. Before
that happens, define:

- compatible core version range;
- supported Python versions;
- public facade modules;
- stable artifact kinds;
- stable diagnostic prefixes and catalog entries;
- fixture compatibility expectations;
- deprecation policy.

## Relationship To Core

Core owns generic records and workflow APIs:

- quantities, relation expressions, diagnostics, parameters, and experiment
  specs;
- planning, dry-run previews, execution records, result contracts, and storage
  references;
- `Workspace`, `Experiment`, `Run`, `Data`, `Analysis`, `AnalysisStep`,
  candidate configs, comparisons, and reports.

Domain packages or demo packages own domain vocabulary and compilers:

- qubit, resonator, coupler, pulse, line, sample, and gate vocabulary;
- experiment builders and calibration recipes;
- sequence/pulse compiler IR;
- hardware or virtual-lab policy;
- classifier artifacts and readout schemas.

## Extraction Readiness Checklist

Extraction is ready only when:

- the target package is smaller than the demo support package;
- examples import it through a deliberate public facade;
- package-local docs list public modules, ids, artifact kinds, and diagnostic
  prefixes;
- fixtures are assigned to package tests, examples, or core boundary contracts;
- relation functions, if present, register through the function registry;
- generated artifacts use manifest artifact ids and package-owned kinds;
- package tests and example tests pass without private core imports;
- a core/domain version policy is documented.

## Accepted Decisions

- Keep `packages/scopecat` as the only current product package.
- Keep quantum demo lab code under `examples/quantum/support`.
- Treat `quantum_lab_demo` as demo support code, not a stable extension.
- Defer `scopecat-quantum` until a small building-block boundary is clear.
- Keep core domain-neutral and protected by import/vocabulary guard tests.
