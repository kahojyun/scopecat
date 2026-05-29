# Calibration Continuation Route Input Contract Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It validates a narrow input contract for a future calibration continuation
route. The candidate records which upstream facts are required to render the
route, which supporting facts may be unavailable with attention, and which
facts are only carried as references owned by other slices.

The package does not implement a GUI, execute calibration or fit code, score
results, read measurement payloads, resolve references, replay cases, apply
parameter writes, provide a runner, implement a dataset registry, emit a
portable/public dataset package, or control hardware.
