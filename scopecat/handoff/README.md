# Handoff Prototype Module

Engineering prototype module for Scopecat-authored handoff package use and the
current durable Measurement Records handoff import route.

This module is route-local prototype code. It tests a production-shaped Python
entrypoint over validated handoff discovery candidates without accepting final
public SDK names, package format, broad storage import behavior, GUI
architecture, plotting stack, or shared measurement-record domain model.

The runtime API exposes route-local objects rather than discovery candidate
summary dictionaries. `as_open_summary()` exists as a copy-safe prototype
snapshot, not as a public contract.

The prototype owns its handoff-specific manifest preview and contract helpers
inside this module. Discovery implementation candidates remain historical
validation inputs, not runtime dependencies for this route.

Raw manifest dictionaries are validated at the package boundary. After that,
manifest preview classification, review findings, opener internals, and
package projections consume typed route-local manifest fragments.
Raw workflow dictionaries are accepted only at public `run_*` edge adapters.
Internal receiving/import/preflight/storage composition should pass typed
route-local request and run objects rather than serializing prior workflow
state back into nested dictionaries.
`observe_package_integrity(...)` is a read-only receiving/import prerequisite:
it compares package-local regular files with paired manifest-declared
digest/size facts where available. It does not verify signatures,
authenticity, trust, archive contents, import acceptance, or storage mutation.
`run_receiving_gate(...)` adds explicit review approval and reviewed fact
continuity over the opened package plus integrity report. It has no destination
or storage-mutation fields.
`run_import_plan(...)` composes read-only package open, optional local
inspection artifact generation, the receiving gate, and a non-mutating
measurement import plan. It names the package members that would be considered
for a later acceptance mutation, but it accepts no destination path, performs
no conflict detection, writes no storage records, and does not decide final
storage schema or rollback policy.
Durable Measurement Records import is a separate boundary from candidate
handoff storage acceptance. When a reviewed handoff package feeds durable
storage, the accepted path is to adapt exactly one ready import-plan
measurement into `MeasurementRecordImportSource` and
`MeasurementRecordDurableImportRequest`, then use the Measurement Records
durable import pipeline. The first handoff integration should not extend
`measurement_record_directory_candidate_v0`, import linked-context payloads,
or batch multiple package measurements in one durable import operation.
`run_handoff_durable_import_from_plan(...)` implements that route for a ready
single-measurement `HandoffImportPlanRun`; `run_handoff_durable_import(...)`
is the raw edge that runs the import plan first and then delegates mutation to
the durable Measurement Records import pipeline.
`summarize_handoff_durable_import_receipt(...)` reads the local adapter receipt
back into a small continuation summary with package id, selected measurement,
destination record, final state, next action, and durable import outcome. It
does not authorize retry, reopen packages, reuse prior import-plan facts, or
mutate storage.
`review_handoff_durable_import_retry(...)` compares that local summary with a
fresh ready import plan and reports whether retry is locally reasonable. It
does not create a durable import request, recheck destination freshness,
authorize mutation, or reuse the prior receipt as authority.
The module CLI remains a local operator surface. `python -m scopecat.handoff
<package-dir>` opens a package for read-only orientation; `python -m
scopecat.handoff --receipt-summary <receipt.json>` summarizes either a local
legacy candidate import workflow receipt or a local handoff durable-import receipt
for continuation review. The CLI does not run package import, approve storage
acceptance or durable import, or persist review state.

The older candidate storage acceptance route remains only as historical
engineering evidence in direct modules:
`scopecat.handoff.acceptance_preflight`,
`scopecat.handoff.storage_acceptance`, and
`scopecat.handoff.import_workflow`. It proved reviewed destination continuity,
no-overwrite checks, local operator decisions, rollback classification, receipt
summary, and retry review for `measurement_record_directory_candidate_v0`.
That route is no longer exported from the top-level `scopecat.handoff` API and
should not be extended for durable Measurement Records import.

The route-local writer uses a caller-provided `source_root` plus declared
relative source paths for already-normalized primary data. That source-root
boundary deliberately avoids accepting final Scopecat storage architecture.
The writer materializes the current directory-shaped package subset, preflights
declared sha256/size facts, writes with no-overwrite behavior, and returns a
local review receipt. It does not create archives, import packages, mutate the
source root, or decide package acceptance.
Raw write-request dictionaries are accepted only at `write_package(...)`; the
writer validates and parses them into route-local write-source objects before
filesystem preflight, manifest generation, package writes, or receipt
serialization.
`run_package_workflow(...)` composes the promoted writer, reader, and optional
local inspection artifact into one route-local review workflow. It does not
create archives, import or accept packages, verify package integrity, or decide
final storage layout.

## API Surface

Current user-facing prototype surface:

- `open_package(package_dir)`;
- `observe_package_integrity(package_dir)`;
- `run_receiving_gate(source, package_dir=...)`;
- `run_import_plan(source, package_dir=...)`;
- `run_handoff_durable_import(source, package_dir=..., storage_root=...)`;
- `run_handoff_durable_import_from_plan(request, import_plan=..., storage_root=...)`;
- `build_durable_import_request_from_handoff_plan(request, import_plan=...)`;
- `summarize_handoff_durable_import_receipt(receipt)`;
- `review_handoff_durable_import_retry(previous_summary, fresh_import_plan=...)`;
- `write_package(source, source_root=..., package_root=...)`;
- `run_package_workflow(source, source_root=..., package_root=...)`;
- `python -m scopecat.handoff <package-dir>`;
- `write_inspection_artifact(...)` and `build_inspection_html(...)`;
- route projection objects exported from `scopecat.handoff`.

The CLI entrypoint supports:

- `python -m scopecat.handoff <package-dir>`;
- `python -m scopecat.handoff <package-dir> --html-dir <output-dir>`;
- `python -m scopecat.handoff --receipt-summary <receipt.json>`.

Modules with leading underscores are route-private implementation modules.
They may be tested directly while the prototype hardens, but they are not
public SDK or cross-route domain APIs.
Legacy candidate storage modules remain direct-module historical coverage, not
the current top-level handoff API.
