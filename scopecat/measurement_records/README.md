# Measurement Records Engineering Prototype

This route-local module currently owns the first durable measurement-record
creation prototype.

The accepted boundary is intentionally narrow:

```text
approved creation request
  -> caller-provided storage root
  -> caller-declared record id and record directory
  -> no-overwrite record directory creation
  -> initial record-manifest.json
  -> local creation receipt
```

It does not define final storage schema, record-id generation, import
acceptance, existing-record update, conflict resolution beyond no-overwrite,
crash recovery, GUI review state, or a shared measurement-record domain model.

The first writer-integration slice attaches primary data to a created record:

```text
approved writer request
  -> existing creation manifest continuity check
  -> declared chunk digest and size preflight
  -> no-overwrite primary data write
  -> record-local writer receipt
  -> local writer integration receipt
```

It does not replace the creation manifest, refresh a read model, mark records
complete or failed, merge existing primary data, or define final storage
schema.

The normalized primary table contract is implemented through
`summarize_normalized_primary_table(...)` and
`summarize_normalized_primary_table_from_request(...)`:

```text
caller-provided normalized CSV bytes
  -> UTF-8 decode
  -> unique non-blank header validation
  -> rectangular string-row validation
  -> declared preview-column binding
  -> local normalized table summary
```

It is side-effect-free and route-local. It does not observe files, validate
file integrity, parse legacy sources, mutate storage, infer schemas, infer
scalar types, infer scan shapes, invoke dataframe adapters, build plot series,
or define public SDK names. The created-record read view uses the same
normalized CSV validation for its writer-receipt-declared primary data while
preserving its existing receipt/read-view authority.

The first read-view slice reads primary table facts through a writer receipt:

```text
read request
  -> existing creation manifest continuity check
  -> record-local writer receipt continuity check
  -> writer-receipt-declared primary data digest and size check
  -> normalized CSV string-row read
  -> local read summary
```

It does not replace the creation manifest, refresh a read model, finalize
lifecycle state, infer schema/scalar types, build plot series, or invoke a
dataframe adapter.

The finalization boundary is receipt-based:

```text
creation manifest
  -> writer receipt
  -> read-view summary
  -> approved finalization request
  -> record-local finalization receipt
  -> local finalization run receipt
```

It writes `finalization-receipt.json` without replacing
`record-manifest.json`. `complete` requires ready read-view evidence; `failed`
requires an explicit operator reason. Manifest replacement and read-model
refresh remain separate decisions.

The next accepted boundary is derived read-model projection:

```text
creation manifest
  -> writer receipt
  -> read-view summary
  -> finalization receipt
  -> approved projection request
  -> record-local record-read-model.json
  -> local projection run receipt
```

`record-read-model.json` is a local convenience summary, not canonical storage
authority. Receipts and the creation manifest win over a stale or conflicting
projection. The first projection slice should use no-overwrite behavior and
must not replace the manifest, mutate receipts, refresh an existing read
model, or define final storage schema.

This projection slice is now implemented through
`project_measurement_record_read_model(...)` and
`project_measurement_record_read_model_from_read_view(...)`. It writes one
record-local `record-read-model.json` from the creation manifest, writer
receipt, read view, and finalization receipt, leaving all source artifacts
unchanged.

The first read-only catalog slice is implemented through
`catalog_measurement_record_read_models(...)` and
`catalog_measurement_record_read_models_from_request(...)`. It scans projected
read models under a caller-declared records directory, returns compact catalog
entries, and reports missing, malformed, conflicting, or source-digest-stale
projections as review findings. It does not refresh read models, repair
storage, replace manifests, or revalidate primary data.

The accepted explicit read-model refresh boundary recomputes
`record-read-model.json` from the creation manifest, writer receipt, read view,
and finalization receipt, writes a temporary record-local model, then atomically
replace only the derived read model. The previous read model is an overwrite
guard, not source evidence. Refresh must not replace manifests, mutate
receipts, repair primary data, or define canonical storage authority.

This refresh slice is now implemented through
`refresh_measurement_record_read_model(...)` and
`refresh_measurement_record_read_model_from_read_view(...)`. It supports
caller-declared `missing` and `replace_existing` target conditions; replacing
an existing read model requires the expected current digest.

Manifest replacement is not accepted for this prototype line.
`record-manifest.json` remains the immutable creation shell and origin
identity. Current lifecycle state, primary-data facts, and compact consumer
summaries are carried by receipts and refreshed read models instead.

The first durable import slice is implemented through
`import_measurement_record(...)` and `import_measurement_record_from_request(...)`.
It consumes reviewed normalized primary-data facts, creates a new record,
writes primary data through the writer integration, finalizes the record,
projects a read model, and returns a local durable import receipt. It does not
import into existing records, attach to pre-created shells, merge primary data,
replace manifests, or import linked-context payloads.
The import preflight validates the declared source digest, byte size, CSV table
shape, and row count before creating the durable record shell. If a later
pipeline step fails synchronously after record creation, the import path
best-effort removes the new record directory rather than leaving a partial
new-record import.

The first legacy-run storage slice is implemented through
`record_legacy_measurement_run(...)` and
`record_legacy_measurement_run_from_request(...)`. It records declared facts
about an externally executed legacy run by creating a Measurement Records shell
with `creation_source_kind: legacy_system` and writing one record-local
`legacy-run-receipt.json`. The receipt preserves declared legacy system/run
identity, optional timing labels, declared locators, optional context
references, and operator notes. It does not import primary data, observe
legacy files, parse old formats, execute legacy code, validate locator
availability, refresh read models, finalize lifecycle state, or decide
measurement validity.

The first storage-inventory slice is implemented through
`list_measurement_record_storage(...)` and
`list_measurement_record_storage_from_request(...)`. It scans a caller-declared
`records/` directory and lists visible record manifests, projected read models
when present, and record-local legacy receipts when present. It reports missing
or malformed manifests, read models, and legacy receipts as review findings.
It is read-only: it does not repair storage, refresh read models, observe
primary data, import legacy payloads, replace manifests, or persist GUI state.

The first in-progress update slice is implemented through
`append_in_progress_measurement_record(...)` and
`append_in_progress_measurement_record_from_request(...)`. It consumes an
existing `in_progress` creation manifest plus a record-local writer receipt,
then writes one append segment and one update receipt under no-overwrite
behavior. Second and later append requests must declare the previous update
receipt path so row progress remains contiguous without rewriting the writer
receipt. It does not merge the append segment into primary data, replace the
manifest, refresh the read model, finalize lifecycle state, or define crash
recovery.

The first running-inspection slice is implemented through
`inspect_running_measurement_record(...)` and
`inspect_running_measurement_record_from_request(...)`. It reads the base
writer-receipt-declared primary data plus caller-declared update receipts and
append segments, then returns a visible string-row table and progress summary
for local inspection. `summarize_running_measurement_inspection(...)` projects
a compact local summary with latest visible rows, progress, review finding
codes, and a next local action. These operations perform no storage mutation
and do not make append segments canonical primary data. Append segments are
validated as row-only CSV segments against the base primary table header during
inspection; repeated headers, empty segments, or row-width mismatches block the
inspection view rather than being shown as visible data rows.

The first existing-record append update slice is implemented through
`append_existing_measurement_record(...)` and
`append_existing_measurement_record_from_request(...)`. It consumes an
approved update request for a caller-declared existing record directory,
preflights the current manifest and primary-data digest/size facts, reads only
the declared append chunk, writes one new append segment and one update
receipt, and releases a direct record-local lock guard. It does not replace
the existing manifest, merge or compact primary data, refresh read models,
scan storage, define stale-lock cleanup or crash recovery, infer schema, or
make append segments canonical primary data.

The module also exposes a narrow read-only CLI smoke entrypoint:

```sh
python -m scopecat.measurement_records running-inspection-summary \
  --storage-root ./storage \
  --request-id inspect-run-001 \
  --record-id run-001 \
  --record-dir records/run-001 \
  --writer-receipt-path records/run-001/writer-receipt.json \
  --update-receipt-path records/run-001/updates/update-001-2.json
```

It prints the compact running-inspection JSON summary. It does not discover
records, scan update directories, mutate storage, or persist monitor state.

The first operator-review composition is implemented through
`review_measurement_records(...)` and
`review_measurement_records_from_request(...)`. It catalogs projected read
models, optionally runs caller-declared running inspections, and projects a
selected local record summary for operator review. It is read-only: it does
not refresh read models, discover update receipts, replace manifests, finalize
lifecycle state, mutate storage, or persist GUI review state. When a declared
running inspection intentionally surfaces an in-progress record, the
composition does not treat that same record's missing projected read model as
a top-level operator-review finding. Catalog entries whose projected read
model already carries review findings are still promoted into operator-review
findings, so a stale or incomplete read model does not appear ready merely
because its detailed finding object was embedded in the projection.

The CLI also exposes:

```sh
python -m scopecat.measurement_records operator-review \
  --storage-root ./storage \
  --request-id operator-review-001 \
  --selected-record-id run-001
```

Optional `--running-record-id`, `--running-record-dir`,
`--running-writer-receipt-path`, and repeated
`--running-update-receipt-path` arguments add one caller-declared running
inspection to the local review. For multiple declared running inspections, use
`--source ./operator-review-source.json` with the raw operator-review source
schema instead of growing ad hoc flags. Declared running inspections must have
unique request ids and unique record ids so the selected-record summary is not
ambiguous. When `--source` is present, request
shaping flags are rejected rather than silently ignored. Partial running flags
without `--running-record-id` are also rejected so declared running-inspection
intent is not dropped. The CLI remains a smoke surface; it does not scan for
update receipts or run import, refresh, finalization, repair, or GUI state
persistence.

The CLI can record declared legacy-run information and list local storage:

```sh
python -m scopecat.measurement_records record-legacy-run \
  --storage-root ./storage \
  --source ./legacy-run-source.json

python -m scopecat.measurement_records storage-inventory \
  --storage-root ./storage \
  --request-id inventory-001
```

These commands are smoke surfaces. `record-legacy-run` writes only the record
shell and record-local legacy receipt described by its source JSON.
`storage-inventory` scans only the declared records directory and does not
repair, refresh, import, observe legacy files, or infer primary-data shape.

The first saved operator-review receipt boundary is implemented through
`save_measurement_record_operator_review_receipt(...)` and
`summarize_measurement_record_operator_review_receipt(...)`. It takes an
already computed operator-review run plus an approved receipt request, writes
one local no-overwrite receipt, and projects a compact continuation summary.
Receipt paths must stay under `operator-reviews/`; they cannot be materialized
inside record directories. The summary path validates the saved receipt posture,
policy, approval state, disposition, review finding shape, and embedded summary
continuity before emitting a compact summary. It also validates the receipt and
embedded review non-claim posture, and recomputes the embedded review
classification, selected-record posture, and next action from the saved review
snapshot before projecting the local summary. If the operator selected a record
that was not visible in the review, the summary preserves the requested
`selected_record_id` with `selected_record_source: not_visible` instead of
pretending a record summary was available. The receipt summary accepts only
review/navigation `next_action` values and public-safe request identifiers. The
receipt parser keeps selected-record posture as a private helper rather than
promoting a shared record domain model.
The saved receipt is a local continuation note only: it does not resolve
findings, approve import, approve refresh, grant retry authority, mutate
records, or persist canonical GUI review state.

The CLI can summarize a saved operator-review receipt:

```sh
python -m scopecat.measurement_records operator-review-receipt-summary \
  --receipt-path ./storage/operator-reviews/review-001.json
```

This command reads one caller-declared receipt JSON and prints the compact
continuation summary. It does not reopen records, re-run review, grant retry
authority, approve refresh/import, mutate storage, or persist GUI state.
