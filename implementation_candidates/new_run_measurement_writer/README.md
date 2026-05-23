# New Run Measurement Writer

Experimental implementation candidate for summarizing a new-run measurement
record from explicit writer events.

This candidate is deliberately side-effect free. It validates event order,
declared preview metadata, progress facts, and boundary policy without writing
storage, reading primary data files, controlling hardware, opening GUIs, or
inferring schemas.
