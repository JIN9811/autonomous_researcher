/* Analysis-owned background FEM evidence. Viewing performs read-only GETs only. */
(function (root) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const format = value => finite(value) ? Number(value).toLocaleString('en-US', {maximumSignificantDigits: 4}) : '—';
  const display = value => value && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—');
  const fields = ['job_id', 'run_id', 'loop_key', 'specimen_id'];
  function identity(pointer) {
    return pointer && fields.every(key => ['string', 'number'].includes(typeof pointer[key]) && String(pointer[key]).trim())
      ? JSON.stringify(fields.map(key => String(pointer[key]))) : null;
  }
  function artifactPath(value) {
    const path = String(value || '');
    return path && !/[\u0000-\u001f]/.test(path) && !/^[a-z][a-z0-9+.-]*:/i.test(path) && !path.startsWith('//') ? path : '';
  }
  function curveSeries(curve, geometry, mode) {
    if (mode === 'ss' && !(Number(geometry.gauge_length_mm) > 0 && Number(geometry.cross_section_area_mm2) > 0)) return [];
    return (Array.isArray(curve) ? curve : []).filter(p => p && finite(p.displacement_mm) && finite(p.force_N)).map(p => ({
      x: Number(p.displacement_mm) * (mode === 'ss' ? 100 / Number(geometry.gauge_length_mm) : 1),
      y: Number(p.force_N) / (mode === 'ss' ? Number(geometry.cross_section_area_mm2) : 1),
    }));
  }
  function chart(series, mode, empty) {
    const points = series.flatMap(s => s.points);
    if (!points.length) return `<p class="fem-empty">${escape(empty)}</p>`;
    // Data-derived domains include both measured and simulated endpoints. No assumed strain target.
    const xs = points.map(p => p.x), ys = points.map(p => p.y);
    const xmin = Math.min(0, ...xs), ymin = Math.min(0, ...ys);
    const xmax = Math.max(...xs, xmin + 1e-9), ymax = Math.max(...ys, ymin + 1e-9);
    const dx = xmax - xmin, dy = ymax - ymin;
    const px = x => 72 + (x - xmin) / dx * 480, py = y => 272 - (y - ymin) / dy * 222;
    const xLabel = mode === 'ss' ? 'Engineering strain (%)' : 'Displacement (mm)';
    const yLabel = mode === 'ss' ? 'Engineering stress (MPa)' : 'Force (N)';
    let ticks = '';
    for (let i = 0; i <= 5; i++) {
      const x = xmin + dx * i / 5, y = ymin + dy * i / 5;
      ticks += `<path class="fem-grid" d="M${px(x)},50V272 M72,${py(y)}H552"/><text x="${px(x)}" y="291" text-anchor="middle">${format(x)}</text><text x="62" y="${py(y) + 4}" text-anchor="end">${format(y)}</text>`;
    }
    return `<svg class="fem-chart" viewBox="0 0 600 330" role="img" aria-label="${escape(xLabel)} versus ${escape(yLabel)}"><rect x="72" y="50" width="480" height="222" class="fem-plot-background"/>${ticks}<path class="fem-axis" d="M72,50V272H552"/>${series.map(s => `<polyline data-series="${escape(s.name)}" class="fem-line fem-line-${escape(s.name)}" points="${s.points.map(p => `${px(p.x)},${py(p.y)}`).join(' ')}"/>`).join('')}<text x="312" y="320" text-anchor="middle">${xLabel}</text><text transform="translate(18 160) rotate(-90)" text-anchor="middle">${yLabel}</text></svg>`;
  }
  function createController(options = {}) {
    const request = options.fetch || ((...args) => root.fetch(...args));
    let analysis = {}, key = null, pointer = null, job = null, generation = 0, inFlight = null, error = '';
    let mode = 'fd', field = 'S_MISES', selectedAttempt = '', selectedContour = '', mounted = null;
    const navigation = new Map(), metadata = new Map(), metadataRequests = new Map();
    function attempts() { return (Array.isArray(job?.attempts) ? job.attempts : []).filter(a => a && a.attempt_id != null); }
    function contours() {
      return attempts().filter(a => artifactPath(a.field_asset_path)).flatMap(attempt => {
        const path = artifactPath(attempt.field_asset_path), meta = metadata.get(path);
        const frames = meta?.frames?.length ? meta.frames : [{frame_index: 0}];
        return frames.map((frame, index) => ({attempt, path, frame, index: Number.isInteger(frame.frame_index) ? frame.frame_index : index,
          key: JSON.stringify([attempt.attempt_id, path, Number.isInteger(frame.frame_index) ? frame.frame_index : index])}));
      });
    }
    function reconcile() {
      const all = attempts(), available = contours();
      if (!all.some(a => String(a.attempt_id) === selectedAttempt)) selectedAttempt = String(all[0]?.attempt_id ?? '');
      if (!available.some(c => c.key === selectedContour)) selectedContour = available[0]?.key || '';
      if (key) navigation.set(key, {selectedAttempt, selectedContour, mode, field});
    }
    function snapshot() {
      reconcile();
      const attempt = attempts().find(a => String(a.attempt_id) === selectedAttempt) || null;
      const contour = contours().find(c => c.key === selectedContour) || null;
      const geometry = job?.specimen_geometry || analysis.specimen_geometry || {};
      const measured = job?.experiment_curve?.length ? job.experiment_curve : analysis.utm_curve?.preview || analysis.force_displacement_curve?.preview || [];
      const names = contour?.frame?.fields ? Object.keys(contour.frame.fields).filter(name => ['S_MISES', 'U'].includes(name)) : [];
      const selectedField = names.includes(field) ? field : names[0];
      const contourUrl = contour && selectedField ? `/api/cae/fields/render?path=${encodeURIComponent(contour.path)}&field=${encodeURIComponent(selectedField)}&frame=${contour.index}` : '';
      return {identity: key, job, attempt, contour, contourUrl, selectedField, fieldNames: names, mode,
        experimentSeries: curveSeries(measured, geometry, mode), femSeries: curveSeries(attempt?.curve, geometry, mode)};
    }
    function nav(kind, list, index) {
      return `<nav class="fem-navigation" aria-label="${kind === 'attempt' ? 'FEM attempts' : 'Solver contours'}"><button type="button" data-fem-nav="${kind}" data-step="-1" ${index <= 0 ? 'disabled' : ''}>Previous</button><span>${list.length ? index + 1 : 0} / ${list.length}</span><button type="button" data-fem-nav="${kind}" data-step="1" ${index < 0 || index >= list.length - 1 ? 'disabled' : ''}>Next</button></nav>`;
    }
    function rows(items) { return `<dl class="fem-evidence">${items.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(display(value))}</dd></div>`).join('')}</dl>`; }
    function content() {
      const s = snapshot(), a = s.attempt, comparison = a?.comparison || {}, progress = job?.progress || {};
      const attemptNav = nav('attempt', attempts(), attempts().indexOf(a));
      const toggle = `<div class="fem-mode" role="group" aria-label="Curve units"><button type="button" data-fem-mode="fd" aria-pressed="${mode === 'fd'}">Force–displacement</button><button type="button" data-fem-mode="ss" aria-pressed="${mode === 'ss'}">Stress–strain</button></div>`;
      const overlay = `${attemptNav}${toggle}<div class="fem-legend"><span class="experiment">Experiment</span><span class="simulation">FEM</span></div>${chart([{name: 'experiment', points: s.experimentSeries}, ...(s.femSeries.length ? [{name: 'fem', points: s.femSeries}] : [])], mode, 'Measured curve pending. Stress–strain requires specimen geometry.')}${!s.femSeries.length ? '<p class="fem-note">FEM pending — measured evidence remains available.</p>' : ''}${rows([['Selected attempt', a?.attempt_id], ['Matching interval end (mm)', comparison.end_mm], ['Peak error (%)', comparison.peak_error_pct], ['Work error (%)', comparison.work_error_pct], ['RMSE (N)', comparison.rmse_N]])}`;
      const response = `${attemptNav}${chart(s.femSeries.length ? [{name: 'fem', points: s.femSeries}] : [], mode, 'FEM response pending. No simulated curve has been recorded.')}${rows([['Attempt', a?.attempt_id], ['Mesh size (mm)', a?.mesh_size_mm], ['Solver status', a?.solver_status], ['Endpoint', a ? (a.endpoint_reached === true ? 'Requested endpoint reached' : a.endpoint_reached === false ? 'Partial endpoint — not a full-range prediction' : 'Endpoint not established') : 'Pending']])}`;
      const c = s.contour, metaError = c && metadata.get(c.path)?.error;
      const contour = `${nav('contour', contours(), contours().findIndex(v => v.key === c?.key))}<div class="fem-mode" role="group" aria-label="Contour field">${s.fieldNames.map(name => `<button type="button" data-fem-field="${escape(name)}" aria-pressed="${name === s.selectedField}">${name === 'U' ? 'Displacement (mm)' : 'von Mises stress (MPa)'}</button>`).join('')}</div>${s.contourUrl ? `<img class="fem-contour-image" loading="lazy" src="${escape(s.contourUrl)}" alt="Actual solver ${escape(s.selectedField)} contour for attempt ${escape(c.attempt.attempt_id)}, frame ${c.index}"/><p class="fem-image-error" hidden>Contour rendering unavailable. Open the field viewer or retry after postprocessing is available.</p>` : `<p class="fem-empty">${escape(metaError || (c ? 'Reading selected field metadata…' : 'Actual solver stress/displacement fields pending. No synthetic contour is shown.'))}</p>`}${c ? `${rows([['Attempt', c.attempt.attempt_id], ['Frame', c.index], ['Step', c.frame.step], ['Time', c.frame.time]])}<a href="/cae/results?path=${encodeURIComponent(c.path)}" target="_blank" rel="noreferrer">Open interactive field viewer</a><button class="fem-retry" type="button" data-fem-retry>Retry contour</button>` : ''}`;
      const events = Array.isArray(job?.events) ? job.events : [];
      const agentic = `${rows([['Background job', job?.status || pointer?.status || 'Not registered'], ['Run / loop / specimen', pointer ? `${pointer.run_id} / ${pointer.loop_key} / ${pointer.specimen_id}` : 'Awaiting current Analysis identity'], ['Phase', progress.phase], ['Message', progress.message], ['Elapsed (s)', progress.elapsed_s], ['Resident memory (MiB)', finite(progress.rss_bytes) ? Number(progress.rss_bytes) / 1048576 : null], ['CPU (%)', progress.cpu_percent], ['Mesh quality (selected attempt)', a?.mesh_quality], ['Response convergence', job?.summary?.convergence || progress.convergence || a?.comparison?.convergence], ['Summary', job?.summary]])}<ol class="fem-events">${events.slice(-30).map(event => `<li><strong>${escape(event.phase || event.event || 'Observation')}</strong> ${escape(display(event.decision || event.message || event))}</li>`).join('')}</ol><p class="fem-note">Mesh quality and response convergence are separate evidence. Background FEM does not delay measured BO handoff.</p>${error ? `<p class="fem-error" role="status">${escape(error)}</p>` : ''}`;
      return {overlay, response, contour, agentic: agentic + (pointer?.reason ? `<p class="fem-note">${escape(pointer.reason)}</p>` : '')};
    }
    function html() {
      const parts = content(), titles = {overlay: 'Experiment vs FEM', response: 'FEM Response', contour: 'Solver Contour', agentic: 'Agentic Progress'};
      return `<section class="analysis-fem-live" data-live-preserve="fem:${escape(key || 'pending')}" aria-label="Analysis FEM evidence">${Object.entries(parts).map(([name, body]) => `<article class="fem-live-card" data-fem-card="${name}"><h3>${titles[name]}</h3><div data-fem-body="${name}">${body}</div></article>`).join('')}</section>`;
    }
    function update() {
      if (mounted?.isConnected) {
        const parts = content();
        Object.entries(parts).forEach(([name, body]) => {
          const node = mounted.querySelector(`[data-fem-body="${name}"]`);
          if (node && node.__femHTML !== body) {
            // Preserve the selected contour image even if frame-count/progress metadata changes.
            const image = name === 'contour' ? node.querySelector('img') : null;
            const url = image?.getAttribute('src');
            const template = mounted.ownerDocument.createElement('template'); template.innerHTML = body;
            const nextImage = template.content.querySelector('img');
            if (image && nextImage?.getAttribute('src') === url) nextImage.replaceWith(image);
            node.replaceChildren(template.content); node.__femHTML = body;
          }
        });
      }
      options.onChange?.(snapshot());
    }
    function setContext(next = {}) {
      const nextPointer = next.fem_job || next.improvement;
      const nextKey = identity(nextPointer);
      analysis = next;
      pointer = nextPointer && typeof nextPointer === 'object' ? nextPointer : null;
      if (key !== nextKey) {
        key = nextKey; generation++; job = null; error = ''; inFlight = null;
        const saved = navigation.get(key) || {};
        selectedAttempt = saved.selectedAttempt || ''; selectedContour = saved.selectedContour || '';
        mode = saved.mode || 'fd'; field = saved.field || 'S_MISES';
        mounted = null;
      }
    }
    function accept(payload) {
      job = key ? (payload?.jobs || []).find(item => identity(item) === key) || null : null;
      error = ''; reconcile(); update();
    }
    async function poll() {
      if (!key || inFlight) return;
      const requestGeneration = generation;
      const query = ['run_id', 'loop_key', 'specimen_id'].map(name => `${name}=${encodeURIComponent(pointer[name])}`).join('&');
      const token = {}; inFlight = token;
      try {
        const response = await request(`/api/analysis/fem/jobs?${query}`, {method: 'GET'});
        if (!response.ok) throw Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (generation === requestGeneration) { accept(payload); await loadContour(); }
      } catch (err) {
        if (generation === requestGeneration) { error = `FEM evidence refresh unavailable: ${err.message}`; update(); }
      } finally { if (inFlight === token) inFlight = null; }
    }
    async function loadContour() {
      const c = snapshot().contour;
      if (!c || metadata.has(c.path)) return;
      if (metadataRequests.has(c.path)) return metadataRequests.get(c.path);
      const task = (async () => {
        try {
          const response = await request(`/api/cae/fields/metadata?path=${encodeURIComponent(c.path)}`, {method: 'GET'});
          if (!response.ok) throw Error(`HTTP ${response.status}`);
          metadata.set(c.path, await response.json());
        } catch (err) { metadata.set(c.path, {error: `Field metadata unavailable: ${err.message}`}); }
        finally { metadataRequests.delete(c.path); update(); }
      })();
      metadataRequests.set(c.path, task); return task;
    }
    function navigate(kind, step) {
      const all = kind === 'contour' ? contours() : attempts();
      const index = all.findIndex(item => kind === 'contour' ? item.key === selectedContour : String(item.attempt_id) === selectedAttempt);
      const selected = all[Math.max(0, Math.min(all.length - 1, index + Number(step)))];
      if (selected) {
        if (kind === 'contour') selectedContour = selected.key; else selectedAttempt = String(selected.attempt_id);
        reconcile(); update();
      }
    }
    function setMode(value) { if (['fd', 'ss'].includes(value)) {mode = value; update();} }
    function mount(element) {
      if (!element) return;
      mounted = element;
      if (!element.__femBound) {
        element.__femBound = true;
        element.addEventListener('click', event => {
          const button = event.target.closest('button'); if (!button || button.disabled) return;
          if (button.dataset.femNav) { navigate(button.dataset.femNav, Number(button.dataset.step)); loadContour(); }
          if (button.dataset.femMode) setMode(button.dataset.femMode);
          if (button.dataset.femField) {field = button.dataset.femField; update();}
          if (button.hasAttribute('data-fem-retry')) {
            const c = snapshot().contour; if (c) metadata.delete(c.path);
            const body = element.querySelector('[data-fem-body="contour"]'); if (body) {body.__femHTML = ''; body.replaceChildren();}
            loadContour();
          }
        });
        element.addEventListener('error', event => {
          if (event.target.matches?.('.fem-contour-image')) {
            const note = event.target.nextElementSibling; if (note) note.hidden = false;
          }
        }, true);
      }
      update(); loadContour();
    }
    return {setContext, accept, snapshot, html, poll, loadContour, navigate, setMode, mount};
  }
  const api = {createController, curveSeries};
  if (typeof module !== 'undefined') module.exports = api;
  root.AnalysisFemLive = api;
})(typeof window !== 'undefined' ? window : globalThis);
