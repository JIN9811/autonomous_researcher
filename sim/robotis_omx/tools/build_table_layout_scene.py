#!/usr/bin/env python3
from pathlib import Path

from PIL import Image, ImageDraw
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade, Vt

ROOT = Path('/home/jin/autonomous_researcher/sim/robotis_omx')
OUT = ROOT / 'scene' / 'omx_table_layout.usda'
ROBOT_USD = ROOT / 'omx' / 'omx.usda'
TEXTURE_DIR = ROOT / 'scene' / 'Textures'
REDWOOD_TEXTURE = TEXTURE_DIR / 'redwood_table_grain.png'


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


def _set_attr(prim, name, type_name, value):
    attr = prim.GetAttribute(name)
    if not attr:
        attr = prim.CreateAttribute(name, type_name)
    attr.Set(value)
    return attr


def apply_static_collider(geom_prim, *, approximation='box'):
    """Give fixed workspace geometry a lightweight physics collision contract."""
    prim = geom_prim.GetPrim()
    UsdPhysics.CollisionAPI.Apply(prim)
    _set_attr(prim, 'physics:collisionEnabled', Sdf.ValueTypeNames.Bool, True)
    if approximation:
        _set_attr(prim, 'physics:approximation', Sdf.ValueTypeNames.Token, approximation)
    return geom_prim


def apply_dynamic_rigid_body(geom_prim, *, mass_kg, approximation='box'):
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
    _set_attr(physics_scene.GetPrim(), 'physxScene:timeStepsPerSecond', Sdf.ValueTypeNames.Int, 60)

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

    # Coordinate convention: X left->right, Y front->back, Z up. Origin is front-left table-top corner.
    # Desk outer boundary follows the provided top-view drawing: 700 x 450 mm.
    table_w = 0.700
    table_d = 0.450
    table_th = 0.030
    table_center = (table_w / 2.0, table_d / 2.0, -table_th / 2.0)
    apply_static_collider(cube(stage, '/World/Table/TableTop', table_center, (table_w, table_d, table_th), desk_mat))
    textured_rect_mesh(stage, '/World/Table/TableTopRedwoodGrainSurface', 0.0, table_w, 0.0, table_d, 0.00003, desk_texture_mat)

    # Robot base slot from drawing: 150 x 120 mm, front-left at x=240 mm, y=0.
    robot_center_x = 0.240 + 0.150 / 2.0
    robot_center_y = 0.120 / 2.0

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
        )
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
    robot_xform.AddTranslateOp().Set(Gf.Vec3d(robot_center_x, robot_center_y, 0.0))
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
    apply_dynamic_rigid_body(
        cube(
            stage,
            '/World/Workspace/RedSpecimenBlock',
            (a4_center_x + 0.085, 0.300, paper_th + 0.030 / 2.0),
            (0.030, 0.030, 0.030),
            cube_mat,
        ),
        mass_kg=0.02,
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
