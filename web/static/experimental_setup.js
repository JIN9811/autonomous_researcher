/* Server-projected Setup presentation only. This module never sends commands. */
(function (host, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else host.ExperimentalSetup = api;
})(typeof window === 'object' ? window : this, function () {
  'use strict';
  const views = new WeakMap();

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

  function makeCard(doc) {
    const card = element(doc, 'article', 'setup-block');
    const title = element(doc, 'h3', 'setup-block-title');
    const meta = element(doc, 'p', 'setup-block-meta');
    const status = element(doc, 'p', 'setup-block-status');
    const timing = element(doc, 'p', 'setup-block-timing');
    const reason = element(doc, 'p', 'setup-readonly-reason');
    const editing = element(doc, 'p', 'setup-editing');
    const details = element(doc, 'details', 'setup-block-details');
    const summary = element(doc, 'summary', '', 'Values and change diff');
    details.append(summary);
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
    card.append(title, meta, status, timing, editing, reason, details, actions);
    return {card, title, meta, status, timing, editing, reason, details, values, buttons};
  }

  function updateCard(view, block, callbacks) {
    const title = block.title || block.topic_key || block.block_id;
    const writable = block.active === true && block.editable === true;
    const request = callbacks.actionRequests && callbacks.actionRequests.get(block.block_id);
    const busy = Boolean(request && request.pending);
    const draft = Boolean(block.current_draft_proposal_id);
    const context = callbacks.editContext;
    const editing = context && context.block_id === block.block_id;
    view.card.dataset.blockId = block.block_id;
    view.card.dataset.revision = String(block.revision);
    view.card.dataset.editable = String(writable);
    setText(view.title, title);
    setText(view.meta, `Owner: ${(block.owners || []).join(', ') || 'Unknown'} · Revision ${block.revision}`);
    setText(view.status, `Agreement: ${block.agreement_status || 'unknown'} · Application: ${block.application_status || 'unknown'}${block.validation_status ? ` · Validation: ${block.validation_status}` : ''}`);
    setText(view.timing, 'Apply time: next new run only. Confirming does not start a run.');
    setText(view.editing, editing ? `Editing this block in Chat · revision ${context.revision}${context.revision !== block.revision ? ' (changed — select Edit again to use the latest revision)' : ''}` : '');
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
    for (const [label, callback] of [['Edit', 'onEdit'], ['Confirm', 'onConfirm'], ['Discard', 'onDiscard']]) {
      const button = view.buttons[label];
      const retry = request && !request.pending && request.body.action === label.toLowerCase()
        && request.body.proposal_id === block.current_draft_proposal_id && request.body.expected_revision === block.revision;
      setText(button, retry ? `Retry ${label.toLowerCase()}` : label);
      button.disabled = !writable || busy || (label !== 'Edit' && !draft);
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
      root.append(intro, notice, blocks, owners);
      view = {intro, notice, blocks, owners, cards:new Map(), ownerCards:new Map()}; views.set(root, view);
    }
    setText(view.intro, snapshot ? `Setup revision ${snapshot.revision} · Availability is owner-reported; unknown is not ready.` : 'Waiting for the current session’s setup snapshot.');
    setText(view.notice, callbacks.notice || ''); view.notice.hidden = !callbacks.notice;
    const ids = new Set();
    (snapshot && snapshot.blocks || []).forEach((block, index) => {
      if (!block || !block.block_id || ids.has(block.block_id)) return;
      ids.add(block.block_id);
      let card = view.cards.get(block.block_id);
      if (!card) { card = makeCard(doc); view.cards.set(block.block_id, card); }
      updateCard(card, block, callbacks);
      // Never detach an unchanged card: focus and details remain browser-owned.
      if (view.blocks.children[index] !== card.card) view.blocks.insertBefore(card.card, view.blocks.children[index] || null);
    });
    for (const [id, card] of view.cards) if (!ids.has(id)) { card.card.remove(); view.cards.delete(id); }
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
