# Engineering Governance

## Status

Engineering governance navigation.

## Purpose

This directory owns cross-route engineering process rules after discovery
evidence starts moving toward implementation. It exists to prevent drift
between product workflows, product capabilities, validation artifacts, and live
implementation owners.

Use these documents before adding or promoting live code:

| Document | Use For |
| --- | --- |
| [`delivery-maturity-model.md`](delivery-maturity-model.md) | Classify workflow and capability maturity; choose validation methods without treating candidate/prototype counts as progress. |
| [`workflow-validation-map.md`](workflow-validation-map.md) | Start from user workflow threads, validated steps, missing seams, and next validation questions. |
| [`capability-register.md`](capability-register.md) | Track product capabilities, maturity, supported workflows, evidence, implementation owners, and open advancement questions. |
| [`prototype-boundaries/README.md`](prototype-boundaries/README.md) | Find current route-local engineering prototype boundaries and next decision gates. |
| [`pr-documentation-drift-checklist.md`](pr-documentation-drift-checklist.md) | Lightweight PR checklist for avoiding documentation drift without freezing future decisions. |
| [`archive/README.md`](archive/README.md) | Find historical prototype plans, readiness checkpoints, and retired engineering decisions. |

## Boundary

This directory does not replace:

- discovery validation plans or results;
- route-specific prototype boundary notes;
- module READMEs that own live API details;
- public user documentation.

It defines the project-level rules for when those narrower owners should be
created, updated, promoted, or left as historical evidence.

Artifact/export boundary labels belong on generated fixtures, expected outputs,
review artifacts, packages, public docs, or other generated artifacts only when
they are part of a validation, review, portable/export, or public boundary.
They are not required for ordinary internal engineering governance documents in
this directory.
