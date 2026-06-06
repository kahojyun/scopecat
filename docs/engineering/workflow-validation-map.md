# Use Case Validation Map

## Status

Validation evidence owner for canonical journeys and use cases.

## Purpose

Track what has been validated for the `UC-*`, `UC-CAND-*`, and workflow smoke
rows owned by
[`../product/target-journeys.md`](../product/target-journeys.md). Use this map
to decide what behavior is proven, what seam is still missing, and what the
next validation question is.

Do not use this file as the canonical journey/use-case catalog, implementation
register, issue tracker, or ADR rationale. Product relationships live in the
journey index; implementation owners live in
[`implementation-register.md`](implementation-register.md).

## Reading Rules

- Keep rows keyed by the canonical ID from the journey index.
- Record validation evidence at use-case, workflow-segment, scenario, or
  operation scale.
- Keep API contracts and module-local route detail in module README files and
  prototype-boundary notes.
- Promote `UC-CAND-*` only after the use case has acceptance criteria, owned
  validation evidence, and a clear maturity state.

Use maturity terms from
[`delivery-maturity-model.md`](delivery-maturity-model.md): `Discovery`,
`Engineering prototype`, `Production vertical slice`, `Production readiness`,
or `Maintained product capability`.

## Candidate Use Case Evidence

| ID | Maturity | Validation Evidence | Missing Seam | Next Validation Question |
| --- | --- | --- | --- | --- |
| UC-CAND-002 | Discovery | Brownfield pain points [`BR-PAIN-003`](../brownfield/pain-points.md#br-pain-003), [`BR-PAIN-004`](../brownfield/pain-points.md#br-pain-004), [`BR-PAIN-005`](../brownfield/pain-points.md#br-pain-005), and [`BR-PAIN-009`](../brownfield/pain-points.md#br-pain-009) show pressure around context construction, review gates, acknowledgement, and setup/environment inputs. | No live prepared-run route owner owns explicit command/result inputs, acknowledgement or deferral, no-run-start semantics, or a receipt shape that a later Measurement Record can reference. | Does the user-facing use case have explicit input, review, acknowledgement or deferral, and no-run-start semantics? |
| UC-CAND-003 | Discovery | Brownfield pain points [`BR-PAIN-005`](../brownfield/pain-points.md#br-pain-005) and [`BR-PAIN-010`](../brownfield/pain-points.md#br-pain-010) show pressure around recording, comparing, materializing, observing editable folders, preparing reruns, and GUI review. | No single promoted step has an independently useful user goal or live product owner. | Which one experiment-code step should be promoted first? |
| UC-CAND-004 | Discovery | Brownfield pain points [`BR-PAIN-006`](../brownfield/pain-points.md#br-pain-006) and [`BR-PAIN-011`](../brownfield/pain-points.md#br-pain-011), plus [scan-data-shape discovery fixtures](../../tests/fixtures/discovery/scan_data_shapes/README.md), show pressure around lifecycle, progress, partial data, and shaped-data completeness. | No live event route proves lifecycle, progress, partial-data, or shaped-data recording from Python-driven measurements without scan control. | Can Python-driven measurements emit reviewable lifecycle, progress, partial-data, and shape/completeness events without granting scan control? |
| UC-CAND-005 | Discovery | Brownfield pain point [`BR-PAIN-007`](../brownfield/pain-points.md#br-pain-007) shows pressure around review surfaces, action recording, fit recovery, continuation composition, and parameter-state handoff. | No live owner-native workflow entrypoint owns explicit user actions, review state transitions, or production-shaped acceptance criteria. | Do repeated calibration continuation cases require stable review state, continuation actions, and support expectations beyond one scenario? |
| UC-CAND-006 | Discovery | Brownfield pain point [`BR-PAIN-009`](../brownfield/pain-points.md#br-pain-009) shows pressure to compare declared context facts and selected code context. | No live route owns comparison findings, reference selection, setup truth non-claims, or action handoff. | Can Scopecat compare declared context facts and selected code context without claiming setup truth or domain judgment? |
| UC-CAND-007 | Discovery | Brownfield pain points [`BR-PAIN-008`](../brownfield/pain-points.md#br-pain-008) and [`BR-PAIN-011`](../brownfield/pain-points.md#br-pain-011), plus [scan-data-shape discovery fixtures](../../tests/fixtures/discovery/scan_data_shapes/README.md), show pressure around records browsing, plotting, shaped-data review, readiness review, and selected-record export freshness. | No live post-run route owns records browsing, plotting, readiness review, shaped-data review, operator notes, or review state. | Which first route should own records browser, plotter, shaped-data review, and readiness-review behavior before handoff, comparison, calibration continuation, or rerun preparation? |

## Accepted Use Case And Workflow Evidence

| ID | Maturity | Validated Behavior | Missing Seam | Next Validation Question |
| --- | --- | --- | --- | --- |
| UC-001 | Engineering prototype | Adopt-first recording can create a `legacy_system` Measurement Records shell, write a source receipt, optionally attach reviewed normalized primary data later to the same user measurement, record declared references, and expose a stable open-by-id record view. | Legacy file observation, legacy parsing, adapter discovery, legacy code execution, reference repair, richer primary-data shape declaration, GUI state persistence, and scientific validity remain unvalidated. | Maintenance only unless the adopt-first route earns a user-facing orchestration shape. |
| UC-002 | Engineering prototype | Import-ready recording can import reviewed normalized primary CSV into durable local Measurement Records storage, create the record shell, write primary data, validate normalized table shape, finalize, project/read a read model, and roll back synchronous partial new-record failures. | Final storage schema, richer primary payloads, declared scan-shape schema, existing-record merge import, manifest replacement, conflict resolution beyond accepted no-overwrite paths, and shared domain model remain unvalidated. | Decide separately if existing-record import/update, primary-data shape declaration, or another recording route becomes a production vertical slice. |
| UC-003 | Engineering prototype | The handoff writer can package one or more caller-declared normalized primary data files from a source root, copy files after digest/size preflight, optionally copy explicitly declared linked-context payloads, write the ADR-0006 directory package subset, create/open safe zip transport archives under ADR-0015/ADR-0016, and observe declared package-member integrity without authenticity claims. | Archive authority beyond ADR-0014/ADR-0015/ADR-0016, package import, final package format, durable record lifecycle evidence, and GUI architecture remain unvalidated. | Keep as an owner-local writer capability unless a separate adapter-owned product workflow needs direct packaging without prior durable storage. |
| UC-004 | Engineering prototype | The receiving side can open a handoff package read-only, observe manifest-declared integrity, run a receiving gate, create a non-mutating import plan, safely materialize zip transport archives, adapt exactly one ready planned measurement into Measurement Records durable import, and keep linked-context payloads reviewable without durable materialization under ADR-0012. | Conflict resolution beyond delegated durable import rules, GUI-owned persisted receiving state, archive-backed durable import beyond ADR-0015/ADR-0016, and batch durable import beyond ADR-0013 remain unvalidated. | Decide separately if GUI-owned persisted receiving state, archive-backed import, or another receiving extension is the next user risk. |
| UC-006 | Production vertical slice segment | Selected stored-record export uses a Measurement Records-owned packageable projection by `record_id`; Handoff writes an openable package without parsing Measurement Record storage artifacts directly; package facts preserve durable record identity, label, experiment type, primary-data digest/size/source path, preview metadata, and selected linked-context payloads under explicit selection. | Receiving/import workflow belongs to UC-004. Source-storage mutation, durable linked-context payload import beyond ADR-0012, existing-record update/import beyond ADR-0017, post-run browser/plotter/readiness review beyond JNY-008, and shared domain schema remain unvalidated. | Decide whether source-side selected export needs more production hardening, batch export productization, linked-context payload follow-up, or post-run readiness review. |
| JNY-001-SMOKE | Production vertical slice | The smoke path validates the workflow backbone across selected stored-record export, safe zip archive creation, safe zip archive materialization, UC-004 read-only receiving review, import plan, and new-record durable import into a second storage root. | GUI-owned persisted receiving state, archive-backed import beyond ADR-0015/ADR-0016, batch durable import beyond ADR-0013, linked-context payload import beyond ADR-0012, existing-record update/import beyond ADR-0017, post-run browser/plotter/readiness review beyond JNY-008, and shared domain schema remain unvalidated. | Use this row to decide whether to continue cross-segment production hardening or branch into a named product fork. |

## Update Rule

Update this map when a branch:

- validates new behavior for an existing use case or candidate use case;
- changes maturity, missing seams, or next validation questions;
- validates a seam between accepted routes;
- discovers that evidence is being counted as progress without closing a named
  use case, workflow, capability, or scenario question.

Update [`../product/target-journeys.md`](../product/target-journeys.md) when a
journey/use-case relationship changes.
