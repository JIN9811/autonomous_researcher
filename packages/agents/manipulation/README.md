# Manipulation agent package

The Manipulation agent owns bounded manipulation decisions and the existing
composite transfer and UTM-clear workflows. It depends on the installed
`lerobot@1.0.0` bridge for actual rollout, replay, stop, and robot execution.

The package is a declarative composition contract, not a device or a second
runtime. Configuration, session state, calibration, datasets, and run evidence
remain in their existing stores and are not bundled into exported packages.
