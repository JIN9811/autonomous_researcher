"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const modulePath = path.resolve(__dirname, "../../web/static/agent_module_host.js");
const source = fs.readFileSync(modulePath, "utf8");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

function manifest(version = "1.0.0", frontend = {}) {
  return {
    id: "design",
    implementation: {
      version,
      frontend: {
        asset_url: "/module-assets/design/live_report.js",
        namespace: "AX4LABDesignUI",
        factory: "createFrontend",
        ...frontend,
      },
    },
  };
}

function loadApi(globalObject = {}) {
  const context = { window: globalObject, URL, Promise, console };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: modulePath });
  return context.window.AX4LABAgentModuleHost;
}

(async () => {
  {
    const globalObject = {AX4LABDesignUI: {createFrontend: () => ({dispose() {}})}};
    const gate = deferred();
    const started = deferred();
    const host = loadApi(globalObject).createModuleHost({globalObject, loadAsset: async () => {
      started.resolve();
      await gate.promise;
    }});
    const first = host.reconcile([manifest()]);
    await started.promise;
    let finished = false;
    const second = host.reconcile([manifest()]).then(() => { finished = true; });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(finished, false, 'refresh must await a module that is still activating');
    gate.resolve();
    await Promise.all([first, second]);
    assert.ok(host.get('design'));
  }
  {
    const globalObject = {};
    const api = loadApi(globalObject);
    const calls = { load: [], create: 0, dispose: 0 };
    const host = api.createModuleHost({
      globalObject,
      loadAsset: async (url) => {
        calls.load.push(url);
        globalObject.AX4LABDesignUI = {
          createFrontend(services) {
            calls.create += 1;
            return { services, dispose() { calls.dispose += 1; } };
          },
        };
      },
    });
    const services = { marker: "host-services" };

    await host.reconcile([manifest()], services);
    const first = host.get("design");
    assert.equal(first.services.marker, "host-services");
    assert.deepEqual(calls.load, ["/module-assets/design/live_report.js?v=1.0.0"]);
    assert.equal(calls.create, 1);

    await host.reconcile([manifest()], services);
    assert.equal(host.get("design"), first);
    assert.equal(calls.create, 1);
    assert.equal(calls.dispose, 0);

    await host.reconcile([], services);
    assert.equal(host.get("design"), null);
    assert.equal(calls.dispose, 1);

    await host.reconcile([manifest()], services);
    assert.notEqual(host.get("design"), first);
    assert.equal(calls.create, 2);
    assert.equal(calls.load.length, 1);
  }

  {
    const globalObject = {};
    const gate = deferred();
    const started = deferred();
    let createCalls = 0;
    const api = loadApi(globalObject);
    const host = api.createModuleHost({
      globalObject,
      loadAsset: async () => {
        started.resolve();
        await gate.promise;
        globalObject.AX4LABDesignUI = {
          createFrontend() {
            createCalls += 1;
            return { dispose() {} };
          },
        };
      },
    });

    const adding = host.reconcile([manifest()], {});
    await started.promise;
    await host.reconcile([], {});
    gate.resolve();
    await adding;
    assert.equal(createCalls, 0);
    assert.equal(host.get("design"), null);
  }

  {
    const globalObject = {
      AX4LABDesignUI: {
        createFrontend() { return { dispose() {} }; },
      },
    };
    const api = loadApi(globalObject);
    const host = api.createModuleHost({ globalObject, loadAsset: async () => {} });

    await Promise.all([
      host.reconcile([manifest()], {}),
      host.reconcile([], {}),
    ]);
    assert.equal(host.get("design"), null);
  }

  {
    const globalObject = {};
    const disposeGate = deferred();
    let factoryCalls = 0;
    const api = loadApi(globalObject);
    const host = api.createModuleHost({
      globalObject,
      loadAsset: async () => {
        globalObject.AX4LABDesignUI = {
          createFrontend() {
            factoryCalls += 1;
            return {
              async dispose() { await disposeGate.promise; },
            };
          },
        };
      },
    });
    await host.reconcile([manifest("1.0.0")], {});

    const changing = host.reconcile([manifest("2.0.0")], {});
    await Promise.resolve();
    const removing = host.reconcile([], {});
    disposeGate.resolve();
    await Promise.all([changing, removing]);
    assert.equal(factoryCalls, 1);
    assert.equal(host.get("design"), null);
  }

  {
    const globalObject = {};
    let loadCalls = 0;
    const api = loadApi(globalObject);
    const host = api.createModuleHost({
      globalObject,
      loadAsset: async () => { loadCalls += 1; },
    });

    const results = await host.reconcile([
      manifest("1.0.0", { asset_url: "https://evil.invalid/live_report.js" }),
      {
        id: "unsafe",
        implementation: {
          version: "1",
          frontend: {
            asset_url: "/module-assets/unsafe/ui.js",
            namespace: "constructor.constructor",
            factory: "createFrontend",
          },
        },
      },
    ], {});
    assert.equal(loadCalls, 0);
    assert.equal(host.get("design"), null);
    assert.equal(host.get("unsafe"), null);
    assert.deepEqual(
      JSON.parse(JSON.stringify(results.errors.map((item) => item.agentId))),
      ["design", "unsafe"],
    );
  }

  console.log("agent module host lifecycle: ok");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
