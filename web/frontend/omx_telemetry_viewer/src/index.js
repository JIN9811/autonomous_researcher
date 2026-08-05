import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

const MODEL_ROOT = "/assets/robotis-omx";
const MODEL_XML_URL = "/assets/robotis-omx/omx.xml";
const ENVIRONMENT_MANIFEST_URL = "/assets/robotis-omx/scene/omx_table_layout.web.json?v=20260714-grid5mm-1";
const TELEMETRY_WS_PATH = "/ws/lerobot/joint-telemetry";
const SNAPSHOT_URL = "/api/lerobot/joint-telemetry/snapshot";
const SPECIMEN_POSE_URL = "/api/lerobot/active-robot-cam/specimen-pose";
const SPECIMEN_POSE_POLL_MS = 1000;
const MAX_HISTORY_SAMPLES = 1200;
const CAMERA_FIT_PADDING = 1.0;
const CAMERA_FIT_DISTANCE_SCALE = 1.34;
const CAMERA_FIT_VERTICAL_OFFSET_M = -0.115;
const JOINT_NAMES = ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper"];
const ACTUAL_LABEL = "Measured follower";
const TARGET_LABEL = "Policy target";
const MOTION_STATES = ["home", "moving", "grasping", "ungrasping"];
const BASE_MOTION_STATES = ["home", "moving"];
const GRIPPER_MOTION_STATES = ["grasping", "ungrasping"];
const GRASP_OUTCOME_STATES = ["idle", "pending", "success", "failed"];
const GRASP_SUCCESS_COLOR = "#22c55e";
const GRASP_FAILED_COLOR = "#ef4444";
const GRASP_ANCHOR_FORWARD_M = 0.018;
const TARGET_SUPPORT_NAME = "RightDiskAluminumTop";
const SPECIMEN_NAME = "RedSpecimenBlock";
const SPECIMEN_SUPPORT_CLEARANCE_M = 0.0005;
const WORLD_UP_AXIS = new THREE.Vector3(0, 0, 1);
const anchorWorldPosition = new THREE.Vector3();
const anchorWorldQuaternion = new THREE.Quaternion();
const parentWorldQuaternion = new THREE.Quaternion();
const desiredWorldQuaternion = new THREE.Quaternion();
const localUprightQuaternion = new THREE.Quaternion();
const anchorWorldEuler = new THREE.Euler();

const runtime = {
  sessionId: "",
  status: "idle",
  history: [],
  latestSequence: -1,
  latestActualRad: {},
  latestTargetRad: {},
  latestMotionState: {},
  artifacts: {},
  runtimeView: {},
  websocket: null,
  reconnectTimer: null,
  reconnectAttempt: 0,
  chartFrame: null,
  selectedJoint: "Joint1",
  poseMount: null,
  chartMount: null,
  viewer: null,
  viewerPromise: null,
  chart: null,
  chartResizeObserver: null,
  stableYDomains: {},
  specimenPoseFrameId: "",
  specimenPosePollTimer: null,
  specimenPoseRequestPending: false,
};

function parseVector(value, fallback = [0, 0, 0]) {
  if (!value) return [...fallback];
  const parsed = String(value).trim().split(/\s+/).map(Number);
  return parsed.length >= 3 && parsed.slice(0, 3).every(Number.isFinite) ? parsed.slice(0, 3) : [...fallback];
}

function directChildren(element, tagName) {
  return Array.from(element.children || []).filter((child) => child.tagName === tagName);
}

function parseOmxModel(xmlText) {
  const xml = new DOMParser().parseFromString(xmlText, "application/xml");
  const parserError = xml.querySelector("parsererror");
  if (parserError) throw new Error(`OMX MJCF parse failed: ${parserError.textContent || "invalid XML"}`);

  const meshAssets = new Map();
  xml.querySelectorAll("asset > mesh").forEach((mesh) => {
    const name = mesh.getAttribute("name") || "";
    const file = mesh.getAttribute("file") || "";
    if (name && file) meshAssets.set(name, { file, scale: parseVector(mesh.getAttribute("scale"), [1, 1, 1]) });
  });

  const jointAxes = new Map();
  xml.querySelectorAll("default[class]").forEach((defaults) => {
    const joint = directChildren(defaults, "joint")[0];
    if (joint) jointAxes.set(defaults.getAttribute("class"), parseVector(joint.getAttribute("axis"), [0, 0, 1]));
  });

  function bodyDescriptor(body) {
    const joint = directChildren(body, "joint")[0] || null;
    const visualMeshes = directChildren(body, "geom")
      .filter((geom) => (geom.getAttribute("class") || "visual") === "visual")
      .map((geom) => geom.getAttribute("mesh"))
      .filter(Boolean);
    const jointName = joint ? joint.getAttribute("name") || "" : "";
    const jointClass = joint ? joint.getAttribute("class") || jointName : "";
    return {
      name: body.getAttribute("name") || "body",
      position: parseVector(body.getAttribute("pos")),
      jointName,
      jointAxis: jointAxes.get(jointClass) || [0, 0, 1],
      meshes: visualMeshes,
      children: directChildren(body, "body").map(bodyDescriptor),
    };
  }

  const rootBody = directChildren(xml.querySelector("worldbody"), "body")[0];
  if (!rootBody) throw new Error("OMX MJCF worldbody has no root body");
  return { meshAssets, root: bodyDescriptor(rootBody) };
}

async function loadOmxGeometry(model) {
  const loader = new STLLoader();
  const geometries = new Map();
  await Promise.all(Array.from(model.meshAssets.entries()).map(async ([name, asset]) => {
    const geometry = await loader.loadAsync(`${MODEL_ROOT}/assets/${asset.file}`);
    geometry.scale(asset.scale[0], asset.scale[1], asset.scale[2]);
    geometry.computeVertexNormals();
    geometries.set(name, geometry);
  }));
  return geometries;
}

function buildRobotTree(descriptor, geometries, material) {
  const joints = new Map();

  function buildBody(body) {
    const group = new THREE.Group();
    group.name = body.name;
    group.position.fromArray(body.position);
    if (body.jointName) {
      joints.set(body.jointName, {
        group,
        axis: new THREE.Vector3(...body.jointAxis).normalize(),
      });
    }
    body.meshes.forEach((name) => {
      const geometry = geometries.get(name);
      if (!geometry) return;
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = material.opacity >= 1;
      mesh.receiveShadow = material.opacity >= 1;
      group.add(mesh);
    });
    body.children.forEach((child) => group.add(buildBody(child)));
    return group;
  }

  return { root: buildBody(descriptor), joints };
}

function createGraspAnchor(robot) {
  const gripper = robot.joints.get("Gripper");
  const mimic = robot.joints.get("Gripper_mimic");
  if (!gripper || !mimic || !gripper.group.parent || gripper.group.parent !== mimic.group.parent) return null;
  const graspAnchor = new THREE.Group();
  graspAnchor.name = "measured-gripper-grasp-anchor";
  graspAnchor.position.copy(gripper.group.position).add(mimic.group.position).multiplyScalar(0.5);
  graspAnchor.position.x += GRASP_ANCHOR_FORWARD_M;
  gripper.group.parent.add(graspAnchor);
  return graspAnchor;
}

function createGripperOutcomeGlow(robot) {
  const material = new THREE.MeshBasicMaterial({
    color: new THREE.Color(GRASP_SUCCESS_COLOR),
    transparent: true,
    opacity: 0.72,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  });
  const meshes = [];
  ["Gripper", "Gripper_mimic"].forEach((jointName) => {
    const joint = robot.joints.get(jointName);
    if (!joint) return;
    const sources = [];
    joint.group.traverse((object) => {
      if (object.isMesh) sources.push(object);
    });
    sources.forEach((source) => {
      const overlay = new THREE.Mesh(source.geometry, material);
      overlay.name = `${jointName}-grasp-outcome-overlay`;
      overlay.position.copy(source.position);
      overlay.quaternion.copy(source.quaternion);
      overlay.scale.copy(source.scale).multiplyScalar(1.025);
      overlay.visible = false;
      overlay.renderOrder = 6;
      source.parent.add(overlay);
      meshes.push(overlay);
    });
  });
  return { material, meshes, status: "idle" };
}

function environmentGeometry(item) {
  if (item.primitive === "box") {
    return new THREE.BoxGeometry(...item.size.map(Number));
  }
  if (item.primitive === "cylinder") {
    const geometry = new THREE.CylinderGeometry(Number(item.radius), Number(item.radius), Number(item.height), 32);
    geometry.rotateX(Math.PI / 2);
    return geometry;
  }
  return null;
}

function surfaceGridMaterial(wireframe) {
  return new THREE.LineBasicMaterial({
    color: new THREE.Color(wireframe.color || "#8fb7cc"),
    transparent: true,
    opacity: Number(wireframe.opacity ?? 0.3),
    depthWrite: false,
  });
}

function boundedDivisions(length, spacing, maximum) {
  if (!(length > 0) || !(spacing > 0)) return 0;
  return Math.min(Math.max(Math.ceil(length / spacing), 1), maximum);
}

function appendLine(positions, start, end) {
  positions.push(...start, ...end);
}

function buildBoxSurfaceGrid(item, wireframe) {
  const size = (item.size || []).map(Number);
  const spacing = Number(wireframe.spacing_m);
  const maximum = Number(wireframe.max_divisions || 180);
  const offset = Number(wireframe.surface_offset_m || 0.00015);
  if (size.length < 3 || size.some((value) => !(value > 0)) || !(spacing > 0)) return null;
  const [width, depth, height] = size;
  const [halfWidth, halfDepth, halfHeight] = size.map((value) => value / 2);
  const positions = [];

  const xDivisions = boundedDivisions(width, spacing, maximum);
  const yDivisions = boundedDivisions(depth, spacing, maximum);
  const zDivisions = boundedDivisions(height, spacing, maximum);
  const sample = (index, count, length, half) => Math.min(index * spacing, length) - half;

  for (const z of [-halfHeight - offset, halfHeight + offset]) {
    for (let index = 0; index <= xDivisions; index += 1) {
      const x = sample(index, xDivisions, width, halfWidth);
      appendLine(positions, [x, -halfDepth, z], [x, halfDepth, z]);
    }
    for (let index = 0; index <= yDivisions; index += 1) {
      const y = sample(index, yDivisions, depth, halfDepth);
      appendLine(positions, [-halfWidth, y, z], [halfWidth, y, z]);
    }
  }
  for (const x of [-halfWidth - offset, halfWidth + offset]) {
    for (let index = 0; index <= yDivisions; index += 1) {
      const y = sample(index, yDivisions, depth, halfDepth);
      appendLine(positions, [x, y, -halfHeight], [x, y, halfHeight]);
    }
    for (let index = 0; index <= zDivisions; index += 1) {
      const z = sample(index, zDivisions, height, halfHeight);
      appendLine(positions, [x, -halfDepth, z], [x, halfDepth, z]);
    }
  }
  for (const y of [-halfDepth - offset, halfDepth + offset]) {
    for (let index = 0; index <= xDivisions; index += 1) {
      const x = sample(index, xDivisions, width, halfWidth);
      appendLine(positions, [x, y, -halfHeight], [x, y, halfHeight]);
    }
    for (let index = 0; index <= zDivisions; index += 1) {
      const z = sample(index, zDivisions, height, halfHeight);
      appendLine(positions, [-halfWidth, y, z], [halfWidth, y, z]);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const lines = new THREE.LineSegments(geometry, surfaceGridMaterial(wireframe));
  lines.name = "environment-surface-grid-5mm-box";
  lines.renderOrder = 2;
  return lines;
}

function buildCylinderSurfaceGrid(item, wireframe) {
  const radius = Number(item.radius);
  const height = Number(item.height);
  const spacing = Number(wireframe.spacing_m);
  const maximum = Number(wireframe.max_divisions || 180);
  const offset = Number(wireframe.surface_offset_m || 0.00015);
  if (!(radius > 0) || !(height > 0) || !(spacing > 0)) return null;
  const radialDivisions = Math.max(12, boundedDivisions(Math.PI * 2 * radius, spacing, maximum));
  const heightDivisions = boundedDivisions(height, spacing, maximum);
  const lineRadius = radius + offset;
  const halfHeight = height / 2;
  const positions = [];

  for (let radial = 0; radial < radialDivisions; radial += 1) {
    const angle = (radial / radialDivisions) * Math.PI * 2;
    const x = Math.cos(angle) * lineRadius;
    const y = Math.sin(angle) * lineRadius;
    appendLine(positions, [x, y, -halfHeight], [x, y, halfHeight]);
  }
  for (let level = 0; level <= heightDivisions; level += 1) {
    const z = Math.min(level * spacing, height) - halfHeight;
    for (let radial = 0; radial < radialDivisions; radial += 1) {
      const angleA = (radial / radialDivisions) * Math.PI * 2;
      const angleB = ((radial + 1) / radialDivisions) * Math.PI * 2;
      appendLine(
        positions,
        [Math.cos(angleA) * lineRadius, Math.sin(angleA) * lineRadius, z],
        [Math.cos(angleB) * lineRadius, Math.sin(angleB) * lineRadius, z],
      );
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const lines = new THREE.LineSegments(geometry, surfaceGridMaterial(wireframe));
  lines.name = "environment-surface-grid-5mm-cylinder";
  lines.renderOrder = 2;
  return lines;
}

function buildEnvironmentObject(item, wireframe) {
  const material = new THREE.LineBasicMaterial({
    color: new THREE.Color(item.color || "#7894aa"),
    transparent: true,
    opacity: Number(item.opacity ?? 0.55),
    depthWrite: false,
  });
  let object;
  if (item.primitive === "circle") {
    const radius = Number(item.radius);
    const points = Array.from({ length: 48 }, (_, index) => {
      const angle = (index / 48) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
    });
    object = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points), material);
  } else {
    const geometry = environmentGeometry(item);
    if (!geometry) return null;
    object = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 20), material);
    geometry.dispose();
  }
  const group = new THREE.Group();
  group.name = item.name || "environment-object";
  group.userData.environmentItem = {
    primitive: String(item.primitive || ""),
    size: Array.isArray(item.size) ? item.size.map(Number) : null,
    radius: Number(item.radius),
    height: Number(item.height),
  };
  object.name = `${group.name}-outline`;
  object.renderOrder = 1;
  group.add(object);
  if (wireframe && item.surface_grid !== false && item.primitive === "box") {
    const surfaceGrid = buildBoxSurfaceGrid(item, wireframe);
    if (surfaceGrid) group.add(surfaceGrid);
  } else if (wireframe && item.surface_grid !== false && item.primitive === "cylinder") {
    const surfaceGrid = buildCylinderSurfaceGrid(item, wireframe);
    if (surfaceGrid) group.add(surfaceGrid);
  }
  group.position.fromArray(item.position.map(Number));
  group.rotation.z = THREE.MathUtils.degToRad(Number(item.rotation_z_deg || 0));
  return group;
}

function buildEnvironment(manifest) {
  const environmentGroup = new THREE.Group();
  environmentGroup.name = "omx-table-layout-wireframe";
  const grid = buildEnvironmentGrid(manifest.grid);
  if (grid) environmentGroup.add(grid);
  (manifest.objects || []).forEach((item) => {
    const object = buildEnvironmentObject(item, manifest.wireframe);
    if (object) environmentGroup.add(object);
  });
  return environmentGroup;
}

function buildGridLines(grid, major) {
  const origin = (grid.origin || [0, 0, 0]).map(Number);
  const size = (grid.size || [0, 0]).map(Number);
  const spacing = Number(grid.spacing_m);
  const majorSpacing = Number(grid.major_spacing_m);
  if (!(spacing > 0) || !(majorSpacing >= spacing) || size.length < 2) return null;
  const positions = [];
  const xSteps = Math.round(size[0] / spacing);
  const ySteps = Math.round(size[1] / spacing);
  const isMajor = (value) => Math.abs((value / majorSpacing) - Math.round(value / majorSpacing)) < 1e-6;
  for (let index = 0; index <= xSteps; index += 1) {
    const xOffset = Math.min(index * spacing, size[0]);
    if (isMajor(xOffset) !== major) continue;
    positions.push(origin[0] + xOffset, origin[1], origin[2], origin[0] + xOffset, origin[1] + size[1], origin[2]);
  }
  for (let index = 0; index <= ySteps; index += 1) {
    const yOffset = Math.min(index * spacing, size[1]);
    if (isMajor(yOffset) !== major) continue;
    positions.push(origin[0], origin[1] + yOffset, origin[2], origin[0] + size[0], origin[1] + yOffset, origin[2]);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.LineBasicMaterial({
    color: new THREE.Color(major ? grid.major_color : grid.minor_color),
    transparent: true,
    opacity: Number(major ? grid.major_opacity : grid.minor_opacity),
    depthWrite: false,
  });
  const lines = new THREE.LineSegments(geometry, material);
  lines.name = major ? "environment-grid-major-50mm" : "environment-grid-minor-5mm";
  return lines;
}

function buildEnvironmentGrid(grid) {
  if (!grid || typeof grid !== "object" || grid.visible === false) return null;
  const group = new THREE.Group();
  group.name = "environment-grid-5mm";
  const minor = buildGridLines(grid, false);
  const major = buildGridLines(grid, true);
  if (minor) group.add(minor);
  if (major) group.add(major);
  return group;
}

function specimenObject(viewer = runtime.viewer) {
  return viewer && viewer.scene ? viewer.scene.getObjectByName(SPECIMEN_NAME) : null;
}

function settleSpecimenOnSupport(viewer, specimen) {
  if (!viewer || !viewer.environmentGroup || !specimen) return false;
  const support = viewer.environmentGroup.getObjectByName(TARGET_SUPPORT_NAME);
  if (!support) return false;
  const supportData = support.userData.environmentItem || {};
  const specimenData = specimen.userData.environmentItem || {};
  const radius = Number(supportData.radius);
  const supportHeight = Number(supportData.height);
  const specimenSize = Array.isArray(specimenData.size) ? specimenData.size : [];
  const specimenHalfHeight = Number(specimenSize[2]) / 2;
  if (!(radius > 0) || !(supportHeight > 0) || !(specimenHalfHeight > 0)) return false;

  const dx = specimen.position.x - support.position.x;
  const dy = specimen.position.y - support.position.y;
  if (Math.hypot(dx, dy) > radius) return false;
  const supportTop = support.position.z + (supportHeight / 2);
  specimen.position.z = Math.max(
    specimen.position.z,
    supportTop + specimenHalfHeight + SPECIMEN_SUPPORT_CLEARANCE_M,
  );
  return true;
}

function captureSpecimenOrigin(viewer, specimen) {
  const state = viewer && viewer.specimenGraspState;
  if (!state || !specimen || !specimen.parent) return false;
  state.original = {
    parent: specimen.parent,
    position: specimen.position.clone(),
    quaternion: specimen.quaternion.clone(),
    scale: specimen.scale.clone(),
  };
  return true;
}

function restoreSpecimenOrigin(viewer = runtime.viewer) {
  const state = viewer && viewer.specimenGraspState;
  const specimen = specimenObject(viewer);
  if (!state || !state.original || !specimen) return false;
  const parent = state.original.parent || viewer.environmentGroup;
  parent.add(specimen);
  specimen.position.copy(state.original.position);
  specimen.quaternion.copy(state.original.quaternion);
  specimen.scale.copy(state.original.scale);
  state.held = false;
  return true;
}

function setGripperOutcomeGlow(status, viewer = runtime.viewer) {
  const glow = viewer && viewer.gripperOutcomeGlow;
  if (!glow) return false;
  const visible = status === "success" || status === "failed";
  glow.status = visible ? status : "idle";
  glow.material.color.set(status === "failed" ? GRASP_FAILED_COLOR : GRASP_SUCCESS_COLOR);
  glow.meshes.forEach((mesh) => { mesh.visible = visible; });
  return visible;
}

function attachSpecimenToGripper(viewer = runtime.viewer) {
  const state = viewer && viewer.specimenGraspState;
  const specimen = specimenObject(viewer);
  const graspAnchor = viewer && viewer.graspAnchor;
  if (!state || !specimen || !graspAnchor || !viewer.environmentGroup) return false;
  if (!state.original) captureSpecimenOrigin(viewer, specimen);
  viewer.environmentGroup.add(specimen);
  specimen.scale.copy(state.original ? state.original.scale : new THREE.Vector3(1, 1, 1));
  state.held = true;
  return syncHeldSpecimenPose(viewer);
}

function syncHeldSpecimenPose(viewer = runtime.viewer) {
  const state = viewer && viewer.specimenGraspState;
  const specimen = specimenObject(viewer);
  const graspAnchor = viewer && viewer.graspAnchor;
  if (!state || !state.held || !specimen || !graspAnchor || !viewer.environmentGroup) return false;

  viewer.scene.updateMatrixWorld(true);
  graspAnchor.getWorldPosition(anchorWorldPosition);
  graspAnchor.getWorldQuaternion(anchorWorldQuaternion);
  const yaw = anchorWorldEuler.setFromQuaternion(anchorWorldQuaternion, "ZYX").z;
  desiredWorldQuaternion.setFromAxisAngle(WORLD_UP_AXIS, yaw);
  viewer.environmentGroup.getWorldQuaternion(parentWorldQuaternion);
  localUprightQuaternion.copy(parentWorldQuaternion).invert();
  localUprightQuaternion.multiply(desiredWorldQuaternion);

  if (specimen.parent !== viewer.environmentGroup) viewer.environmentGroup.add(specimen);
  viewer.environmentGroup.worldToLocal(anchorWorldPosition);
  specimen.position.copy(anchorWorldPosition);
  specimen.quaternion.copy(localUprightQuaternion);
  specimen.scale.copy(state.original ? state.original.scale : specimen.scale);
  return true;
}

function releaseSpecimenFromGripper(viewer = runtime.viewer) {
  const state = viewer && viewer.specimenGraspState;
  const specimen = specimenObject(viewer);
  if (!state || !state.held || !specimen || !viewer.environmentGroup) return false;
  syncHeldSpecimenPose(viewer);
  state.held = false;
  settleSpecimenOnSupport(viewer, specimen);
  state.releasedAttemptIndex = state.attemptIndex;
  return true;
}

function resetSpecimenGraspVisualization(viewer = runtime.viewer) {
  const state = viewer && viewer.specimenGraspState;
  if (!state) return;
  if (state.held) releaseSpecimenFromGripper(viewer);
  state.attemptIndex = null;
  state.releasedAttemptIndex = null;
  state.original = null;
  state.poseLocked = false;
  setGripperOutcomeGlow("idle", viewer);
}

function applySpecimenGraspVisualization(outcome, measuredMotion, viewer = runtime.viewer) {
  const state = viewer && viewer.specimenGraspState;
  const specimen = specimenObject(viewer);
  if (!state || !specimen) return false;
  const value = outcome && typeof outcome === "object" ? outcome : {};
  const status = GRASP_OUTCOME_STATES.includes(value.status) ? value.status : "idle";
  const attemptIndex = Number.isFinite(Number(value.attempt_index)) ? Number(value.attempt_index) : null;
  const gripperState = String((measuredMotion && measuredMotion.gripper_state) || "idle");

  if (status === "pending" && attemptIndex !== state.attemptIndex) {
    if (state.held) releaseSpecimenFromGripper(viewer);
    state.attemptIndex = attemptIndex;
    state.releasedAttemptIndex = null;
    state.original = null;
    captureSpecimenOrigin(viewer, specimen);
    state.poseLocked = true;
    attachSpecimenToGripper(viewer);
    setGripperOutcomeGlow("idle", viewer);
    return true;
  }

  if ((status === "success" || status === "failed") && attemptIndex !== state.attemptIndex) {
    state.attemptIndex = attemptIndex;
    state.releasedAttemptIndex = null;
    state.original = null;
    captureSpecimenOrigin(viewer, specimen);
    state.poseLocked = true;
  }

  if (status === "success") {
    if (gripperState === "ungrasping") {
      releaseSpecimenFromGripper(viewer);
      setGripperOutcomeGlow("idle", viewer);
      return true;
    }
    if (!state.held && state.releasedAttemptIndex !== state.attemptIndex) {
      attachSpecimenToGripper(viewer);
    }
    setGripperOutcomeGlow(state.held ? "success" : "idle", viewer);
    return true;
  }

  if (status === "failed") {
    restoreSpecimenOrigin(viewer);
    setGripperOutcomeGlow("failed", viewer);
    return true;
  }

  if (status === "idle") {
    setGripperOutcomeGlow("idle", viewer);
  }
  return false;
}

function applyRecordingSpecimenPose(pose) {
  if (!runtime.viewer || !runtime.viewer.environmentGroup || !pose || pose.schema !== "specimen_pose.v1") return false;
  if (runtime.viewer.specimenGraspState && runtime.viewer.specimenGraspState.poseLocked) return false;
  const frameId = String(pose.frame_id || pose.timestamp || "");
  if (frameId && frameId === runtime.specimenPoseFrameId) return false;
  const world = pose.position_isaac_world_mm;
  const x = Number(world && world.x);
  const y = Number(world && world.y);
  const z = Number(world && world.z);
  if (![x, y, z].every(Number.isFinite)) return false;
  const specimen = runtime.viewer.environmentGroup.getObjectByName("RedSpecimenBlock");
  if (!specimen) return false;
  specimen.position.set(x / 1000, y / 1000, z / 1000);
  settleSpecimenOnSupport(runtime.viewer, specimen);
  const yaw = Number(pose.orientation_deg && pose.orientation_deg.yaw);
  if (Number.isFinite(yaw)) specimen.rotation.z = THREE.MathUtils.degToRad(yaw);
  runtime.specimenPoseFrameId = frameId;
  return true;
}

async function pollRecordingSpecimenPose() {
  if (runtime.specimenPoseRequestPending || !runtime.poseMount || !runtime.poseMount.isConnected) return;
  runtime.specimenPoseRequestPending = true;
  try {
    const response = await fetch(SPECIMEN_POSE_URL, { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    applyRecordingSpecimenPose(payload.pose);
  } catch (_error) {
    // Pose evidence is optional; keep the last validated scene position.
  } finally {
    runtime.specimenPoseRequestPending = false;
  }
}

function startSpecimenPosePolling() {
  if (runtime.specimenPosePollTimer) return;
  pollRecordingSpecimenPose();
  runtime.specimenPosePollTimer = window.setInterval(pollRecordingSpecimenPose, SPECIMEN_POSE_POLL_MS);
}

function stopSpecimenPosePolling() {
  if (runtime.specimenPosePollTimer) window.clearInterval(runtime.specimenPosePollTimer);
  runtime.specimenPosePollTimer = null;
}

async function loadEnvironmentManifest() {
  const response = await fetch(ENVIRONMENT_MANIFEST_URL, { cache: "force-cache" });
  if (!response.ok) throw new Error(`OMX environment HTTP ${response.status}`);
  const manifest = await response.json();
  if (manifest.schema !== "atr.omx_web_scene.v1" || !Array.isArray(manifest.objects)) {
    throw new Error("OMX environment manifest is invalid");
  }
  return manifest;
}

function applyRobotAnchor(robot, anchor) {
  robot.root.position.fromArray((anchor.position || [0, 0, 0]).map(Number));
  robot.root.rotation.z = THREE.MathUtils.degToRad(Number(anchor.rotation_z_deg || 0));
}

function applyJointRadians(robot, values) {
  JOINT_NAMES.forEach((jointName) => {
    const joint = robot.joints.get(jointName);
    const value = Number(values && values[jointName]);
    if (joint && Number.isFinite(value)) joint.group.setRotationFromAxisAngle(joint.axis, value);
  });
  const mimic = robot.joints.get("Gripper_mimic");
  const gripper = Number(values && values.Gripper);
  if (mimic && Number.isFinite(gripper)) mimic.group.setRotationFromAxisAngle(mimic.axis, -gripper);
}

function interpolateJointMap(current, target, alpha) {
  JOINT_NAMES.forEach((name) => {
    const next = Number(target && target[name]);
    if (!Number.isFinite(next)) return;
    const previous = Number(current[name]);
    current[name] = Number.isFinite(previous) ? previous + ((next - previous) * alpha) : next;
  });
}

function setPoseStatus(text, tone = "idle") {
  document.querySelectorAll("[data-atr-robot-pose-status]").forEach((element) => {
    element.textContent = text;
    element.dataset.tone = tone;
  });
}

function setTrackingStatus(text, tone = "idle") {
  document.querySelectorAll("[data-atr-policy-status]").forEach((element) => {
    element.textContent = text;
    element.dataset.tone = tone;
  });
}

async function createViewer() {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#091321");
  const camera = new THREE.PerspectiveCamera(38, 1, 0.005, 10);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.HemisphereLight(0xe8f4ff, 0x111827, 2.6));
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.2);
  keyLight.position.set(0.4, -0.35, 0.7);
  keyLight.castShadow = true;
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0x7dd3fc, 1.4);
  fillLight.position.set(-0.35, 0.45, 0.25);
  scene.add(fillLight);

  const [xmlText, environmentManifest] = await Promise.all([
    fetch(MODEL_XML_URL, { cache: "force-cache" }).then((response) => {
      if (!response.ok) throw new Error(`OMX MJCF HTTP ${response.status}`);
      return response.text();
    }),
    loadEnvironmentManifest().catch(() => null),
  ]);
  const model = parseOmxModel(xmlText);
  const geometries = await loadOmxGeometry(model);
  const measuredMaterial = new THREE.MeshStandardMaterial({ color: 0xdce7ef, roughness: 0.58, metalness: 0.18 });
  const targetMaterial = new THREE.MeshStandardMaterial({
    color: 0x38bdf8,
    roughness: 0.35,
    metalness: 0.05,
    transparent: true,
    opacity: 0.24,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const measuredRobot = buildRobotTree(model.root, geometries, measuredMaterial);
  const policyTargetGhost = buildRobotTree(model.root, geometries, targetMaterial);
  const graspAnchor = createGraspAnchor(measuredRobot);
  const gripperOutcomeGlow = createGripperOutcomeGlow(measuredRobot);
  const robotAnchor = environmentManifest && environmentManifest.robot_anchor;
  if (robotAnchor) {
    applyRobotAnchor(measuredRobot, robotAnchor);
    applyRobotAnchor(policyTargetGhost, robotAnchor);
  }
  policyTargetGhost.root.visible = false;
  policyTargetGhost.root.traverse((object) => { object.renderOrder = 3; });
  scene.add(measuredRobot.root, policyTargetGhost.root);

  let environmentGroup = null;
  if (environmentManifest) {
    environmentGroup = buildEnvironment(environmentManifest);
    scene.add(environmentGroup);
  } else {
    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(0.34, 64),
      new THREE.MeshStandardMaterial({ color: 0x101e31, roughness: 0.92, metalness: 0.02 }),
    );
    floor.receiveShadow = true;
    floor.position.z = -0.002;
    scene.add(floor);
  }

  const bounds = new THREE.Box3().setFromObject(measuredRobot.root);
  if (environmentGroup) bounds.expandByObject(environmentGroup);
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z, 0.25);
  const fitTarget = center.clone().add(new THREE.Vector3(0.03, 0, CAMERA_FIT_VERTICAL_OFFSET_M));
  const fitDirection = new THREE.Vector3(1.25, -1.65, 1.1).normalize();

  function zoomToFit() {
    controls.target.copy(fitTarget);
    camera.position.copy(fitTarget).addScaledVector(
      fitDirection,
      radius * CAMERA_FIT_DISTANCE_SCALE * CAMERA_FIT_PADDING,
    );
    camera.zoom = 1;
    camera.near = Math.max(0.001, radius / 100);
    camera.far = radius * 30;
    camera.updateProjectionMatrix();
    controls.update();
  }

  const currentActual = {};
  const currentTarget = {};
  let animationFrame = null;
  let active = false;
  let initialFitApplied = false;

  function resize() {
    if (!runtime.poseMount) return;
    const width = Math.max(320, runtime.poseMount.clientWidth || 320);
    const height = Math.max(260, runtime.poseMount.clientHeight || 260);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function frame() {
    if (!active) return;
    interpolateJointMap(currentActual, runtime.latestActualRad, 0.28);
    interpolateJointMap(currentTarget, runtime.latestTargetRad, 0.28);
    applyJointRadians(measuredRobot, currentActual);
    applyJointRadians(policyTargetGhost, currentTarget);
    syncHeldSpecimenPose();
    policyTargetGhost.root.visible = Object.keys(runtime.latestTargetRad || {}).length > 0;
    controls.update();
    renderer.render(scene, camera);
    animationFrame = window.requestAnimationFrame(frame);
  }

  function start() {
    if (active) return;
    active = true;
    resize();
    if (!initialFitApplied) {
      zoomToFit();
      initialFitApplied = true;
    }
    startSpecimenPosePolling();
    frame();
  }

  function pause() {
    active = false;
    stopSpecimenPosePolling();
    if (animationFrame) window.cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }

  const resizeObserver = new ResizeObserver(resize);
  return {
    renderer,
    scene,
    camera,
    controls,
    environmentGroup,
    measuredRobot,
    policyTargetGhost,
    graspAnchor,
    gripperOutcomeGlow,
    specimenGraspState: {
      held: false,
      attemptIndex: null,
      releasedAttemptIndex: null,
      original: null,
      poseLocked: false,
    },
    resizeObserver,
    start,
    pause,
    resize,
    zoomToFit,
  };
}

async function ensureViewer() {
  if (runtime.viewer) return runtime.viewer;
  if (!runtime.viewerPromise) {
    runtime.viewerPromise = createViewer()
      .then((viewer) => {
        runtime.viewer = viewer;
        return viewer;
      })
      .finally(() => {
        runtime.viewerPromise = null;
      });
  }
  return runtime.viewerPromise;
}

async function hydratePoseViewer(mount) {
  runtime.poseMount = mount;
  setPoseStatus(runtime.viewer ? runtime.status : "loading model", runtime.viewer ? runtime.status : "loading");
  try {
    const viewer = await ensureViewer();
    if (runtime.poseMount !== mount || !mount.isConnected) return;
    if (viewer.renderer.domElement.parentElement !== mount) {
      mount.replaceChildren(viewer.renderer.domElement);
    }
    viewer.resizeObserver.disconnect();
    viewer.resizeObserver.observe(mount);
    viewer.start();
    applySpecimenGraspVisualization(
      runtime.latestMotionState.grasp_outcome || null,
      runtime.latestMotionState.measured || null,
      viewer,
    );
    setPoseStatus(runtime.status === "live" ? "live follower telemetry" : runtime.status, runtime.status);
  } catch (error) {
    mount.textContent = "OMX model unavailable";
    setPoseStatus(String(error && error.message ? error.message : error), "failed");
  }
}

function chartOption() {
  const joint = runtime.selectedJoint;
  const originElapsed = Number(runtime.history[0] && runtime.history[0].elapsed_s) || 0;
  const actual = runtime.history.map((sample) => [normalizedElapsed(sample, originElapsed), sample.actual_source && sample.actual_source[joint]]);
  const target = runtime.history.map((sample) => [normalizedElapsed(sample, originElapsed), sample.target_source && sample.target_source[joint]]);
  const unit = sourceUnit(joint);
  const yDomain = stableYDomain(joint, actual, target);
  const latestElapsed = runtime.history.length ? normalizedElapsed(runtime.history[runtime.history.length - 1], originElapsed) : 1;
  return {
    backgroundColor: "#ffffff",
    animation: false,
    color: ["#2563eb", "#e87522"],
    textStyle: { color: "#1f2937", fontFamily: "Arial, sans-serif", fontSize: 12 },
    grid: { left: 74, right: 24, top: 48, bottom: 56, containLabel: false },
    legend: { top: 12, left: "center", data: [ACTUAL_LABEL, TARGET_LABEL], textStyle: { color: "#1f2937", fontSize: 12 } },
    tooltip: { trigger: "axis", valueFormatter: (value) => `${Number(value).toFixed(2)} ${unit}` },
    xAxis: {
      type: "value",
      min: 0,
      max: Math.max(1, latestElapsed),
      boundaryGap: [0, 0],
      name: "Elapsed time (s)",
      nameLocation: "middle",
      nameGap: 34,
      axisLine: { lineStyle: { color: "#374151" } },
      axisTick: { lineStyle: { color: "#374151" } },
      axisLabel: { color: "#374151" },
      splitLine: { lineStyle: { color: "#e5e7eb", type: "dashed" } },
    },
    yAxis: {
      type: "value",
      name: "LeRobot joint value",
      nameLocation: "middle",
      nameGap: 44,
      min: yDomain ? yDomain.minimum : undefined,
      max: yDomain ? yDomain.maximum : undefined,
      axisLine: { show: true, lineStyle: { color: "#374151" } },
      axisTick: { show: true, lineStyle: { color: "#374151" } },
      axisLabel: { color: "#374151", formatter: formatAxisValue },
      splitLine: { lineStyle: { color: "#e5e7eb", type: "dashed" } },
    },
    series: [
      { name: ACTUAL_LABEL, type: "line", data: actual, showSymbol: false, connectNulls: false, lineStyle: { width: 2 } },
      { name: TARGET_LABEL, type: "line", data: target, showSymbol: false, connectNulls: false, lineStyle: { width: 2 } },
    ],
  };
}

function formatAxisValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(1) : "-";
}

function normalizedElapsed(sample, originElapsed) {
  return Math.max(0, (Number(sample && sample.elapsed_s) || 0) - originElapsed);
}

function compactHistory(samples, maximum = MAX_HISTORY_SAMPLES) {
  const clean = Array.isArray(samples) ? samples : [];
  if (clean.length <= maximum) return clean;
  const targetSize = Math.max(3, Math.floor(maximum * 0.75));
  const lastIndex = clean.length - 1;
  const compacted = [];
  let previousIndex = -1;
  for (let index = 0; index < targetSize; index += 1) {
    const sourceIndex = Math.round((index * lastIndex) / (targetSize - 1));
    if (sourceIndex === previousIndex) continue;
    compacted.push(clean[sourceIndex]);
    previousIndex = sourceIndex;
  }
  if (compacted[compacted.length - 1] !== clean[lastIndex]) compacted.push(clean[lastIndex]);
  return compacted;
}

function sourceUnit(joint) {
  const latest = runtime.history[runtime.history.length - 1] || {};
  const configured = latest.source_units && latest.source_units[joint];
  if (configured) return configured;
  if (joint === "Gripper") return "%";
  if (joint === "Joint1" || joint === "Joint5") return "deg";
  return "native";
}

function stableYDomain(joint, ...series) {
  const values = series.flatMap((items) => items.map((item) => Number(item && item[1]))).filter(Number.isFinite);
  if (!values.length) return runtime.stableYDomains[joint] || null;
  const minimumValue = Math.min(...values);
  const maximumValue = Math.max(...values);
  const span = Math.max(0, maximumValue - minimumValue);
  const minimumPadding = joint === "Gripper" ? 5 : 2;
  const padding = Math.max(minimumPadding, span * 0.1);
  const candidate = {
    minimum: Math.floor((minimumValue - padding) * 10) / 10,
    maximum: Math.ceil((maximumValue + padding) * 10) / 10,
  };
  const existing = runtime.stableYDomains[joint];
  runtime.stableYDomains[joint] = existing
    ? {
        minimum: Math.min(existing.minimum, candidate.minimum),
        maximum: Math.max(existing.maximum, candidate.maximum),
      }
    : candidate;
  return runtime.stableYDomains[joint];
}

function formatNativeValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "-";
}

function setNodeTextIfChanged(node, value) {
  if (!node) return false;
  const text = String(value);
  if (node.textContent === text) return false;
  node.textContent = text;
  return true;
}

function runtimeDisplayValue(value, field = "") {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (field === "elapsed_s" && Number.isFinite(number)) return `${number.toFixed(1)} s`;
  if (field === "duration_s" && Number.isFinite(number)) return `${number.toFixed(1)} s`;
  if (field.endsWith("latency_s") && Number.isFinite(number)) return `${number.toFixed(2)} s`;
  if (field === "effective_action_rate_hz" && Number.isFinite(number)) return `${number.toFixed(1)} Hz`;
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function applyRuntimeFields(section, values) {
  const clean = values && typeof values === "object" ? values : {};
  document.querySelectorAll(`[data-atr-runtime-field^="${section}."]`).forEach((node) => {
    const key = String(node.dataset.atrRuntimeField || "").split(".").slice(1).join(".");
    setNodeTextIfChanged(node, runtimeDisplayValue(clean[key], key));
  });
}

function applyRuntimeExecution(execution) {
  applyRuntimeFields("execution", execution);
}

function applyRuntimeInterlocks(interlocks) {
  const gates = new Map((Array.isArray(interlocks) ? interlocks : []).map((gate) => [String(gate.id || ""), gate]));
  document.querySelectorAll("[data-atr-runtime-gate]").forEach((row) => {
    const gate = gates.get(String(row.dataset.atrRuntimeGate || "")) || {};
    const status = String(gate.status || "unknown");
    row.dataset.status = status;
    setNodeTextIfChanged(row.querySelector("strong"), status);
    setNodeTextIfChanged(row.querySelector("small"), gate.reason || gate.source || "");
  });
}

function applyCompletionVerification(completion) {
  const value = completion && typeof completion === "object" ? completion : {};
  const steps = new Map((Array.isArray(value.steps) ? value.steps : []).map((step) => [String(step.id || ""), step]));
  const currentStep = String(value.current_step || "");
  document.querySelectorAll("[data-atr-runtime-step]").forEach((row) => {
    const step = steps.get(String(row.dataset.atrRuntimeStep || "")) || {};
    let status = String(step.status || "waiting");
    if (status === "waiting" && row.dataset.atrRuntimeStep === currentStep) status = "active";
    row.dataset.status = status;
    setNodeTextIfChanged(row.querySelector("strong"), status);
    const evidence = step.evidence_path || step.reason || (step.sequence ? `sequence ${step.sequence}` : "");
    setNodeTextIfChanged(row.querySelector("small"), evidence);
  });
}

function applyRunResult(result) {
  const value = result && typeof result === "object" ? result : {};
  document.querySelectorAll("[data-atr-runtime-result]").forEach((container) => {
    const status = String(value.status || "not_started").toLowerCase();
    container.dataset.status = status;
    setNodeTextIfChanged(container.querySelector("[data-atr-runtime-result-status]"), status.replaceAll("_", " ").toUpperCase());
    setNodeTextIfChanged(container.querySelector("[data-atr-runtime-result-terminal]"), value.terminal ? "terminal state" : "live state");
  });
  applyRuntimeFields("result", value);
}

function applyMetricDonut(kind, metric) {
  const value = metric && typeof metric === "object" ? metric : {};
  const attempts = Math.max(0, Number(value.attempt_count) || 0);
  const rate = attempts > 0 && Number.isFinite(Number(value.success_rate))
    ? Math.max(0, Math.min(1, Number(value.success_rate)))
    : 0;
  document.querySelectorAll(`[data-atr-runtime-donut="${kind}"]`).forEach((donut) => {
    donut.style.setProperty("--rate", `${rate * 100}%`);
  });
  document.querySelectorAll(`[data-atr-${kind}-success-rate]`).forEach((node) => {
    setNodeTextIfChanged(node, attempts > 0 ? `${Math.round(rate * 100)}%` : "—");
  });
  ["attempt_count", "completed_count", "success_count", "failed_count", "pending_count"].forEach((field) => {
    const attribute = `[data-atr-${kind}-${field.replaceAll("_", "-")}]`;
    document.querySelectorAll(attribute).forEach((node) => setNodeTextIfChanged(node, Math.max(0, Number(value[field]) || 0)));
  });
}

function applyRunMetrics(metrics) {
  const value = metrics && typeof metrics === "object" ? metrics : {};
  applyMetricDonut("task", value.task_cycle);
  applyMetricDonut("grasp", value.grasp);
  applyRuntimeFields("metrics", value);
}

function applyRuntimeView(view) {
  runtime.runtimeView = view && typeof view === "object" ? view : {};
  applyRuntimeExecution(runtime.runtimeView.execution);
  applyRuntimeInterlocks(runtime.runtimeView.interlocks);
  applyCompletionVerification(runtime.runtimeView.completion);
  applyRunResult(runtime.runtimeView.result);
  applyRunMetrics(runtime.runtimeView.metrics);
}

function normalizedMotionAxes(annotation) {
  const value = annotation && typeof annotation === "object" ? annotation : {};
  const legacy = MOTION_STATES.includes(value.state) ? value.state : "";
  const baseState = BASE_MOTION_STATES.includes(value.base_state)
    ? value.base_state
    : BASE_MOTION_STATES.includes(legacy) ? legacy : "";
  const gripperState = GRIPPER_MOTION_STATES.includes(value.gripper_state)
    ? value.gripper_state
    : GRIPPER_MOTION_STATES.includes(legacy) ? legacy : "idle";
  return { baseState, gripperState };
}

function motionAnnotationLabel(annotation) {
  const { baseState, gripperState } = normalizedMotionAxes(annotation);
  const text = [baseState, gripperState !== "idle" ? gripperState : ""].filter(Boolean).join(" + ") || "waiting";
  return {
    text,
    state: gripperState !== "idle" ? gripperState : (baseState || "waiting"),
  };
}

function applyRobotMotionLabel(annotation) {
  const label = motionAnnotationLabel(annotation);
  document.querySelectorAll("[data-atr-robot-motion-state]").forEach((element) => {
    element.textContent = label.text;
    element.dataset.state = label.state;
  });
}

function clampedPercent(value) {
  return Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100);
}

function applyMotionChannel(channel, annotation) {
  const activeClass = channel === "policy" ? "is-policy" : "is-measured";
  const value = annotation && typeof annotation === "object" ? annotation : {};
  const { baseState, gripperState } = normalizedMotionAxes(value);
  const activeStates = new Set([baseState, gripperState].filter((state) => MOTION_STATES.includes(state)));
  const baseConfidence = clampedPercent(value.base_confidence ?? value.confidence);
  const gripperConfidence = clampedPercent(value.gripper_confidence);
  const currentText = motionAnnotationLabel(value).text;
  const confidenceText = gripperState !== "idle"
    ? `${baseConfidence}% / ${gripperConfidence}%`
    : `${baseConfidence}%`;
  const reasonText = [
    value.base_reason || (BASE_MOTION_STATES.includes(value.state) ? value.reason : ""),
    gripperState !== "idle" ? value.gripper_reason || value.reason : "",
  ].filter(Boolean).join(" · ") || "Waiting for joint telemetry.";

  document.querySelectorAll("[data-atr-motion-state]").forEach((container) => {
    const summary = container.querySelector(`[data-atr-motion-summary="${channel}"]`);
    const current = summary && summary.querySelector("[data-atr-motion-current]");
    const confidence = summary && summary.querySelector("[data-atr-motion-confidence]");
    const reason = container.querySelector(`[data-atr-motion-reason="${channel}"]`);
    if (current) current.textContent = currentText;
    if (confidence) confidence.textContent = confidenceText;
    if (reason) reason.textContent = reasonText;
    if (summary) summary.dataset.currentState = currentText;
    container.querySelectorAll("[data-motion-state]").forEach((segment) => {
      segment.classList.toggle(activeClass, activeStates.has(segment.dataset.motionState));
    });
  });
}

function applyHomeGate(annotation) {
  const gate = annotation && annotation.home_gate;
  document.querySelectorAll("[data-atr-home-gate]").forEach((container) => {
    const status = container.querySelector("[data-atr-home-status]");
    const passed = Boolean(gate && gate.passed);
    const positionPassed = Boolean(gate && gate.position_passed);
    const statusText = passed ? "home" : positionPassed ? "stabilizing" : "outside range";
    if (status) {
      status.textContent = gate ? statusText : "waiting";
      status.dataset.tone = gate ? (passed ? "home" : "pending") : "waiting";
    }
    container.querySelectorAll("[data-home-joint]").forEach((row) => {
      const joint = row.dataset.homeJoint;
      const jointGate = gate && gate.joints && gate.joints[joint];
      const value = row.querySelector("[data-home-value]");
      if (value) value.textContent = formatNativeValue(jointGate && jointGate.value);
      row.dataset.pass = jointGate ? (jointGate.passed ? "yes" : "no") : "waiting";
    });
  });
}

function applyGraspOutcome(outcome) {
  const value = outcome && typeof outcome === "object" ? outcome : {};
  const status = GRASP_OUTCOME_STATES.includes(value.status) ? value.status : "idle";
  const reason = String(value.reason || "Waiting for a measured grasp attempt.");
  const gap = formatNativeValue(value.contact_gap);
  const threshold = formatNativeValue(value.contact_gap_threshold ?? 2.0);
  document.querySelectorAll("[data-atr-grasp-outcome]").forEach((container) => {
    container.dataset.status = status;
    const statusNode = container.querySelector("[data-atr-grasp-status]");
    const reasonNode = container.querySelector("[data-atr-grasp-reason]");
    const measuredNode = container.querySelector("[data-atr-grasp-measured]");
    const targetNode = container.querySelector("[data-atr-grasp-target]");
    const gapNode = container.querySelector("[data-atr-grasp-gap]");
    const overlapNode = container.querySelector("[data-atr-grasp-overlap]");
    setNodeTextIfChanged(statusNode, status);
    setNodeTextIfChanged(reasonNode, reason);
    setNodeTextIfChanged(measuredNode, formatNativeValue(value.measured_gripper));
    setNodeTextIfChanged(targetNode, formatNativeValue(value.policy_target_gripper));
    setNodeTextIfChanged(gapNode, `${gap} / ${threshold}`);
    setNodeTextIfChanged(overlapNode, value.transport_overlap ? "yes" : "no");
  });
}

function applyMotionState(motionState) {
  const state = motionState && typeof motionState === "object" ? motionState : {};
  runtime.latestMotionState = state;
  applyRobotMotionLabel(state.measured || null);
  applyMotionChannel("measured", state.measured || null);
  applyMotionChannel("policy", state.policy || null);
  applyHomeGate(state.measured || null);
  applyGraspOutcome(state.grasp_outcome || null);
  applySpecimenGraspVisualization(state.grasp_outcome || null, state.measured || null);
}

function scheduleChartRender() {
  if (runtime.chartFrame) return;
  runtime.chartFrame = window.requestAnimationFrame(() => {
    runtime.chartFrame = null;
    if (runtime.chart) runtime.chart.setOption(chartOption(), true);
  });
}

function hydrateTrackingChart(mount) {
  runtime.chartMount = mount;
  if (!window.echarts) {
    mount.textContent = "Chart engine unavailable";
    return;
  }
  if (runtime.chart) runtime.chart.dispose();
  runtime.chart = window.echarts.init(mount, null, { renderer: "canvas" });
  runtime.chart.setOption(chartOption(), true);
  if (runtime.chartResizeObserver) runtime.chartResizeObserver.disconnect();
  runtime.chartResizeObserver = new ResizeObserver(() => runtime.chart && runtime.chart.resize());
  runtime.chartResizeObserver.observe(mount);
}

function applyArtifacts(artifacts) {
  runtime.artifacts = artifacts && typeof artifacts === "object" ? artifacts : {};
  if (runtime.artifacts.latest_grasp_outcome) {
    applyGraspOutcome(runtime.artifacts.latest_grasp_outcome);
  }
  const linkKeys = {
    png: "plot_png_url",
    csv: "raw_csv_url",
    jsonl: "raw_jsonl_url",
    summary: "summary_json_url",
  };
  document.querySelectorAll("[data-atr-policy-artifact]").forEach((link) => {
    const url = runtime.artifacts[linkKeys[link.dataset.atrPolicyArtifact]] || "";
    if (url) {
      link.href = url;
      link.removeAttribute("aria-disabled");
      link.classList.remove("is-disabled");
    } else {
      link.removeAttribute("href");
      link.setAttribute("aria-disabled", "true");
      link.classList.add("is-disabled");
    }
  });
}

function resetSession(sessionId) {
  resetSpecimenGraspVisualization();
  runtime.sessionId = sessionId;
  runtime.history = [];
  runtime.latestSequence = -1;
  runtime.latestActualRad = {};
  runtime.latestTargetRad = {};
  runtime.latestMotionState = {};
  runtime.stableYDomains = {};
  runtime.artifacts = {};
  runtime.runtimeView = {};
  applyArtifacts({});
  applyRuntimeView({});
  applyGraspOutcome(null);
  applyRobotMotionLabel(null);
  scheduleChartRender();
}

function appendSample(sample) {
  if (!sample || sample.type !== "joint_sample") return;
  const sessionId = String(sample.session_id || "");
  if (sessionId && sessionId !== runtime.sessionId) resetSession(sessionId);
  const sequence = Number(sample.sequence);
  if (Number.isFinite(sequence) && sequence <= runtime.latestSequence) return;
  if (Number.isFinite(sequence)) runtime.latestSequence = sequence;
  runtime.latestActualRad = sample.actual_rad || {};
  runtime.latestTargetRad = sample.target_rad || {};
  runtime.history = compactHistory([...runtime.history, sample]);
  applyMotionState(sample.motion_state || {});
  runtime.status = sample.status || "live";
  setPoseStatus("live follower telemetry", "live");
  setTrackingStatus(`${runtime.history.length} samples`, "live");
  scheduleChartRender();
}

function replaceJointHistory(samples) {
  runtime.history = [];
  runtime.latestSequence = -1;
  runtime.latestActualRad = {};
  runtime.latestTargetRad = {};
  (Array.isArray(samples) ? samples : [])
    .slice()
    .sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0))
    .forEach(appendSample);
}

function consumePacket(packet) {
  if (!packet || typeof packet !== "object") return;
  const sessionId = String((packet.session && packet.session.session_id) || packet.session_id || "");
  if (sessionId && sessionId !== runtime.sessionId) resetSession(sessionId);
  runtime.status = String(packet.status || runtime.status || "idle");
  if (packet.runtime_view) applyRuntimeView(packet.runtime_view);
  if (packet.type === "joint_history") {
    replaceJointHistory(packet.samples);
  } else if (packet.type === "joint_sample") {
    appendSample(packet);
  } else if (packet.type === "telemetry_artifacts") {
    applyArtifacts(packet.artifacts || {});
    setTrackingStatus("session artifacts saved", packet.status || "complete");
  } else if (packet.type === "telemetry_state") {
    setPoseStatus(runtime.status, runtime.status);
    setTrackingStatus(runtime.status, runtime.status);
  }
}

function telemetryMountsPresent() {
  return Boolean(document.querySelector("[data-atr-robot-pose]") || document.querySelector("[data-atr-policy-tracking]"));
}

function websocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${TELEMETRY_WS_PATH}`;
}

function closeTelemetrySocket() {
  if (runtime.reconnectTimer) window.clearTimeout(runtime.reconnectTimer);
  runtime.reconnectTimer = null;
  if (runtime.websocket) {
    runtime.websocket.onclose = null;
    runtime.websocket.close();
  }
  runtime.websocket = null;
  runtime.reconnectAttempt = 0;
}

function connectTelemetrySocket() {
  if (!telemetryMountsPresent()) return;
  if (runtime.websocket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(runtime.websocket.readyState)) return;
  const socket = new WebSocket(websocketUrl());
  runtime.websocket = socket;
  socket.onopen = () => {
    runtime.reconnectAttempt = 0;
    setPoseStatus("telemetry connected", "live");
  };
  socket.onmessage = (event) => {
    try {
      consumePacket(JSON.parse(event.data));
    } catch (error) {
      setTrackingStatus("invalid telemetry packet", "failed");
    }
  };
  socket.onerror = () => setPoseStatus("telemetry connection error", "failed");
  socket.onclose = () => {
    if (runtime.websocket === socket) runtime.websocket = null;
    if (!telemetryMountsPresent()) return;
    const delay = Math.min(5000, 250 * (2 ** runtime.reconnectAttempt));
    runtime.reconnectAttempt = Math.min(runtime.reconnectAttempt + 1, 5);
    runtime.reconnectTimer = window.setTimeout(connectTelemetrySocket, delay);
  };
}

async function loadSnapshot() {
  try {
    const response = await fetch(SNAPSHOT_URL, { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    if (payload.packet) consumePacket(payload.packet);
    if (payload.artifacts) applyArtifacts(payload.artifacts);
    if (payload.runtime_view) applyRuntimeView(payload.runtime_view);
    runtime.status = payload.status || runtime.status;
  } catch (_error) {
    // The WebSocket remains authoritative; a missing initial snapshot is non-fatal.
  }
}

function bindJointSelectors() {
  document.querySelectorAll("[data-atr-joint-selector]").forEach((select) => {
    select.value = runtime.selectedJoint;
    if (select.dataset.bound === "1") return;
    select.dataset.bound = "1";
    select.addEventListener("change", () => {
      runtime.selectedJoint = JOINT_NAMES.includes(select.value) ? select.value : "Joint1";
      document.querySelectorAll("[data-atr-joint-selector]").forEach((other) => { other.value = runtime.selectedJoint; });
      scheduleChartRender();
    });
  });
}

function bindPoseFitButtons() {
  document.querySelectorAll("[data-atr-pose-fit]").forEach((button) => {
    if (button.dataset.bound === "1") return;
    button.dataset.bound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!runtime.viewer) return;
      runtime.viewer.resize();
      runtime.viewer.zoomToFit();
    });
  });
}

function hydrate() {
  const poseMount = document.querySelector("[data-atr-robot-pose]");
  const chartMount = document.querySelector("[data-atr-policy-tracking]");
  bindJointSelectors();
  bindPoseFitButtons();
  applyArtifacts(runtime.artifacts);
  applyRuntimeView(runtime.runtimeView);

  if (poseMount && poseMount !== runtime.poseMount) hydratePoseViewer(poseMount);
  else if (poseMount && runtime.viewer) runtime.viewer.start();
  if (chartMount && chartMount !== runtime.chartMount) hydrateTrackingChart(chartMount);

  if (poseMount || chartMount) {
    connectTelemetrySocket();
    if (!runtime.sessionId) loadSnapshot();
  } else {
    if (runtime.viewer) runtime.viewer.pause();
    if (runtime.chart) runtime.chart.dispose();
    runtime.chart = null;
    runtime.poseMount = null;
    runtime.chartMount = null;
    closeTelemetrySocket();
  }
}

window.ATRRobotTelemetryCards = { hydrate, disconnect: closeTelemetrySocket };

const domObserver = new MutationObserver(() => window.queueMicrotask(hydrate));
domObserver.observe(document.documentElement, { childList: true, subtree: true });
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", hydrate, { once: true });
else hydrate();
