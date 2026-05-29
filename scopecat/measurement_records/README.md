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
