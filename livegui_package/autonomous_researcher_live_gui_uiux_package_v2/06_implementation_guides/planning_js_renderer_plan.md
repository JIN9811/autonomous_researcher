# planning.js Renderer Plan

```js
const AGENT_REPORT_SECTIONS = {
  orchestrator: ['mission_contract', 'route_state', 'missing_inputs', 'decision_register', 'followup_questions', 'approval_summary', 'risk_register', 'task_queue', 'next_action'],
  design: ['design_brief', 'candidate_board', 'candidate_ranking', 'parameter_sweep', 'expected_performance', 'manufacturability', 'material_notes', 'handoff_to_specimen', 'artifact_ledger'],
  specimen: ['slicer_configuration', 'printer_profile', 'build_queue', 'estimated_print_time', 'filament_usage', 'gcode_validation', 'print_readiness', 'build_timeline', 'layer_preview', 'artifact_ledger', 'printer_status', 'handoff_status'],
  vision: ['camera_health', 'calibration_summary', 'confidence_distribution', 'inspection_feed', 'segmentation', 'defect_summary', 'pose_estimation', 'confusion_matrix', 'quality_metrics', 'evidence_review', 'handoff_recommendations'],
  manipulation: ['success_metrics', 'grasp_plan', 'waypoint_sequence', 'motion_execution', 'robot_workspace', 'reachability_map', 'collision_safety', 'object_pose_handoff', 'motion_trajectory', 'reaction_timeline', 'camera_views', 'key_artifacts'],
  equipment: ['equipment_readiness', 'live_test_status', 'load_displacement_preview', 'test_recipe', 'sensor_channels', 'environmental_conditions', 'safety_interlocks', 'event_log', 'control_approval'],
  analysis: ['preprocessing_status', 'signal_overview', 'data_quality', 'extracted_features', 'time_series', 'histogram', 'frequency_analysis', 'model_output', 'confusion_matrix', 'key_insights', 'anomaly_detection', 'artifacts', 'result_summary'],
  bo: ['optimization_goal', 'iterations', 'best_observed', 'current_regret', 'surrogate_model', 'acquisition_function', 'convergence_history', 'objective_space', 'stop_continue_recommendation', 'acquisition_breakdown', 'parameter_importance', 'parallel_coordinates', 'candidate_queue', 'uncertainty_map', 'recent_evaluations', 'artifacts'],
  guardian: ['risk_map', 'gate_timeline', 'incident_ledger', 'approval_queue', 'corrective_actions'],
  knowledge: ['memory_commit', 'evidence_pack', 'retrieval_results', 'evolution_proposals', 'deployment_gate']
};

function normalizePlanningMessage(raw) {
  if (raw?.schema === 'live_chat_message.v1') return raw;
  if (typeof raw?.content === 'string' && raw.content.includes('SYSTEM_EVENT')) {
    return normalizeLegacySystemEvent(raw);
  }
  return normalizeLegacyChatMessage(raw);
}

function renderAgentReport(agentId, report) {
  const keys = AGENT_REPORT_SECTIONS[agentId] || ['overview', 'current_status', 'decisions', 'next_action'];
  return keys.map(key => renderAgentReportSection(key, report?.sections?.[key] ?? report?.[key])).join('');
}
```
