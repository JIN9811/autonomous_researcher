const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../web/static/planning.js'), 'utf8');

function setup() {
  const handlers = {};
  const inside = {};
  const icon = {dataset: {agentId: 'design'}};
  icon.closest = () => icon;
  const other = {closest: () => null};
  const menu = {hidden: false, innerHTML: 'actions', dataset: {agentId: 'design'}, contains: t => t === inside};
  const ctx = vm.createContext({liveBinderContextMenu: menu,
    liveAgentBinderList: {contains: t => t === icon},
    document: {addEventListener: (type, handler) => {handlers[type] = handler;}},
    window: {addEventListener: (type, handler) => {handlers[type] = handler;}},
  });
  for (const name of ['closeBinderContextMenu', 'bindBinderContextMenuDismissal']) {
    const start = source.indexOf(`function ${name}(`);
    if (start >= 0) vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), ctx);
  }
  if (ctx.bindBinderContextMenuDismissal) ctx.bindBinderContextMenuDismissal();
  return {handlers, menu, inside, icon, other};
}

test('pointer leaving the menu and its source icon dismisses without a click', () => {
  const {handlers, menu, other} = setup();
  handlers.pointermove?.({target: other});
  assert.equal(menu.hidden, true);
  assert.equal(menu.innerHTML, '');
});

test('moving between source icon and menu actions keeps actions available', () => {
  const {handlers, menu, inside, icon} = setup();
  handlers.pointermove?.({target: icon});
  handlers.pointermove?.({target: inside});
  assert.equal(menu.hidden, false);
});

test('outside pointer press closes even before another control consumes click', () => {
  const {handlers, menu, other} = setup();
  handlers.pointerdown?.({target: other});
  assert.equal(menu.hidden, true);
});

test('scrolling the page closes, but scrolling inside the menu does not', () => {
  const {handlers, menu, inside, other} = setup();
  handlers.scroll?.({target: inside});
  assert.equal(menu.hidden, false);
  handlers.scroll?.({target: other});
  assert.equal(menu.hidden, true);
});

test('window blur, resize and keyboard focus outside dismiss the menu', () => {
  for (const event of ['blur', 'resize', 'focusin']) {
    const {handlers, menu, other} = setup();
    handlers[event]?.({target: other});
    assert.equal(menu.hidden, true, event);
  }
});
