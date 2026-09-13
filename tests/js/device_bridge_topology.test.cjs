const test = require('node:test');
const assert = require('node:assert/strict');
const packages = require('../../web/static/experimental_packages.js');

const catalog = {
  schema:'ax4lab.package_catalog.v1', ok:true,
  agent_packages:[{id:'specimen',version:'1.0.0',bridge_modules:[{id:'printer_fleet',version:'1.0.0'}]},
    {id:'other',version:'1.0.0',bridge_modules:[{id:'printer_fleet',version:'1.0.0'}]},
    {id:'design',version:'1.0.0',bridge_modules:[]}],
  bridge_modules:[{id:'printer_fleet',version:'1.0.0',providers:[{id:'bambu'},{id:'prusa'}]}],
};

test('one fleet node owns its two internal providers and all package relationships', () => {
  assert.equal(typeof packages.projectBridgeTopology, 'function');
  const view = packages.projectBridgeTopology(catalog, [{id:'specimen',version:'1.0.0'}]);
  assert.equal(view.ok,true);
  assert.equal(view.nodes.filter(n=>n.kind==='bridge').length,1);
  assert.deepEqual(view.nodes.filter(n=>n.kind==='provider').map(n=>n.label),['bambu','prusa']);
  assert.deepEqual(view.edges.map(e=>e.kind).sort(),['contains','contains','uses','uses']);
  assert.equal(view.nodes.some(n=>n.label==='design'),false);
  assert.equal(view.nodes.find(n=>n.label==='other').inDraft,false);
  for (const edge of view.edges) {
    assert.ok(view.nodes.some(n=>n.id===edge.from));
    assert.ok(view.nodes.some(n=>n.id===edge.to));
  }
});

test('empty and unavailable catalogs have no fabricated provider nodes', () => {
  assert.equal(typeof packages.projectBridgeTopology,'function');
  assert.equal(packages.projectBridgeTopology({ok:false,errors:['offline']},[]).ok,false);
  assert.deepEqual(packages.projectBridgeTopology({...catalog,agent_packages:[],bridge_modules:[]},[]).nodes,[]);
  const view = packages.projectBridgeTopology({...catalog,bridge_modules:[{id:'printer_fleet',version:'1.0.0'}]},[]);
  assert.equal(view.nodes.filter(n=>n.kind==='provider').length,0);
});
