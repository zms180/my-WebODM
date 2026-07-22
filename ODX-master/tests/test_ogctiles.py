import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from pyproj import CRS, Transformer

from opendm.ogc_enu import create_enu_obj, ecef_to_enu


class TestOgcTiles(unittest.TestCase):
    def test_ecef_to_enu_axes(self):
        reference = (6378137.0, 0.0, 0.0)

        np.testing.assert_allclose(ecef_to_enu(6378137.0, 1.0, 0.0, reference, 0.0, 0.0), [1, 0, 0])
        np.testing.assert_allclose(ecef_to_enu(6378137.0, 0.0, 1.0, reference, 0.0, 0.0), [0, 1, 0])
        np.testing.assert_allclose(ecef_to_enu(6378138.0, 0.0, 0.0, reference, 0.0, 0.0), [0, 0, 1])

    def test_create_enu_obj(self):
        source_srs = CRS.from_epsg(32649)
        source_offset = (774924.0, 2718508.0)
        to_lla = Transformer.from_crs(source_srs, CRS.from_epsg(4979), always_xy=True)
        longitude, latitude, _ = to_lla.transform(*source_offset, 0.0)
        reference_lla = {
            'latitude': latitude,
            'longitude': longitude,
            'altitude': 0.0,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            input_obj = os.path.join(temp_dir, "input.obj")
            output_obj = os.path.join(temp_dir, "output.obj")
            with open(input_obj, 'w') as f:
                f.write("mtllib model.mtl\n")
                f.write("v 0 0 0 0.1 0.2 0.3\n")
                f.write("v 100 0 0\n")
                f.write("v 0 100 0\n")
                f.write("vn 1 0 0\n")
                f.write("vt 0.25 0.75\n")
                f.write("f 1/1/1 2/1/1 3/1/1\n")

            create_enu_obj(input_obj, output_obj, source_srs, source_offset, reference_lla)

            with open(output_obj) as f:
                lines = f.readlines()

        vertices = [np.fromstring(line[2:], sep=' ')[:3] for line in lines if line.startswith("v ")]
        normal = np.fromstring(next(line[3:] for line in lines if line.startswith("vn ")), sep=' ')

        np.testing.assert_allclose(vertices[0], [0, 0, 0], atol=1e-6)
        self.assertAlmostEqual(np.linalg.norm(vertices[1]), 100.0, delta=0.1)
        self.assertAlmostEqual(np.linalg.norm(vertices[2]), 100.0, delta=0.1)
        self.assertGreater(abs(vertices[1][1]), 0.1)
        self.assertAlmostEqual(np.linalg.norm(normal), 1.0, places=7)
        self.assertTrue(next(line for line in lines if line.startswith("v ")).endswith(" 0.1 0.2 0.3\n"))
        self.assertIn("mtllib model.mtl\n", lines)
        self.assertIn("vt 0.25 0.75\n", lines)
        self.assertIn("f 1/1/1 2/1/1 3/1/1\n", lines)

    @unittest.skipUnless(importlib.util.find_spec("osgeo"), "requires GDAL")
    def test_clipped_model_uses_single_lod(self):
        command = self._build_textured_model(
            [(-1, -1), (2, -1), (2, 2), (-1, 2)])

        self.assertIn("--lods 1", command)

    @unittest.skipUnless(importlib.util.find_spec("osgeo"), "requires GDAL")
    def test_unclipped_model_keeps_multiple_lods(self):
        command = self._build_textured_model(None)

        self.assertIn("--lods 4", command)

    def _build_textured_model(self, boundary):
        from opendm.ogctiles import build_textured_model

        with tempfile.TemporaryDirectory() as temp_dir:
            input_obj = os.path.join(temp_dir, "model.obj")
            output_path = os.path.join(temp_dir, "tiles")
            with open(input_obj, "w") as output:
                output.write("v 0 0 0\n")
                output.write("v 1 0 0\n")
                output.write("v 0 1 0\n")
                output.write("f 1 2 3\n")

            commands = []

            def run(command):
                commands.append(command)
                os.makedirs(output_path)
                with open(os.path.join(output_path, "tileset.json"), "w") as output:
                    output.write("{}")

            with patch("opendm.ogctiles.system.run", side_effect=run):
                build_textured_model(
                    input_obj, output_path, boundary=boundary)

        self.assertEqual(len(commands), 1)
        return commands[0]


if __name__ == '__main__':
    unittest.main()
