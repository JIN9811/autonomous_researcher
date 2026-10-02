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

  function createDefaultNode(operator, manifest, metrics) {
    const descriptors = descriptorMap(manifest);
    const descriptor = descriptors.get(operator);
    if (!descriptor || descriptor.enabled === false) throw new Error(`operator is not available: ${operator}`);
    if (operator === "literal") return { op: "literal", value: 0, unit: "1" };
    if (operator === "metric") {
      const metricId = metrics?.[0]?.metric_id;
      if (!metricId) throw new Error("Metric Registry is empty");
      return { op: "metric", metric_id: metricId };
    }

    const node = { op: operator };
    (descriptor.fields || []).forEach((field) => {
      if (field.default !== undefined) node[field.name] = clone(field.default);
    });
    const numericChild = () => ({ op: "literal", value: 0, unit: "1" });
    const booleanChild = () => {
      const comparison = ["greater_equal", "equal", "less_equal"].find((name) => descriptors.get(name)?.enabled !== false && descriptors.has(name));
      return comparison
        ? { op: comparison, args: [numericChild(), numericChild()] }
        : numericChild();
    };
    const contract = descriptor.children || { mode: "none" };
    if (contract.mode === "arg") node.arg = operator === "not" ? booleanChild() : numericChild();
    if (contract.mode === "args") {
      const makeChild = ["and", "or"].includes(operator) ? booleanChild : numericChild;
      node.args = Array.from({ length: Number(contract.minimum || 0) }, makeChild);
    }
    if (contract.mode === "slots") {
      (contract.slots || []).forEach((slot) => { node[slot] = numericChild(); });
    }
    if (contract.mode === "terms") {
      node.terms = [{ name: "term_1", weight: 1, expression: numericChild() }];
    }
    if (contract.mode === "piecewise") {
      node.value = numericChild();
      node.points = [
        { x: numericChild(), y: 0 },
        { x: { op: "literal", value: 1, unit: "1" }, y: 1 },
      ];
    }
    return node;
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
      storage.setItem(storageKey, JSON.stringify({ lastValidSpec, jsonBuffer, jsonErrors, dirty: true }));
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
          jsonBuffer = typeof payload.jsonBuffer === "string" ? payload.jsonBuffer : pretty(lastValidSpec);
          jsonErrors = Array.isArray(payload.jsonErrors) ? clone(payload.jsonErrors) : [];
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
      updateValue(path, value) {
        const next = clone(lastValidSpec);
        setAt(next, path, clone(value));
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
      reparentNode(sourcePath, targetPath) {
        const sourceParts = pathParts(sourcePath);
        const targetParts = pathParts(targetPath);
        if (!sourceParts.length || sourceParts.join(".") === "expression") {
          throw new Error("root expression cannot be reparented");
        }
        if (targetParts.join(".").startsWith(`${sourceParts.join(".")}.`)) {
          throw new Error("a node cannot be moved into its own subtree");
        }
        const next = clone(lastValidSpec);
        const sourceNode = clone(getAt(next, sourceParts));
        const targetNode = getAt(next, targetParts);
        const descriptor = descriptorMap(manifest).get(targetNode?.op);
        if (!sourceNode || !descriptor || descriptor.enabled === false) {
          throw new Error("source or target node is not available");
        }
        const { parent, key } = parentAt(next, sourceParts);
        if (Array.isArray(parent) && Number.isInteger(key)) parent.splice(key, 1);
        else delete parent[key];

        const contract = descriptor.children || { mode: "none" };
        if (contract.mode === "args") {
          if (!Array.isArray(targetNode.args)) targetNode.args = [];
          targetNode.args.push(sourceNode);
        } else if (contract.mode === "arg") {
          if (targetNode.arg !== undefined) throw new Error("target child slot is already populated");
          targetNode.arg = sourceNode;
        } else if (contract.mode === "slots") {
          const slot = (contract.slots || []).find((name) => targetNode[name] === undefined);
          if (!slot) throw new Error("target child slots are already populated");
          targetNode[slot] = sourceNode;
        } else if (contract.mode === "terms") {
          if (!Array.isArray(targetNode.terms)) targetNode.terms = [];
          targetNode.terms.push({ name: `term_${targetNode.terms.length + 1}`, weight: 1, expression: sourceNode });
        } else if (contract.mode === "piecewise" && targetNode.value === undefined) {
          targetNode.value = sourceNode;
        } else {
          throw new Error("target operator cannot accept the subtree");
        }
        replaceCanonical(next);
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
      addPoint(path) {
        const next = clone(lastValidSpec);
        const node = getAt(next, path);
        if (node?.op !== "piecewise_penalty") throw new Error("piecewise penalty node is required");
        if (!Array.isArray(node.points)) node.points = [];
        const previous = node.points.at(-1);
        const previousX = previous?.x?.op === "literal" ? Number(previous.x.value) : node.points.length - 1;
        const previousY = Number(previous?.y);
        node.points.push({
          x: { op: "literal", value: Number.isFinite(previousX) ? previousX + 1 : node.points.length, unit: previous?.x?.unit || "1" },
          y: Number.isFinite(previousY) ? previousY + 1 : node.points.length,
        });
        replaceCanonical(next);
      },
      removePoint(path, index) {
        const next = clone(lastValidSpec);
        const node = getAt(next, path);
        if (node?.op !== "piecewise_penalty" || !Array.isArray(node.points)) {
          throw new Error("piecewise penalty node is required");
        }
        if (node.points.length <= 2) throw new Error("piecewise penalty requires at least two points");
        node.points.splice(Number(index), 1);
        replaceCanonical(next);
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
      loadRevision(serverSpec) {
        const errors = validateSpec(serverSpec, { manifest, metrics, allowIncomplete: false });
        if (errors.length) throw new Error(errors[0].message);
        lastValidSpec = clone(serverSpec);
        lastValidSpec.lifecycle = "draft";
        lastValidSpec.metadata = {
          ...(lastValidSpec.metadata || {}),
          authoring_mode: "manual",
          parent_objective_id: serverSpec.objective_id,
          parent_version: serverSpec.version,
        };
        jsonBuffer = pretty(lastValidSpec);
        selectedObjective = {
          objective_id: serverSpec.objective_id,
          version: serverSpec.version,
        };
        jsonErrors = [];
        dirty = true;
        persist();
      },
      loadPreset(presetSpec) {
        const errors = validateSpec(presetSpec, { manifest, metrics, allowIncomplete: false });
        if (errors.length) throw new Error(errors[0].message);
        lastValidSpec = clone(presetSpec);
        const presetId = String(lastValidSpec.metadata?.preset_id || lastValidSpec.objective_id || "");
        lastValidSpec.version = 1;
        lastValidSpec.lifecycle = "draft";
        lastValidSpec.created_by = "operator";
        lastValidSpec.metadata = {
          ...(lastValidSpec.metadata || {}),
          authoring_mode: "manual",
          source_preset_id: presetId,
        };
        delete lastValidSpec.metadata.parent_objective_id;
        delete lastValidSpec.metadata.parent_version;
        jsonBuffer = pretty(lastValidSpec);
        selectedObjective = null;
        jsonErrors = [];
        dirty = true;
        persist();
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

  function mountEditor(options) {
    const state = options.state;
    const manifest = options.manifest;
    const metrics = options.metrics || [];
    const elements = options.elements || {};
    const operators = descriptorMap(manifest);
    const doc = elements.expression?.ownerDocument || document;
    let dragPath = "";

    function button(label, action, title = label) {
      const control = doc.createElement("button");
      control.type = "button";
      control.className = "bo-tree-action";
      control.textContent = label;
      control.title = title;
      control.setAttribute("aria-label", title);
      control.addEventListener("click", action);
      return control;
    }

    function notify(message = "") {
      if (elements.status && message) elements.status.textContent = message;
      if (typeof options.onChange === "function") options.onChange(state.snapshot());
    }

    function runMutation(action, successMessage) {
      try {
        action();
        render();
        notify(successMessage);
      } catch (error) {
        if (elements.status) elements.status.textContent = `Error: ${error.message || error}`;
      }
    }

    function inputFor(path, value, type = "text", config = {}) {
      const input = doc.createElement("input");
      input.className = "bo-tree-field";
      input.type = type;
      input.value = value ?? "";
      if (config.min !== undefined) input.min = config.min;
      if (config.max !== undefined) input.max = config.max;
      if (config.step !== undefined) input.step = config.step;
      input.addEventListener("change", () => {
        const next = type === "number" ? Number(input.value) : input.value;
        runMutation(() => state.updateValue(path, next), "Manual objective updated.");
      });
      return input;
    }

    function selectFor(path, value, choices, className = "bo-tree-field") {
      const select = doc.createElement("select");
      select.className = className;
      choices.forEach((choice) => {
        const option = doc.createElement("option");
        const resolvedValue = typeof choice === "object" ? choice.value : choice;
        option.value = resolvedValue;
        option.textContent = typeof choice === "object" ? choice.label : choice;
        option.selected = String(resolvedValue) === String(value);
        select.append(option);
      });
      select.addEventListener("change", () => runMutation(
        () => state.updateValue(path, select.value),
        "Manual objective updated.",
      ));
      return select;
    }

    function operatorSelect(node, path, expectedKind) {
      const choices = (manifest.operators || [])
        .filter((item) => item.enabled !== false && item.result_kind === expectedKind)
        .map((item) => ({ value: item.op, label: item.label || item.op }));
      const select = doc.createElement("select");
      select.className = "bo-tree-operator";
      select.setAttribute("aria-label", `Operator at ${path}`);
      choices.forEach((choice) => {
        const option = doc.createElement("option");
        option.value = choice.value;
        option.textContent = choice.label;
        option.selected = choice.value === node.op;
        select.append(option);
      });
      select.addEventListener("change", () => runMutation(
        () => state.replaceNode(path, createDefaultNode(select.value, manifest, metrics)),
        `Operator changed to ${select.value}.`,
      ));
      return select;
    }

    function canListOperate(path) {
      return /\.(args|constraints)\.\d+$/.test(path);
    }

    function renderScalarFields(node, path, descriptor) {
      const fields = doc.createElement("div");
      fields.className = "bo-tree-fields";
      if (node.op === "literal") {
        const valueLabel = doc.createElement("label");
        valueLabel.textContent = "Value";
        valueLabel.append(inputFor(`${path}.value`, node.value, "number", { step: "any" }));
        const unitLabel = doc.createElement("label");
        unitLabel.textContent = "Unit";
        unitLabel.append(selectFor(`${path}.unit`, node.unit || "1", manifest.units || []));
        fields.append(valueLabel, unitLabel);
      } else if (node.op === "metric") {
        const label = doc.createElement("label");
        label.textContent = "Registered metric";
        label.append(selectFor(
          `${path}.metric_id`,
          node.metric_id,
          metrics.map((metric) => ({
            value: metric.metric_id,
            label: `${metric.label || metric.metric_id} [${metric.unit || "1"}]`,
          })),
        ));
        fields.append(label);
      }
      (descriptor.fields || []).forEach((field) => {
        if (["value", "unit", "metric_id"].includes(field.name)) return;
        const label = doc.createElement("label");
        label.textContent = field.name.replaceAll("_", " ");
        if (field.type === "choice") {
          label.append(selectFor(`${path}.${field.name}`, node[field.name] ?? field.default, field.choices || []));
        } else {
          label.append(inputFor(`${path}.${field.name}`, node[field.name] ?? field.default, "number", {
            min: field.min,
            max: field.max,
            step: "any",
          }));
        }
        fields.append(label);
      });
      return fields;
    }

    function appendNodeControls(container, node, path, descriptor) {
      const mode = descriptor.children?.mode || "none";
      const comparisons = new Set(["less_than", "less_equal", "greater_than", "greater_equal", "equal"]);
      const canAdd = mode === "terms"
        || (mode === "args" && !comparisons.has(node.op))
        || (mode === "arg" && node.arg === undefined)
        || (mode === "slots" && (descriptor.children.slots || []).some((slot) => node[slot] === undefined));
      if (canAdd) {
        container.append(button("+", () => runMutation(
          () => state.addChild(path, { op: "literal", value: 0, unit: "1" }),
          "Child expression added.",
        ), "Add child expression"));
      }
      if (mode === "piecewise") {
        container.append(button("+ point", () => runMutation(
          () => state.addPoint(path),
          "Piecewise point added.",
        ), "Add piecewise point"));
      }
      if (canListOperate(path)) {
        container.append(
          button("↑", () => runMutation(() => state.moveNode(path, -1), "Node moved up."), "Move node up"),
          button("↓", () => runMutation(() => state.moveNode(path, 1), "Node moved down."), "Move node down"),
          button("⧉", () => runMutation(() => state.duplicateNode(path), "Node duplicated."), "Duplicate node"),
          button("×", () => runMutation(() => state.removeNode(path), "Node removed."), "Delete node"),
        );
      }
    }

    function renderNode(node, path, expectedKind = "number", label = "") {
      const descriptor = operators.get(node?.op);
      const card = doc.createElement("article");
      card.className = `bo-tree-node ${expectedKind === "boolean" ? "constraint" : "numeric"}`;
      card.dataset.nodePath = path;
      card.draggable = path !== "expression";
      card.addEventListener("dragstart", (event) => {
        dragPath = path;
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", path);
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", () => {
        dragPath = "";
        card.classList.remove("dragging");
      });
      card.addEventListener("dragover", (event) => {
        if (!dragPath || !descriptor || descriptor.children?.mode === "none") return;
        event.preventDefault();
        card.classList.add("drag-target");
      });
      card.addEventListener("dragleave", () => card.classList.remove("drag-target"));
      card.addEventListener("drop", (event) => {
        event.preventDefault();
        event.stopPropagation();
        card.classList.remove("drag-target");
        const sourcePath = event.dataTransfer.getData("text/plain") || dragPath;
        if (sourcePath && sourcePath !== path) {
          runMutation(() => state.reparentNode(sourcePath, path), "Subtree moved.");
        }
      });

      if (!descriptor) {
        card.textContent = `Unknown operator: ${String(node?.op || "")}`;
        return card;
      }
      const head = doc.createElement("header");
      head.className = "bo-tree-node-head";
      const identity = doc.createElement("div");
      identity.className = "bo-tree-node-identity";
      if (label) {
        const slotLabel = doc.createElement("span");
        slotLabel.className = "bo-tree-slot-label";
        slotLabel.textContent = label;
        identity.append(slotLabel);
      }
      identity.append(operatorSelect(node, path, expectedKind));
      const controls = doc.createElement("div");
      controls.className = "bo-tree-node-actions";
      appendNodeControls(controls, node, path, descriptor);
      head.append(identity, controls);
      card.append(head, renderScalarFields(node, path, descriptor));

      const children = doc.createElement("div");
      children.className = "bo-tree-children";
      const contract = descriptor.children || { mode: "none" };
      const nestedKind = ["and", "or", "not"].includes(node.op) ? "boolean" : "number";
      if (contract.mode === "arg" && node.arg) children.append(renderNode(node.arg, `${path}.arg`, nestedKind, "arg"));
      if (contract.mode === "args") {
        (node.args || []).forEach((child, index) => children.append(renderNode(child, `${path}.args.${index}`, nestedKind, `arg ${index + 1}`)));
      }
      if (contract.mode === "slots") {
        (contract.slots || []).forEach((slot) => {
          if (node[slot]) children.append(renderNode(node[slot], `${path}.${slot}`, "number", slot));
        });
      }
      if (contract.mode === "terms") {
        (node.terms || []).forEach((term, index) => {
          const wrapper = doc.createElement("section");
          wrapper.className = "bo-weighted-term";
          const termHead = doc.createElement("div");
          termHead.className = "bo-weighted-term-head";
          const termPath = `${path}.terms.${index}`;
          const nameInput = inputFor(`${termPath}.name`, term.name, "text");
          nameInput.setAttribute("aria-label", `Term ${index + 1} name`);
          const weightInput = inputFor(`${termPath}.weight`, term.weight, "number", { step: "any" });
          weightInput.setAttribute("aria-label", `Term ${index + 1} weight`);
          termHead.append(nameInput, weightInput);
          const termActions = doc.createElement("div");
          termActions.className = "bo-tree-node-actions";
          termActions.append(
            button("↑", () => runMutation(() => state.moveNode(termPath, -1), "Term moved up."), "Move term up"),
            button("↓", () => runMutation(() => state.moveNode(termPath, 1), "Term moved down."), "Move term down"),
            button("⧉", () => runMutation(() => state.duplicateNode(termPath), "Term duplicated."), "Duplicate term"),
            button("×", () => runMutation(() => state.removeNode(termPath), "Term removed."), "Delete term"),
          );
          termHead.append(termActions);
          wrapper.append(termHead, renderNode(term.expression, `${termPath}.expression`, "number", `term ${index + 1}`));
          children.append(wrapper);
        });
      }
      if (contract.mode === "piecewise") {
        if (node.value) children.append(renderNode(node.value, `${path}.value`, "number", "value"));
        const points = doc.createElement("div");
        points.className = "bo-piecewise-points";
        (node.points || []).forEach((point, index) => {
          const pointRow = doc.createElement("div");
          pointRow.className = "bo-piecewise-point";
          pointRow.append(renderNode(point.x, `${path}.points.${index}.x`, "number", `x ${index + 1}`));
          pointRow.append(inputFor(`${path}.points.${index}.y`, point.y, "number", { step: "any" }));
          const removePoint = button("×", () => runMutation(
            () => state.removePoint(path, index),
            "Piecewise point removed.",
          ), `Delete piecewise point ${index + 1}`);
          removePoint.disabled = (node.points || []).length <= 2;
          pointRow.append(removePoint);
          points.append(pointRow);
        });
        children.append(points);
      }
      if (children.childElementCount) card.append(children);
      return card;
    }

    function renderJsonErrors(snapshot) {
      if (!elements.jsonErrors) return;
      elements.jsonErrors.replaceChildren();
      if (!snapshot.jsonErrors.length) return;
      snapshot.jsonErrors.forEach((item) => {
        const row = doc.createElement("p");
        row.textContent = `${item.path}: ${item.message}`;
        elements.jsonErrors.append(row);
      });
    }

    function syncMetadata(spec) {
      const fields = elements.metadata || {};
      Object.entries(fields).forEach(([key, input]) => {
        if (input && doc.activeElement !== input) input.value = spec[key] ?? "";
      });
    }

    function render() {
      const snapshot = state.snapshot();
      const spec = snapshot.lastValidSpec;
      syncMetadata(spec);
      if (elements.expression) elements.expression.replaceChildren(renderNode(spec.expression, "expression", "number", "root"));
      if (elements.constraints) {
        elements.constraints.replaceChildren();
        if (!spec.constraints.length) {
          const empty = doc.createElement("p");
          empty.className = "bo-builder-empty";
          empty.textContent = "No hard constraints. Add a Boolean expression when required.";
          elements.constraints.append(empty);
        } else {
          spec.constraints.forEach((constraint, index) => elements.constraints.append(
            renderNode(constraint, `constraints.${index}`, "boolean", `constraint ${index + 1}`),
          ));
        }
      }
      if (elements.json && doc.activeElement !== elements.json) elements.json.value = snapshot.jsonBuffer;
      if (elements.dirty) {
        elements.dirty.textContent = snapshot.dirty ? "unsaved" : "saved";
        elements.dirty.className = `runtime-chip ${snapshot.dirty ? "warning" : "ok"}`;
      }
      renderJsonErrors(snapshot);
      return snapshot;
    }

    Object.entries(elements.metadata || {}).forEach(([key, input]) => {
      if (!input) return;
      input.addEventListener("change", () => runMutation(
        () => state.setMetadata({ [key]: input.value }),
        "Objective metadata updated.",
      ));
    });
    elements.addConstraint?.addEventListener("click", () => runMutation(
      () => state.addConstraint(createDefaultNode("greater_equal", manifest, metrics)),
      "Constraint added.",
    ));
    elements.json?.addEventListener("input", () => {
      state.setJsonBuffer(elements.json.value);
      if (elements.dirty) {
        elements.dirty.textContent = "unsaved";
        elements.dirty.className = "runtime-chip warning";
      }
    });
    elements.applyJson?.addEventListener("click", () => {
      const result = state.applyJson(elements.json.value);
      if (result.ok) {
        render();
        notify("JSON applied to Visual Builder.");
      } else {
        renderJsonErrors(state.snapshot());
        if (elements.status) elements.status.textContent = "JSON was not applied. Fix the listed errors.";
      }
    });
    elements.restoreJson?.addEventListener("click", () => {
      state.restoreLastValid();
      render();
      notify("Last valid objective restored.");
    });
    elements.formatJson?.addEventListener("click", () => {
      try {
        elements.json.value = pretty(JSON.parse(elements.json.value));
        state.setJsonBuffer(elements.json.value);
        if (elements.status) elements.status.textContent = "JSON formatted. Apply it to update the builder.";
      } catch (error) {
        if (elements.status) elements.status.textContent = `JSON parse error: ${error.message || error}`;
      }
    });

    render();
    return { render };
  }

  return {
    STORAGE_KEY,
    createDefaultNode,
    createState,
    mountEditor,
    defaultSpec,
    validateSpec,
  };
});
