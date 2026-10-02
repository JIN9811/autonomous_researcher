# Bambu compatibility paths

The implementation belongs to the single [Printer Fleet package](../printer_fleet/README.md).
`bridge.py` and `autoejection.py` only alias its canonical modules, preserving
legacy imports and monkeypatches. This directory is not a separate bridge package.

`paho-mqtt` is optional at import time and required for the existing live MQTT
path. Shared placement/material helpers use Pydantic; explicit-position STL
preflight lazily imports NumPy and trimesh. Their requirements retain the
existing root dependency floors. FTP/TLS/sockets use stdlib. External slicers and ffmpeg remain separately
configured applications, not pip dependencies. This move installs nothing.

State remains at `memory/bambu_connection.json` and `memory/printer_fleet.json`.
Removing composition references never removes those files or print artifacts.
