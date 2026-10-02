"""CPU-only USD checks: shrink the pad footprint, not thickness or placement."""
import unittest
from pathlib import Path

try:
    from pxr import Gf, Usd, UsdGeom, UsdShade
except ImportError:
    Usd = None

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(Usd is None, "Requires USD Python; no simulator/GPU needed")
class GripPadInsetTests(unittest.TestCase):
    def test_pad_edges_retreat_half_mm_without_changing_thickness_or_center(self):
        # Bounds derive from the original footprint minus 0.5 mm per edge.
        expected = {
            "InnerGripPadCollision": ((.05868, -.00855, 0), (.00582, .0004, .00997)),
            "InnerGripPadCollision_mimic": ((.05869, .00855, 0), (.005815, .0004, .01037)),
        }
        for relative in (
            "sim/robotis_omx/omx/omx.usda",
            "sim/robotis_omx/scene/payloads/base.usda",
            "sim/robotis_omx/scene/omx_table_layout_20260915.usda",
        ):
            stage = Usd.Stage.Open(str(ROOT / relative))
            pads = [p for p in stage.Traverse() if p.GetName() in expected]
            self.assertEqual(len(pads), 2, relative)
            for pad in pads:
                with self.subTest(asset=relative, pad=pad.GetName()):
                    center, half_extent = expected[pad.GetName()]
                    matrix = UsdGeom.Xformable(pad).GetLocalTransformation()
                    size = UsdGeom.Cube(pad).GetSizeAttr().Get()
                    for sign in (-1, 1):
                        corner = matrix.Transform(Gf.Vec3d(*([sign * size / 2] * 3)))
                        for axis in range(3):
                            self.assertAlmostEqual(corner[axis], center[axis] + sign * half_extent[axis], places=8)
                    material, _ = UsdShade.MaterialBindingAPI(pad).ComputeBoundMaterial("physics")
                    self.assertEqual(material.GetPrim().GetName(), "AntiSlipTapeMaterial")
                    self.assertEqual(material.GetPrim().GetAttribute("physics:staticFriction").Get(), 5)
                    self.assertEqual(material.GetPrim().GetAttribute("physics:dynamicFriction").Get(), 4)
                    self.assertTrue(pad.GetAttribute("physics:collisionEnabled").Get())


if __name__ == "__main__":
    unittest.main()
