# Capability Map

## Status

Current product capability map.

## Purpose

Track Scopecat product capabilities and their maturity. This is a product
planning document, not an implementation inventory. A capability may support
multiple workflows and may be implemented by one or more modules.

Use this document with:

- [`adoption-model.md`](adoption-model.md) for user adoption paths and
  brownfield boundaries;
- [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md)
  for maturity vocabulary;
- [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
  for workflow seams and next validation questions;
- [`../engineering/implementation-register.md`](../engineering/implementation-register.md)
  for live implementation owners and their detailed module/boundary docs.

## Capability Map

| Capability | Maturity | Evidence State | Open Advancement Questions |
| --- | --- | --- | --- |
| Measurement Records | Engineering prototype | Live prototype evidence | Decide whether selected stored measurement export, existing-record update/import, running measurement lifecycle, or storage schema readiness is the next vertical-slice pressure. |
| Handoff Packages | Engineering prototype | Live prototype evidence | Validate selected stored Measurement Record to single-measurement handoff package export; decide later trust/authenticity, batch receiving, archive format, and linked-context payload import questions. |
| Parameter State Review | Engineering prototype | Live prototype evidence | Decide whether compatibility-file writing, hardware apply, catalog discovery, automatic run start, or a shared parameter/run-context schema is justified by a workflow. |
| Environment Operation | Engineering prototype | Live prototype evidence | Decide whether runtime readiness, manifest integration, manager expansion, execution hardening, or GUI/runtime monitoring is the next validated product need. |
| Experiment Code Context | Discovery | Discovery and implementation-candidate evidence | Decide which concrete user step merits promotion first: record, materialize, observe editable folder, prepare rerun, or GUI review. |
| Running Measurement Monitor | Discovery | Evidence-backed validation question | Validate whether Python measurement scripts can emit lifecycle/progress/partial-data events that a long-lived local GUI can monitor across multiple active measurements. |
| Calibration Continuation Review | Discovery | Discovery and implementation-candidate evidence | Promote only around explicit user actions, review state transitions, and route-native acceptance criteria. |

## Update Rule

Update this map when a branch changes product capability maturity, product
boundary, evidence state, or advancement questions.

Do not use this file to list every implementation entrypoint or test. Use
[`../engineering/implementation-register.md`](../engineering/implementation-register.md)
for live implementation ownership and boundary/module docs.
