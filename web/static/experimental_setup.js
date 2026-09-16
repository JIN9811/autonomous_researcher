/* Server-projected Setup presentation only. This module never sends commands. */
(function (host, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else host.ExperimentalSetup = api;
})(typeof window === 'object' ? window : this, function () {
  'use strict';
  const views = new WeakMap();
  let cardSequence = 0;

  function beginEdit(block) {
    return { block_id: block.block_id, revision: block.revision };
  }

  function acceptSnapshot(current, incoming) {
    if (!incoming || !Number.isInteger(incoming.revision) || !Array.isArray(incoming.blocks)) return current;
    if (current && current.session_id && incoming.session_id !== current.session_id) return current;
    if (current && incoming.revision < current.revision) return current;
    // A projection hash is identity, not an ordering key. Transport ordering is
    // handled by planning.js; graph/status changes need not change value revision.
    return incoming;
  }

  function element(doc, tag, className, text) {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function setText(node, text) {
    const next = String(text);
    if (node.textContent !== next) node.textContent = next;
  }

  function valueText(value) {
    if (value === null || value === undefined) return 'Not set';
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  }

  function fieldLabel(key) {
    const labels = {goal:'Goal', 'research.goal':'Goal', material:'Material',
      specimen_size_mm:'Specimen size', geometry_type:'Structure', experiment_domain:'Experiment type',
      objective_type:'Objective', objective_direction:'Direction', cell_size_mm:'Cell size',
      wall_thickness_mm:'Wall thickness', cell_size_bounds_mm:'Cell size range (mm)',
      wall_thickness_bounds_mm:'Wall thickness range (mm)', relative_density:'Relative density (derived)'};
    return labels[key] || String(key).replace(/^conversation\.input\./, '').replace(/[_.]+/g, ' ').replace(/^./, s=>s.toUpperCase());
  }

  function readableValue(value, key) {
    if (value === null || value === undefined || value === '') return 'Not set';
    if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
    if (Array.isArray(value)) {
      const dimensions = /size_mm$|limit_mm$/.test(key) && value.length === 3;
      return value.map(v=>readableValue(v, '')).join(dimensions ? ' × ' : ', ') + (dimensions ? ' mm' : '');
    }
    if (typeof value === 'object') return Object.entries(value).map(([k,v])=>`${fieldLabel(k)}: ${readableValue(v,k)}`).join('; ');
    const unit = typeof value === 'number' ? (/mm_s$/.test(key) ? ' mm/s' : /_mm$/.test(key) ? ' mm' : /_percent$/.test(key) ? '%' : /_c$/.test(key) ? ' °C' : '') : '';
    return String(value).replace(/_/g, ' ') + unit;
  }

  function currentValues(block) {
    for (const values of [block.draft_values, block.confirmed_values, block.effective_values]) {
      if (values && Object.keys(values).length) return values;
    }
    return {};
  }

  function groupedBlocks(snapshot) {
    const originals = (snapshot && snapshot.blocks || []).filter(b=>!b.internal_default_only);
    if (!originals.some(b=>String(b.topic_key).startsWith('conversation.input.'))) return originals;
    const definitions = [
      ['objective','Research objective',['goal','objective_type','objective_direction']],
      ['specimen','Specimen',['material','specimen_size_mm','geometry_type','experiment_domain']],
      ['range','Design range',['cell_size_bounds_mm','wall_thickness_bounds_mm']],
      ['constraints','Constraints',['min_wall_thickness_mm','fdm_min_wall_thickness_mm']],
      ['bo','BO settings',['bo.acquisition']]
    ];
    const groups = definitions.map(([id,title,keys])=>({block_id:`__setup_${id}__`,title,keys,
      grouped:true,revision:snapshot.revision,active:true,editable:false,owners:[],
      draft_values:{}, source_fields:{}, source_blocks:[], current_run_values:{}}));
    const remaining = [];
    // Conversation values supersede their legacy presentation aliases only.
    // The underlying versioned blocks remain intact for edits and audit.
    const sorted = [...originals].sort((a,b)=>Number(String(a.topic_key).startsWith('conversation.input.'))-Number(String(b.topic_key).startsWith('conversation.input.')));
    for (const block of sorted) {
      const entries = block.topic_key === 'bo.parameter_space'
        ? Object.entries(currentValues(block)['bo.parameter_space'] || {}).filter(([k])=>['cell_size_mm','wall_thickness_mm'].includes(k)).map(([k,v])=>[k==='cell_size_mm'?'cell_size_bounds_mm':'wall_thickness_bounds_mm',v])
        : Object.entries(currentValues(block)).map(([k,v])=>[k==='research.goal'?'goal':k,v]);
      let used = false;
      for (const [key,value] of entries) {
        const group = groups.find(g=>g.keys.includes(key));
        if (!group) continue;
        used = true;
        group.draft_values[key] = value;
        group.source_fields[key] = block;
        if (!group.source_blocks.includes(block)) group.source_blocks.push(block);
        if (Object.prototype.hasOwnProperty.call(snapshot.current_run_values || {},key)) group.current_run_values[key] = snapshot.current_run_values[key];
      }
      if (!used) remaining.push(block);
    }
    return [...groups.filter(g=>g.source_blocks.length), ...remaining];
  }

  function shortStatus(block) {
    if (block.grouped) {
      if (block.source_blocks.some(b=>shortStatus(b)==='Needs attention')) return 'Needs attention';
      return Object.entries(block.current_run_values).some(([k,v])=>JSON.stringify(v)!==JSON.stringify(block.draft_values[k])) ? 'Differs from run' : 'Saved inputs';
    }
    if (block.package_summary) return block.active ? 'Bound' : 'Not bound';
    if (block.active === false) return 'Inactive';
    if (['failed','invalid','blocked'].includes(block.validation_status) || ['failed','blocked','rejected','partial','unknown'].includes(block.application_status)) return 'Needs attention';
    if (block.application_status === 'applying') return 'Applying';
    if (block.conversation_input) return 'Saved';
    if (block.current_draft_proposal_id) return 'Unsaved changes';
    if (block.application_status === 'applied') return 'Applied';
    if (block.agreement_status === 'confirmed') return 'For next run';
    return block.editable ? 'Current' : 'Read-only';
  }

  function setExpanded(card, expanded) {
    card.body.hidden = !expanded;
    card.toggle.setAttribute('aria-expanded', String(expanded));
  }

  function toggleCard(view, id) {
    const at = view.expanded.indexOf(id);
    if (at >= 0) view.expanded.splice(at, 1);
    else { view.expanded.push(id); if (view.expanded.length > 3) view.expanded.shift(); }
    for (const [key, card] of view.cards) setExpanded(card, view.expanded.includes(key));
  }

  function makeCard(doc) {
    const card = element(doc, 'article', 'setup-block');
    const toggle = element(doc, 'button', 'setup-block-toggle');
    toggle.type = 'button';
    const title = element(doc, 'span', 'setup-block-title');
    const preview = element(doc, 'span', 'setup-block-preview');
    const badge = element(doc, 'span', 'setup-block-badge');
    toggle.append(title, preview, badge);
    const body = element(doc, 'div', 'setup-block-body');
    body.setAttribute('id', `setup-card-body-${++cardSequence}`);
    toggle.setAttribute('aria-controls', `setup-card-body-${cardSequence}`);
    const readable = element(doc, 'dl', 'setup-readable-values');
    const meta = element(doc, 'p', 'setup-block-meta');
    const status = element(doc, 'p', 'setup-block-status');
    const timing = element(doc, 'p', 'setup-block-timing');
    const reason = element(doc, 'p', 'setup-readonly-reason');
    const editing = element(doc, 'p', 'setup-editing');
    const details = element(doc, 'details', 'setup-block-details');
    const summary = element(doc, 'summary', '', 'Technical details');
    details.append(summary, meta, status, timing, reason);
    const values = {};
    for (const label of ['Draft', 'Confirmed', 'Effective', 'Change diff', 'Receipts']) {
      const section = element(doc, 'section', 'setup-value-section');
      const heading = element(doc, 'h4', '', label);
      const pre = element(doc, 'pre', 'setup-value');
      section.append(heading, pre); details.append(section); values[label] = pre;
    }
    const actions = element(doc, 'div', 'setup-block-actions');
    const buttons = {};
    for (const label of ['Edit', 'Confirm', 'Discard']) {
      const button = element(doc, 'button', 'btn', label);
      button.type = 'button'; button.dataset.setupAction = label.toLowerCase();
      actions.append(button); buttons[label] = button;
    }
    body.append(readable, editing, actions, details);
    card.append(toggle, body);
    const view = {card, toggle, body, title, preview, badge, readable, meta, status, timing, editing, reason, details, values, buttons};
    setExpanded(view, false);
    return view;
  }

  function updateCard(view, block, callbacks) {
    const title = block.title || fieldLabel(block.topic_key || block.block_id);
    const writable = block.active === true && block.editable === true;
    const request = callbacks.actionRequests && callbacks.actionRequests.get(block.block_id);
    const busy = Boolean(request && request.pending);
    const draft = Boolean(block.current_draft_proposal_id);
    const context = callbacks.editContext;
    const editing = context && context.block_id === block.block_id;
    view.card.dataset.blockId = block.block_id;
    view.card.dataset.revision = String(block.revision);
    view.card.dataset.editable = String(writable);
    view.card.dataset.kind = block.package_summary ? 'package' : 'setting';
    view.details.hidden = Boolean(block.package_summary);
    setText(view.title, title);
    const entries = Object.entries(currentValues(block));
    const preview = block.package_summary ? readableValue(currentValues(block).package, 'package')
      : entries.map(([key,value])=>readableValue(value,key)).join(' · ') || 'Not set';
    setText(view.preview, preview);
    view.toggle.setAttribute('aria-label', `${title}: ${preview}`);
    view.toggle.setAttribute('title', `${title}: ${preview}`);
    setText(view.badge, shortStatus(block));
    view.card.dataset.status = shortStatus(block).toLowerCase().replace(/ /g, '-');
    const signature = JSON.stringify([entries, block.current_run_values, block.source_blocks, callbacks.editContext]);
    if (view.readableSignature !== signature) {
      view.readable.textContent = '';
      entries.forEach(([key, value])=>{
        const doc = view.card.ownerDocument;
        const cell = element(doc, 'dd', '', readableValue(value,key));
        if (block.grouped) {
          const applied = block.current_run_values;
          if (Object.prototype.hasOwnProperty.call(applied,key) && JSON.stringify(applied[key])!==JSON.stringify(value)) {
            cell.append(element(doc,'small','setup-run-value',`Current run: ${readableValue(applied[key],key)}`));
          }
          const source = block.source_fields[key];
          const edit = element(doc,'button','btn setup-field-edit','Edit');
          edit.type='button'; edit.disabled=!(source.active && source.editable);
          edit.setAttribute('aria-label',`Edit ${fieldLabel(key)}`);
          edit.onclick=()=>{if(!edit.disabled && callbacks.onEdit) callbacks.onEdit(source);};
          cell.append(edit);
          if (!source.conversation_input && source.current_draft_proposal_id) {
            for (const [label,handler] of [['Confirm','onConfirm'],['Discard','onDiscard']]) {
              const action=element(doc,'button','btn setup-field-edit',label);
              action.type='button'; action.disabled=edit.disabled;
              action.setAttribute('aria-label',`${label} ${fieldLabel(key)}`);
              action.onclick=()=>{if(!action.disabled && callbacks[handler]) callbacks[handler](source);};
              cell.append(action);
            }
          }
        }
        view.readable.append(element(doc, 'dt', '', fieldLabel(key)),cell);
      });
      view.readableSignature = signature;
    }
    setText(view.meta, `Owner: ${(block.owners || []).join(', ') || 'Unknown'} · Revision ${block.revision}`);
    setText(view.status, `Agreement: ${block.agreement_status || 'unknown'} · Application: ${block.application_status || 'unknown'}${block.validation_status ? ` · Validation: ${block.validation_status}` : ''}`);
    setText(view.timing, block.conversation_input
      ? 'Research input saved from Chat. Review and approve execution in Chat.'
      : 'Apply time: next new run only. Confirming does not start a run.');
    setText(view.editing, editing ? (context.revision !== block.revision ? 'Updated since editing. Select Edit again.' : 'Editing in Chat') : '');
    view.editing.hidden = !editing;
    view.reason.hidden = writable;
    setText(view.reason, writable ? '' : `Read-only: ${block.readonly_reason || (block.active === false ? 'Inactive in the current graph.' : 'No supported writable setup contract.')}`);
    setText(view.values.Draft, valueText(block.draft_values));
    setText(view.values.Confirmed, valueText(block.confirmed_values));
    setText(view.values.Effective, valueText(block.effective_values));
    const baseline = block.confirmed_values || block.effective_values || {};
    const next = block.draft_values || {};
    const changed = [...new Set([...Object.keys(baseline), ...Object.keys(next)])]
      .filter(key => JSON.stringify(baseline[key]) !== JSON.stringify(next[key]));
    setText(view.values['Change diff'], changed.length
      ? changed.map(key => `${key}\n− ${valueText(baseline[key])}\n+ ${valueText(next[key])}`).join('\n\n')
      : 'No changes from the confirmed values (or effective values if not confirmed).');
    setText(view.values.Receipts, valueText(block.receipts || {}));
    if (block.grouped) {
      setText(view.values.Draft, valueText(block.source_blocks));
      setText(view.timing,'Saved inputs are edited in Chat. Differences from the current run are shown explicitly; editing does not apply or execute a run.');
      setText(view.values.Effective, valueText(block.current_run_values));
    }
    for (const [label, callback] of [['Edit', 'onEdit'], ['Confirm', 'onConfirm'], ['Discard', 'onDiscard']]) {
      const button = view.buttons[label];
      const retry = request && !request.pending && request.body.action === label.toLowerCase()
        && request.body.proposal_id === block.current_draft_proposal_id && request.body.expected_revision === block.revision;
      setText(button, retry ? `Retry ${label.toLowerCase()}` : label);
      button.disabled = !writable || busy || (label !== 'Edit' && !draft);
      if (block.conversation_input && label !== 'Edit') button.disabled = true;
      button.hidden = Boolean(block.package_summary || block.grouped || (block.conversation_input && label !== 'Edit'));
      button.setAttribute('aria-label', `${retry ? 'Retry ' : ''}${label} ${title}`);
      button.onclick = () => { if (!button.disabled && callbacks[callback]) callbacks[callback](block); };
    }
    view.card.setAttribute('aria-busy', String(busy));
  }

  function renderBlocks(root, snapshot, callbacks = {}) {
    if (!root) return;
    const doc = root.ownerDocument;
    let view = views.get(root);
    if (!view) {
      const intro = element(doc, 'p', 'setup-intro');
      const notice = element(doc, 'p', 'setup-notice'); notice.setAttribute('role', 'status');
      const blocks = element(doc, 'div', 'setup-block-list');
      const owners = element(doc, 'div', 'setup-owner-list');
      const technical = element(doc, 'details', 'setup-technical');
      technical.append(element(doc, 'summary', '', 'Technical details'), intro, owners);
      root.append(notice, blocks, technical);
      view = {intro, notice, blocks, owners, cards:new Map(), ownerCards:new Map(), expanded:[], sessionId:snapshot && snapshot.session_id}; views.set(root, view);
    }
    if (snapshot && view.sessionId !== snapshot.session_id) {
      view.expanded = []; view.sessionId = snapshot.session_id;
      for (const card of view.cards.values()) card.details.open = false;
    }
    setText(view.intro, snapshot ? `Setup revision ${snapshot.revision} · Availability is owner-reported; unknown is not ready.` : 'Waiting for the current session’s setup snapshot.');
    setText(view.notice, callbacks.notice || ''); view.notice.hidden = !callbacks.notice;
    const ids = new Set();
    const blocks = [...groupedBlocks(snapshot)];
    if (callbacks.graph !== undefined) {
      const graph = callbacks.graph || {};
      const pkg = graph.metadata && graph.metadata.experimental_package;
      const bound = Boolean(pkg && pkg.id && pkg.version);
      blocks.unshift({block_id:'__experimental_package__', title:'Experimental Package',
        revision:0, package_summary:true, active:bound, editable:false,
        readonly_reason:'Composition follows the active orchestration plan. Configure packages in Runtime IDE.',
        draft_values:bound ? {package:pkg.display_name || pkg.id, package_id:pkg.id,
          version:pkg.version, orchestration_plan:graph.name || graph.id} : {package:'Not bound',
          orchestration_plan:graph.name || graph.id || 'Not bound'},
        owners:[], agreement_status:'unknown', application_status:'not_applied'});
    }
    blocks.forEach((block, index) => {
      if (!block || !block.block_id || ids.has(block.block_id)) return;
      ids.add(block.block_id);
      let card = view.cards.get(block.block_id);
      if (!card) { card = makeCard(doc); view.cards.set(block.block_id, card); }
      updateCard(card, block, callbacks);
      card.toggle.onclick = () => toggleCard(view, block.block_id);
      setExpanded(card, view.expanded.includes(block.block_id));
      // Never detach an unchanged card: focus and details remain browser-owned.
      if (view.blocks.children[index] !== card.card) view.blocks.insertBefore(card.card, view.blocks.children[index] || null);
    });
    for (const [id, card] of view.cards) if (!ids.has(id)) { card.card.remove(); view.cards.delete(id); }
    view.expanded = view.expanded.filter(id=>ids.has(id));
    const ownerIds = new Set();
    (snapshot && snapshot.owners || []).forEach((owner, index) => {
      const id = JSON.stringify([owner.owner, owner.node_id, owner.step_id, owner.module_id, owner.handler]);
      if (ownerIds.has(id)) return;
      ownerIds.add(id);
      let card = view.ownerCards.get(id);
      if (!card) { card = element(doc, 'p', 'setup-owner'); view.ownerCards.set(id, card); }
      const writable = owner.setup && owner.setup.write_enabled;
      const reason = owner.setup && (owner.setup.reason || owner.setup.readonly_reason);
      setText(card, `Owner: ${owner.owner || 'Unknown'} · ${owner.node_id || owner.module_id || 'Unknown binding'} · Contract: ${owner.contract_status || 'unknown'} · Availability: ${owner.availability && owner.availability.status || 'unknown'}${writable ? '' : ` · Read-only: ${reason || 'No supported writable setup contract.'}`}`);
      if (view.owners.children[index] !== card) view.owners.insertBefore(card, view.owners.children[index] || null);
    });
    for (const [id, card] of view.ownerCards) if (!ownerIds.has(id)) { card.remove(); view.ownerCards.delete(id); }
  }

  return {beginEdit, acceptSnapshot, renderBlocks};
});
