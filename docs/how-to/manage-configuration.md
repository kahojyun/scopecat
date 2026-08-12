# Review and publish project configuration

A project's `src/<package>/configuration.py` is ordinary version-controlled
Python. The daemon owns the accepted configuration history; it does not watch or
rewrite that source file.

Validate the source without starting the daemon:

```sh
scopecat config check ./my-lab
```

With the project daemon running, compare a freshly evaluated source snapshot
with the current daemon default:

```sh
scopecat config diff ./my-lab
```

Review the diff, then explicitly publish it with an operator identity and useful
audit note:

```sh
scopecat config apply ./my-lab \
  --actor alice \
  --note "add readout VNA and reviewed defaults"
```

Export a complete JSON snapshot for review or backup:

```sh
scopecat config export ./my-lab --output ./active-config.json
```

The exported JSON is generated state, not the primary editing format. Continue
editing the project's Python configuration source and use `diff` and `apply` for
subsequent changes.
