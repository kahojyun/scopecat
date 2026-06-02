# Engineering Governance

## Status

Engineering governance navigation, not an ADR, roadmap, or public user
documentation.

## Purpose

This directory owns cross-route engineering process rules after discovery
evidence starts moving toward implementation. It exists to prevent drift
between discovery candidates, engineering prototypes, and production vertical
slices.

Use these documents before adding or promoting live code:

| Document | Use For |
| --- | --- |
| [`project-phase-model.md`](project-phase-model.md) | Classify work by phase and apply promotion, code, test, fixture, and drift-control rules. |
| [`workflow-validation-map.md`](workflow-validation-map.md) | Start from user workflow threads, validated steps, missing seams, and next validation questions. |
| [`vertical-slice-register.md`](vertical-slice-register.md) | Find accepted implementation slices, owners, entrypoints, artifact boundaries, tests, and non-goals. |

## Boundary

This directory does not replace:

- discovery validation plans or results;
- route-specific architecture decisions;
- module READMEs that own live API details;
- public user documentation.

It defines the project-level rules for when those narrower owners should be
created, updated, promoted, or left as historical evidence.

Artifact/export boundary labels belong on generated fixtures, expected outputs,
review artifacts, packages, public docs, or other artifacts whose portability
or redaction behavior matters. They are not required for ordinary internal
engineering governance documents in this directory.
