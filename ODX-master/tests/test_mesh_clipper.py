import os
import tempfile
import unittest

from shapely.geometry import Polygon

from opendm.mesh_clipper import clip_obj_by_boundary, point_in_boundary


class TestMeshClipper(unittest.TestCase):
    def test_point_in_boundary_includes_boundary(self):
        boundary = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])

        self.assertTrue(point_in_boundary((5, 5), boundary))
        self.assertTrue(point_in_boundary((0, 0), boundary))
        self.assertFalse(point_in_boundary((11, 5), boundary))

    def test_clip_preserves_obj_records_and_splits_crossing_faces(self):
        source = (
            "mtllib model.mtl\n"
            "v 0 0 0\n"
            "v 5 0 0\n"
            "v 5 5 0\n"
            "v 12 5 0\n"
            "vt 0 0\n"
            "vt 1 0\n"
            "vt 1 1\n"
            "vn 0 0 1\n"
            "usemtl material0000\n"
            "f 1/1/1 2/2/1 3/3/1\n"
            "f 2/1/1 3/2/1 4/3/1\n"
        )

        output, kept_faces = self._clip(source, [(0, 0), (10, 0), (10, 10), (0, 10)])

        vertices, texcoords, normals, faces = self._parse_obj(output)

        self.assertEqual(kept_faces, 3)
        self.assertIn("mtllib model.mtl\n", output)
        self.assertIn("usemtl material0000\n", output)
        self.assertIn("vt 1 1\n", output)
        self.assertIn("vn 0 0 1\n", output)
        self.assertIn("f 1/1/1 2/2/1 3/3/1\n", output)
        self.assertTrue(all(0 <= vertex[0] <= 10 for vertex in vertices))
        self.assertTrue(any(abs(vertex[0] - 10) < 1e-9 for vertex in vertices))
        self.assertTrue(all(all(len(reference) == 3 for reference in face) for face in faces))
        for face in faces:
            for vertex, texcoord, normal in face:
                self.assertLessEqual(vertex, len(vertices))
                self.assertLessEqual(texcoord, len(texcoords))
                self.assertLessEqual(normal, len(normals))

    def test_negative_indices_use_vertices_defined_at_face(self):
        source = (
            "v 1 1 0\n"
            "v 2 1 0\n"
            "v 1 2 0\n"
            "f -3 -2 -1\n"
            "v 20 20 0\n"
            "v 21 20 0\n"
            "v 20 21 0\n"
            "f -3 -2 -1\n"
        )

        output, kept_faces = self._clip(source, [(0, 0), (10, 0), (10, 10), (0, 10)])

        vertices, _, _, faces = self._parse_obj(output)

        self.assertEqual(kept_faces, 1)
        self.assertEqual(len(faces), 1)
        self.assertTrue(all(vertex[0] <= 10 and vertex[1] <= 10 for vertex in vertices))
        self.assertNotIn("f -3 -2 -1\n", output)

    def test_ngon_is_triangulated_and_clipped(self):
        source = (
            "v 1 1 0\n"
            "v 2 1 0\n"
            "v 2 2 0\n"
            "v 20 2 0\n"
            "f 1 2 3 4\n"
        )

        output, kept_faces = self._clip(source, [(0, 0), (10, 0), (10, 10), (0, 10)])

        vertices, _, _, faces = self._parse_obj(output)

        self.assertEqual(kept_faces, 3)
        self.assertEqual(len(faces), 3)
        self.assertTrue(all(vertex[0] <= 10 for vertex in vertices))
        self.assertTrue(any(abs(vertex[0] - 10) < 1e-9 for vertex in vertices))

    def test_concave_boundary_clips_crossing_triangle(self):
        source = (
            "v 1 1 0\n"
            "v 5 1 0\n"
            "v 1 5 0\n"
            "f 1 2 3\n"
        )
        boundary = [(0, 0), (6, 0), (6, 2), (2, 2), (2, 6), (0, 6)]

        output, kept_faces = self._clip(source, boundary)

        vertices, _, _, faces = self._parse_obj(output)
        polygon = Polygon(boundary)

        self.assertGreater(kept_faces, 0)
        for face in faces:
            coordinates = [vertices[reference[0] - 1][:2] for reference in face]
            self.assertTrue(polygon.covers(Polygon(coordinates)))

    def test_removes_small_disconnected_component(self):
        source = (
            "v 0 0 10\n"
            "v 4 0 10\n"
            "v 4 4 10\n"
            "v 0 4 10\n"
            "v 7 7 -100\n"
            "v 8 7 -100\n"
            "v 7 8 -100\n"
            "f 1 2 3\n"
            "f 1 3 4\n"
            "f 5 6 7\n"
        )

        output, kept_faces = self._clip(source, [(-1, -1), (10, -1), (10, 10), (-1, 10)])
        vertices, _, _, faces = self._parse_obj(output)

        self.assertEqual(kept_faces, 2)
        self.assertEqual(len(faces), 2)
        self.assertTrue(all(vertex[2] == 10 for vertex in vertices))

    def _clip(self, source, boundary):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_obj = os.path.join(temp_dir, "input.obj")
            output_obj = os.path.join(temp_dir, "output.obj")
            with open(input_obj, 'w') as output:
                output.write(source)

            kept_faces = clip_obj_by_boundary(input_obj, output_obj, boundary)

            with open(output_obj) as output:
                return output.read(), kept_faces

    def _parse_obj(self, source):
        vertices = []
        texcoords = []
        normals = []
        faces = []
        for line in source.splitlines():
            if line.startswith("v "):
                vertices.append(tuple(map(float, line.split()[1:])))
            elif line.startswith("vt "):
                texcoords.append(tuple(map(float, line.split()[1:])))
            elif line.startswith("vn "):
                normals.append(tuple(map(float, line.split()[1:])))
            elif line.startswith("f "):
                faces.append([
                    tuple(int(value) if value else None for value in reference.split('/'))
                    for reference in line.split()[1:]
                ])
        return vertices, texcoords, normals, faces


if __name__ == '__main__':
    unittest.main()
