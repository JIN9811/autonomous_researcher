/* Pure Experimental Package projection helpers shared by the Runtime IDE and Node tests. */
(function experimentalPackagesModule(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.AX4LABExperimentalPackages = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildExperimentalPackagesApi() {
  "use strict";

  const PACKAGE_SCHEMA = "ax4lab.experimental_package.v1";
  const CATALOG_SCHEMA = "ax4lab.package_catalog.v1";

  function clone(value) {
    return value == null ? value : JSON.parse(JSON.stringify(value));
  }

  function refKey(ref) {
    return `${String(ref?.id || "")}@${String(ref?.version || "")}`;
  }

  function uniqueRefs(refs) {
    const seen = new Set();
    return (Array.isArray(refs) ? refs : []).flatMap((ref) => {
      const normalized = { id: String(ref?.id || ""), version: String(ref?.version || "") };
      const key = refKey(normalized);
      if (!normalized.id || !normalized.version || seen.has(key)) return [];
      seen.add(key);
      return [normalized];
    });
  }

  function normalizeCatalog(payload) {
    const errors = Array.isArray(payload?.errors) ? payload.errors.map(String) : [];
    const schemaOk = payload?.schema === CATALOG_SCHEMA;
    const ok = payload?.ok === true && schemaOk;
    return {
      ok,
      errors: ok ? errors : (errors.length ? errors : [schemaOk ? "Package catalog is unavailable." : "Unexpected package catalog schema."]),
      agentPackages: ok && Array.isArray(payload.agent_packages) ? clone(payload.agent_packages) : [],
      bridgeModules: ok && Array.isArray(payload.bridge_modules) ? clone(payload.bridge_modules) : [],
    };
  }

  function packageRefsForGraph(graph, catalogPayload) {
    const catalog = normalizeCatalog(catalogPayload);
    if (!catalog.ok) return [];
    const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
    const handlers = new Set(nodes.map((node) => String(node?.handler || "")).filter(Boolean));
    const moduleIds = new Set(nodes.map((node) => String(node?.module_id || "").split("/").filter(Boolean).pop() || "").filter(Boolean));
    return catalog.agentPackages.flatMap((pkg) => {
      const moduleId = String(pkg?.agent_module?.id || pkg?.id || "");
      return handlers.has(String(pkg?.handler || "")) || moduleIds.has(moduleId)
        ? [{ id: String(pkg.id), version: String(pkg.version) }]
        : [];
    });
  }

  function moduleIdFromRef(value) {
    return String(value || "").split("/").filter(Boolean).pop() || "";
  }

  function cacheValue(cache, moduleId) {
    if (cache && typeof cache.get === "function") return cache.get(moduleId);
    return cache && typeof cache === "object" ? cache[moduleId] : undefined;
  }

  function buildExportState({ graph, catalogPayload, selectedAgentPackages, modulePayloadCache, openModuleTabs } = {}) {
    const agentPackages = Array.isArray(selectedAgentPackages)
      ? uniqueRefs(selectedAgentPackages)
      : packageRefsForGraph(graph, catalogPayload);
    const catalog = normalizeCatalog(catalogPayload);
    const graphPackageRefs = packageRefsForGraph(graph, catalogPayload);
    const relevantModuleIds = new Set((Array.isArray(graph?.nodes) ? graph.nodes : [])
      .map((node) => moduleIdFromRef(node?.module_id))
      .filter(Boolean));
    if (catalog.ok) {
      const relevantPackageKeys = new Set(uniqueRefs([...graphPackageRefs, ...agentPackages]).map(refKey));
      for (const pkg of catalog.agentPackages) {
        if (!relevantPackageKeys.has(refKey(pkg))) continue;
        const moduleId = moduleIdFromRef(pkg?.agent_module?.id || pkg?.id);
        if (moduleId) relevantModuleIds.add(moduleId);
      }
    }
    const tabs = Array.isArray(openModuleTabs) ? openModuleTabs : [];
    const moduleConfigurations = {};
    for (const moduleId of relevantModuleIds) {
      const tab = tabs.find((item) => item?.kind === "module" && moduleIdFromRef(item?.moduleId) === moduleId);
      const payload = tab?.modulePayload || cacheValue(modulePayloadCache, moduleId);
      if (payload?.module && typeof payload.module === "object") moduleConfigurations[moduleId] = clone(payload);
    }
    return { agentPackages, moduleConfigurations };
  }

  function projectComposition(catalogPayload, draftRefs) {
    const catalog = normalizeCatalog(catalogPayload);
    if (!catalog.ok) return { ok: false, errors: catalog.errors, packages: [], bridges: [] };
    const selected = new Set(uniqueRefs(draftRefs).map(refKey));
    const packages = catalog.agentPackages.map((pkg) => {
      const reference = { id: String(pkg.id || ""), version: String(pkg.version || "") };
      return {
        ...clone(pkg),
        id: reference.id,
        version: reference.version,
        inDraft: selected.has(refKey(reference)),
        bridges: uniqueRefs(pkg.bridge_modules),
      };
    });
    const packagesByKey = new Map(packages.map((pkg) => [refKey(pkg), pkg]));
    const bridges = catalog.bridgeModules.map((bridge) => {
      const reference = { id: String(bridge.id || ""), version: String(bridge.version || "") };
      const declaredOwners = uniqueRefs(bridge.package_owners);
      const derivedOwners = packages.flatMap((pkg) => pkg.bridges.some((item) => refKey(item) === refKey(reference))
        ? [{ id: pkg.id, version: pkg.version }]
        : []);
      const owners = uniqueRefs([...declaredOwners, ...derivedOwners]).map((owner) => ({
        ...owner,
        inDraft: Boolean(packagesByKey.get(refKey(owner))?.inDraft),
      }));
      return {
        ...clone(bridge),
        id: reference.id,
        version: reference.version,
        owners,
        inDraft: owners.some((owner) => owner.inDraft),
        bindingRequirements: clone(Array.isArray(bridge.binding_requirements) ? bridge.binding_requirements : []),
      };
    });
    return { ok: true, errors: [], packages, bridges };
  }

  // Read-only topology: providers belong to one bridge, never separate packages.
  function projectBridgeTopology(catalogPayload, draftRefs) {
    const composition = projectComposition(catalogPayload, draftRefs);
    const nodes = [], edges = [];
    let top = 64;
    for (const bridge of composition.bridges) {
      const providers = Array.isArray(bridge.providers) ? bridge.providers : [];
      const height = Math.max(180, Math.max(providers.length, bridge.owners.length) * 96);
      const id = `bridge:${refKey(bridge)}`;
      const center = top + height / 2;
      nodes.push({ id, kind: "bridge", label: bridge.label || bridge.id, x: 360, y: center,
        inDraft: bridge.inDraft, bridgeId: bridge.id, data: bridge });
      bridge.owners.forEach((owner, index) => {
        const ownerId = `${id}:owner:${refKey(owner)}`;
        nodes.push({ id: ownerId, kind: "package", label: owner.id, x: 40,
          y: center + (index - (bridge.owners.length - 1) / 2) * 96,
          inDraft: owner.inDraft, bridgeId: bridge.id, data: owner });
        edges.push({ from: ownerId, to: id, kind: "uses" });
      });
      providers.forEach((provider, index) => {
        const providerId = `${id}:provider:${provider.id}`;
        nodes.push({ id: providerId, kind: "provider", label: provider.label || provider.id, x: 680,
          y: center + (index - (providers.length - 1) / 2) * 96,
          inDraft: bridge.inDraft, bridgeId: bridge.id, data: provider });
        edges.push({ from: id, to: providerId, kind: "contains" });
      });
      top += height + 48;
    }
    return { ok: composition.ok, errors: composition.errors, nodes, edges, width: 960, height: Math.max(340, top) };
  }

  function packageId(value) {
    const clean = String(value || "runtime")
      .trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
    return `${clean || "runtime"}_experiment`;
  }

  function portableBindings(bindings) {
    const fields = ["id", "kind", "owner_id", "required"];
    return (Array.isArray(bindings) ? bindings : []).map((binding) => Object.fromEntries(
      fields.filter((field) => Object.prototype.hasOwnProperty.call(binding || {}, field))
        .map((field) => [field, clone(binding[field])]),
    ));
  }

  function buildExportPayload({ graph, agentPackages, moduleConfigurations, sourcePackage, id, version, bindings } = {}) {
    const source = sourcePackage && typeof sourcePackage === "object" ? sourcePackage : {};
    return {
      schema: PACKAGE_SCHEMA,
      id: String(id || source.id || packageId(graph?.id)),
      version: String(version || source.version || "1.0.0"),
      graph: clone(graph || {}),
      agent_packages: uniqueRefs(agentPackages),
      module_configurations: clone(moduleConfigurations && typeof moduleConfigurations === "object" ? moduleConfigurations : {}),
      bindings: portableBindings(bindings === undefined ? source.bindings : bindings),
    };
  }

  function parsePackageJson(text) {
    let payload;
    try {
      payload = JSON.parse(String(text || ""));
    } catch (_error) {
      throw new Error("Experimental Package file is not valid JSON.");
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("Experimental Package file must contain one JSON object.");
    }
    if (payload.schema !== PACKAGE_SCHEMA) {
      throw new Error(`Experimental Package schema must be ${PACKAGE_SCHEMA}.`);
    }
    return payload;
  }

  function acceptImportResult({ requestToken, activeToken, requestFingerprint, currentFingerprint, result, currentDraft }) {
    if (requestToken !== activeToken || requestFingerprint !== currentFingerprint) {
      return { applied: false, reason: "stale", draft: currentDraft, errors: [] };
    }
    if (result?.ok !== true || !result?.draft) {
      return {
        applied: false,
        reason: "failed",
        draft: currentDraft,
        errors: Array.isArray(result?.errors) && result.errors.length ? result.errors.map(String) : ["Experimental Package import failed."],
      };
    }
    return { applied: true, reason: "accepted", draft: clone(result.draft), errors: [] };
  }

  function acceptExportResult({ requestToken, activeToken, requestFingerprint, currentFingerprint, result, currentDraft }) {
    if (requestToken !== activeToken || requestFingerprint !== currentFingerprint) {
      return { applied: false, reason: "stale", draft: currentDraft, errors: [] };
    }
    if (result?.ok !== true || !result?.package) {
      return {
        applied: false,
        reason: "failed",
        draft: currentDraft,
        errors: Array.isArray(result?.errors) && result.errors.length ? result.errors.map(String) : ["Experimental Package export failed."],
      };
    }
    return { applied: true, reason: "accepted", draft: clone(result.package), errors: [] };
  }

  return {
    PACKAGE_SCHEMA,
    CATALOG_SCHEMA,
    normalizeCatalog,
    packageRefsForGraph,
    buildExportState,
    projectComposition,
    projectBridgeTopology,
    buildExportPayload,
    parsePackageJson,
    acceptImportResult,
    acceptExportResult,
  };
});
