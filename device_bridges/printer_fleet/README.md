# Printer Fleet Device Bridge Package

`module.MODULE.describe()` publishes the single installed `printer_fleet@1.0.0`
shared by referring Agent Packages, provider components, existing 3DP UI/API
and storage references. It never reads connection files or creates transports.

`printer_fleet` is one Device Bridge Package. Bambu and Prusa are internal
provider implementations, not separate installable bridge packages.

```text
device_bridges/printer_fleet/
  module.py                 # Declarative package/IDE contract
  bridge.py                 # Shared manager and existing Bambu runtime
  requirements.txt          # One dependency entry point
  providers/
    bambu.py                # Internal alias to the shared runtime
    bambu_autoejection.py   # File-only G-code transformer
    bambu-requirements.txt
    prusa.py                # PrusaLink and slicer workflow
    prusa-requirements.txt
```

`mcp_tools.printer_tools.register_printer_tools` still owns `printer.prepare`
and `device.health`; it calls the canonical fleet manager and Prusa workflow.
Provider selection, payloads, execution gates, artifact and connection paths are
unchanged. Bambu transport classes remain with the shared manager to preserve
existing global dependencies and monkeypatch behavior; this is package
consolidation, not a rewrite of the transport runtime.

The old `bambu_bridge`, `prusa_bridge`, `bambu_autoejection`, `bambu/bridge`,
`bambu/autoejection`, and `prusa/bridge` imports are compatibility aliases to
the same canonical module objects. Their former requirements files forward
to the internal provider requirements. They do not register extra packages.

| Internal provider | Dependencies | External applications |
|---|---|---|
| Bambu | paho-mqtt, Pydantic; NumPy/trimesh for placement preflight | Configured slicer and ffmpeg |
| Prusa | httpx | Configured PrusaSlicer |

In Runtime IDE, **Device Bridges** shows Agent Package → Printer Fleet →
internal provider relationships and a node Inspector. **Package Manager** is
separate: draft membership and Experimental Package import/export live there.
Use the existing `/printer` workspace for connection setup and device operations.

Experimental Package bindings are symbolic requirements. Configure credentials
through the existing printer UI. Removing a reference neither uninstalls the
bridge nor deletes its storage.
