const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/live_fullscreen.js', 'utf8');
function setup(path = '/live', replay = false) {
  const data = new Map(), calls = [];
  const context = {window: {location: {pathname: path}},
    document: {title: 'Live GUI', body: {classList: {contains: () => replay}}},
    sessionStorage: {getItem: k => data.get(k), setItem: (k, v) => data.set(k, v)},
    crypto: {getRandomValues: array => array.fill(10)}, Uint8Array, AbortSignal,
    fetch: (...args) => { calls.push(args); return Promise.resolve({ok: true}); }};
  return {context, calls};
}
test('LIVE requests fullscreen once, restores title, never repeats on refresh', async () => {
  const {context, calls} = setup();
  vm.runInNewContext(source, context);
  assert.match(context.document.title, /^AX4LAB LIVE \[[a-f0-9]{32}\]$/);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(context.document.title, 'Live GUI');
  vm.runInNewContext(source, context);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], '/api/ui/live-fullscreen');
});
test('main, Replay, and workspace pages never request fullscreen', () => {
  for (const path of ['/', '/replay', '/printer', '/ide', '/knowledge']) {
    const {context, calls} = setup(path);
    vm.runInNewContext(source, context);
    assert.equal(calls.length, 0);
  }
  const {context, calls} = setup('/live', true);
  vm.runInNewContext(source, context);
  assert.equal(calls.length, 0);
});
test('network failure restores title without retry or runtime operations', async () => {
  const {context} = setup();
  context.fetch = () => Promise.reject(new Error('offline'));
  vm.runInNewContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(context.document.title, 'Live GUI');
});
