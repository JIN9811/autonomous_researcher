# Bambu provider

`bridge.py` owns Bambu and the shared `PrinterDeviceBridgeManager`. The flat
`device_bridges.bambu_bridge` import aliases this module object, preserving
legacy monkeypatches. Fleet references the manager without duplicating it.
`autoejection.py` owns the G-code patcher; the flat
`device_bridges.bambu_autoejection` import is also a module identity alias.

`paho-mqtt` is optional at import time and required for the existing live MQTT
path. Shared placement/material helpers use Pydantic; explicit-position STL
preflight lazily imports NumPy and trimesh. Their requirements retain the
existing root dependency floors. FTP/TLS/sockets use stdlib. External slicers and ffmpeg remain separately
configured applications, not pip dependencies. This move installs nothing.

State remains at `memory/bambu_connection.json` and `memory/printer_fleet.json`.
Removing composition references never removes those files or print artifacts.
