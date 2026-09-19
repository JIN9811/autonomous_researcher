/*
AX4-Lab Design live-report renderer.

This module owns Design-only report markup. The planning host supplies shared
formatting, chart serialization, and capture lookup helpers explicitly.
It performs no polling, subscriptions, DOM mutation, or hardware actions.
*/
(function installDesignLiveReport(global) {
  "use strict";

  function createLiveReportRenderer(dependencies) {
    const {
      escapeHtml,
      compactText,
      renderRuntimeValue,
      renderDashboardRows,
      dashboardList,
      orcChartPayloadAttr,
      designImageUrlFromSource,
      designCandidateDirectCaptureUrl,
    } = dependencies || {};

    const required = {
      escapeHtml,
      compactText,
      renderRuntimeValue,
      renderDashboardRows,
      dashboardList,
      orcChartPayloadAttr,
      designImageUrlFromSource,
      designCandidateDirectCaptureUrl,
    };
    Object.entries(required).forEach(([name, value]) => {
      if (typeof value !== "function") throw new TypeError(`AX4LABDesignUI requires ${name}`);
    });

    function finiteNumber(value) {
      if (value === null || value === undefined || value === "") return null;
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }

    function scoreText(value, digits = 2) {
      const number = finiteNumber(value);
      return number === null ? "-" : String(Number(number.toFixed(digits)));
    }

    function firstPresent(...values) {
      return values.find((value) => value !== null && value !== undefined && value !== "");
    }

    function renderEmpty(message) {
      return `<div class="ar-design-empty">${escapeHtml(message || "Waiting for backend data.")}</div>`;
    }

    function scatterRows(points) {
      const clean = (points || []).map((point) => ({
        ...point,
        x: finiteNumber(point && point.x_mass_g),
        y: finiteNumber(point && point.y_predicted_objective),
        r: finiteNumber(point && point.radius_uncertainty),
      })).filter((point) => point.x !== null && point.y !== null).slice(0, 24);
      return clean.map((point) => ({
        candidate_id: point.candidate_id || "candidate",
        geometry_type: point.geometry_type || "",
        x: point.x,
        y: point.y,
        r: point.r || 0,
        score: finiteNumber(point.score),
        status: point.status || "",
      }));
    }

    function radarRows(source, fallbackMetrics = {}) {
      const explicit = Array.isArray(source) ? source.map((item) => ({
        label: item.axis || item.label || "metric",
        value: finiteNumber(item.value),
        max: finiteNumber(item.max) || 1,
      })).filter((item) => item.value !== null) : [];
      if (explicit.length) return explicit.slice(0, 6);
      return [
        ["objective", fallbackMetrics.selected_score],
        ["manufacturing", fallbackMetrics.manufacturability_score],
        ["info_gain", fallbackMetrics.information_gain_score],
        ["margin", fallbackMetrics.constraint_margin_score],
        ["risk_inv", (() => {
          const risk = finiteNumber(fallbackMetrics.risk_score);
          return risk === null ? null : Math.max(0, 1 - risk);
        })()],
      ].map(([label, value]) => ({ label, value: finiteNumber(value), max: 1 }))
        .filter((item) => item.value !== null);
    }

    function renderEvidence(evaluation, details = false) {
      const e = evaluation || {};
      const validity = e.validity || {};
      const performance = e.performance || {};
      const cost = e.cost || {};
      const quantity = (quantityValue) => quantityValue && quantityValue.value != null
        ? `${renderRuntimeValue(quantityValue.value)} ${quantityValue.unit || ""}` : "unavailable";
      const rows = [
        ["Validity", validity.status || "unknown"],
        ["Performance", performance.status === "unassessed" ? "unassessed" : quantity(performance)],
        ["Mass (estimated)", quantity(cost.mass)],
        ["Print time (slicer)", quantity(cost.duration?.source === 'slicer' ? cost.duration : null)],
      ];
      const margins = visibleConstraintRows(details ? e.constraint_margins : []);
      const reasons = Array.isArray(validity.reasons) ? validity.reasons : [];
      return `<div class="ar-design-metric-strip">${rows.map(([label, value]) => `<span><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>`).join("")}</div>
    ${margins.length ? `<div class="ar-design-note-list">${margins.map((margin) => `<span>${escapeHtml(margin.constraint)}: ${escapeHtml(margin.margin)} ${escapeHtml(margin.unit)} margin · ${escapeHtml(margin.status)}</span>`).join("")}</div>` : ""}
    ${reasons.length ? `<div class="ar-design-note-list">${reasons.map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div>` : ""}`;
    }

    function evidenceTable(headers, rows, selectedIndex = -1) {
      if (!rows.length) return renderEmpty("No recorded evidence.");
      return `<div style="overflow-x:auto"><table class="ar-design-evidence-table"><thead><tr>${headers.map(h=>`<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row,i)=>`<tr${i===selectedIndex?' class="dsn-selected-candidate" aria-label="Selected candidate"':''}>${row.map(v=>`<td>${escapeHtml(String(v ?? "Not recorded"))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }

    function renderDesignSpace(screenReport, selected = {}, plannedPoints = []) {
      const parameters = screenReport.parameter_sweep?.parameters || [];
      const sources = [
        ...plannedPoints.map(p=>({candidate_id:p.candidate_id, status:p.status || 'planned',
          x_wall_thickness_mm:(p.parameters || p).wall_thickness_mm,
          y_cell_size_mm:(p.parameters || p).cell_size_mm})),
        ...(screenReport.parameter_sweep?.heatmap_cells || []),
        {...selected, status:'selected', x_wall_thickness_mm:selected.wall_thickness_mm, y_cell_size_mm:selected.cell_size_mm},
      ];
      const byPosition = new Map();
      sources.filter(p=>finiteNumber(p.x_wall_thickness_mm)!==null && finiteNumber(p.y_cell_size_mm)!==null).forEach(p=>{
        const key=`${Number(p.x_wall_thickness_mm).toFixed(8)}:${Number(p.y_cell_size_mm).toFixed(8)}`;
        const previous=byPosition.get(key);
        byPosition.set(key, {...p, measured:p.status==='measured'||p.measured===true||previous?.measured===true});
      });
      const points = [...byPosition.values()];
      let chart = renderEmpty("Candidate coordinates not recorded.");
      if (points.length) {
        // Stored field names predate the LHS axis convention. Map the display,
        // not the recorded candidate coordinates: cell size on X, wall on Y.
        const xs=points.map(p=>Number(p.y_cell_size_mm)), ys=points.map(p=>Number(p.x_wall_thickness_mm));
        const domain=values=>{const lo=Math.min(...values),hi=Math.max(...values),pad=(hi-lo||Math.abs(lo)*0.1||0.1)*0.15;return [lo-pad,hi+pad];};
        const agreedDomain=(name,values)=>{const p=parameters.find(p=>p.parameter===name);return p && finiteNumber(p.min)!==null && finiteNumber(p.max)!==null && Number(p.min)<Number(p.max)?[Number(p.min),Number(p.max)]:domain(values);};
        const [xmin,xmax]=agreedDomain("cell_size_mm",xs),[ymin,ymax]=agreedDomain("wall_thickness_mm",ys);
        // Keep limit candidates inside the frame so boundary markers stay whole.
        const x=v=>60+((v-xmin)/(xmax-xmin)+0.05)/1.1*380;
        const y=v=>230-((v-ymin)/(ymax-ymin)+0.05)/1.1*180;
        const ticks=Array.from({length:5},(_,i)=>i/4);
        const chosen=p=>p.status==='selected'||(selected.candidate_id!=null&&p.candidate_id===selected.candidate_id);
        const markers=[...points.filter(p=>!chosen(p)), ...points.filter(chosen)].map(p=>{
          const cx=x(Number(p.y_cell_size_mm)),cy=y(Number(p.x_wall_thickness_mm));
          const title=`<title>${escapeHtml(p.candidate_id||'Candidate')} · cell=${scoreText(p.y_cell_size_mm,3)} mm · wall=${scoreText(p.x_wall_thickness_mm,3)} mm${chosen(p)?' · selected':''}</title>`;
          const dot = `<circle class="dsn-space-candidate" cx="${cx}" cy="${cy}" data-status="${p.measured?'measured':'planned'}" ${p.measured?'style="fill:#83cbb1;stroke:#d3f7e5"':''} r="5">${title}${p.measured?'<title>Measured / completed</title>':''}</circle>`;
          return dot + (chosen(p) ? `<g class="dsn-space-selected" transform="translate(${cx} ${cy})"><path d="M-6 -6 L6 6 M-6 6 L6 -6"/>${title}</g>` : '');
        }).join('');
        chart=`<svg class="dsn-space-chart" viewBox="0 0 460 290" role="img" aria-label="Design candidate positions">
          <title>Cell size versus wall thickness; cross marks the selected candidate. Overlapping candidates share a position. No performance score.</title>
          <g class="dsn-space-legend" transform="translate(60 20)"><circle class="dsn-space-candidate" r="4"/><text x="12" y="4">Candidate</text><g class="dsn-space-selected" transform="translate(116 0)"><path d="M-5 -5 L5 5 M-5 5 L5 -5"/></g><text x="128" y="4">Selected</text></g>
          <g transform="translate(310 20)"><circle r="4" fill="#83cbb1"/><text x="12" y="4">Measured</text></g>
          ${ticks.map(t=>{const xv=xmin+t*(xmax-xmin),yv=ymin+t*(ymax-ymin);return `<path d="M ${x(xv)} 50 V 230 M 60 ${y(yv)} H 440" stroke="currentColor" opacity=".13"/><text x="${x(xv)}" y="252" text-anchor="middle">${scoreText(xv,3)}</text><text x="50" y="${y(yv)+4}" text-anchor="end">${scoreText(yv,3)}</text>`;}).join('')}
          <path d="M60 50 V230 H440" fill="none" stroke="currentColor"/>${markers}
          <text class="dsn-space-axis-label" x="250" y="282" text-anchor="middle">Cell size (mm)</text>
          <text class="dsn-space-axis-label" transform="translate(15 140) rotate(-90)" text-anchor="middle">Wall thickness (mm)</text>
        </svg>`;
      }
      return chart + '<details class="dsn-variable-details"><summary>Variables & ranges</summary>' + evidenceTable(["Variable", "Selected", "Range"], parameters.map(p=>[
        p.parameter, p.selected ?? p.value ?? selected[p.parameter],
        p.min != null && p.max != null ? `${p.min} – ${p.max}` : "Not recorded"
      ])) + '</details>';
    }

    function renderExpectedPerformance(screenReport, designReport, selected = {}, candidates = [], report = {}) {
      const evaluations = [...(designReport.candidate_evaluations || []), ...(screenReport.candidate_evaluations || [])];
      const fallback = designReport.design_evaluation || screenReport.design_evaluation || selected.design_evaluation;
      const selectedId = selected.candidate_id || screenReport.design_evaluation?.candidate_id || designReport.design_evaluation?.candidate_id;
      const byId = new Map();
      const merge = (item, evaluationOnly = false) => {
        if (!item || typeof item !== 'object') return;
        const id = item.candidate_id || item.id || (evaluationOnly ? selectedId || '__unidentified_evaluation' : null);
        if (!id) return;
        const previous = byId.get(id) || {};
        const evaluation = evaluationOnly ? item : item.design_evaluation;
        byId.set(id, {...previous, ...(evaluationOnly ? {} : item), candidate_id:id,
          status:previous.status === 'measured' ? 'measured' : item.status || previous.status,
          parameters:{...(previous.parameters || {}), ...(item.parameters || {})},
          design_evaluation:evaluation || previous.design_evaluation});
      };
      [ ...(screenReport.candidate_board?.candidate_ledger || []),
        ...(designReport.candidate_generation?.candidate_ledger || []),
        ...(designReport.candidate_generation?.top_candidates || []), ...candidates ].forEach(item=>merge(item));
      evaluations.forEach(item=>merge(item, true));
      if (fallback) merge(fallback, true);
      if (selectedId) merge({...selected,candidate_id:selectedId});
      const rows = [...byId.values()];
      const state = report.state || {};
      const observations = (state.experiment_evaluations || []).filter(item => item &&
        (!item.run_id || item.run_id === state.run_id) &&
        (item.source === 'analysis_agent' || item.tool === 'analysis.agent') &&
        item.ok !== false && item.status !== 'analysis_blocked' &&
        item.objective?.metric_name && item.objective?.unit &&
        finiteNumber(item.objective_score) !== null);
      const measuredObservation = row => {
        const ids = new Set([row.specimen_id, row.candidate_id].filter(Boolean));
        let measured = [...observations].reverse().find(item=>ids.has(item.candidate_id) || ids.has(item.specimen_id));
        // Planned LHS/BO IDs differ from fabricated specimen IDs. Match only
        // a unique, same-run observation at the exact two-variable point.
        if (!measured && /^(lhs|bo)-candidate-/.test(row.candidate_id || '')) {
          const matches = observations.filter(item=>['cell_size_mm','wall_thickness_mm'].every(key=>{
            const a=finiteNumber(row.parameters?.[key] ?? row[key]);
            const b=finiteNumber(item.parameters?.[key] ?? item.metrics?.[key]);
            return a !== null && b !== null && Math.abs(a-b) <= 1e-6;
          }));
          if (matches.length === 1) measured = matches[0];
        }
        return measured;
      };
      const performance = row => {
        const measured = measuredObservation(row);
        if (measured) return `${measured.objective_score} ${measured.objective.unit} · ${measured.objective.metric_name} · ${measured.fidelity === 'synthetic' ? 'Synthetic' : 'Measured'} · Analysis`;
        const evidence = row.design_evaluation?.performance;
        return evidence?.value != null && evidence?.source
          ? `${evidence.value} ${evidence.unit || ''} · ${evidence.source}`
          : `Unassessed · ${evidence?.reason || 'No analysis result linked to this candidate yet.'}`;
      };
      const mass = row => {
        const measured = measuredObservation(row);
        const archived = (report.specimenEvidence || []).find(item =>
          (row.specimen_id && item.specimen_id === row.specimen_id) ||
          (row.candidate_id && item.candidate_id === row.candidate_id) ||
          (measured?.candidate_id && item.candidate_id === measured.candidate_id));
        const geometry = measured?.specimen_geometry || archived?.specimen_geometry;
        const grams = finiteNumber(geometry?.mass_g);
        return grams !== null && grams > 0 && geometry.mass_source === 'slicer' ? `${grams} g` : 'Not recorded';
      };
      const constraints = row => {
        const e = row.design_evaluation || {};
        const checks = visibleConstraintRows(e.constraint_margins?.length ? e.constraint_margins : e.selection_evaluation?.constraint_margins);
        if (!checks.length) return e.validity?.status || 'Not evaluated';
        const counts = checks.reduce((acc, item) => {const key=item.status || 'unassessed'; acc[key]=(acc[key]||0)+1; return acc;}, {});
        return `${e.validity?.status || 'Not evaluated'} · ${Object.entries(counts).map(([key,count])=>`${count} ${key}`).join(', ')}${e.constraint_margins?.length ? '' : ' · selection-time checks'}`;
      };
      return '<div class="dsn-comparison-scroll" tabindex="0" role="region" aria-label="Candidate comparison">' + evidenceTable(["Candidate", "Cell size (mm)", "Wall (mm)", "Progress", "Constraints", "Mass", "Performance evidence"], rows.map(row=>{
        const e = row.design_evaluation || {};
        return [
          `${row.candidate_id === '__unidentified_evaluation' ? 'Not recorded' : row.candidate_id}${selectedId && row.candidate_id===selectedId?' · Selected':''}`,
          row.cell_size_mm ?? row.parameters?.cell_size_mm ?? 'Not recorded',
          row.wall_thickness_mm ?? row.parameters?.wall_thickness_mm ?? 'Not recorded',
          row.status || (row.__actual_specimen ? 'generated' : 'recorded'),
          constraints(row),
          mass(row),
          performance(row)
        ];
      }), selectedId ? rows.findIndex(row=>row.candidate_id===selectedId) : -1) + '</div>';
    }

    function renderArtifactLedger(items) {
      const rows = (Array.isArray(items) ? items : []).map((item) => {
        const status = item.status || "recorded";
        return `${item.artifact_type || "artifact"} / ${item.artifact_id || "-"} / ${status}`;
      });
      return dashboardList(rows, "No design artifact ledger recorded.", 8);
    }

    function renderBriefCard(brief, objective, hypothesis, spec, prior, material = {}, manufacturability = {}, selected = {}) {
      const constraints = Array.isArray(brief.success_criteria) ? brief.success_criteria.slice(0, 3) : [];
      const goal = brief.hypothesis || hypothesis.statement || objective.statement || spec.objective || "Objective pending.";
      return `
    <div class="ar-design-brief-layout">
      ${renderDashboardRows([
        ["Metric", brief.primary_metric || objective.primary_metric || spec.objective_type || "-"],
        ["Test", spec.specimen_type || spec.specimen_kind || "compression"],
        ["Standard", spec.standard || spec.test_standard || "-"],
        ["Material", material.material || brief.material || spec.material || spec.material_family || "-"],
        ["Printer", manufacturability.printer_model || spec.printer_model || "-"],
        ["Selected", selected.candidate_id || spec.candidate_id || "-"],
        ["Priors", prior.prior_count || 0],
      ])}
      ${constraints.length ? `<ul class="ar-design-check-list">${constraints.map((item) => `<li>${escapeHtml(compactText(item, 72))}</li>`).join("")}</ul>` : ""}
      <p>${escapeHtml(compactText(goal, 120))}</p>
    </div>
  `;
    }

    function visibleConstraintRows(rows) {
      return (Array.isArray(rows) ? rows : []).filter(row =>
        !['estimated_mass', 'estimated_duration'].includes(String(row.constraint || '').toLowerCase().replace(/\s+/g, '_')));
    }

    function renderManufacturabilityCard(screenReport, designReport, selected, spec) {
      const selectedId = spec.candidate_id || selected.candidate_id;
      const matches = item => item && (!selectedId || !item.candidate_id || item.candidate_id === selectedId);
      const evidence = [spec.design_evaluation, selected.design_evaluation, screenReport.design_evaluation,
        designReport.design_evaluation, ...(screenReport.candidate_evaluations || []), ...(designReport.candidate_evaluations || [])]
        .find(item => matches(item) && (item.validity || item.constraint_margins?.length || item.selection_evaluation));
      const currentRows = evidence?.constraint_margins || [];
      const selection = evidence?.selection_evaluation;
      const historical = !currentRows.length && matches(selection) && selection.constraint_margins?.length;
      const rows = visibleConstraintRows(historical ? selection.constraint_margins : currentRows);
      const summary = evidence ? `<p class="ar-design-empty">Current design: ${escapeHtml(evidence.validity?.status || 'Not evaluated')}${evidence.adapted_fields?.length ? ` · Adapted: ${escapeHtml(evidence.adapted_fields.join(', '))}` : ''}</p>` : '';
      const provenance = historical ? '<p class="ar-design-empty"><strong>Selection-time evidence — before adaptation.</strong> These checks are not a pass verdict for the current geometry.</p>' : '';
      const bars=rows.filter(m=>finiteNumber(m.actual)!==null && finiteNumber(m.limit)!==null && m.actual>=0 && m.limit>0 && ['>=','<='].includes(m.relation));
      const chart=bars.map(m=>{const maximum=Math.max(m.actual,m.limit)*1.15,actual=m.actual/maximum*100,limit=m.limit/maximum*100;return `<div class="dsn-constraint-row"><div><strong>${escapeHtml(m.constraint)}</strong><span>${escapeHtml(`${m.actual} ${m.unit||''} · ${m.relation} ${m.limit} · ${m.status||'unknown'}`)}</span></div><svg viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label="Constraint value relative to limit"><rect x="${m.relation==='>='?limit:0}" width="${m.relation==='>='?100-limit:limit}" height="8" fill="#54d3ef" opacity=".09"/><rect y="2" width="${actual}" height="4" fill="${m.status==='fail'?'#e5ad69':'#54c7e8'}"/><path d="M${limit} 0 V8" stroke="#dce8f0" stroke-width=".6"/></svg><small>${escapeHtml(`Margin: ${m.margin??'Not recorded'} ${m.unit||''}`)}</small></div>`;}).join('');
      const unmeasured = rows.filter(m=>finiteNumber(m.actual)===null).map(m=>`${m.constraint}: ${m.status || 'Not measured'} · limit ${m.relation || ''} ${m.limit ?? 'Not recorded'} ${m.unit || ''}`);
      return summary + provenance + (chart?`<div class="dsn-constraint-bars">${chart}</div>`:'') + (unmeasured.length ? `<p class="ar-design-empty">${escapeHtml(unmeasured.join(' · '))}</p>` : '') + '<details class="dsn-variable-details"><summary>Constraint details</summary><p class="ar-design-empty">Line: limit · Shading: allowed region · Each row uses its own scale</p>' + evidenceTable(["Constraint", "Actual", "Limit", "Margin", "Result"], rows.map(m=>[
        m.constraint, m.actual == null ? "Not recorded" : `${m.actual} ${m.unit || ""}`, m.limit == null ? "Not recorded" : `${m.relation || ""} ${m.limit} ${m.unit || ""}`,
        m.margin == null ? "Not recorded" : `${m.margin} ${m.unit || ""}`, m.status
      ])) + '<p class="ar-design-empty">Design constraints only; manufacturing verification belongs to SPC.</p></details>';
    }

    function renderMaterialCard(material, spec) {
      const notes = Array.isArray(material.notes) ? material.notes.slice(0, 3) : [];
      return `
    <div class="ar-design-material-layout">
      <div class="ar-design-metric-strip">
        <span><b>Material</b>${escapeHtml(compactText(material.material || spec.material || "-", 22))}</span>
        <span><b>Layer</b>${escapeHtml(renderRuntimeValue(firstPresent(material.layer_height_mm, spec.layer_height_mm, "-")))}</span>
        <span><b>Nozzle</b>${escapeHtml(renderRuntimeValue(firstPresent(material.nozzle_diameter_mm, spec.nozzle_diameter_mm, "-")))}</span>
        <span><b>Bed</b>${escapeHtml(renderRuntimeValue(firstPresent(material.bed_temperature_c, spec.bed_temperature_c, "-")))}</span>
      </div>
      <div class="ar-design-note-list">
        ${(notes.length ? notes : ["Material notes pending."]).map((item) => `<span>${escapeHtml(compactText(item, 88))}</span>`).join("")}
      </div>
    </div>
  `;
    }

    function renderHandoffCard(handoff, selected, material, spec, artifactLedger = []) {
      const missing = Array.isArray(handoff.missing_required_fields) ? handoff.missing_required_fields : [];
      const ready = handoff.required_fields_present !== false && !missing.length;
      return `
    <div class="ar-design-handoff-layout">
      <div class="ar-design-handoff-main">
        <span class="tone-${ready ? "success" : "warning"}">${ready ? "Ready" : "Needs Input"}</span>
        <strong>${escapeHtml(compactText(handoff.authoritative_candidate_id || selected.candidate_id || spec.candidate_id || "-", 34))}</strong>
        <em>${escapeHtml(compactText(handoff.authoritative_specimen_id || selected.specimen_id || spec.specimen_id || "-", 44))}</em>
      </div>
      <div class="ar-design-metric-strip">
        <span><b>Next</b>SPC</span>
        <span><b>Status</b>${escapeHtml(handoff.packet_status || (ready ? "ready" : "blocked"))}</span>
        <span><b>Profile</b>${escapeHtml(compactText(material.printer_profile || spec.printer_profile || "-", 18))}</span>
        <span><b>Evidence</b>${escapeHtml(`${Array.isArray(artifactLedger) ? artifactLedger.length : 0} files`)}</span>
      </div>
      ${missing.length ? `<div class="ar-design-note-list">${missing.slice(0, 4).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    </div>
  `;
    }

    function renderEvidenceCard(artifactLedger, rejected) {
      const artifacts = Array.isArray(artifactLedger) ? artifactLedger.slice(0, 5) : [];
      const repairs = Array.isArray(rejected) ? rejected.slice(0, 4) : [];
      return `
    <div class="ar-design-evidence-layout">
      <section>
        <h5>Artifacts</h5>
        ${renderArtifactLedger(artifacts)}
      </section>
      <section>
        <h5>Rejected / Repair</h5>
        ${dashboardList(repairs.map((item) => renderRuntimeValue(item)), "No rejected entries.", 4)}
      </section>
    </div>
  `;
    }

    return Object.freeze({
      scatterRows,
      radarRows,
      renderEvidence,
      renderExpectedPerformance,
      renderArtifactLedger,
      renderBriefCard,
      renderManufacturabilityCard,
      renderDesignSpace,
      renderMaterialCard,
      renderHandoffCard,
      renderEvidenceCard,
    });
  }

  function createFrontend(hostServices) {
    const services = hostServices || {};
    const renderer = createLiveReportRenderer(services);
    const required = {
      latestDesignAgentReport: services.latestDesignAgentReport,
      latestDesignReport: services.latestDesignReport,
      designSelectedCandidate: services.designSelectedCandidate,
      designCandidateRows: services.designCandidateRows,
      designActualSpecimenRows: services.designActualSpecimenRows,
      renderDesignCandidateCards: services.renderDesignCandidateCards,
      renderDesignParameterSweep: services.renderDesignParameterSweep,
      renderDashboardCard: services.renderDashboardCard,
      runtimeRows: services.runtimeRows,
      renderReportList: services.renderReportList,
    };
    Object.entries(required).forEach(([name, value]) => {
      if (typeof value !== "function") throw new TypeError(`AX4LABDesignUI frontend requires ${name}`);
    });

    function renderDashboard(report, status, label, profile) {
      const currentSpec = report?.spec || report?.state?.current_experiment_spec || {};
      const specimenEvidence = services.designArchivedSpecimenEvidence?.(report) || [];
      const saved = specimenEvidence.find(item => item.specimen_id === currentSpec.specimen_id &&
        item.candidate_id === currentSpec.candidate_id &&
        ['cell_size_mm','wall_thickness_mm'].every(key => currentSpec[key] == null || item[key] === currentSpec[key]) &&
        (!currentSpec.candidate_fingerprint || item.candidate_fingerprint === currentSpec.candidate_fingerprint));
      // Durable, same-specimen evidence survives compact refresh messages.
      const spec = saved?.design_evaluation ? {...currentSpec, design_evaluation:saved.design_evaluation} : currentSpec;
      report = {...report, spec, specimenEvidence};
      const screenReport = services.latestDesignAgentReport(report) || {};
      const designReport = services.latestDesignReport(report) || {};
      const plannedPoints = [...(services.latestBoInitialDesign?.(report)?.points || [])];
      const next = report?.state?.run_metadata?.next_design_request;
      if (next && next.status === 'ready' && next.run_id === report?.state?.run_id) {
        plannedPoints.push({candidate_id:next.candidate_id, parameters:next.constraints || {}});
      }
      const decision = designReport.design_decision;
      if (decision && ["returned", "failed"].includes(decision.status)) {
        return services.renderDashboardCard("Design Decision — Review Required", services.runtimeRows([
          ["status", decision.status], ["reason", decision.reason || decision.failure_code || "No accepted candidate"],
          ["handoff", "blocked — no specification emitted"],
        ]), { span: 12, tone: "warning", eyebrow: "dsn decision" });
      }
      const brief = screenReport.design_brief || {};
      const material = screenReport.material_notes || {};
      const artifactLedger = Array.isArray(screenReport.artifact_ledger) ? screenReport.artifact_ledger : [];
      const objective = designReport.objective || {};
      const hypothesis = designReport.hypothesis || {};
      const generation = designReport.candidate_generation || {};
      const evaluation = designReport.candidate_evaluation || {};
      const prior = designReport.prior_context || {};
      const manufacturability = screenReport.manufacturability || designReport.manufacturability || {};
      const handoff = screenReport.handoff_to_specimen || designReport.handoff_to_specimen || {};
      const rejected = Array.isArray(designReport.rejected_candidates) ? designReport.rejected_candidates
        : Array.isArray(generation.rejection_log) ? generation.rejection_log
          : Array.isArray(generation.rejected_candidates) ? generation.rejected_candidates
            : Array.isArray(evaluation.rejected_candidates) ? evaluation.rejected_candidates : [];
      const selected = {...services.designSelectedCandidate(screenReport, designReport, spec)};
      if (spec.candidate_id) selected.candidate_id = spec.candidate_id;
      for (const key of ['cell_size_mm','wall_thickness_mm']) {
        if (spec[key] != null) selected[key] = spec[key];
      }
      if (spec.design_evaluation) selected.design_evaluation = spec.design_evaluation;
      const candidateRows = services.designCandidateRows(screenReport, designReport, report);
      const specimenRows = services.designActualSpecimenRows(screenReport, designReport, report).map(row => {
        const archived = specimenEvidence.find(item => item.specimen_id === row.specimen_id);
        return archived ? {...row, design_evaluation:archived.design_evaluation || row.design_evaluation} : row;
      });
      const generatedCount = specimenRows.length;
      const validCount = specimenRows.filter((item) => !/reject|fail|block|invalid/i.test(String(item.status || item.candidate_status || ""))).length;
      const previewCount = specimenRows.filter((item) => services.designImageUrlFromSource(item)).length;
      return `
    ${services.renderDashboardCard("Experiment Contract", renderer.renderBriefCard(brief, objective, hypothesis, spec, prior, material, manufacturability, selected), { span: 3, tone: "design", eyebrow: "mission input", className: "ar-design-reference-card ar-design-brief-card" })}
    ${services.renderDashboardCard("Generated Specimens", services.renderDesignCandidateCards(screenReport, designReport, report, { renderEvidence: renderer.renderEvidence }), { span: 9, tone: "design", eyebrow: "built specimen log", className: "ar-design-reference-card ar-design-candidates-card", meta: `${services.renderRuntimeValue(generatedCount)} built / ${services.renderRuntimeValue(validCount)} usable / ${services.renderRuntimeValue(previewCount)} previews` })}
    ${services.renderDashboardCard("Design Space", renderer.renderDesignSpace(screenReport, selected, plannedPoints), { span: 4, tone: "metrics", eyebrow: "recorded variables", className: "ar-design-reference-card ar-design-sweep-card" })}
    ${services.renderDashboardCard("Candidate Comparison", renderer.renderExpectedPerformance(screenReport, designReport, selected, [...plannedPoints.map((point,index)=>({...point,candidate_id:point.candidate_id || point.id || `LHS ${index+1}`,status:point.status || 'planned'})), ...candidateRows, ...specimenRows], report), { span: 4, tone: "metrics", eyebrow: "recorded candidate evidence", className: "ar-design-reference-card ar-design-performance-card" })}
    ${services.renderDashboardCard("Constraint Check", renderer.renderManufacturabilityCard(screenReport, designReport, selected, spec, material, specimenRows.length ? specimenRows : candidateRows), { span: 4, tone: (spec.design_evaluation || screenReport.design_evaluation || designReport.design_evaluation)?.validity?.status === "pass" ? "success" : "warning", eyebrow: "design checks", className: "ar-design-reference-card ar-design-manufacturing-card" })}
    ${services.renderDashboardCard("Active Handoff", renderer.renderHandoffCard(handoff, selected, material, spec, artifactLedger), { span: 12, tone: handoff.required_fields_present === false || rejected.length ? "warning" : "success", eyebrow: "dsn -> spc", className: "ar-design-reference-card ar-design-handoff-card" })}
  `;
    }

    function renderReport(report) {
      const designReport = services.latestDesignReport(report);
      if (!designReport || typeof designReport !== "object") return "";
      const hypothesis = designReport.hypothesis || {};
      const objective = designReport.objective || {};
      const generation = designReport.candidate_generation || {};
      const evaluation = designReport.candidate_evaluation || {};
      const prior = designReport.prior_context || {};
      const handoff = designReport.handoff_to_specimen || {};
      const topCandidates = Array.isArray(generation.top_candidates) ? generation.top_candidates.slice(0, 5) : [];
      const rejected = Array.isArray(designReport.rejected_candidates) ? designReport.rejected_candidates.slice(0, 6) : [];
      const decisions = Array.isArray(designReport.decision_register) ? designReport.decision_register.slice(0, 6) : [];
      const evidenceBased = designReport.evaluation_semantics === "evidence_based_v1";
      const topList = topCandidates.map((item) => evidenceBased
        ? `${item.candidate_id || "candidate"} · ${item.geometry_type || "-"} · validity=${item.design_evaluation?.validity?.status || "unknown"} · performance=${item.design_evaluation?.performance?.status || "unassessed"}`
        : `${item.candidate_id || "candidate"} · ${item.geometry_type || "-"} · score=${services.renderRuntimeValue(item.expected_objective_proxy_score ?? item.predicted_objective)} · risk=${services.renderRuntimeValue(item.risk_score)}`);
      const rejectedList = rejected.map((item) => `${item.candidate_id || "candidate"} · ${item.reason || "rejected"}`);
      const decisionList = decisions.map((item) => `${item.decision_id || item.decision || "decision"} · ${item.status || "-"} · ${item.rationale || ""}`);
      return `
    <div class="live-agent-specific-design-details">
      ${services.runtimeRows([
        ["report_id", designReport.report_id || "-"],
        ["primary_metric", objective.primary_metric || "-"],
        ["direction", objective.direction || "-"],
        ["variables", hypothesis.variables_under_test || "-"],
        ["selected_candidate", evaluation.selected_candidate_id || "-"],
        evidenceBased ? ["validity", designReport.design_evaluation?.validity?.status || "unknown"] : ["manufacturability", evaluation.manufacturability_score ?? "-"],
        ["knowledge_prior", prior.knowledge_summary || "-"],
        ["bo_recommendation", prior.bo_recommendation || "-"],
        ["handoff_missing", handoff.missing_required_fields || []],
      ])}
      <h5>Candidate Board</h5>
      ${services.renderReportList(topList, "No candidate board recorded.")}
      <h5>Rejected / Repair Log</h5>
      ${services.renderReportList(rejectedList, "No rejected candidates recorded.")}
      <h5>Decision Register</h5>
      ${services.renderReportList(decisionList, "No design decisions recorded.")}
    </div>
  `;
    }

    function dispose() {}

    return Object.freeze({ renderDashboard, renderReport, dispose });
  }

  global.AX4LABDesignUI = Object.freeze({ createLiveReportRenderer, createFrontend });
})(window);
