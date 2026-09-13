const { test } = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const packages = require('../../web/static/experimental_packages.js');

const catalog = {
  ok: true,
  schema: 'ax4lab.package_catalog.v1',
  errors: [],
  agent_packages: [
    {
      id: 'design', version: '1.0.0', handler: 'agent.design_agent',
      agent_module: { id: 'design', version: '1.0.0' }, bridge_modules: [],
    },
    {
      id: 'specimen', version: '1.0.0', handler: 'agent.specimen_agent',
      agent_module: { id: 'specimen', version: '1.0.0' },
      bridge_modules: [{ id: 'printer_fleet', version: '1.0.0' }],
    },
    {
      id: 'shared_specimen', version: '1.0.0', handler: 'agent.shared_specimen_agent',
      agent_module: { id: 'shared_specimen', version: '1.0.0' },
      bridge_modules: [{ id: 'printer_fleet', version: '1.0.0' }],
    },
  ],
  bridge_modules: [{
    id: 'printer_fleet', version: '1.0.0',
    package_owners: [{ id: 'specimen', version: '1.0.0' }, { id: 'shared_specimen', version: '1.0.0' }],
    binding_requirements: [{ id: 'printer_fleet_connection', kind: 'device', owner_id: 'printer_fleet', required: true }],
  }],
};

test('bridge drill-down retains selected and unselected shared package owners', () => {
  for (const refs of [[], [{id:'specimen',version:'1.0.0'}], [{id:'specimen',version:'1.0.0'},{id:'shared_specimen',version:'1.0.0'}]]) {
    const graph = packages.projectBridgeInternal(catalog, 'printer_fleet', [], refs);
    const owners = graph.nodes[0].metadata.contract.owners;
    assert.deepEqual(owners.map(owner => [owner.id, owner.inDraft]), [
      ['specimen', refs.some(ref => ref.id === 'specimen')],
      ['shared_specimen', refs.some(ref => ref.id === 'shared_specimen')],
    ]);
  }
});

test('installed LeRobot drill-down groups real capabilities instead of expanding every tool', () => {
  const root = require('node:path').resolve(__dirname, '../..');
  const bridge = JSON.parse(execFileSync(process.env.PYTHON || 'python3', [
    '-c',
    'import json; from device_bridges.lerobot.module import MODULE; print(json.dumps(MODULE.describe()))',
  ], { cwd: root, encoding: 'utf8' }));
  const graph = packages.projectBridgeInternal({
    ok: true, schema: 'ax4lab.package_catalog.v1', errors: [], agent_packages: [],
    bridge_modules: [{ ...bridge, package_owners: [] }],
  }, 'lerobot');
  const internals = graph.nodes.slice(1);

  assert.deepEqual(internals.map(node => node.metadata.contract.id), [
    'profiles_ports', 'active_robot_cam', 'teleoperation', 'recording', 'training',
    'rollout', 'replay', 'datasets_policies', 'isaac_sidecars', 'visualization',
  ]);
  assert.ok(internals.every(node => node.metadata.structure_kind === 'provider'));
  assert.equal(graph.edges.length, 10);
  assert.ok(graph.edges.every(edge => edge.label === 'contains'));
});

test('graph projection selects exact installed Agent Packages and keeps bridge-free packages explicit', () => {
  const graph = { nodes: [
    { handler: 'agent.design_agent', module_id: 'modules/design' },
    { handler: 'agent.specimen_agent', module_id: 'modules/specimen' },
    { handler: 'runtime.terminal', module_id: null },
  ] };
  assert.deepEqual(packages.packageRefsForGraph(graph, catalog), [
    { id: 'design', version: '1.0.0' },
    { id: 'specimen', version: '1.0.0' },
  ]);
  const view = packages.projectComposition(catalog, [{ id: 'design', version: '1.0.0' }]);
  assert.deepEqual(view.packages.map(item => [item.id, item.inDraft, item.bridges.length]), [
    ['design', true, 0],
    ['specimen', false, 1],
    ['shared_specimen', false, 1],
  ]);
});

test('composition preserves every shared owner while rendering one installed bridge', () => {
  const view = packages.projectComposition(catalog, [
    { id: 'specimen', version: '1.0.0' },
    { id: 'shared_specimen', version: '1.0.0' },
  ]);
  assert.equal(view.bridges.length, 1);
  assert.deepEqual(view.bridges[0].owners.map(owner => [owner.id, owner.inDraft]), [
    ['specimen', true],
    ['shared_specimen', true],
  ]);
});

test('export payload carries current graph, selected package refs, and detached module drafts', () => {
  const graph = { id: 'printer_pipeline', nodes: [{ handler: 'agent.specimen_agent', module_id: 'modules/specimen' }] };
  const moduleDraft = { module: { id: 'specimen', execution_graph: { entry: 'prepare' } } };
  assert.deepEqual(packages.buildExportPayload({
    graph,
    agentPackages: [{ id: 'specimen', version: '1.0.0' }],
    moduleConfigurations: { specimen: moduleDraft },
  }), {
    schema: 'ax4lab.experimental_package.v1',
    id: 'printer_pipeline_experiment',
    version: '1.0.0',
    graph,
    agent_packages: [{ id: 'specimen', version: '1.0.0' }],
    module_configurations: { specimen: moduleDraft },
    bindings: [],
  });
  assert.notEqual(packages.buildExportPayload({ graph, agentPackages: [], moduleConfigurations: {} }).graph, graph);
});

test('export state distinguishes an uninitialized selection from an intentionally empty selection', () => {
  const graph = { id: 'printer_pipeline', nodes: [{ handler: 'agent.specimen_agent', module_id: 'modules/specimen' }] };
  assert.deepEqual(packages.buildExportState({
    graph, catalogPayload: catalog, selectedAgentPackages: null, modulePayloadCache: new Map(), openModuleTabs: [],
  }).agentPackages, [{ id: 'specimen', version: '1.0.0' }]);
  assert.deepEqual(packages.buildExportState({
    graph, catalogPayload: catalog, selectedAgentPackages: [], modulePayloadCache: new Map(), openModuleTabs: [],
  }).agentPackages, []);
});

test('export state keeps relevant closed-tab cache entries and prefers open dirty payloads', () => {
  const graph = { nodes: [
    { handler: 'agent.design_agent', module_id: 'modules/design' },
    { handler: 'agent.specimen_agent', module_id: 'modules/specimen' },
  ] };
  const cache = new Map([
    ['design', { module: { id: 'design', label: 'closed-tab cache' } }],
    ['specimen', { module: { id: 'specimen', label: 'stale cache' } }],
    ['shared_specimen', { module: { id: 'shared_specimen', label: 'selected cache' } }],
    ['private_connection', { module: { id: 'private_connection', token: 'must not export' } }],
  ]);
  const state = packages.buildExportState({
    graph,
    catalogPayload: catalog,
    selectedAgentPackages: [{ id: 'shared_specimen', version: '1.0.0' }],
    modulePayloadCache: cache,
    openModuleTabs: [{
      kind: 'module', moduleId: 'specimen', dirty: true,
      modulePayload: { module: { id: 'specimen', label: 'open dirty draft' } },
    }],
  });
  assert.deepEqual(state.moduleConfigurations, {
    design: { module: { id: 'design', label: 'closed-tab cache' } },
    specimen: { module: { id: 'specimen', label: 'open dirty draft' } },
    shared_specimen: { module: { id: 'shared_specimen', label: 'selected cache' } },
  });
});

test('accepted import metadata and portable bindings survive the next shared-helper export', () => {
  const imported = packages.parsePackageJson(JSON.stringify({
    schema: 'ax4lab.experimental_package.v1',
    id: 'custom_fixture_run',
    version: '2.7.3',
    graph: { id: 'printer_pipeline' },
    agent_packages: [{ id: 'specimen', version: '1.0.0' }],
    module_configurations: {},
    bindings: [{ id: 'custom_printer', kind: 'device', owner_id: 'printer_fleet', required: true }],
  }));
  const exported = packages.buildExportPayload({
    graph: imported.graph,
    agentPackages: imported.agent_packages,
    moduleConfigurations: imported.module_configurations,
    sourcePackage: {
      ...imported,
      bindings: imported.bindings.map(binding => ({ ...binding, status: 'requires_local_configuration' })),
    },
  });
  assert.equal(exported.id, 'custom_fixture_run');
  assert.equal(exported.version, '2.7.3');
  assert.deepEqual(exported.bindings, [
    { id: 'custom_printer', kind: 'device', owner_id: 'printer_fleet', required: true },
  ]);
  assert.equal('status' in exported.bindings[0], false);
});

test('stale export response keeps the newer package draft and membership', async () => {
  const current = {
    schema: 'ax4lab.experimental_package.v1', id: 'newer', version: '2.7.4',
    agent_packages: [{ id: 'specimen', version: '1.0.0' }], bindings: [],
  };
  const older = {
    schema: 'ax4lab.experimental_package.v1', id: 'older', version: '2.7.3',
    agent_packages: [{ id: 'design', version: '1.0.0' }], bindings: [],
  };
  const result = await Promise.resolve({ ok: true, package: older });
  assert.deepEqual(packages.acceptExportResult({
    requestToken: 3, activeToken: 4, requestFingerprint: 'before', currentFingerprint: 'after',
    result, currentDraft: current,
  }), { applied: false, reason: 'stale', draft: current, errors: [] });
  assert.deepEqual(packages.acceptExportResult({
    requestToken: 4, activeToken: 4, requestFingerprint: 'after', currentFingerprint: 'after',
    result, currentDraft: current,
  }), { applied: true, reason: 'accepted', draft: older, errors: [] });
});

test('local import parsing rejects arrays and the wrong schema before a request', () => {
  assert.throws(() => packages.parsePackageJson('[]'), /JSON object/);
  assert.throws(() => packages.parsePackageJson('{"schema":"wrong"}'), /experimental_package/);
  assert.equal(packages.parsePackageJson('{"schema":"ax4lab.experimental_package.v1","graph":{}}').graph.constructor, Object);
});

test('stale and failed responses preserve the current draft; only the owning success applies', () => {
  const current = { schema: 'ax4lab.experimental_package.v1', id: 'newer' };
  const imported = { schema: 'ax4lab.experimental_package.v1', id: 'accepted' };
  assert.deepEqual(packages.acceptImportResult({
    requestToken: 1, activeToken: 2, requestFingerprint: 'before', currentFingerprint: 'before',
    result: { ok: true, draft: imported }, currentDraft: current,
  }), { applied: false, reason: 'stale', draft: current, errors: [] });
  assert.deepEqual(packages.acceptImportResult({
    requestToken: 2, activeToken: 2, requestFingerprint: 'before', currentFingerprint: 'edited',
    result: { ok: true, draft: imported }, currentDraft: current,
  }), { applied: false, reason: 'stale', draft: current, errors: [] });
  assert.deepEqual(packages.acceptImportResult({
    requestToken: 2, activeToken: 2, requestFingerprint: 'before', currentFingerprint: 'before',
    result: { ok: false, errors: ['invalid'], draft: null }, currentDraft: current,
  }), { applied: false, reason: 'failed', draft: current, errors: ['invalid'] });
  assert.deepEqual(packages.acceptImportResult({
    requestToken: 2, activeToken: 2, requestFingerprint: 'before', currentFingerprint: 'before',
    result: { ok: true, errors: [], draft: imported }, currentDraft: current,
  }), { applied: true, reason: 'accepted', draft: imported, errors: [] });
});
