# Python API reference

Scopecat has three public authoring surfaces:

- [`scopecat`](scopecat.md) is the high-level experiment and notebook facade.
- [`scopecat_instruments`](instruments.md) exposes generated typed instrument
  clients and state models.
- [`scopecat_quantum.authoring`](quantum.md) exposes hardware-independent quantum
  authoring constructs.

The reference intentionally does not enumerate compiler, storage, wire, or
generated implementation modules. Extension authors should import explicit
contracts from their owning public modules as described by the extension guides.
