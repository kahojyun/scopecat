# Workspace Materialization Implementation Candidate

Experimental implementation candidate for the workspace materialization
validation slice.

The candidate creates an editable workspace from a selected managed code
version only when the request is explicitly approved and the caller provides
the managed-content root and workspace root.

Boundary:

- writes only declared content-available files;
- creates target directories as needed;
- refuses overwrites by reporting existing target paths;
- reports redacted and unavailable files without creating placeholders;
- validates declared content size and sha256 digest before writing;
- does not restore environments, import code, execute code, inspect Git state,
  merge folders, delete files, or define final managed-workspace storage.
