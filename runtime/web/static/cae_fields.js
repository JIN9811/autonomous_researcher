/* Actual solver field viewer. All interactions are read-only; no run endpoint. */
(function (root) {
  'use strict';
  function scalars(field, component) {
    if (!field || !Array.isArray(field.values) || !field.values.length) throw Error('Field unavailable');
    return field.values.map((row) => {
      const values = Array.isArray(row) ? row : [row];
      if (!values.length || !values.every((v) => typeof v === 'number' && Number.isFinite(v))) throw Error('Missing/non-finite field values');
      if (component < -1 || component >= values.length) throw Error('Component unavailable');
      if (component === -1 && values.length > 3) throw Error('Tensor magnitude unavailable; select a component or S_MISES');
      return component === -1 && values.length > 1 ? Math.hypot(...values) : values[Math.max(0, component)];
    });
  }
  function colorRange(arrays) {
    let lo = Infinity, hi = -Infinity;
    arrays.forEach((values) => values.forEach((v) => {if (Number.isFinite(v)) {lo = Math.min(lo,v); hi = Math.max(hi,v);}}));
    if (!Number.isFinite(lo)) throw Error('No finite field range');
    return [lo, hi === lo ? lo + Math.max(1,Math.abs(lo)) * 1e-9 : hi];
  }
  function matchFrame(frames, target) {
    if(!target) return undefined;
    const time=target.time ?? target.value;
    if(typeof time!=='number'||!Number.isFinite(time)) return undefined;
    return frames.find(frame => frame.step === target.step && (frame.time ?? frame.value) === time);
  }
  function compatibleField(left, right) {
    if(!left||!right||left.units!==right.units||left.association!==right.association||JSON.stringify(left.components)!==JSON.stringify(right.components))
      throw Error('Comparison field units, association or components differ');
  }
  function fieldLabel(name, field, component) {
    const componentName=component===-1&&field.components?.length>1?'Magnitude':field.components?.[Math.max(0,component)]||'Value';
    return `${name} · ${componentName} [${field.units||'—'}]`;
  }
  if (typeof module !== 'undefined') module.exports = {scalars, colorRange, matchFrame, compatibleField, fieldLabel};
  if (typeof document === 'undefined' || !document.getElementById('field-viewer')) return;
  const $ = (id) => document.getElementById(id);
  let datasets = [], views = [], timer = null, rendering = 0;
  function status(text, error=false) {$('field-status').textContent=text; $('field-status').className=error?'error':'';}
  async function get(url) {const response=await fetch(url); const data=await response.json(); if(!response.ok) throw Error(data.detail||'Unable to read field artifact'); return data;}
  function settings() {return {field:$('field-name').value, component:Number($('field-component').value), frame:Number($('field-frame').value), scale:Number($('field-scale').value), edges:$('field-edges').checked, range:$('range-mode').value};}
  function frameAt(data, index) {
    if (data === datasets[0] || !datasets[0]) return data.frames[index];
    const target = datasets[0].frames[index];
    // Equal time in different load steps is not an equal result state.
    return matchFrame(data.frames,target);
  }
  function buildPoly(points, triangles, values) {
    const poly=vtk.Common.DataModel.vtkPolyData.newInstance();
    poly.getPoints().setData(Float64Array.from(points.flat()),3);
    poly.getPolys().setData(Uint32Array.from(triangles.flatMap((row)=>[3,...row])));
    if(values) poly.getPointData().setScalars(vtk.Common.Core.vtkDataArray.newInstance({name:'value',values:Float64Array.from(values)}));
    return poly;
  }
  function makeView(id) {
    const win=vtk.Rendering.Misc.vtkGenericRenderWindow.newInstance({background:[1,1,1]});
    win.setContainer($(id)); win.resize();
    const renderer=win.getRenderer(), mapper=vtk.Rendering.Core.vtkMapper.newInstance(), actor=vtk.Rendering.Core.vtkActor.newInstance();
    const lut=vtk.Rendering.Core.vtkColorTransferFunction.newInstance();
    [[0,.267,.005,.329],[.25,.230,.322,.545],[.5,.128,.567,.551],[.75,.369,.789,.383],[1,.993,.906,.144]].forEach(([x,r,g,b])=>lut.addRGBPoint(x,r,g,b));
    mapper.setLookupTable(lut); mapper.setInterpolateScalarsBeforeMapping(true); actor.setMapper(mapper); actor.getProperty().setAmbient(.28); actor.getProperty().setDiffuse(.72); actor.getProperty().setSpecular(.12); renderer.addActor(actor);
    const bar=vtk.Rendering.Core.vtkScalarBarActor.newInstance(); bar.setScalarsToColors(lut); bar.setAxisLabel('Field'); bar.setTickTextStyle({fontColor:'black',fontSize:12}); bar.setAxisTextStyle({fontColor:'black',fontSize:13}); renderer.addActor(bar);
    const axes=vtk.Rendering.Core.vtkAxesActor.newInstance();
    const marker=vtk.Interaction.Widgets.vtkOrientationMarkerWidget.newInstance({actor:axes,interactor:win.getInteractor()}); marker.setEnabled(true); marker.setViewportSize(.13);
    const picker=vtk.Rendering.Core.vtkPointPicker.newInstance(); picker.setPickFromList(true); picker.addPickList(actor); picker.setTolerance(.02);
    const view={win,renderer,mapper,actor,lut,bar,marker,picker,poly:null,overlay:null,section:null};
    win.getInteractor().onLeftButtonPress((event)=>{
      if(!view.poly) return;
      picker.pick([event.position.x,event.position.y,0],renderer); const point=picker.getPointId();
      if(point<0 || point>=view.points.length) return;
      const value=view.values[point], location=view.points[point];
      $('field-probe').textContent=`${view.section?'Interpolated section point':`Node ${view.nodeIds[point]}`} · (${location.map(v=>v.toFixed(4)).join(', ')}) mm · ${value.toPrecision(6)} ${view.unit}`;
    });
    let syncing=false;
    const syncCamera=()=>{if(syncing||views.length<2)return; syncing=true; const camera=renderer.getActiveCamera(); views.filter(v=>v!==view).forEach(v=>{v.renderer.getActiveCamera().set({position:camera.getPosition(),focalPoint:camera.getFocalPoint(),viewUp:camera.getViewUp(),parallelScale:camera.getParallelScale()}); v.renderer.resetCameraClippingRange(); v.win.getRenderWindow().render();}); syncing=false;};
    $(id).addEventListener('pointerup',syncCamera); $(id).addEventListener('wheel',()=>requestAnimationFrame(syncCamera));
    new ResizeObserver(()=>win.resize()).observe($(id));
    return view;
  }
  function components() {
    const field=datasets[0].frames[Number($('field-frame').value)]?.fields[$('field-name').value];
    $('field-component').replaceChildren();
    if(!field) return;
    const names=field.components||['Value'];
    if(names.length>1 && names.length<=3) $('field-component').add(new Option('Magnitude',-1));
    names.forEach((name,i)=>$('field-component').add(new Option(name,i)));
  }
  async function render(reset=false) {
    if(!datasets.length)return;
    const generation=++rendering;
    try {
      const s=settings(); if(!Number.isFinite(s.scale)||s.scale<0||s.scale>1000)throw Error('Deformation scale must be 0–1000');
      const selected=datasets[0].frames[s.frame];
      datasets.forEach(data=>{const frame=frameAt(data,s.frame);if(!frame)throw Error('Comparison has no matching solver step and time');compatibleField(selected?.fields[s.field],frame.fields[s.field]);});
      let ranges=[];
      datasets.forEach(data=>{const frames=s.range==='shared'?data.frames:[frameAt(data,s.frame)]; frames.forEach(f=>{if(f?.fields[s.field]?.values?.length) ranges.push(scalars(f.fields[s.field],s.component));});});
      const limits=s.range==='manual'?[Number($('field-min').value),Number($('field-max').value)]:colorRange(ranges);
      if(!limits.every(Number.isFinite)||limits[0]>=limits[1])throw Error('Minimum must be below maximum');
      $('field-min').value=limits[0]; $('field-max').value=limits[1];
      for(let n=0;n<datasets.length;n++) {
        const data=datasets[n], view=views[n], frame=frameAt(data,s.frame);
        if(!frame)throw Error('Comparison has no matching physical frame; choose a common frame');
        const field=frame.fields[s.field], values=scalars(field,s.component), geo=data.geometry;
        if(field.association!=='point'||values.length!==geo.node_ids.length)throw Error('Complete nodal field required');
        const displacement=s.scale?frame.fields.U?.values:null;
        if(s.scale && (!displacement || displacement.length!==geo.points.length))throw Error('Full displacement unavailable: set scale to 0 for undeformed results');
        let points=geo.points.map((p,i)=>p.map((v,j)=>v+(s.scale?displacement[i][j]*s.scale:0)));
        const indices=new Map(geo.node_ids.map((id,i)=>[id,i]));
        let triangles=geo.surface.triangles.map(row=>row.map(id=>indices.get(id)));
        if(triangles.some(row=>row.some(index=>index===undefined)))throw Error('Surface node mapping invalid');
        let shownValues=values;
        view.section=$('section-axis').value!=='none';
        if(view.section) {
          const query=new URLSearchParams({path:data._path,field:s.field,frame:data.frames.indexOf(frame),component:s.component,scale:s.scale,axis:$('section-axis').value,position:$('section-position').value});
          const cut=await get(`/api/cae/fields/section?${query}`); if(generation!==rendering)return;
          points=cut.points; triangles=cut.triangles; shownValues=cut.values;
        }
        const poly=buildPoly(points,triangles,shownValues); const old=view.poly; view.mapper.setInputData(poly); view.poly=poly; if(old)old.delete();
        view.points=points; view.values=shownValues; view.nodeIds=geo.node_ids; view.unit=field.units||'';
        view.lut.setMappingRange(...limits); view.lut.updateRange(); view.mapper.setScalarRange(...limits);
        view.actor.getProperty().setEdgeVisibility(s.edges); view.actor.getProperty().setEdgeColor(.35,.39,.43);
        view.bar.setAxisLabel(fieldLabel(s.field,field,s.component));
        if(view.overlay){view.renderer.removeActor(view.overlay); view.overlay.getMapper().getInputData().delete(); view.overlay.getMapper().delete(); view.overlay.delete(); view.overlay=null;}
        if($('field-overlay').checked) {
          const outline=vtk.Rendering.Core.vtkActor.newInstance(), mapper=vtk.Rendering.Core.vtkMapper.newInstance();
          mapper.setInputData(buildPoly(geo.points,geo.surface.triangles.map(row=>row.map(id=>indices.get(id))))); outline.setMapper(mapper); outline.getProperty().setRepresentationToWireframe(); outline.getProperty().setColor(.65,.68,.72); outline.getProperty().setOpacity(.25); view.renderer.addActor(outline); view.overlay=outline;
        }
        if(reset){view.renderer.getActiveCamera().setPosition(1,-1,1); view.renderer.getActiveCamera().setViewUp(0,0,1); view.renderer.resetCamera();}
        view.renderer.resetCameraClippingRange(); view.win.getRenderWindow().render();
        $(n?'compare-meta':'baseline-meta').textContent=`${geo.node_ids.length.toLocaleString()} nodes · ${geo.elements.length.toLocaleString()} elements`;
      }
      const frame=datasets[0].frames[s.frame], field=frame.fields[s.field];
      $('frame-label').textContent=`${s.frame+1}/${datasets[0].frames.length} · t=${frame.time??frame.value}`;
      $('field-semantics').textContent=`${field.association||'point'} · ${field.averaging||'as exported'} · ${field.coordinate_system||'global'} · deformation ×${s.scale}. ${field.source||''}`;
      status('Showing saved solver data. Camera, probes, sections and exports do not run the solver.'+(datasets.length>1?' Comparison aligns solver step/time; verify matching loading conditions before interpreting differences.':''));
    } catch(error){status(error.message,true);}
  }
  async function load(event) {
    event?.preventDefault(); status('Loading field evidence…'); if(timer){clearInterval(timer);timer=null;}$('field-play').textContent='Play';
    try {
      const paths=[$('field-path').value,$('compare-path').value].filter(Boolean);
      datasets=await Promise.all(paths.map(async path=>({...await get(`/api/cae/fields?path=${encodeURIComponent(path)}`),_path:path})));
      if(datasets.some(d=>!d.frames?.length||!d.geometry?.surface))throw Error(datasets[0].failure_code||'No supported solver fields in artifact');
      if(!views.length)views.push(makeView('field-viewer'));
      $('compare-card').hidden=datasets.length<2;
      if(datasets.length>1&&!views[1])views.push(makeView('compare-viewer'));
      views.forEach(v=>v.win.resize());
      const fields=new Set(datasets[0].frames.flatMap(f=>Object.keys(f.fields).filter(k=>f.fields[k].values?.length)));
      $('field-name').replaceChildren(...[...fields].map(name=>new Option(name,name)));
      if(fields.has('S_MISES'))$('field-name').value='S_MISES';
      $('field-frame').max=datasets[0].frames.length-1;
      $('field-frame').value=datasets[0].frames.findLastIndex(frame=>frame.fields[$('field-name').value]?.values?.length);
      components(); $('field-provenance').textContent=JSON.stringify(datasets.map(d=>({path:d._path,source_hashes:d.source_hashes,mesh_evidence:d.mesh_evidence,warnings:d.warnings})),null,2);
      await render(true);
    }catch(error){status(error.message,true);}
  }
  $('load-fields').addEventListener('submit',load);
  $('field-name').addEventListener('change',()=>{components();render();});
  ['field-component','field-frame','field-scale','field-edges','field-overlay','range-mode','field-min','field-max'].forEach(id=>$(id).addEventListener('change',()=>render()));
  $('section-apply').onclick=()=>render(); $('field-fit').onclick=()=>render(true);
  $('field-view').onchange=()=>{const axis=$('field-view').value; views.forEach(v=>{const c=v.renderer.getActiveCamera(); c.setFocalPoint(0,0,0); c.setPosition(...(axis==='iso'?[1,-1,1]:axis==='x'?[1,0,0]:axis==='y'?[0,-1,0]:[0,0,1]));c.setViewUp(...(axis==='z'?[0,1,0]:[0,0,1]));v.renderer.resetCamera();v.win.getRenderWindow().render();});};
  $('field-play').onclick=()=>{if(!datasets.length)return;if(timer){clearInterval(timer);timer=null;$('field-play').textContent='Play';}else{timer=setInterval(()=>{$('field-frame').value=(Number($('field-frame').value)+1)%datasets[0].frames.length;render();},1000);$('field-play').textContent='Pause';}};
  $('field-export').onclick=()=>{if(!datasets.length)return;const s=settings(),camera=views[0].renderer.getActiveCamera(); const query=new URLSearchParams({...s,path:datasets[0]._path,minimum:$('field-min').value,maximum:$('field-max').value,axis:$('section-axis').value,position:$('section-position').value,overlay:$('field-overlay').checked,camera:JSON.stringify([camera.getPosition(),camera.getFocalPoint(),camera.getViewUp()])});window.open(`/api/cae/fields/render?${query}`,'_blank','noopener');};
  $('field-recipe').onclick=()=>{if(!datasets.length)return;const camera=views[0].renderer.getActiveCamera();const recipe={schema:'cae_render_recipe.v1',paths:datasets.map(d=>d._path),source_hashes:datasets.map(d=>d.source_hashes),...settings(),limits:[$('field-min').value,$('field-max').value],section:{axis:$('section-axis').value,position:$('section-position').value},camera:{position:camera.getPosition(),focalPoint:camera.getFocalPoint(),viewUp:camera.getViewUp()}};const url=URL.createObjectURL(new Blob([JSON.stringify(recipe,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='analysis-view-recipe.json';link.click();URL.revokeObjectURL(url);};
  const initial=new URLSearchParams(location.search);if(initial.get('path')){$('field-path').value=initial.get('path');$('compare-path').value=initial.get('compare')||'';load();}
})(typeof window !== 'undefined' ? window : globalThis);
