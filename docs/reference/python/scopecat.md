# `scopecat`

The package root is the supported import facade for experiments and notebooks.
It is implemented with lazy exports, so the generated sections below document
the public objects at their owning modules while examples continue to use
`import scopecat as sc`.

## Project discovery

::: scopecat.project.Project
    options:
      show_bases: false
      show_root_full_path: false
      show_signature_annotations: true

::: scopecat.project.open_project
    options:
      show_root_full_path: false
      show_signature_annotations: true

## Experiment authoring

::: scopecat.authoring
    options:
      filters:
        - "!^_"
        - "!.*_internal$"
      show_bases: false
      show_root_full_path: false
      show_signature_annotations: true
