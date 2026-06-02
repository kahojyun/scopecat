# Discovery Policies

## Status

Discovery policy navigation index.

Policies record repeated boundary vocabulary and product posture that more than
one route or slice may need. They do not accept final product architecture,
storage schema, or public API behavior unless a narrower decision document says
so.

## Current Policies

| Policy | Use For |
| --- | --- |
| [`artifact-boundary-and-redaction.md`](artifact-boundary-and-redaction.md) | Distinguish repository-safe discovery artifacts and local UI/review surfaces from portable/public/export boundaries. |
| [`artifact-preview-boundary.md`](artifact-preview-boundary.md) | Separate arbitrary artifacts from Scopecat-declared previewable data items. |
| [`complex-response-boundary.md`](complex-response-boundary.md) | Treat complex-valued responses as logical value metadata over declared previewable data items. |
| [`external-file-reference.md`](external-file-reference.md) | Candidate vocabulary for external files, latest state, observed file state, and non-backup boundaries. |
| [`managed-experiment-code-posture.md`](managed-experiment-code-posture.md) | Product posture for Git-like managed experiment-code versions without requiring users to operate Git. |
| [`measurement-data-reference-boundary.md`](measurement-data-reference-boundary.md) | Distinguish normalized primary data from external source references, attachments/artifacts, and previewable data items. |
| [`package-purpose-boundary.md`](package-purpose-boundary.md) | Separate analysis/review packages, shared lab references, and future offline execution migration. |
