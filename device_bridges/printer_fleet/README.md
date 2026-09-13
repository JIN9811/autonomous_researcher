# Printer Fleet module

`module.MODULE.describe()` publishes the single installed `printer_fleet@1.0.0`
shared by referring Agent Packages, provider components, existing 3DP UI/API
and storage references. It never reads connection files or creates transports.

`mcp_tools.printer_tools.register_printer_tools` still owns `printer.prepare`,
`device.health`, provider selection and execution gates. Bambu's shared manager
stays in `device_bridges.bambu.bridge`; Prusa's workflow stays in
`device_bridges.prusa.bridge`. Requirements list both existing providers.

Experimental Package bindings are symbolic requirements. Configure credentials
through the existing printer UI. Removing a reference neither uninstalls the
bridge nor deletes its storage.
