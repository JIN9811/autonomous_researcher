"""Hardware history is not current blocking authority.

Only an explicitly auto-resolvable device observation with a newer, matching,
fresh physical report can be resolved here. Unknown/legacy/manual/interlock
alerts remain active; age alone never clears an alarm.
"""
from copy import deepcopy
from datetime import datetime, timezone
import math

MAX_REPORT_AGE_SECONDS = 5.0
AUTO_CODE = 'BAMBU_DEVICE_ERROR'
# A terminal/paused job is not a current device fault. Start/resume permission
# is checked separately by the printer command gate, never granted here.
OBSERVED_JOB_STATES = {'IDLE', 'FINISH', 'RUNNING', 'PREPARE', 'SLICING',
    'FAILED', 'FAIL', 'CANCELLED', 'CANCELED', 'ABORTED', 'PAUSE', 'PAUSED'}


def _time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp if stamp.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def observation(result):
    """Extract sanitized monitor evidence, never credentials/connection data."""
    if not isinstance(result, dict):
        return {}
    health = result.get('health') if isinstance(result.get('health'), dict) else result
    selected = health.get('selected_printer') or result.get('selected_printer') or {}
    mqtt = health.get('mqtt_snapshot') or {}
    selected = selected if isinstance(selected, dict) else {}
    mqtt = mqtt if isinstance(mqtt, dict) else {}
    return {'device_class':'printer', 'device_id':str(selected.get('profile_id') or ''),
        'device_identity':health.get('device_identity'),
        'provider':health.get('provider') or result.get('provider'),
        'physical':health.get('physical_transport') is True,
        'ok':health.get('ok') is True, 'failure_code':health.get('failure_code') or '',
        'received_at':mqtt.get('received_at'), 'report_ok':mqtt.get('ok') is True,
        'device_error':health.get('device_error'),
        'error_fields_observed':health.get('error_fields_observed') is True,
        'job_id':str(health.get('observed_job_id') or ''),
        'state':str(health.get('observed_job_state') or '')}


def stamp_alert(alert, state, result=None):
    value = deepcopy(alert)
    value.setdefault('lifecycle', 'active')
    value.setdefault('run_id', state.run_id)
    value.setdefault('loop_id', state.loop_count)
    value.setdefault('scope', 'device')
    obs = observation(result or {})
    if obs.get('device_id'):
        value.setdefault('device_id', obs['device_id'])
        value.setdefault('job_id', obs.get('job_id', ''))
        value.setdefault('device_identity', obs.get('device_identity'))
    # Generic requires_ack historically meant "a blocking alert", not a PLC
    # latch. New non-latching monitor alerts have an explicit policy instead.
    if (value.get('device_class') == 'printer' and value.get('tool') == 'printer.status'
            and value.get('failure_code') == AUTO_CODE and obs.get('device_id')
            and obs.get('physical') and obs.get('error_fields_observed') and obs.get('device_identity')
            and not any(value.get(k) for k in ('manual_reset_required', 'latched', 'safety_interlock'))
            and value.get('severity') != 'critical' and not value.get('requires_ack')):
        value['resolution_policy'] = 'fresh_matching_device_report'
    else:
        value.setdefault('resolution_policy', 'explicit_recovery')
    return value


def is_active(alert):
    if not isinstance(alert, dict) or not alert.get('blocks_workflow', alert.get('severity') in {'blocking','critical'}):
        return False
    return alert.get('lifecycle', alert.get('status')) not in {'resolved', 'closed', 'dismissed'}


def active_alerts(state):
    values = state.run_metadata.get('hardware_alerts', [])
    return [a for a in values if is_active(a)] if isinstance(values, list) else []


def record_alert(state, alert, result=None):
    """Merge once; replaying an old result cannot reopen its resolved alert."""
    alerts = state.run_metadata.setdefault('hardware_alerts', [])
    if not isinstance(alerts, list):
        alerts = state.run_metadata['hardware_alerts'] = []
    identifier = alert.get('alert_id')
    existing = next((a for a in alerts if isinstance(a, dict) and identifier and a.get('alert_id') == identifier), None)
    if existing is not None:
        return existing
    value = stamp_alert(alert, state, result)
    if value.get('resolution_policy') == 'fresh_matching_device_report':
        identity = ('device_class','device_id','device_identity','failure_code','tool','run_id','job_id')
        repeated = next((a for a in alerts if is_active(a)
            and a.get('resolution_policy') == value['resolution_policy']
            and all(a.get(k) == value.get(k) for k in identity)), None)
        if repeated is not None:
            repeated['repeat_count'] = int(repeated.get('repeat_count', 1)) + 1
            prior, incoming = _time(repeated.get('last_seen_at') or repeated.get('created_at')), _time(value.get('created_at'))
            if incoming and (prior is None or incoming > prior):
                repeated['last_seen_at'] = value['created_at']
            repeated['last_observed_alert_id'] = value.get('alert_id')
            return repeated
    alerts.append(value)
    # Retain all unresolved alerts; only old resolved history is bounded here.
    history = [a for a in alerts if not is_active(a)][-50:]
    alerts[:] = [a for a in alerts if is_active(a) or any(a is h for h in history)]
    if is_active(value):
        state.device_health[value.get('device_class') or 'hardware'] = (
            f"{value.get('severity') or 'warning'}:{value.get('failure_code') or value.get('status') or 'alert'}")
    return value


def reconcile(state, result, *, now=None):
    obs = observation(result)
    now = now or datetime.now(timezone.utc)
    stamp = _time(obs.get('received_at'))
    age = (now - stamp).total_seconds() if stamp else math.inf
    if (not obs.get('device_id') or not obs.get('device_identity') or not obs.get('physical') or not obs.get('ok')
            or not obs.get('report_ok') or obs.get('failure_code')
            or not obs.get('error_fields_observed') or str(obs.get('device_error')) not in {'0','0.0','0x0','0x00000000'}
            or not 0 <= age <= MAX_REPORT_AGE_SECONDS
            or obs.get('state').upper() not in OBSERVED_JOB_STATES):
        return []
    events = []
    for alert in active_alerts(state):
        created = _time(alert.get('last_seen_at') or alert.get('created_at'))
        if (alert.get('resolution_policy') != 'fresh_matching_device_report'
                or alert.get('device_class') != obs['device_class']
                or alert.get('device_id') != obs['device_id']
                or alert.get('device_identity') != obs['device_identity']
                or alert.get('failure_code') != AUTO_CODE
                or alert.get('requires_ack') or alert.get('severity') == 'critical'
                or any(alert.get(k) for k in ('manual_reset_required','latched','safety_interlock'))
                or created is None or created >= stamp):
            continue
        alert.update(lifecycle='resolved', blocks_workflow=False,
            resolved_at=now.isoformat(), resolution={'reason':'fresh_matching_device_report', 'observation':deepcopy(obs)})
        # Close only this monitor alert's incident; unrelated/ambiguous incidents
        # and all manual/PLC safety holds keep their own recovery requirements.
        incidents = state.run_metadata.get('incident_records', [])
        linked = [alert.get('incident_record')]
        if isinstance(incidents, list):
            linked.extend(incidents)
        for incident in linked:
            if (isinstance(incident, dict) and alert.get('alert_id')
                    and incident.get('incident_id') == alert['alert_id']
                    and incident.get('source') == 'hardware_alert'):
                incident.update(status='resolved', resolved_at=now.isoformat(),
                    resolution=deepcopy(alert['resolution']))
        events.append({'schema':'hardware_alert_resolution.v1','alert_id':alert.get('alert_id'),
            'run_id':state.run_id,'loop_id':state.loop_count,'created_at':now.isoformat(),
            'resolution':deepcopy(alert['resolution'])})
    if events and not any(a.get('device_class') == 'printer' for a in active_alerts(state)):
        if state.device_health.get('printer') == 'blocking:' + AUTO_CODE:
            state.device_health['printer'] = 'ready'
    if events:
        history = state.run_metadata.setdefault('hardware_alert_resolutions', [])
        history.extend(deepcopy(events))
        del history[:-100]
    return events


async def refresh_before_gate(state, tools):
    """No GUI required: bounded read-only refresh of explicitly eligible alerts."""
    import asyncio
    if any(getattr(state, key, False) for key in ('stop_requested','safe_stop_requested','emergency_stop_requested')):
        return []
    if state.run_metadata.get('active_safety_sources'):
        return []
    profiles = {a.get('device_id') for a in active_alerts(state)
        if a.get('resolution_policy') == 'fresh_matching_device_report' and not a.get('requires_ack')
        and a.get('device_class') == 'printer' and a.get('device_id')}
    events = []
    for profile in sorted(profiles)[:4]:
        try:
            result = await asyncio.wait_for(asyncio.to_thread(tools.call, 'printer.prepare', {
                'runtime_mode':'live', 'printer_profile_id':profile,
                'health_only':True, 'status_only':True, 'skip_ftps_probe':True}), timeout=8)
        except Exception:
            continue
        events.extend(reconcile(state, result))
    return events
