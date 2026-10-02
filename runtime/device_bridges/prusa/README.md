# Prusa compatibility paths

`bridge.py` aliases the internal provider in the single
[Printer Fleet package](../printer_fleet/README.md), which owns PrusaLink,
PrusaSlicer, safety validation and `PrinterAgenticWorkflow`. The flat
`device_bridges.prusa_bridge` import shares that module object. This directory
is not a separate bridge package. `httpx` is the direct dependency. PrusaSlicer
is an external executable, not a pip dependency; package import installs nothing.

Connection state remains at `memory/prusa_connection.json`; G-code uses the
existing configured artifacts directory. Package import never reads connection
state, invokes the workflow or activates a device.
