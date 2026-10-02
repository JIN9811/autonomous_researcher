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

test('plane separates package contracts from bridges; providers appear only inside a bridge', () => {
  assert.equal(typeof packages.projectBridgeTopology, 'function');
  const view = packages.projectBridgeTopology(catalog, [{id:'specimen',version:'1.0.0'}]);
  assert.equal(view.ok,true);
  assert.equal(view.nodes.filter(n=>n.kind==='bridge').length,1);
  assert.deepEqual(view.nodes.filter(n=>n.kind==='provider'),[]);
  assert.deepEqual(view.edges.map(e=>e.label).sort(),['uses','uses']);
  assert.equal(view.metadata.read_only,true);
  assert.deepEqual(view.stage_dispatch,{});
  const internal = packages.projectBridgeInternal(catalog, 'printer_fleet');
  assert.deepEqual(internal.nodes.filter(n=>n.metadata.structure_kind==='provider').map(n=>n.label),['bambu','prusa']);
  assert.equal(internal.nodes.some(n=>n.kind==='package'),false);
  assert.equal(view.nodes.some(n=>n.label==='design'),false);
  assert.equal(view.nodes.find(n=>n.label==='other').inDraft,false);
  for (const edge of view.edges) {
    assert.ok(view.nodes.some(n=>n.id===edge.source));
    assert.ok(view.nodes.some(n=>n.id===edge.target));
  }
});

test('runtime bridges remain visible without fabricated package owners and aliases deduplicate', () => {
  const runtime = [{id:'printer_legacy',label:'Old Printer'}, {id:'robot_bridge',label:'Robot',tools:['robot.move']}];
  const input = {...catalog,bridge_modules:[{...catalog.bridge_modules[0],runtime_bridge_ids:['printer_legacy']}]};
  const before = JSON.stringify(input);
  const view = packages.projectBridgeTopology(input,[],runtime);
  assert.deepEqual(view.nodes.filter(n=>n.kind==='bridge').map(n=>n.metadata.bridge_id),['printer_fleet','robot_bridge']);
  assert.equal(view.edges.some(e=>e.target==='bridge:robot_bridge'),false);
  assert.equal(JSON.stringify(input),before);
  const detail = packages.projectBridgeInternal(input,'robot_bridge',runtime);
  assert.ok(detail.nodes.some(n=>n.label==='robot.move'));
  assert.equal(packages.projectBridgeInternal(input,'missing',runtime).ok,false);
});

test('empty and unavailable catalogs have no fabricated provider nodes', () => {
  assert.equal(typeof packages.projectBridgeTopology,'function');
  assert.equal(packages.projectBridgeTopology({ok:false,errors:['offline']},[]).ok,false);
  assert.deepEqual(packages.projectBridgeTopology({...catalog,agent_packages:[],bridge_modules:[]},[]).nodes,[]);
  const view = packages.projectBridgeTopology({...catalog,bridge_modules:[{id:'printer_fleet',version:'1.0.0'}]},[]);
  assert.equal(view.nodes.filter(n=>n.kind==='provider').length,0);
});
