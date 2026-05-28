# Existing Record Update Candidate

This implementation candidate validates one approved append update against an
existing measurement record directory.

The candidate is intentionally narrower than a final storage update model. It
requires explicit current-record facts, first checks that the existing record
directory is present without creating it, acquires a direct record-local lock
guard, checks one declared existing manifest and primary-data file, and writes
only new append-segment and update-receipt files. It does not rewrite the
current primary data, replace the manifest, compact segments, infer schemas,
scan storage, define lock identity, define a live service, define crash
recovery, or control hardware.
