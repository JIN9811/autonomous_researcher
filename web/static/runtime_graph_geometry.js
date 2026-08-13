/*
File purpose:
- Shared runtime graph geometry for main dashboard and Runtime IDE edge rendering.

Key functions:
- portPoint
- inferPorts
- assignOffsets
- controlPoints
- path
- labelPoint

Design rule:
- Edges always start/end at a single node port point.
- Fan-out is applied only to Bezier handles, so parallel edges spread like a fan and converge again.
*/
(function attachRuntimeGraphGeometry(global) {
  const DEFAULT_NODE_WIDTH = 184;
  const DEFAULT_NODE_HEIGHT = 76;
  const DEFAULT_EDGE_SPACING = 14;
  const DEFAULT_PARALLEL_SPACING = 26;
  const DEFAULT_HANDLE_PERCENT = 0.28;
  const DEFAULT_OUTWARD_OFFSET = 8;
  const DEFAULT_COLLISION_GAP_X = 44;
  const DEFAULT_COLLISION_GAP_Y = 34;
  const SIDES = ["top", "right", "bottom", "left"];

  function number(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function optionsWithDefaults(options = {}) {
    return {
      nodeWidth: number(options.nodeWidth, DEFAULT_NODE_WIDTH),
      nodeHeight: number(options.nodeHeight, DEFAULT_NODE_HEIGHT),
      edgeSpacing: number(options.edgeSpacing, DEFAULT_EDGE_SPACING),
      parallelSpacing: number(options.parallelSpacing, DEFAULT_PARALLEL_SPACING),
      handlePercent: Math.max(0.12, Math.min(0.45, number(options.handlePercent, DEFAULT_HANDLE_PERCENT))),
      outwardOffset: number(options.outwardOffset, DEFAULT_OUTWARD_OFFSET),
      collisionGapX: Math.max(0, number(options.collisionGapX, DEFAULT_COLLISION_GAP_X)),
      collisionGapY: Math.max(0, number(options.collisionGapY, DEFAULT_COLLISION_GAP_Y)),
    };
  }

  function portPoint(node, side = "right", alongOffset = 0, outwardOffset = 0, options = {}) {
    const opts = optionsWithDefaults(options);
    const x = number(node?.position?.x, 0);
    const y = number(node?.position?.y, 0);
    if (side === "left") return { x: x - outwardOffset, y: y + opts.nodeHeight / 2 + alongOffset };
    if (side === "right") return { x: x + opts.nodeWidth + outwardOffset, y: y + opts.nodeHeight / 2 + alongOffset };
    if (side === "top") return { x: x + opts.nodeWidth / 2 + alongOffset, y: y - outwardOffset };
    if (side === "bottom") return { x: x + opts.nodeWidth / 2 + alongOffset, y: y + opts.nodeHeight + outwardOffset };
    return { x: x + opts.nodeWidth + outwardOffset, y: y + opts.nodeHeight / 2 + alongOffset };
  }

  function inferPorts(source, target, options = {}) {
    let best = { sourceSide: "right", targetSide: "left", distance: Number.POSITIVE_INFINITY };
    for (const sourceSide of SIDES) {
      const sourcePoint = portPoint(source, sourceSide, 0, 0, options);
      for (const targetSide of SIDES) {
        const targetPoint = portPoint(target, targetSide, 0, 0, options);
        const distance = Math.hypot(targetPoint.x - sourcePoint.x, targetPoint.y - sourcePoint.y);
        if (distance < best.distance) best = { sourceSide, targetSide, distance };
      }
    }
    return { sourceSide: best.sourceSide, targetSide: best.targetSide };
  }

  function spread(index, total, step) {
    if (total <= 1) return 0;
    return (index - (total - 1) / 2) * step;
  }

  function edgeStableKey(edge = {}) {
    return String(edge.key || `${edge.source?.id || edge.sourceNodeId || "source"}->${edge.target?.id || edge.targetNodeId || "target"}:${edge.runtimeEdgeType || "edge"}:${edge.condition || ""}`);
  }

  function positionSortKey(node = {}) {
    const y = String(Math.round(number(node?.position?.y, 0))).padStart(5, "0");
    const x = String(Math.round(number(node?.position?.x, 0))).padStart(5, "0");
    return `${y}:${x}`;
  }

  function nodeKey(node = {}, fallback = "node") {
    return String(node?.id || node?.stage || fallback);
  }

  function undirectedPairKey(edge = {}) {
    const sourceKey = nodeKey(edge.source, edge.sourceNodeId || "source");
    const targetKey = nodeKey(edge.target, edge.targetNodeId || "target");
    return [sourceKey, targetKey].sort().join("<->");
  }

  function canonicalPairDirection(edge = {}) {
    const sourceKey = nodeKey(edge.source, edge.sourceNodeId || "source");
    const targetKey = nodeKey(edge.target, edge.targetNodeId || "target");
    return sourceKey <= targetKey ? 1 : -1;
  }

  function assignOffsets(edges = [], options = {}) {
    const opts = optionsWithDefaults(options);
    const sourceGroups = new Map();
    const targetGroups = new Map();
    const pairGroups = new Map();
    const add = (map, key, edge) => {
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(edge);
    };
    for (const edge of edges) {
      add(sourceGroups, `${edge.source?.id || edge.sourceNodeId || "source"}:${edge.sourceSide || "right"}`, edge);
      add(targetGroups, `${edge.target?.id || edge.targetNodeId || "target"}:${edge.targetSide || "left"}`, edge);
      add(pairGroups, undirectedPairKey(edge), edge);
    }
    for (const group of sourceGroups.values()) {
      group.sort((a, b) => `${positionSortKey(a.target)}:${edgeStableKey(a)}`.localeCompare(`${positionSortKey(b.target)}:${edgeStableKey(b)}`));
      group.forEach((edge, index) => {
        edge.sourceOffset = spread(index, group.length, opts.edgeSpacing);
      });
    }
    for (const group of targetGroups.values()) {
      group.sort((a, b) => `${positionSortKey(a.source)}:${edgeStableKey(a)}`.localeCompare(`${positionSortKey(b.source)}:${edgeStableKey(b)}`));
      group.forEach((edge, index) => {
        edge.targetOffset = spread(index, group.length, opts.edgeSpacing);
      });
    }
    for (const group of pairGroups.values()) {
      group.sort((a, b) => edgeStableKey(a).localeCompare(edgeStableKey(b)));
      group.forEach((edge, index) => {
        const canonicalOffset = spread(index, group.length, opts.parallelSpacing);
        edge.parallelOffset = canonicalOffset * canonicalPairDirection(edge);
        edge.parallelIndex = index;
        edge.parallelTotal = group.length;
      });
    }
    return edges;
  }

  function sideVector(side = "right") {
    if (side === "left") return { x: -1, y: 0 };
    if (side === "right") return { x: 1, y: 0 };
    if (side === "top") return { x: 0, y: -1 };
    if (side === "bottom") return { x: 0, y: 1 };
    return { x: 1, y: 0 };
  }

  function fanAxis(sourcePoint, targetPoint, sourceSide = "right", targetSide = "left") {
    const dx = targetPoint.x - sourcePoint.x;
    const dy = targetPoint.y - sourcePoint.y;
    const length = Math.hypot(dx, dy);
    if (length > 0.001) {
      return { x: -dy / length, y: dx / length };
    }
    const sourceHorizontal = sourceSide === "left" || sourceSide === "right";
    const targetHorizontal = targetSide === "left" || targetSide === "right";
    return sourceHorizontal || targetHorizontal ? { x: 0, y: 1 } : { x: 1, y: 0 };
  }

  function controlPoints(edge = {}, options = {}) {
    const opts = optionsWithDefaults(options);
    const sourcePoint = portPoint(edge.source, edge.sourceSide, 0, opts.outwardOffset, opts);
    const targetPoint = portPoint(edge.target, edge.targetSide, 0, opts.outwardOffset, opts);
    const dx = targetPoint.x - sourcePoint.x;
    const dy = targetPoint.y - sourcePoint.y;
    const length = Math.max(1, Math.hypot(dx, dy));
    const handleDistance = length * opts.handlePercent;
    const sourceOut = sideVector(edge.sourceSide);
    const targetOut = sideVector(edge.targetSide);
    const axis = fanAxis(sourcePoint, targetPoint, edge.sourceSide, edge.targetSide);
    const sourceFan = number(edge.sourceOffset, 0) + number(edge.parallelOffset, 0);
    const targetFan = number(edge.targetOffset, 0) + number(edge.parallelOffset, 0);
    return {
      sourcePoint,
      targetPoint,
      c1: {
        x: sourcePoint.x + sourceOut.x * handleDistance + axis.x * sourceFan,
        y: sourcePoint.y + sourceOut.y * handleDistance + axis.y * sourceFan,
      },
      c2: {
        x: targetPoint.x + targetOut.x * handleDistance + axis.x * targetFan,
        y: targetPoint.y + targetOut.y * handleDistance + axis.y * targetFan,
      },
    };
  }

  function path(edge = {}, options = {}) {
    const { sourcePoint, targetPoint, c1, c2 } = controlPoints(edge, options);
    return `M ${sourcePoint.x} ${sourcePoint.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${targetPoint.x} ${targetPoint.y}`;
  }

  function labelPoint(edge = {}, options = {}) {
    const { sourcePoint, targetPoint, c1, c2 } = controlPoints(edge, options);
    const t = 0.5;
    const mt = 1 - t;
    return {
      x: mt ** 3 * sourcePoint.x + 3 * mt ** 2 * t * c1.x + 3 * mt * t ** 2 * c2.x + t ** 3 * targetPoint.x,
      y: mt ** 3 * sourcePoint.y + 3 * mt ** 2 * t * c1.y + 3 * mt * t ** 2 * c2.y + t ** 3 * targetPoint.y,
    };
  }

  function snapToGrid(value, grid = 16) {
    const cleanGrid = Math.max(1, number(grid, 16));
    return Math.max(0, Math.round(number(value, 0) / cleanGrid) * cleanGrid);
  }

  function defaultNodePosition(index = 0) {
    const columns = 5;
    return { x: 36 + (index % columns) * 220, y: 36 + Math.floor(index / columns) * 156 };
  }

  function snapUpToGrid(value, grid = 16) {
    const cleanGrid = Math.max(1, number(grid, 16));
    return Math.max(0, Math.ceil(number(value, 0) / cleanGrid) * cleanGrid);
  }

  function snapDownToGrid(value, grid = 16) {
    const cleanGrid = Math.max(1, number(grid, 16));
    return Math.max(0, Math.floor(number(value, 0) / cleanGrid) * cleanGrid);
  }

  function collisionRect(position = {}, options = {}) {
    const opts = optionsWithDefaults(options);
    const x = number(position.x, 0);
    const y = number(position.y, 0);
    return {
      left: x,
      top: y,
      right: x + opts.nodeWidth + opts.collisionGapX,
      bottom: y + opts.nodeHeight + opts.collisionGapY,
    };
  }

  function rectsCollide(left, right) {
    return left.left < right.right
      && left.right > right.left
      && left.top < right.bottom
      && left.bottom > right.top;
  }

  function candidateAxisPositions(origin, placed, axis, span, grid) {
    const values = new Set([snapToGrid(origin, grid)]);
    for (const node of placed) {
      const anchor = number(node.position?.[axis], 0);
      values.add(snapUpToGrid(anchor + span, grid));
      if (anchor >= span) values.add(snapDownToGrid(anchor - span, grid));
    }
    return Array.from(values);
  }

  function placementScore(position, origin) {
    const dx = Math.abs(position.x - origin.x);
    const dy = Math.abs(position.y - origin.y);
    const changedAxes = Number(dx > 0) + Number(dy > 0);
    // Prefer a one-axis correction so the authored graph rows and columns remain recognizable.
    return dx * dx + dy * dy + Math.max(0, changedAxes - 1) * 1_000_000;
  }

  function resolveNodeCollisions(graph = {}, options = {}) {
    const opts = optionsWithDefaults(options);
    const grid = number(options.grid, 16);
    const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    if (nodes.length < 2) return graph;
    // Graph configs list executable nodes in semantic route order. Resolve later
    // nodes around earlier anchors so collision cleanup does not reorder the flow.
    const ordered = [...nodes];
    const placed = [];
    const spanX = opts.nodeWidth + opts.collisionGapX;
    const spanY = opts.nodeHeight + opts.collisionGapY;

    for (const node of ordered) {
      const origin = {
        x: number(node.position?.x, 0),
        y: number(node.position?.y, 0),
      };
      const xCandidates = candidateAxisPositions(origin.x, placed, "x", spanX, grid);
      const yCandidates = candidateAxisPositions(origin.y, placed, "y", spanY, grid);
      const candidates = [];
      for (const x of xCandidates) {
        for (const y of yCandidates) candidates.push({ x, y });
      }
      candidates.sort((left, right) => {
        const scoreDelta = placementScore(left, origin) - placementScore(right, origin);
        if (scoreDelta) return scoreDelta;
        const yDelta = Math.abs(left.y - origin.y) - Math.abs(right.y - origin.y);
        if (yDelta) return yDelta;
        return Math.abs(left.x - origin.x) - Math.abs(right.x - origin.x);
      });
      const available = candidates.find((candidate) => {
        const rect = collisionRect(candidate, opts);
        return placed.every((other) => !rectsCollide(rect, collisionRect(other.position, opts)));
      });
      node.position = available || {
        x: snapToGrid(origin.x, grid),
        y: snapUpToGrid(placed.length * spanY, grid),
      };
      placed.push(node);
    }
    return graph;
  }

  function labelRect(label = {}, gap = 0) {
    const halfGap = Math.max(0, number(gap, 0)) / 2;
    const halfWidth = Math.max(1, number(label.width, 1)) / 2 + halfGap;
    const halfHeight = Math.max(1, number(label.height, 1)) / 2 + halfGap;
    const x = number(label.x, 0);
    const y = number(label.y, 0);
    return {
      left: x - halfWidth,
      top: y - halfHeight,
      right: x + halfWidth,
      bottom: y + halfHeight,
    };
  }

  function resolveLabelCollisions(labels = [], options = {}) {
    const gap = Math.max(0, number(options.gap, 8));
    const obstacles = Array.isArray(options.obstacles) ? options.obstacles : [];
    const placedRects = [];
    return labels.map((label) => {
      const origin = { x: number(label.x, 0), y: number(label.y, 0) };
      const stepX = Math.max(24, number(label.width, 1) * 0.42 + gap);
      const stepY = Math.max(18, number(label.height, 1) + gap);
      const candidates = [];
      for (let yLevel = 0; yLevel <= 16; yLevel += 1) {
        const yOffsets = yLevel === 0 ? [0] : [-yLevel * stepY, yLevel * stepY];
        for (let xLevel = 0; xLevel <= 4; xLevel += 1) {
          const xOffsets = xLevel === 0 ? [0] : [-xLevel * stepX, xLevel * stepX];
          for (const dy of yOffsets) {
            for (const dx of xOffsets) {
              candidates.push({ x: origin.x + dx, y: origin.y + dy, distance: dx * dx + dy * dy });
            }
          }
        }
      }
      candidates.sort((left, right) => left.distance - right.distance || Math.abs(left.x - origin.x) - Math.abs(right.x - origin.x));
      const available = candidates.find((candidate) => {
        const rect = labelRect({ ...label, ...candidate }, gap);
        if (rect.left < 0 || rect.top < 0) return false;
        if (Number.isFinite(options.maxX) && rect.right > Number(options.maxX)) return false;
        if (Number.isFinite(options.maxY) && rect.bottom > Number(options.maxY)) return false;
        return obstacles.every((obstacle) => !rectsCollide(rect, obstacle))
          && placedRects.every((placed) => !rectsCollide(rect, placed));
      }) || origin;
      const resolved = { ...label, x: available.x, y: available.y };
      placedRects.push(labelRect(resolved, gap));
      return resolved;
    });
  }

  function normalizeNodePositions(graph = {}, options = {}) {
    const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    const grid = number(options.grid, 16);
    const fallbackPosition = typeof options.defaultPosition === "function" ? options.defaultPosition : defaultNodePosition;
    nodes.forEach((node, index) => {
      const fallback = fallbackPosition(index) || defaultNodePosition(index);
      const source = node.position || node.metadata?.position || fallback;
      node.position = {
        x: snapToGrid(source.x ?? fallback.x, grid),
        y: snapToGrid(source.y ?? fallback.y, grid),
      };
    });
    return resolveNodeCollisions(graph, { ...options, grid });
  }

  global.ATRRuntimeGraphGeometry = {
    portPoint,
    inferPorts,
    spread,
    assignOffsets,
    controlPoints,
    path,
    labelPoint,
    snapToGrid,
    resolveNodeCollisions,
    resolveLabelCollisions,
    normalizeNodePositions,
  };
})(window);
