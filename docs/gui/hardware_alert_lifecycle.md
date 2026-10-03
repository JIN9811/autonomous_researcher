# Hardware alert lifecycle

Use this page when a device appears healthy again but Live GUI still shows an
alert or the run is paused. An **active** alert can block progress. A **resolved**
alert is retained history, including the observation that cleared it; neither
status by itself starts or resumes equipment.

## Check whether the fault is current

1. Read the Guardian report's gate/incident evidence and the device owner's
   report. Match the device profile and connection identity, not just the run ID.
2. Inspect a fresh device monitor observation. For the narrowly eligible Bambu
   error described below, a qualifying healthy report can resolve the alert
   automatically; restarting the server or acknowledging old history is not
   required to make that observation count.
3. If the alert resolves, check the printer's job state separately. A failed,
   cancelled or paused job does not become a completed or resumed job. Use the
   [matching recovery procedure](run_resume.md) before requesting Resume.
4. If the alert stays active, retain the reason code, incident ID and observation
   timestamp. E-STOP/PLC, latched interlocks and unknown error classes need their
   explicit recovery path. Do not clear them by changing profiles or dismissing
   history.

## Resolution rules and retained history

Hardware history and active blocking evidence use a common lifecycle in the
controller, LangGraph runtime, Guardian pre-gates, Guardian agent, and Knowledge
incident projection. Resolving an alert does not erase its original code,
timestamp, run/cycle/job attribution, or incident record. A resolution includes
the newer observation that justified it. Replaying the same alert ID cannot
reactivate it; a new incident ID can block again.

Automatic resolution is deliberately narrow: a non-latching Bambu
`printer.status` / `BAMBU_DEVICE_ERROR` observation, explicitly marked
`fresh_matching_device_report`, requires a physical MQTT report no more than
five seconds old, from the same printer profile and connection identity, with
an observed zero error code and a known job state. Terminal job states (`FAILED`,
`FAIL`, `CANCELLED`, `CANCELED`, `ABORTED`) and paused jobs may remain in telemetry
after the device fault clears; they do not prevent resolution. Resolution never
changes the job state, issues a command, or resumes a paused run. The independent
printer-start and safety gates still apply. Successful upload,
cached/unknown telemetry, a simulated bridge, a different printer, or elapsed
time alone cannot resolve it. Profile connection changes invalidate identity.

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
