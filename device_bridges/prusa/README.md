# Prusa provider

`bridge.py` owns PrusaLink, PrusaSlicer, safety validation and
`PrinterAgenticWorkflow`. The flat `device_bridges.prusa_bridge` import aliases
this module object. `httpx` is the direct third-party dependency. PrusaSlicer
is an external executable, not a pip dependency; package import installs nothing.

Connection state remains at `memory/prusa_connection.json`; G-code uses the
existing configured artifacts directory. Package import never reads connection
state, invokes the workflow or activates a device.
