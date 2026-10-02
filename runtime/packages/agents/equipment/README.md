# Equipment agent package

The Equipment agent owns bounded workflow selection, terminal evidence review,
recovery admission and Analysis handoff decisions. It depends on the installed
`windows_pyautogui@1.0.0` bridge for actual desktop and UTM execution.

This package is a declarative composition contract, not a device or a second
runtime. Existing Profile, Skill, stacked Flow, workspace, connection, runtime
and run-evidence stores retain their current paths and precedence. Installing or
inspecting the package does not start a worker or authorize hardware execution.
