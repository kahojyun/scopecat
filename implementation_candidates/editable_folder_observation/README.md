# Editable Folder Observation Implementation Candidate

Experimental implementation candidate for the editable folder observation
validation slice.

The candidate observes a caller-provided editable workspace root against a
selected managed code version. It reads file bytes only to compute size and
sha256 facts for expected content-available files and extra observed files.

Boundary:

- inspects only the selected workspace root;
- treats the selected managed-version inventory as the authoritative include
  list for strong code-surface findings;
- treats extra workspace files as bounded, non-authoritative observations;
- skips declared workspace-internal directory names such as `.git`, `.venv`,
  caches, notebook checkpoints, and tool output directories during extra-file
  observation;
- compares declared content-available files by size and sha256 digest;
- reports missing, changed, same-observed, redacted, unavailable, and extra
  observed files;
- treats symlinks as observable path findings without following them;
- does not mutate files, inspect Git state, restore environments, import code,
  execute code, infer semantic source diffs, or define prepared-run readiness.
