# Contract Tests

Contract tests protect behavior that interchangeable adapters, private
integrations, or durable workspace readers must be able to trust while internal
implementations change.

Use a shared contract suite when more than one repository or adapter implements
the same port. Use serialized golden data only for an intentionally durable
boundary record. Import-direction tests are appropriate when dependency
direction is itself the protected boundary.

Keep implementation details in ordinary unit or integration tests. Do not add
contract tests for private helper placement, complete storage layouts, Markdown
wording, transient compiler shapes, or derived snapshots unless the artifact is
itself a supported boundary record.
