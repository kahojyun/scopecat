# Encode typed command payloads

Command payloads carry domain-specific programs from planning code to an
instrument worker. They are distinct from measurement results, configuration
documents, and a vendor device protocol. A payload codec should preserve that
domain value without making every author implement JSON conversion, array
framing, content hashing, or transport envelopes.

Use the narrowest of Scopecat's three public codec layers:

| Need | API |
|---|---|
| Encode an existing byte format | `byte_payload_codec` |
| Encode a typed value without assigning a command schema | `pydantic_buffer_bundle_value_codec` |
| Register and transport a typed command payload | `PayloadContract` with `pydantic_buffer_bundle_codec` |

Schemas are required only at the command boundary, where independently loaded
planning and worker code must agree on domain meaning. Local typed
serialization does not require schema registration.

## Define one array-aware value

Use a strict frozen Pydantic model for a command document. NumPy arrays stay as
binary buffers; they do not become JSON number lists. A value may contain any
number of arrays, including arrays nested inside records, tuples, lists, or
string-keyed mappings.

```python
from typing import ClassVar

import numpy as np
import scopecat as sc
from pydantic import BaseModel, ConfigDict, Field


class WaveformProgram(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    id: str = Field(min_length=1)
    waveforms: tuple[sc.FrozenFloat64Vector, ...] = Field(min_length=1)
    repetitions: int = Field(gt=0)


program = WaveformProgram(
    id="readout",
    waveforms=(np.linspace(-0.25, 0.25, 1024),),
    repetitions=1000,
)
```

`FrozenFloat64Vector` validates a real numeric vector, converts it to float64,
and snapshots it into immutable storage. The structured codec also supports
arbitrary-dimensional NumPy arrays with bool, unsigned integer, signed integer,
float, or complex dtype. Object arrays are rejected. Decoded arrays are
C-contiguous, little-endian, immutable views over their attachment storage.

## Serialize without a schema

A `StructuredValueCodec` is useful for an internal cache, an application-owned
carrier, or another typed boundary that does not participate in command
dispatch:

```python
value_codec = sc.pydantic_buffer_bundle_value_codec(WaveformProgram)

bundle = value_codec.encode(program)
restored = value_codec.decode(bundle)
```

The returned bundle contains one deterministic JSON header and one ordered
attachment for each array or byte field. Multipart transports can consume
those parts directly. A carrier that requires one object can use the bundle's
canonical flat representation without changing the value codec.

## Bind the value to a command contract

Declare the schema and codec together, then reuse that contract in planning and
worker code:

```python
WAVEFORM_PROGRAM = sc.PayloadContract(
    schema_id="my_lab.waveform-program/v1",
    codec=sc.pydantic_buffer_bundle_codec(WaveformProgram),
)


def payload_codecs() -> sc.PayloadCodecRegistry:
    return sc.PayloadCodecRegistry.from_contracts(WAVEFORM_PROGRAM)
```

Planning code creates either a local tagged value or a complete transport
payload without repeating descriptor fields:

```python
symbolic_value = WAVEFORM_PROGRAM(program)
command_payload = WAVEFORM_PROGRAM.command_payload("load-readout", program)
```

The same contract validates schema id, codec id, codec version, media type, and
content format before decoding at the worker. Change the schema id when domain
meaning changes. Change the codec version when the encoded representation
changes while its domain meaning remains compatible.

## Adapt an existing byte codec

Keep a deliberate binary or JSON format when it already is the domain
contract. The byte adapter lets it use the same registry and validation path:

```python
legacy_codec = sc.byte_payload_codec(
    id="my_lab.existing-binary",
    version=3,
    media_type="application/octet-stream",
    encoder=encode_existing_program,
    decoder=decode_existing_program,
)
```

This adapter is also the migration path for callers that previously constructed
`PayloadCodec` with byte-returning functions directly.

## Understand copies and carriers

The in-memory path keeps a header and attachments separate:

```text
typed value -> structured value codec -> attachment bundle
            -> payload contract -> command descriptor
            -> worker multipart frames -> typed value
```

An HTTP or content-addressed blob boundary deliberately flattens the bundle to
one canonical object. The daemon restores its parts before worker IPC, so it
does not repeatedly join arrays between server and worker. Content identity is
computed over the same canonical representation without first materializing
another joined copy.

Measurement results continue to use their Arrow and measurement-array formats,
and drivers continue to implement vendor protocols separately. Those formats
have different schema, persistence, and interoperability requirements and are
not command-payload codec implementations.

## Coordinate format upgrades

The current structured payload format, worker invocation wire, and hardware
receipt wire are version 2. `CommandPayload` also requires a `content_format`
descriptor. This early implementation deliberately does not retain legacy
decoders.

Deploy a format change as one coordinated update of the daemon, project worker,
instrument workers, and private provider packages. Stop old workers first;
discard in-flight worker messages and transient command-payload spools; and
regenerate encoded fixtures. Durable domain data and measurement Arrow objects
are not command payloads and do not need conversion.

Bundles enforce bounded header, attachment-count, per-attachment, and aggregate
sizes at untrusted boundaries. Treat a limit failure as a request-design issue;
do not add a second ad hoc framing format to bypass it.
