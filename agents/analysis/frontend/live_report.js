/* Analysis-owned measurement report; numerical results remain backend-owned. */
(function(global) {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = v => v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v);
  const fmt = v => num(v) === null ? '—' : Number(v).toLocaleString('en-US',{maximumFractionDigits:4});
  function createFrontend(s) {
    let mode = 'ss', expanded = false;
    const change = e => { if(e.target?.matches?.('[data-anl-curve-mode]')) mode=e.target.value; };
    const toggle = e => { if(e.target?.matches?.('[data-anl-details]')) expanded=e.target.open; };
    global.document?.addEventListener('change',change);
    global.document?.addEventListener('toggle',toggle,true);
    function renderDashboard(report={}) {
      const a=s.latestAnalysisPayload(report)||{}, m=a.utm_metrics||{}, source=a.source||{};
      const h=s.latestAnalysisBoHandoff(report)||a.bo_handoff||{}, o=h.objective||{}, evaluation=a.objective_evaluation||{};
      const metric=o.metric_name||evaluation.metric_name||evaluation.objective_id;
      const metricLabel=o.name || (/energy_density/.test(metric||'')?'Energy density':/specific_energy|^sea/.test(metric||'')?'Specific energy absorption':metric?String(metric).replaceAll('_',' '):'Awaiting objective');
      const formula=o.expression || evaluation.expression || (/energy_density/.test(metric||'')?'f(x) = ∫ σ(ε) dε':/specific_energy|^sea/.test(metric||'')?'f(x) = (1/m) ∫ F(δ) dδ':'');
      const score=evaluation.score??o.score??h.objective_score??a.objective_score;
      const strain=num(m.evaluation_strain??m.energy_absorption_limit_strain);
      const interval=strain===null?'Evaluation interval not recorded':`0–${fmt(strain*100)}% strain`;
      const quality=a.quality_gate||a.data_quality_gate||{}, allowed=h.ok_for_bo??a.ok_for_bo??quality.ok_for_bo;
      const gate=allowed===true?'Ready for BO':allowed===false?'Blocked':'Awaiting data';
      const card=(title,body,eyebrow)=>s.renderDashboardCard(title,body,{span:12,tone:'analysis',eyebrow});
      const objective=`<div class="anl-objective"><div><span class="anl-kicker">${esc(o.direction||'Configured objective')}</span><h3>${esc(metricLabel)}</h3><p>${esc(formula)}${formula?' · ':''}${esc(interval)}</p></div><div class="anl-objective-value"><strong>${fmt(score)}</strong><span>${esc(o.unit||evaluation.unit||'')}</span></div></div>`;
      const curve=`<div class="anl-curves"><label><input data-anl-curve-mode type="radio" name="anl-curve-view" value="ss" ${mode==='ss'?'checked':''}> SS curve</label><label><input data-anl-curve-mode type="radio" name="anl-curve-view" value="fd" ${mode==='fd'?'checked':''}> FD curve</label><span>${esc(interval)} · shaded evaluation region</span><div class="anl-ss">${s.renderAnalysisCurveOverlay(a,'ss')}</div><div class="anl-fd">${s.renderAnalysisCurveOverlay(a,'fd')}</div></div>`;
      const energy=num(m.energy_absorption_50pct_mJ);
      const metrics=`<div class="anl-metrics ar-report-metrics">${[
        ['Peak load',m.peak_force_N,'N'],['Peak stress',m.compressive_strength_MPa,'MPa'],
        ['Absorbed energy',energy===null?null:energy/1000,num(m.energy_absorption_limit_strain)===null?'J · recorded interval':`J · 0–${fmt(Number(m.energy_absorption_limit_strain)*100)}% strain`],
        ['Measured travel',m.measured_displacement_max_mm,'mm'],
      ].map(([k,v,u])=>s.renderDashboardMetric(k,fmt(v),u,'info')).join('')}</div>`;
      const decisions=Array.isArray(a.decisions)?a.decisions:[];
      const decision=phase=>{const d=decisions.find(x=>x.phase===phase);return !d?'Not recorded':d.ok===false||/hold|block|reject/i.test(d.action||d.option_id||'')?'Held':'Recorded';};
      const progress=`<div class="ar-spm-progress-steps"><div class="ar-spm-progress-node-rail" role="list" aria-label="Analysis processing stages">${[
        ['Measurement',a.utm_curve?.point_count?`${a.utm_curve.point_count} points`:'Awaiting data'],
        ['Processing decision',decision('data_processing')],['Curves & metrics',Object.keys(m).length?'Available':'Awaiting data'],
        ['Evidence review',decision('data_validation')],['BO handoff',gate],
      ].map(([k,v],i)=>{const tone=/Held|Blocked/.test(v)?'warn':/Awaiting|Not recorded/.test(v)?'muted':'ok';return `<div role="listitem" class="ar-spm-progress-node tone-${tone}"><i>${String(i+1).padStart(2,'0')}</i><span>${esc(k)}</span><b class="ar-spm-progress-action">${esc(v)}</b></div>${i<4?`<span class="ar-spm-progress-edge tone-${tone}" aria-hidden="true"></span>`:''}`;}).join('')}</div></div>`;
      const warnings=quality.warnings||a.failure_tags||[];
      const details=`<details data-anl-details ${expanded?'open':''}><summary>Source & processing details</summary>${s.renderDashboardRows([
        ['Source',source.path||'Not recorded'],['Parser',source.parser_id||source.format||'Not recorded'],
        ['SHA-256',source.fingerprint?.sha256||source.sha256||'Not recorded'],['Rows',source.row_count_probe??a.utm_curve?.point_count??'Not recorded'],
        ['Geometry',a.specimen_geometry||{}],['Metric values',m],['BO contract',h.schema_version||'Not recorded'],
        ['Canonical curve',a.analysis_artifacts?.canonical_curve||'Not recorded'],['Decision evidence',decisions],['Quality evidence',quality],
      ])}</details>`;
      const summary=`<div class="ar-design-handoff-layout"><div class="ar-design-handoff-main"><span class="tone-${allowed===true?'success':'warning'}">${esc(gate)}</span><strong>${esc(h.candidate_id||a.candidate_id||'Candidate not recorded')}</strong><em>${esc(h.specimen_id||a.specimen_id||'Specimen not recorded')}</em></div><div class="ar-design-metric-strip"><span><b>Next</b>${esc(h.next_agent||'BO')}</span><span><b>Data</b>${quality.ok_for_metrics===false?'Blocked':Object.keys(m).length?'Processed':'Awaiting data'}</span><span><b>Objective</b>${fmt(score)} ${esc(o.unit||evaluation.unit||'')}</span><span><b>Warnings</b>${Array.isArray(warnings)?warnings.length:0}</span></div>${Array.isArray(warnings)&&warnings.length?`<div class="ar-design-note-list">${warnings.map(w=>`<span>${esc(w)}</span>`).join('')}</div>`:''}</div>${details}`;
      return card('Objective',objective,'experiment objective')+card('Measured Response',curve,'experimental data')+card('Key Metrics',metrics,'measured values')+card('Agentic Progress',progress,'analysis workflow')+s.renderDashboardCard('Data Quality & BO Handoff',summary,{span:12,tone:allowed===true?'success':'warning',eyebrow:'anl → bo',className:'ar-design-reference-card ar-design-handoff-card'});
    }
    function dispose(){global.document?.removeEventListener('change',change);global.document?.removeEventListener('toggle',toggle,true);}
    return Object.freeze({renderReport:renderDashboard,renderDashboard,dispose});
  }
  global.AX4LABAnalysisUI=Object.freeze({createFrontend});
})(typeof window!=='undefined'?window:globalThis);
