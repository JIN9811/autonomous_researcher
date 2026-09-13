# Analysis agent package

The Analysis agent owns measured-data evaluation, bounded model decisions,
objective and BO handoffs, and its existing background improvement lifecycle.
It depends on the installed `cae@1.0.0` computational bridge for deterministic
CAE and guarded CalculiX work.

The package is declarative. Inspecting it does not instantiate a solver, resume
a background job, or change the lifetime of the existing Analysis resource.
PINN remains inactive and shared.
