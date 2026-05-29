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
