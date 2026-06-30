#!/usr/bin/env python3
from pathlib import Path

from PIL import Image, ImageDraw
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade, Vt

try:
    from pxr import PhysxSchema
except Exception:
    PhysxSchema = None

ROOT = Path('/home/jin/autonomous_researcher/sim/robotis_omx')
OUT = ROOT / 'scene' / 'omx_table_layout.usda'
ROBOT_USD = ROOT / 'omx' / 'omx.usda'
TEXTURE_DIR = ROOT / 'scene' / 'Textures'
REDWOOD_TEXTURE = TEXTURE_DIR / 'redwood_table_grain.png'
COLLISION_SKIN_FRACTION = 0.10
COLLISION_SKIN_MIN_M = 0.0001
COLLISION_SKIN_MAX_M = 0.005


def write_redwood_texture(path):
    import math
    import random

    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1024, 1024
    rng = random.Random(1729)
    img = Image.new('RGB', (width, height), (112, 36, 16))
    pix = img.load()
    # Straight redwood-like grain: mostly parallel longitudinal bands with subtle fine variation.
    band_offsets = [rng.uniform(-0.05, 0.05) for _ in range(8)]
    for y in range(height):
        v = y / height
        broad = math.sin(v * 85.0) + 0.45 * math.sin(v * 173.0 + 0.8) + 0.25 * math.sin(v * 311.0 + 1.7)
        dark_band = 1.0 if broad < -1.05 else 0.0
        for x in range(width):
            u = x / width
            fine = math.sin(v * 760.0 + band_offsets[int(u * len(band_offsets)) % len(band_offsets)])
            pores = math.sin(u * 210.0 + v * 13.0) * 0.35
            shade = int(22 * broad + 7 * fine + 4 * pores - 18 * dark_band)
            r = max(60, min(175, 128 + shade))
            g = max(18, min(78, 39 + shade // 4))
            b = max(8, min(45, 17 + shade // 7))
            pix[x, y] = (r, g, b)
    draw = ImageDraw.Draw(img)
    # Add straight, lengthwise latewood streaks. No curved contour pattern.
    for row in range(28, height, 74):
        y = row + rng.randint(-9, 9)
        draw.line([(0, y), (width, y + rng.randint(-2, 2))], fill=(76, 20, 9), width=rng.choice([1, 2, 3]))
    for row in range(55, height, 151):
        y = row + rng.randint(-14, 14)
        draw.line([(0, y), (width, y + rng.randint(-1, 1))], fill=(168, 56, 22), width=1)
    img.save(path)


def make_material(stage, path, diffuse, roughness=0.55, metallic=0.0):
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + '/PreviewSurface')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*diffuse))
    shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(metallic)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    return mat


def make_textured_material(stage, path, texture_path, fallback_diffuse, roughness=0.55, metallic=0.0):
    mat = UsdShade.Material.Define(stage, path)
    surface = UsdShade.Shader.Define(stage, path + '/PreviewSurface')
    surface.CreateIdAttr('UsdPreviewSurface')
    surface.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*fallback_diffuse))
    surface.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(roughness)
    surface.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(metallic)

    st_reader = UsdShade.Shader.Define(stage, path + '/PrimvarReader_st')
    st_reader.CreateIdAttr('UsdPrimvarReader_float2')
    st_reader.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')

    texture = UsdShade.Shader.Define(stage, path + '/WoodTexture')
    texture.CreateIdAttr('UsdUVTexture')
    texture.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(str(texture_path))
    texture.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('sRGB')
    texture.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(st_reader.ConnectableAPI(), 'result')

    surface.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(), 'rgb')
    mat.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), 'surface')
    return mat


def bind(prim, material):
    UsdShade.MaterialBindingAPI(prim).Bind(material)


def bind_physics(prim, material):
    rel = prim.GetRelationship('material:binding:physics')
    if not rel:
        rel = prim.CreateRelationship('material:binding:physics')
    rel.SetTargets([material.GetPrim().GetPath()])


def _set_attr(prim, name, type_name, value):
    attr = prim.GetAttribute(name)
    if not attr:
        attr = prim.CreateAttribute(name, type_name)
    attr.Set(value)
    return attr


def _set_uniform_attr(prim, name, type_name, value):
    attr = prim.GetAttribute(name)
    if not attr:
        attr = prim.CreateAttribute(name, type_name, False, Sdf.VariabilityUniform)
    else:
        attr.SetVariability(Sdf.VariabilityUniform)
    attr.Set(value)
    return attr


def collision_skin_for_dimensions(dimensions):
    positive_dimensions = [float(value) for value in dimensions if float(value) > 0.0]
    if not positive_dimensions:
        return COLLISION_SKIN_MIN_M
    offset = min(positive_dimensions) * COLLISION_SKIN_FRACTION
    return max(COLLISION_SKIN_MIN_M, min(COLLISION_SKIN_MAX_M, offset))


def _ensure_api_schema(prim, api_name):
    schemas = prim.GetMetadata('apiSchemas')
    items = []
    if schemas is not None:
        try:
            items = [str(item) for item in schemas.GetAddedOrExplicitItems()]
        except Exception:
            items = []
    if api_name not in items:
        items.append(api_name)
    op = Sdf.TokenListOp()
    op.prependedItems = items
    prim.SetMetadata('apiSchemas', op)


def _apply_physx_api(prim, api_name):
    if PhysxSchema is None:
        _ensure_api_schema(prim, api_name)
        return
    try:
        getattr(PhysxSchema, api_name).Apply(prim)
    except Exception:
        _ensure_api_schema(prim, api_name)


def apply_physx_contact_tuning(
    prim,
    *,
    contact_offset=None,
    rest_offset=None,
    enable_ccd=False,
    max_depenetration_velocity=None,
):
    if contact_offset is not None or rest_offset is not None:
        _apply_physx_api(prim, 'PhysxCollisionAPI')
    if enable_ccd or max_depenetration_velocity is not None:
        _apply_physx_api(prim, 'PhysxRigidBodyAPI')
    if contact_offset is not None:
        _set_attr(prim, 'physxCollision:contactOffset', Sdf.ValueTypeNames.Float, float(contact_offset))
    if rest_offset is not None:
        _set_attr(prim, 'physxCollision:restOffset', Sdf.ValueTypeNames.Float, float(rest_offset))
    if enable_ccd:
        _set_attr(prim, 'physxRigidBody:enableCCD', Sdf.ValueTypeNames.Bool, True)
    if max_depenetration_velocity is not None:
        _set_attr(
            prim,
            'physxRigidBody:maxDepenetrationVelocity',
            Sdf.ValueTypeNames.Float,
            float(max_depenetration_velocity),
        )


def make_physics_material(
    stage,
    path,
    *,
    static_friction,
    dynamic_friction,
    restitution=0.0,
    friction_combine_mode=None,
    compliant_contact_stiffness=None,
    compliant_contact_damping=None,
):
    mat = UsdShade.Material.Define(stage, path)
    prim = mat.GetPrim()
    UsdPhysics.MaterialAPI.Apply(prim)
    _set_attr(prim, 'physics:staticFriction', Sdf.ValueTypeNames.Float, float(static_friction))
    _set_attr(prim, 'physics:dynamicFriction', Sdf.ValueTypeNames.Float, float(dynamic_friction))
    _set_attr(prim, 'physics:restitution', Sdf.ValueTypeNames.Float, float(restitution))
    if friction_combine_mode is not None or compliant_contact_stiffness is not None or compliant_contact_damping is not None:
        _apply_physx_api(prim, 'PhysxMaterialAPI')
    if friction_combine_mode is not None:
        _set_uniform_attr(prim, 'physxMaterial:frictionCombineMode', Sdf.ValueTypeNames.Token, str(friction_combine_mode))
    if compliant_contact_stiffness is not None:
        _set_attr(
            prim,
            'physxMaterial:compliantContactStiffness',
            Sdf.ValueTypeNames.Float,
            float(compliant_contact_stiffness),
        )
    if compliant_contact_damping is not None:
        _set_attr(
            prim,
            'physxMaterial:compliantContactDamping',
            Sdf.ValueTypeNames.Float,
            float(compliant_contact_damping),
        )
    return mat


def apply_static_collider(geom_prim, *, approximation='box', physics_material=None, contact_offset=None, rest_offset=None):
    """Give fixed workspace geometry a lightweight physics collision contract."""
    prim = geom_prim.GetPrim()
    UsdPhysics.CollisionAPI.Apply(prim)
    _set_attr(prim, 'physics:collisionEnabled', Sdf.ValueTypeNames.Bool, True)
    if approximation:
        _set_attr(prim, 'physics:approximation', Sdf.ValueTypeNames.Token, approximation)
    apply_physx_contact_tuning(prim, contact_offset=contact_offset, rest_offset=rest_offset)
    if physics_material is not None:
        bind_physics(prim, physics_material)
    return geom_prim


def apply_dynamic_rigid_body(
    geom_prim,
    *,
    mass_kg,
    approximation='box',
    physics_material=None,
    contact_offset=None,
    rest_offset=None,
    enable_ccd=False,
    max_depenetration_velocity=None,
    solver_position_iterations=None,
    solver_velocity_iterations=None,
    contact_report_threshold=None,
):
    """Make a movable object participate in Isaac physics without mesh-heavy collision."""
    prim = geom_prim.GetPrim()
    UsdPhysics.CollisionAPI.Apply(prim)
    UsdPhysics.RigidBodyAPI.Apply(prim)
    UsdPhysics.MassAPI.Apply(prim)
    _set_attr(prim, 'physics:collisionEnabled', Sdf.ValueTypeNames.Bool, True)
    _set_attr(prim, 'physics:rigidBodyEnabled', Sdf.ValueTypeNames.Bool, True)
    _set_attr(prim, 'physics:mass', Sdf.ValueTypeNames.Float, float(mass_kg))
    if approximation:
        _set_attr(prim, 'physics:approximation', Sdf.ValueTypeNames.Token, approximation)
    apply_physx_contact_tuning(
        prim,
        contact_offset=contact_offset,
        rest_offset=rest_offset,
        enable_ccd=enable_ccd,
        max_depenetration_velocity=max_depenetration_velocity,
    )
    if solver_position_iterations is not None:
        _apply_physx_api(prim, 'PhysxRigidBodyAPI')
        _set_attr(
            prim,
            'physxRigidBody:solverPositionIterationCount',
            Sdf.ValueTypeNames.Int,
            int(solver_position_iterations),
        )
    if solver_velocity_iterations is not None:
        _apply_physx_api(prim, 'PhysxRigidBodyAPI')
        _set_attr(
            prim,
            'physxRigidBody:solverVelocityIterationCount',
            Sdf.ValueTypeNames.Int,
            int(solver_velocity_iterations),
        )
    if contact_report_threshold is not None:
        _apply_physx_api(prim, 'PhysxContactReportAPI')
        _set_attr(
            prim,
            'physxContactReport:threshold',
            Sdf.ValueTypeNames.Float,
            float(contact_report_threshold),
        )
    if physics_material is not None:
        bind_physics(prim, physics_material)
    return geom_prim


def cube(stage, path, center, scale, material):
    prim = UsdGeom.Cube.Define(stage, path)
    prim.CreateSizeAttr(1.0)
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*center))
    xform.AddScaleOp().Set(Gf.Vec3f(*scale))
    bind(prim.GetPrim(), material)
    return prim


def cylinder(stage, path, center, radius, height, material):
    prim = UsdGeom.Cylinder.Define(stage, path)
    prim.CreateRadiusAttr(radius)
    prim.CreateHeightAttr(height)
    prim.CreateAxisAttr('Z')
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*center))
    bind(prim.GetPrim(), material)
    return prim


def textured_rect_mesh(stage, path, x_min, x_max, y_min, y_max, z, material):
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(Vt.Vec3fArray([
        Gf.Vec3f(x_min, y_min, z),
        Gf.Vec3f(x_max, y_min, z),
        Gf.Vec3f(x_max, y_max, z),
        Gf.Vec3f(x_min, y_max, z),
    ]))
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    mesh.CreateNormalsAttr(Vt.Vec3fArray([Gf.Vec3f(0, 0, 1)]))
    mesh.SetNormalsInterpolation(UsdGeom.Tokens.uniform)
    st = UsdGeom.PrimvarsAPI(mesh.GetPrim()).CreatePrimvar(
        'st', Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex
    )
    st.Set(Vt.Vec2fArray([
        Gf.Vec2f(0, 0),
        Gf.Vec2f(1, 0),
        Gf.Vec2f(1, 1),
        Gf.Vec2f(0, 1),
    ]))
    bind(mesh.GetPrim(), material)
    return mesh


def flat_circle_marker(stage, path, center, radius, material, segments=48):
    import math
    cx, cy, cz = center
    points = [Gf.Vec3f(cx, cy, cz)]
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        points.append(Gf.Vec3f(cx + radius * math.cos(a), cy + radius * math.sin(a), cz))
    indices = []
    counts = []
    for i in range(segments):
        indices.extend([0, i + 1, 1 + ((i + 1) % segments)])
        counts.append(3)
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(Vt.Vec3fArray(points))
    mesh.CreateFaceVertexCountsAttr(counts)
    mesh.CreateFaceVertexIndicesAttr(indices)
    mesh.CreateNormalsAttr(Vt.Vec3fArray([Gf.Vec3f(0, 0, 1)] * segments))
    mesh.SetNormalsInterpolation(UsdGeom.Tokens.uniform)
    bind(mesh.GetPrim(), material)
    return mesh


def main():
    write_redwood_texture(REDWOOD_TEXTURE)
    stage = Usd.Stage.CreateNew(str(OUT))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, '/World').GetPrim())
    physics_scene = UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
    physics_scene.CreateGravityDirectionAttr(Gf.Vec3f(0.0, 0.0, -1.0))
    physics_scene.CreateGravityMagnitudeAttr(9.81)
    physics_scene_prim = physics_scene.GetPrim()
    _ensure_api_schema(physics_scene_prim, 'NewtonSceneAPI')
    _ensure_api_schema(physics_scene_prim, 'PhysxSceneAPI')
    _set_attr(physics_scene_prim, 'physxScene:enableCCD', Sdf.ValueTypeNames.Bool, True)
    _set_attr(physics_scene_prim, 'physxScene:enableStabilization', Sdf.ValueTypeNames.Bool, True)
    _set_attr(physics_scene_prim, 'physxScene:bounceThresholdVelocity', Sdf.ValueTypeNames.Float, 0.01)
    _set_attr(physics_scene_prim, 'physxScene:frictionCorrelationDistance', Sdf.ValueTypeNames.Float, 0.00625)
    _set_attr(physics_scene_prim, 'physxScene:frictionOffsetThreshold', Sdf.ValueTypeNames.Float, 0.002)
    _set_uniform_attr(physics_scene_prim, 'physxScene:broadphaseType', Sdf.ValueTypeNames.Token, 'GPU')
    _set_attr(physics_scene_prim, 'physxScene:gpuFoundLostAggregatePairsCapacity', Sdf.ValueTypeNames.UInt, 8192)
    _set_attr(physics_scene_prim, 'physxScene:gpuTotalAggregatePairsCapacity', Sdf.ValueTypeNames.UInt, 8192)
    _set_uniform_attr(physics_scene_prim, 'physxScene:solverType', Sdf.ValueTypeNames.Token, 'TGS')
    _set_attr(physics_scene_prim, 'physxScene:timeStepsPerSecond', Sdf.ValueTypeNames.Int, 240)

    # Materials tuned from the supplied photo: redwood-like laminate desk, matte paper, black robot/disk.
    desk_mat = make_material(stage, '/World/Materials/desk_redwood_laminate', (0.42, 0.095, 0.040), 0.60)
    desk_texture_mat = make_textured_material(
        stage,
        '/World/Materials/desk_redwood_textured',
        REDWOOD_TEXTURE,
        (0.50, 0.10, 0.045),
        0.58,
    )
    desk_edge_mat = make_material(stage, '/World/Materials/desk_dark_redwood_edge', (0.20, 0.045, 0.022), 0.70)
    paper_mat = make_material(stage, '/World/Materials/a4_matte_white', (0.93, 0.93, 0.90), 0.78)
    disk_mat = make_material(stage, '/World/Materials/aluminum_disk', (0.72, 0.69, 0.62), 0.35, 0.15)
    black_mat = make_material(stage, '/World/Materials/dark_base', (0.02, 0.02, 0.018), 0.65)
    cube_mat = make_material(stage, '/World/Materials/red_test_cube', (0.86, 0.05, 0.04), 0.55)
    wood_physics_mat = make_physics_material(
        stage,
        '/World/Materials/wood_laminate_contact_physics',
        static_friction=0.45,
        dynamic_friction=0.35,
    )
    paper_physics_mat = make_physics_material(
        stage,
        '/World/Materials/paper_contact_physics',
        static_friction=1.1,
        dynamic_friction=0.9,
    )
    pla_physics_mat = make_physics_material(
        stage,
        '/World/Materials/pla_specimen_contact_physics',
        static_friction=1.0,
        dynamic_friction=0.8,
        friction_combine_mode='max',
        compliant_contact_stiffness=100000,
        compliant_contact_damping=1000,
    )

    # Coordinate convention: X left->right, Y front->back, Z up. Origin is front-left table-top corner.
    # Desk outer boundary follows the provided top-view drawing: 700 x 450 mm.
    table_w = 0.700
    table_d = 0.450
    table_th = 0.030

    # Robot base slot from drawing: 150 x 120 mm, front-left at x=240 mm, y=0.
    robot_slot_x_min = 0.240
    robot_slot_w = 0.150
    robot_slot_x_max = robot_slot_x_min + robot_slot_w
    robot_slot_y_min = 0.0
    robot_slot_d = 0.120
    robot_slot_y_max = robot_slot_y_min + robot_slot_d
    robot_center_x = robot_slot_x_min + robot_slot_w / 2.0
    robot_center_y = robot_slot_y_min + robot_slot_d / 2.0
    robot_base_pocket_depth = 0.020
    robot_base_pocket_floor_th = 0.004

    # Keep the table visual continuous around a real collision recess, so the lowered robot base
    # does not penetrate the tabletop collider.
    apply_static_collider(
        cube(
            stage,
            '/World/Table/TableTop',
            (table_w / 2.0, robot_slot_y_max + (table_d - robot_slot_y_max) / 2.0, -table_th / 2.0),
            (table_w, table_d - robot_slot_y_max, table_th),
            desk_mat,
        ),
        physics_material=wood_physics_mat,
    )
    apply_static_collider(
        cube(
            stage,
            '/World/Table/TableTopFrontLeft',
            (robot_slot_x_min / 2.0, robot_slot_d / 2.0, -table_th / 2.0),
            (robot_slot_x_min, robot_slot_d, table_th),
            desk_mat,
        ),
        physics_material=wood_physics_mat,
    )
    apply_static_collider(
        cube(
            stage,
            '/World/Table/TableTopFrontRight',
            (robot_slot_x_max + (table_w - robot_slot_x_max) / 2.0, robot_slot_d / 2.0, -table_th / 2.0),
            (table_w - robot_slot_x_max, robot_slot_d, table_th),
            desk_mat,
        ),
        physics_material=wood_physics_mat,
    )
    apply_static_collider(
        cube(
            stage,
            '/World/Table/RobotBasePocketFloor',
            (
                robot_center_x,
                robot_center_y,
                -robot_base_pocket_depth - robot_base_pocket_floor_th / 2.0,
            ),
            (robot_slot_w, robot_slot_d, robot_base_pocket_floor_th),
            desk_edge_mat,
        ),
        physics_material=wood_physics_mat,
    )
    textured_rect_mesh(stage, '/World/Table/TableTopRedwoodGrainSurface_Back', 0.0, table_w, robot_slot_y_max, table_d, 0.00003, desk_texture_mat)
    textured_rect_mesh(stage, '/World/Table/TableTopRedwoodGrainSurface_FrontLeft', 0.0, robot_slot_x_min, 0.0, robot_slot_y_max, 0.00003, desk_texture_mat)
    textured_rect_mesh(stage, '/World/Table/TableTopRedwoodGrainSurface_FrontRight', robot_slot_x_max, table_w, 0.0, robot_slot_y_max, 0.00003, desk_texture_mat)
    textured_rect_mesh(
        stage,
        '/World/Table/RobotBasePocketFloorRedwoodGrainSurface',
        robot_slot_x_min,
        robot_slot_x_max,
        robot_slot_y_min,
        robot_slot_y_max,
        -robot_base_pocket_depth + 0.00003,
        desk_edge_mat,
    )

    # A4 sheet from drawing: 297 x 210 mm, 40 mm behind the robot base and symmetric to robot center.
    a4_w = 0.297
    a4_h = 0.210
    a4_center_x = robot_center_x
    a4_bottom_y = 0.120 + 0.040
    paper_th = 0.00012
    apply_static_collider(
        cube(
            stage,
            '/World/Workspace/A4Sheet',
            (a4_center_x, a4_bottom_y + a4_h / 2, paper_th / 2.0),
            (a4_w, a4_h, paper_th),
            paper_mat,
        ),
        physics_material=paper_physics_mat,
        contact_offset=0.001,
        rest_offset=0.0,
    )

    # Blue corner markers visible in the photo.
    marker_mat = make_material(stage, '/World/Materials/blue_corner_marker', (0.02, 0.42, 0.90), 0.45)
    for i, (mx, my) in enumerate([
        (a4_center_x - a4_w / 2, a4_bottom_y),
        (a4_center_x + a4_w / 2, a4_bottom_y),
        (a4_center_x - a4_w / 2, a4_bottom_y + a4_h),
        (a4_center_x + a4_w / 2, a4_bottom_y + a4_h),
    ], 1):
        flat_circle_marker(stage, f'/World/Workspace/A4CornerMarker_{i}', (mx, my, paper_th + 0.00002), 0.004, marker_mat)
    flat_circle_marker(stage, '/World/Workspace/A4CenterMarker', (a4_center_x, a4_bottom_y + a4_h / 2, paper_th + 0.00002), 0.004, marker_mat)

    # Robot sits in the front slot ahead of the A4 sheet. Use the robot-only USD, not the scene USD.
    robot_anchor = UsdGeom.Xform.Define(stage, '/World/Robot')
    robot_anchor.GetPrim().GetReferences().AddReference(str(ROBOT_USD), '/omx')
    robot_xform = UsdGeom.Xformable(robot_anchor.GetPrim())
    robot_xform.ClearXformOpOrder()
    robot_xform.AddTranslateOp().Set(Gf.Vec3d(robot_center_x, robot_center_y, -robot_base_pocket_depth))
    # Rotate the robot toward the A4 workspace behind the front slot.
    robot_xform.AddRotateZOp().Set(90.0)

    # Right disk: diameter 100 mm, height 74 mm, drawing center x=590 mm, y=78 mm.
    apply_static_collider(
        cylinder(stage, '/World/Workspace/RightDiskAluminumTop', (0.590, 0.078, 0.037), 0.050, 0.074, disk_mat),
        approximation='convexHull',
    )
    apply_static_collider(
        cylinder(stage, '/World/Workspace/RightDiskBlackBase', (0.590, 0.078, 0.012), 0.052, 0.024, black_mat),
        approximation='convexHull',
    )
    yellow_marker_mat = make_material(stage, '/World/Materials/yellow_center_marker', (1.0, 0.88, 0.02), 0.38)
    flat_circle_marker(stage, '/World/Workspace/RightDiskCenterYellowMarker', (0.590, 0.078, 0.0743), 0.0045, yellow_marker_mat)

    # Red specimen/cube on A4 near the back side from photo.
    specimen_size = (0.030, 0.030, 0.030)
    apply_dynamic_rigid_body(
        cube(
            stage,
            '/World/Workspace/RedSpecimenBlock',
            (a4_center_x + 0.085, 0.300, paper_th + 0.030 / 2.0 + 0.00008),
            specimen_size,
            cube_mat,
        ),
        mass_kg=0.03,
        approximation=None,
        physics_material=pla_physics_mat,
        contact_offset=collision_skin_for_dimensions(specimen_size),
        rest_offset=0.0,
        enable_ccd=True,
        max_depenetration_velocity=0.2,
        solver_position_iterations=32,
        solver_velocity_iterations=4,
        contact_report_threshold=0.2,
    )

    # Lighting only; no fixed camera requested.
    dome = UsdLux.DomeLight.Define(stage, '/World/Lights/SoftLabDome')
    dome.CreateIntensityAttr(450.0)
    sun = UsdLux.DistantLight.Define(stage, '/World/Lights/OverheadLight')
    sun.CreateIntensityAttr(1200.0)
    sun.CreateAngleAttr(0.35)

    stage.GetRootLayer().Save()
    print(OUT)


if __name__ == '__main__':
    main()
