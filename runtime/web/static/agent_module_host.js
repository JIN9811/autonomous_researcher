/*
Manifest-driven frontend module lifecycle for the Live GUI.

Only code-owned /module-assets/ URLs and identifier-only namespace/factory
paths are accepted. Agent IDs are opaque lookup keys and are never evaluated.
*/
(function installAgentModuleHost(global) {
  "use strict";

  // Refresh presentation assets with the host build, independently of runtime contracts.
  const assetRevision = global.document?.currentScript?.dataset?.assetRevision || "";

  const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]*$/;
  const FORBIDDEN_PATH_PARTS = new Set(["__proto__", "prototype", "constructor"]);

  function safePath(value, label) {
    const parts = String(value || "").split(".");
    if (!parts.length || parts.some((part) => !IDENTIFIER.test(part) || FORBIDDEN_PATH_PARTS.has(part))) {
      throw new TypeError(`invalid frontend ${label}`);
    }
    return parts;
  }

  function resolvePath(root, parts) {
    let value = root;
    for (const part of parts) {
      if (value === null || value === undefined) return undefined;
      value = value[part];
    }
    return value;
  }

  function safeAssetUrl(value, version) {
    const assetUrl = String(value || "").trim();
    if (!assetUrl.startsWith("/module-assets/") || assetUrl.startsWith("//") || /[\\\r\n]/.test(assetUrl)) {
      throw new TypeError("invalid frontend asset_url");
    }
    const separator = assetUrl.includes("?") ? "&" : "?";
    const versioned = version ? `${assetUrl}${separator}v=${encodeURIComponent(version)}` : assetUrl;
    return assetRevision ? `${versioned}${versioned.includes("?") ? "&" : "?"}ui=${encodeURIComponent(assetRevision)}` : versioned;
  }

  function frontendDescriptor(manifest) {
    const raw = manifest && typeof manifest === "object" ? manifest : {};
    const implementation = raw.implementation && typeof raw.implementation === "object" ? raw.implementation : {};
    const frontend = implementation.frontend && typeof implementation.frontend === "object" ? implementation.frontend : null;
    if (!frontend) return null;
    const agentId = String(raw.id || raw.agent_id || raw.module_id || "").trim();
    if (!agentId) throw new TypeError("frontend manifest requires an agent id");
    const version = String(implementation.version || raw.version || "").trim();
    const namespacePath = safePath(frontend.namespace, "namespace");
    const factoryPath = safePath(frontend.factory, "factory");
    const assetUrl = safeAssetUrl(frontend.asset_url, version);
    return {
      agentId,
      assetUrl,
      namespacePath,
      factoryPath,
      signature: JSON.stringify([assetUrl, namespacePath, factoryPath]),
    };
  }

  function browserAssetLoader(url) {
    if (!global.document || !global.document.createElement || !global.document.head) {
      return Promise.reject(new Error("document is unavailable for frontend asset loading"));
    }
    return new Promise((resolve, reject) => {
      const script = global.document.createElement("script");
      script.src = url;
      script.async = true;
      script.dataset.agentModuleAsset = url;
      script.onload = () => resolve();
      script.onerror = () => {
        script.remove();
        reject(new Error(`frontend asset failed to load: ${url}`));
      };
      global.document.head.appendChild(script);
    });
  }

  function createModuleHost(options = {}) {
    const globalObject = options.globalObject || global;
    const loadAsset = typeof options.loadAsset === "function" ? options.loadAsset : browserAssetLoader;
    const records = new Map();
    const loadedAssets = new Map();
    let reconciliationGeneration = 0;

    function loadOnce(url) {
      if (!loadedAssets.has(url)) {
        const pending = Promise.resolve().then(() => loadAsset(url));
        loadedAssets.set(url, pending);
        pending.catch(() => {
          if (loadedAssets.get(url) === pending) loadedAssets.delete(url);
        });
      }
      return loadedAssets.get(url);
    }

    async function disposeRecord(record) {
      if (!record || record.disposed) return;
      record.disposed = true;
      if (record.instance && typeof record.instance.dispose === "function") {
        await Promise.resolve(record.instance.dispose());
      }
      record.instance = null;
    }

    function moduleServices(hostServices) {
      return Object.freeze({ ...(hostServices || {}) });
    }

    async function activate(descriptor, hostServices, record) {
      try {
        await loadOnce(descriptor.assetUrl);
        if (records.get(descriptor.agentId) !== record || record.disposed) return;
        const namespace = resolvePath(globalObject, descriptor.namespacePath);
        const factory = resolvePath(namespace, descriptor.factoryPath);
        if (typeof factory !== "function") throw new TypeError("frontend factory is unavailable");
        const instance = await Promise.resolve(factory(moduleServices(hostServices)));
        if (!instance || typeof instance !== "object") throw new TypeError("frontend factory must return an object");
        if (records.get(descriptor.agentId) !== record || record.disposed) {
          if (typeof instance.dispose === "function") await Promise.resolve(instance.dispose());
          return;
        }
        record.instance = instance;
      } catch (error) {
        if (records.get(descriptor.agentId) === record) records.delete(descriptor.agentId);
        await disposeRecord(record);
        throw error;
      }
    }

    async function reconcile(manifests, hostServices = {}) {
      const generation = ++reconciliationGeneration;
      const desired = new Map();
      const errors = [];
      for (const manifest of Array.isArray(manifests) ? manifests : []) {
        const agentId = String(manifest && (manifest.id || manifest.agent_id || manifest.module_id) || "").trim();
        try {
          const descriptor = frontendDescriptor(manifest);
          if (descriptor) desired.set(descriptor.agentId, descriptor);
        } catch (error) {
          if (agentId) desired.delete(agentId);
          errors.push({ agentId, error: String(error && error.message || error) });
        }
      }

      const disposals = [];
      for (const [agentId, record] of records) {
        const descriptor = desired.get(agentId);
        if (!descriptor || descriptor.signature !== record.signature) {
          records.delete(agentId);
          disposals.push(disposeRecord(record));
        }
      }
      await Promise.all(disposals);
      if (generation !== reconciliationGeneration) return { errors, superseded: true };

      const activations = [];
      for (const descriptor of desired.values()) {
        const existing = records.get(descriptor.agentId);
        if (existing) {
          if (existing.activation) activations.push(existing.activation.catch((error) => {
            errors.push({ agentId: descriptor.agentId, error: String(error && error.message || error) });
          }));
          continue;
        }
        const record = {
          signature: descriptor.signature,
          instance: null,
          disposed: false,
        };
        records.set(descriptor.agentId, record);
        record.activation = activate(descriptor, hostServices, record);
        activations.push(
          record.activation.catch((error) => {
            errors.push({ agentId: descriptor.agentId, error: String(error && error.message || error) });
          }),
        );
      }
      await Promise.all(activations);
      return { errors };
    }

    function get(agentId) {
      const record = records.get(String(agentId || ""));
      return record && !record.disposed ? record.instance : null;
    }

    return Object.freeze({ reconcile, get });
  }

  global.AX4LABAgentModuleHost = Object.freeze({ createModuleHost });
})(window);
