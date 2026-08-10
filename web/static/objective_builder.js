/* Canonical state and tree operations for manual objective authoring. */
(function objectiveBuilderModule(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.ObjectiveBuilder = api;
})(typeof window !== "undefined" ? window : null, function objectiveBuilderFactory() {
  "use strict";

  const STORAGE_KEY = "atr.objective-builder.v1";
  const METADATA_FIELDS = new Set(["objective_id", "name", "description", "intent", "direction"]);

  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function pretty(value) {
    return JSON.stringify(value, null, 2);
  }

  function pathParts(path) {
    if (Array.isArray(path)) return path.map(String);
    return String(path || "").split(".").filter(Boolean);
  }

  function getAt(source, path) {
    return pathParts(path).reduce((value, key) => {
      if (value === null || value === undefined) return undefined;
      return value[Number.isInteger(Number(key)) && String(Number(key)) === key ? Number(key) : key];
    }, source);
  }

  function setAt(source, path, value) {
    const parts = pathParts(path);
    if (!parts.length) throw new Error("tree path is required");
    let cursor = source;
    for (let index = 0; index < parts.length - 1; index += 1) {
      const key = /^\d+$/.test(parts[index]) ? Number(parts[index]) : parts[index];
      if (cursor[key] === undefined || cursor[key] === null) {
        cursor[key] = /^\d+$/.test(parts[index + 1]) ? [] : {};
      }
      cursor = cursor[key];
    }
    const tail = /^\d+$/.test(parts.at(-1)) ? Number(parts.at(-1)) : parts.at(-1);
    cursor[tail] = value;
  }

  function parentAt(source, path) {
    const parts = pathParts(path);
    if (parts.length < 2) throw new Error("root node cannot be moved or removed");
    const keyText = parts.pop();
    return {
      parent: getAt(source, parts),
      key: /^\d+$/.test(keyText) ? Number(keyText) : keyText,
    };
  }

  function defaultSpec() {
    return {
      schema_version: "objective_spec.v1",
      objective_id: "manual-objective",
      version: 1,
      name: "",
      description: "",
      intent: "",
      direction: "maximize",
      expression: { op: "literal", value: 0, unit: "1" },
      constraints: [],
      lifecycle: "draft",
      created_by: "operator",
      metadata: { authoring_mode: "manual" },
    };
  }

  function descriptorMap(manifest) {
    return new Map((manifest?.operators || []).map((item) => [item.op, item]));
  }

  function validateSpec(spec, options) {
    const { manifest, metrics, allowIncomplete = false } = options;
    const operators = descriptorMap(manifest);
    const metricIds = new Set((metrics || []).map((item) => item.metric_id));
    const units = new Set(manifest?.units || []);
    const maxDepth = Number(manifest?.limits?.max_depth || 16);
    const maxNodes = Number(manifest?.limits?.max_nodes || 256);
    const errors = [];
    let nodeCount = 0;

    function error(path, message) {
      errors.push({ path, message });
    }

    function visit(node, path, expectedKind, depth) {
      nodeCount += 1;
      if (nodeCount > maxNodes) {
        error(path, `AST node count exceeds ${maxNodes}`);
        return;
      }
      if (depth > maxDepth) {
        error(path, `AST depth exceeds ${maxDepth}`);
        return;
      }
      if (!node || typeof node !== "object" || Array.isArray(node)) {
        error(path, "expression node must be an object");
        return;
      }
      const descriptor = operators.get(node.op);
      if (!descriptor || descriptor.enabled === false) {
        error(`${path}.op`, `operator is not available: ${String(node.op || "")}`);
        return;
      }
      if (expectedKind && descriptor.result_kind !== expectedKind) {
        error(path, `${expectedKind} expression required`);
      }
      if (node.op === "metric" && !metricIds.has(node.metric_id)) {
        error(`${path}.metric_id`, `metric is not registered: ${String(node.metric_id || "")}`);
      }
      if (node.op === "literal") {
        if (!Number.isFinite(Number(node.value))) error(`${path}.value`, "literal must be finite");
        if (!units.has(String(node.unit ?? "1"))) error(`${path}.unit`, `unit is not supported: ${String(node.unit)}`);
      }

      const childContract = descriptor.children || { mode: "none" };
      const nestedKind = ["and", "or", "not"].includes(node.op) ? "boolean" : "number";
      if (childContract.mode === "none") return;
      if (childContract.mode === "arg") {
        if (node.arg === undefined) {
          if (!allowIncomplete) error(`${path}.arg`, "child expression is required");
        } else {
          visit(node.arg, `${path}.arg`, nestedKind, depth + 1);
        }
        return;
      }
      if (childContract.mode === "args") {
        const args = Array.isArray(node.args) ? node.args : [];
        if (!Array.isArray(node.args) || (!allowIncomplete && args.length < Number(childContract.minimum || 0))) {
          error(`${path}.args`, `at least ${Number(childContract.minimum || 0)} child expressions are required`);
        }
        args.forEach((child, index) => visit(child, `${path}.args.${index}`, nestedKind, depth + 1));
        return;
      }
      if (childContract.mode === "slots") {
        (childContract.slots || []).forEach((slot) => {
          if (node[slot] === undefined) {
            if (!allowIncomplete) error(`${path}.${slot}`, "child expression is required");
          } else {
            visit(node[slot], `${path}.${slot}`, "number", depth + 1);
          }
        });
        return;
      }
      if (childContract.mode === "terms") {
        const terms = Array.isArray(node.terms) ? node.terms : [];
        if (!Array.isArray(node.terms) || (!allowIncomplete && terms.length < Number(childContract.minimum || 1))) {
          error(`${path}.terms`, "at least one weighted term is required");
        }
        terms.forEach((term, index) => {
          if (!term || typeof term !== "object" || Array.isArray(term)) {
            error(`${path}.terms.${index}`, "weighted term must be an object");
            return;
          }
          if (!Number.isFinite(Number(term.weight))) error(`${path}.terms.${index}.weight`, "weight must be finite");
          visit(term.expression, `${path}.terms.${index}.expression`, "number", depth + 1);
        });
        return;
      }
      if (childContract.mode === "piecewise") {
        if (node.value === undefined) {
          if (!allowIncomplete) error(`${path}.value`, "value expression is required");
        } else {
          visit(node.value, `${path}.value`, "number", depth + 1);
        }
        const points = Array.isArray(node.points) ? node.points : [];
        if (!allowIncomplete && points.length < Number(childContract.minimum_points || 2)) {
          error(`${path}.points`, "at least two piecewise points are required");
        }
        points.forEach((point, index) => {
          visit(point?.x, `${path}.points.${index}.x`, "number", depth + 1);
          if (!Number.isFinite(Number(point?.y))) error(`${path}.points.${index}.y`, "penalty value must be finite");
        });
      }
    }

    if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
      return [{ path: "$", message: "objective spec must be one JSON object" }];
    }
    if (spec.schema_version !== "objective_spec.v1") error("$.schema_version", "objective_spec.v1 is required");
    if (!String(spec.objective_id || "").trim()) error("$.objective_id", "objective id is required");
    if (!['maximize', 'minimize'].includes(spec.direction)) error("$.direction", "direction must be maximize or minimize");
    visit(spec.expression, "$.expression", "number", 1);
    if (!Array.isArray(spec.constraints)) {
      error("$.constraints", "constraints must be an array");
    } else {
      spec.constraints.forEach((constraint, index) => visit(constraint, `$.constraints.${index}`, "boolean", 1));
    }
    return errors;
  }

  function createState(options) {
    const manifest = clone(options?.manifest || {});
    const metrics = clone(options?.metrics || []);
    const storage = options?.storage || (typeof window !== "undefined" ? window.localStorage : null);
    const storageKey = options?.storageKey || STORAGE_KEY;
    let lastValidSpec = defaultSpec();
    let jsonBuffer = pretty(lastValidSpec);
    let dirty = false;
    let selectedObjective = null;
    let jsonErrors = [];

    function persist() {
      if (!storage) return;
      if (!dirty) {
        storage.removeItem(storageKey);
        return;
      }
      storage.setItem(storageKey, JSON.stringify({ lastValidSpec, dirty: true }));
    }

    function replaceCanonical(next, { persistState = true, allowIncomplete = true } = {}) {
      const errors = validateSpec(next, { manifest, metrics, allowIncomplete });
      if (errors.length) {
        const failure = new Error(errors[0].message);
        failure.errors = errors;
        throw failure;
      }
      lastValidSpec = clone(next);
      jsonBuffer = pretty(lastValidSpec);
      jsonErrors = [];
      dirty = true;
      if (persistState) persist();
    }

    function restoreStored() {
      if (!storage) return;
      const raw = storage.getItem(storageKey);
      if (!raw) return;
      try {
        const payload = JSON.parse(raw);
        const errors = validateSpec(payload.lastValidSpec, { manifest, metrics, allowIncomplete: true });
        if (!errors.length && payload.dirty === true) {
          lastValidSpec = clone(payload.lastValidSpec);
          jsonBuffer = pretty(lastValidSpec);
          dirty = true;
        }
      } catch (_) {
        storage.removeItem(storageKey);
      }
    }

    restoreStored();

    return {
      snapshot() {
        return clone({ lastValidSpec, jsonBuffer, dirty, selectedObjective, jsonErrors });
      },
      setMetadata(updates) {
        const next = clone(lastValidSpec);
        Object.entries(updates || {}).forEach(([key, value]) => {
          if (METADATA_FIELDS.has(key)) next[key] = value;
        });
        replaceCanonical(next);
      },
      replaceNode(path, node) {
        const next = clone(lastValidSpec);
        setAt(next, path, clone(node));
        replaceCanonical(next);
      },
      addChild(path, node) {
        const next = clone(lastValidSpec);
        const parent = getAt(next, path);
        const descriptor = descriptorMap(manifest).get(parent?.op);
        if (!descriptor || descriptor.enabled === false) throw new Error("parent operator is not available");
        const contract = descriptor.children || { mode: "none" };
        const child = clone(node || { op: "literal", value: 0, unit: "1" });
        if (contract.mode === "args") {
          if (!Array.isArray(parent.args)) parent.args = [];
          parent.args.push(child);
        } else if (contract.mode === "arg") {
          parent.arg = child;
        } else if (contract.mode === "slots") {
          const slot = (contract.slots || []).find((name) => parent[name] === undefined);
          if (!slot) throw new Error("all child slots are already populated");
          parent[slot] = child;
        } else if (contract.mode === "terms") {
          if (!Array.isArray(parent.terms)) parent.terms = [];
          parent.terms.push({ name: `term_${parent.terms.length + 1}`, weight: 1, expression: child });
        } else if (contract.mode === "piecewise") {
          if (parent.value === undefined) parent.value = child;
          else throw new Error("piecewise value slot is already populated");
        } else {
          throw new Error("operator does not accept child expressions");
        }
        replaceCanonical(next);
      },
      duplicateNode(path) {
        const next = clone(lastValidSpec);
        const { parent, key } = parentAt(next, path);
        if (!Array.isArray(parent) || !Number.isInteger(key)) throw new Error("only list entries can be duplicated");
        parent.splice(key + 1, 0, clone(parent[key]));
        replaceCanonical(next);
      },
      moveNode(path, delta) {
        const next = clone(lastValidSpec);
        const { parent, key } = parentAt(next, path);
        if (!Array.isArray(parent) || !Number.isInteger(key)) throw new Error("only list entries can be reordered");
        const target = key + Number(delta);
        if (!Number.isInteger(target) || target < 0 || target >= parent.length) return false;
        const [entry] = parent.splice(key, 1);
        parent.splice(target, 0, entry);
        replaceCanonical(next);
        return true;
      },
      removeNode(path) {
        const next = clone(lastValidSpec);
        const { parent, key } = parentAt(next, path);
        if (!Array.isArray(parent) || !Number.isInteger(key)) throw new Error("only list entries can be removed");
        parent.splice(key, 1);
        replaceCanonical(next);
      },
      addConstraint(node) {
        const candidate = clone(node || { op: "greater_equal", args: [] });
        const probe = clone(lastValidSpec);
        probe.constraints.push(candidate);
        const errors = validateSpec(probe, { manifest, metrics, allowIncomplete: false })
          .filter((item) => item.path.startsWith(`$.constraints.${probe.constraints.length - 1}`));
        if (errors.length) {
          const failure = new Error(`boolean constraint required: ${errors[0].message}`);
          failure.errors = errors;
          throw failure;
        }
        replaceCanonical(probe);
      },
      setJsonBuffer(text) {
        jsonBuffer = String(text ?? "");
        persist();
      },
      applyJson(text) {
        jsonBuffer = String(text ?? "");
        let parsed;
        try {
          parsed = JSON.parse(jsonBuffer);
        } catch (error) {
          jsonErrors = [{ path: "$", message: `JSON parse error: ${error.message || error}` }];
          persist();
          return { ok: false, errors: clone(jsonErrors) };
        }
        const errors = validateSpec(parsed, { manifest, metrics, allowIncomplete: false });
        if (errors.length) {
          jsonErrors = errors;
          persist();
          return { ok: false, errors: clone(errors) };
        }
        lastValidSpec = clone(parsed);
        jsonBuffer = pretty(lastValidSpec);
        jsonErrors = [];
        dirty = true;
        persist();
        return { ok: true, spec: clone(lastValidSpec) };
      },
      restoreLastValid() {
        jsonBuffer = pretty(lastValidSpec);
        jsonErrors = [];
        persist();
        return clone(lastValidSpec);
      },
      markSaved(serverSpec) {
        const errors = validateSpec(serverSpec, { manifest, metrics, allowIncomplete: false });
        if (errors.length) throw new Error(errors[0].message);
        lastValidSpec = clone(serverSpec);
        jsonBuffer = pretty(lastValidSpec);
        selectedObjective = {
          objective_id: serverSpec.objective_id,
          version: serverSpec.version,
        };
        jsonErrors = [];
        dirty = false;
        if (storage) storage.removeItem(storageKey);
      },
    };
  }

  return {
    STORAGE_KEY,
    createState,
    defaultSpec,
    validateSpec,
  };
});
