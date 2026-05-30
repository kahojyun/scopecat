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
