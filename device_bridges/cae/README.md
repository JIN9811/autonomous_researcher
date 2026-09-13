# Computational CAE bridge

This bridge owns the existing deterministic CAE implementation, guarded
CalculiX implementation, tool registrations, and the shared `cae:calculix`
queue. It is a computational Middle boundary, not a physical Low device.

Discovery reads metadata only. It does not construct a bridge, probe a native
solver, or start a worker. Native execution retains the existing configuration
and runtime gates. PINN registration remains inactive and shared outside this
bridge.
