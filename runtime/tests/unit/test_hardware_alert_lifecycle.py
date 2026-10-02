from copy import deepcopy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest

from utils.hardware_alert_lifecycle import record_alert, reconcile, active_alerts, refresh_before_gate


def fixture():
    now=datetime.now(timezone.utc)
    state=SimpleNamespace(run_id='run-2',loop_count=2,run_metadata={},device_health={},
        stop_requested=False,safe_stop_requested=False,emergency_stop_requested=False)
    report={'ok':True,'state':'COMMUNICATION_READY','provider':'bambulab_x2d','selected_printer':{'profile_id':'printer-a'},
        'device_identity':'physical-a','physical_transport':True,'device_error':'0',
        'error_fields_observed':True,'observed_job_id':'job-2','observed_job_state':'RUNNING',
        'mqtt_snapshot':{'ok':True,'received_at':now.isoformat()}}
    alert={'alert_id':'fault-1','device_class':'printer','tool':'printer.status',
        'failure_code':'BAMBU_DEVICE_ERROR','blocks_workflow':True,'severity':'blocking',
        'requires_ack':False,'created_at':(now-timedelta(seconds=20)).isoformat()}
    return state,report,alert,now


def test_resolves_matching_new_observation_preserves_history_and_does_not_reopen():
    state,report,alert,now=fixture()
    record_alert(state,alert,{**report,'ok':False,'device_error':'123'})
    assert active_alerts(state)
    events=reconcile(state,report,now=now)
    assert len(events)==1 and not active_alerts(state)
    stored=state.run_metadata['hardware_alerts'][0]
    assert stored['failure_code']=='BAMBU_DEVICE_ERROR' and stored['lifecycle']=='resolved'
    assert stored['run_id']=='run-2' and stored['job_id']=='job-2'
    assert state.device_health['printer']=='ready'
    record_alert(state,alert)
    assert len(state.run_metadata['hardware_alerts'])==1 and not active_alerts(state)
    # A genuinely new fault must block again.
    record_alert(state,{**alert,'alert_id':'fault-2'},report)
    assert len(active_alerts(state))==1


@pytest.mark.parametrize('change', ['stale','future','unknown','offline','no_error_field',
    'different_device','reconfigured_profile','simulation','error','no_mqtt','missing_identity'])
def test_missing_or_mismatching_evidence_never_clears(change):
    state,report,alert,now=fixture()
    record_alert(state,alert,report)
    changed=deepcopy(report)
    if change=='stale': changed['mqtt_snapshot']['received_at']=(now-timedelta(seconds=6)).isoformat()
    if change=='future': changed['mqtt_snapshot']['received_at']=(now+timedelta(seconds=1)).isoformat()
    if change in ('unknown','offline'): changed['observed_job_state']=change.upper()
    if change=='no_error_field': changed['error_fields_observed']=False
    if change=='different_device': changed['selected_printer']['profile_id']='printer-b'
    if change=='reconfigured_profile': changed['device_identity']='physical-b'
    if change=='simulation': changed['physical_transport']=False
    if change=='error': changed['device_error']='123'
    if change=='no_mqtt': changed['mqtt_snapshot']['ok']=False
    if change=='missing_identity': changed.pop('device_identity')
    assert reconcile(state,changed,now=now)==[]
    assert active_alerts(state)


@pytest.mark.parametrize('job_state', ['FAILED','FAIL','CANCELLED','CANCELED','ABORTED','PAUSE','PAUSED'])
def test_zero_device_error_resolves_without_changing_failed_or_paused_job(job_state):
    state,report,alert,now=fixture()
    report['observed_job_state']=job_state
    incident={'incident_id':alert['alert_id'],'source':'hardware_alert','status':'open'}
    alert['incident_record']=deepcopy(incident)
    state.run_metadata['incident_records']=[incident,{'incident_id':'unrelated','status':'open'}]
    record_alert(state,alert,{**report,'device_error':'5A0300400C','ok':False})
    assert not reconcile(state,{**report,'device_error':'123'},now=now)
    assert len(reconcile(state,report,now=now))==1
    assert state.device_health['printer']=='ready' and not active_alerts(state)
    assert report['observed_job_state']==job_state
    assert state.run_metadata['incident_records'][0]['status']=='resolved'
    assert state.run_metadata['incident_records'][1]['status']=='open'
    # Resolution does not permit motion or auto-resume an existing job/run.
    assert not state.stop_requested and not state.safe_stop_requested


@pytest.mark.parametrize('change', ['ack','plc','estop','latched','critical','unknown','legacy'])
def test_safety_and_manual_alerts_never_auto_resolve(change):
    state,report,alert,now=fixture()
    if change=='ack': alert['requires_ack']=True
    if change in ('plc','estop','unknown'): alert['failure_code']=change.upper()
    if change=='latched': alert['latched']=True
    if change=='critical': alert['severity']='critical'
    record_alert(state,alert,{} if change=='legacy' else report)
    assert not reconcile(state,report,now=now)
    assert active_alerts(state)


def test_time_alone_never_expires_blocking_history():
    state,report,alert,now=fixture()
    alert['created_at']=(now-timedelta(days=300)).isoformat()
    for i in range(60):
        record_alert(state,{**alert,'alert_id':str(i),'requires_ack':True},report)
    assert len(active_alerts(state))==60


def test_repeat_monitor_faults_are_bounded_and_newer_fault_invalidates_older_health():
    state,report,alert,now=fixture()
    record_alert(state,alert,report)
    for i in range(100):
        record_alert(state,{**alert,'alert_id':str(i),'created_at':(now+timedelta(seconds=1)).isoformat()},report)
    assert len(active_alerts(state))==1
    assert active_alerts(state)[0]['repeat_count']==101
    assert not reconcile(state,report,now=now)


@pytest.mark.asyncio
async def test_headless_pre_gate_refresh_uses_only_health_and_keeps_stop_latches():
    state,report,alert,_=fixture()
    record_alert(state,alert,report)
    calls=[]
    def call(tool,payload):
        calls.append((tool,payload))
        return report
    state.emergency_stop_requested=True
    assert not await refresh_before_gate(state,SimpleNamespace(call=call))
    assert not calls
    state.emergency_stop_requested=False
    assert await refresh_before_gate(state,SimpleNamespace(call=call))
    assert calls==[('printer.prepare',{'runtime_mode':'live','printer_profile_id':'printer-a',
        'health_only':True,'status_only':True,'skip_ftps_probe':True})]


def test_guardian_pre_gate_ignores_resolved_history_but_keeps_unresolved():
    from orchestrator.state import OrchestratorState,Mode,Stage
    from policies.guardian_gate import _state_alarm_signals
    source,report,alert,now=fixture()
    state=OrchestratorState(run_id=source.run_id,experiment_id='exp',mode=Mode.LIVE,stage=Stage.EQUIPMENT)
    record_alert(state,alert,report)
    assert _state_alarm_signals(state=state,stage='equipment',phase='pre')
    reconcile(state,report,now=now)
    assert not _state_alarm_signals(state=state,stage='equipment',phase='pre')


def test_guardian_agent_receives_active_not_resolved_faults():
    from tests.unit.test_guardian_agent import _CtxStub,_state
    from agents.core.guardian.agent import GuardianAgent
    _,report,alert,_=fixture()
    state=_state()
    record_alert(state,alert,report)
    result=GuardianAgent()._resolve_device_health(state,_CtxStub(health={'printer':report}))
    assert result['status']=='pass' and not result['active_hardware_alerts']


def test_controller_monitor_marks_only_non_latching_fault_as_automatic():
    from app.controller import MainController
    from orchestrator.state import Stage
    state,report,_,_=fixture()
    controller=MainController.__new__(MainController)
    controller._state=state
    state.experiment_id='exp'
    failed={**report,'ok':False,'failure_code':'BAMBU_DEVICE_ERROR','status':'DEVICE_HEALTH_FAILED','device_error':'123'}
    alert=controller._hardware_alert_for_result(workspace='printer',tool='printer.status',result=failed,
        stage=Stage.SPECIMEN,agent='specimen_agent',workflow='printer_status_monitor',status='DEVICE_HEALTH_FAILED')
    assert alert['resolution_policy']=='fresh_matching_device_report'
    assert alert['requires_ack'] is False
    record_alert(state,alert)
    assert active_alerts(state)


def test_guardian_display_does_not_reblock_resolved_alert_severity(monkeypatch):
    from app import main
    from app.controller import MainController
    state,report,alert,now=fixture()
    record_alert(state,alert,report)
    reconcile(state,report,now=now)
    metadata=MainController._compact_planning_run_metadata(state.run_metadata)
    assert metadata['hardware_alerts'][0]['lifecycle']=='resolved'
    monkeypatch.setattr(main, '_approval_events_for_run', lambda run_id: {'pending':[]})
    snapshot={'is_running':False,'state':{'run_id':'isolated-alert-display',
        'stage':'idle','run_metadata':metadata,'device_health':state.device_health}}
    result=main._guardian_status_payload(snapshot=snapshot)
    assert result['status']=='allow'
    assert result['summary']['blocked_action_count']==0
