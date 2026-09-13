# Windows/PyAutoGUI equipment bridge

This installed bridge packages the existing Windows and local PyAutoGUI runtime
under one `windows_pyautogui@1.0.0` identity. It retains the current registered
`equipment.pyautogui.*` and `equipment.runtime.*` tool IDs, the
`equipment:windows_pyautogui` device queue, and runtime alias
`windows_pyautogui_bridge`.

The package declaration is metadata only. Inspection does not construct a
bridge, scan a network, start the bundled server, connect to a Windows host, or
run a macro. Live execution continues to require the existing connection,
profile, approval, preflight, Guardian, evidence and handoff gates.

The worker/server sources, `/equipment/windows` workspace, configuration,
profiles, Skills, Flow definitions, runtime records and artifact stores remain
at their existing repository paths. Mutable connection values, equipment
profiles and run evidence are referenced by the runtime and are not included in
exported package drafts.
