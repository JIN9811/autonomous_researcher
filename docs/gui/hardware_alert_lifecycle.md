# Hardware alert lifecycle

Hardware history and active blocking evidence use a common lifecycle in the
controller, LangGraph runtime, Guardian pre-gates, Guardian agent, and Knowledge
incident projection. Resolving an alert does not erase its original code,
timestamp, run/cycle/job attribution, or incident record. A resolution includes
the newer observation that justified it. Replaying the same alert ID cannot
reactivate it; a new incident ID can block again.

Automatic resolution applies only to non-latching Bambu
`printer.status` / `BAMBU_DEVICE_ERROR` observations. It requires all of the following:

- The report is marked `fresh_matching_device_report`.
- Physical MQTT telemetry is no more than five seconds old.
- Printer profile and connection identity match the alert.
- The observed error code is zero and the job state is known.

Terminal job states (`FAILED`, `FAIL`, `CANCELLED`, `CANCELED`, `ABORTED`) and
paused jobs do not prevent fault resolution. Resolving the fault does not change
the job state, issue a command or resume a run; printer-start and safety gates
still apply.

A successful upload, cached/unknown telemetry, simulated bridge, different
printer or elapsed time alone cannot resolve an alert. Changing a profile's
connection invalidates its identity.

Both successful GUI monitor updates and a bounded read-only refresh before a
runtime stage's Guardian gate can resolve eligible alerts. The latter does not
depend on an open browser and never uploads, prints, ejects, or moves equipment.
Guardian's own device-health check uses the same resolution rules. Failures and
timeouts preserve the active fault.

The first qualifying healthy monitor report resolves the alert and its explicitly
linked hardware incident. It does not require an IDLE transition, another job,
operator acknowledgement, or a server restart.

E-STOP/PLC flags, active safety sources, critical/latched interlocks, explicit
acknowledgement requirements, unknown error classes, and legacy records without
reliable device identity are not automatically cleared. They retain the existing
explicit recovery path. Device faults are not dismissed merely because the run
or printer job changed. Job/run IDs are provenance, not proof that a physical
fault is gone. Only resolved history is trimmed; unresolved faults are retained.

These changes require the normal server deployment/restart. They must not be
hot-swapped into active device/controller instances during an experiment.
