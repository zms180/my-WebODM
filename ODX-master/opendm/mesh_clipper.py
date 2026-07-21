import math
import os
from collections import Counter

from shapely import constrained_delaunay_triangles
from shapely.geometry import Point, Polygon
from shapely.prepared import prep


STATE_RECORDS = {'g', 'o', 's', 'usemtl'}


def point_in_boundary(point, boundary_polygon):
    return boundary_polygon.covers(Point(point[0], point[1]))


def _record_type(line):
    stripped = line.lstrip()
    if not stripped or stripped.startswith('#'):
        return None
    return stripped.split(None, 1)[0]


def _resolve_index(value, count, line_number, record):
    if not value:
        return None

    try:
        index = int(value)
    except ValueError:
        raise ValueError("Invalid OBJ %s index on line %s" % (record, line_number))

    if index > 0:
        resolved = index - 1
    elif index < 0:
        resolved = count + index
    else:
        raise ValueError("OBJ %s index cannot be zero on line %s" % (record, line_number))

    if resolved < 0 or resolved >= count:
        raise ValueError("Invalid OBJ %s index on line %s" % (record, line_number))

    return resolved


def _parse_reference(token, vertex_count, texcoord_count, normal_count, line_number):
    values = token.split('/')
    if len(values) > 3:
        raise ValueError("Invalid OBJ face reference on line %s" % line_number)

    vertex = _resolve_index(values[0], vertex_count, line_number, 'vertex')
    if vertex is None:
        raise ValueError("Missing OBJ vertex index on line %s" % line_number)

    texcoord = _resolve_index(values[1], texcoord_count, line_number, 'texture') \
        if len(values) > 1 else None
    normal = _resolve_index(values[2], normal_count, line_number, 'normal') \
        if len(values) > 2 else None
    return vertex, texcoord, normal


def _parse_values(line, minimum, line_number, record):
    try:
        values = tuple(map(float, line.split()[1:]))
    except ValueError:
        raise ValueError("Invalid OBJ %s on line %s" % (record, line_number))
    if len(values) < minimum:
        raise ValueError("Invalid OBJ %s on line %s" % (record, line_number))
    return values


def _load_obj(input_obj):
    vertices = []
    texcoords = []
    normals = []
    vertex_lines = []
    texcoord_lines = []
    normal_lines = []
    preamble = []
    records = []

    with open(input_obj, 'r') as source:
        for line_number, line in enumerate(source, 1):
            record = _record_type(line)
            if record == 'v':
                vertices.append(_parse_values(line, 3, line_number, 'vertex'))
                vertex_lines.append(line)
            elif record == 'vt':
                texcoords.append(_parse_values(line, 1, line_number, 'texture coordinate'))
                texcoord_lines.append(line)
            elif record == 'vn':
                normals.append(_parse_values(line, 3, line_number, 'normal'))
                normal_lines.append(line)
            elif record == 'f':
                tokens = []
                for token in line.split()[1:]:
                    if token.startswith('#'):
                        break
                    tokens.append(token)
                if len(tokens) < 3:
                    raise ValueError("Invalid OBJ face on line %s" % line_number)
                references = [
                    _parse_reference(token, len(vertices), len(texcoords), len(normals), line_number)
                    for token in tokens
                ]
                records.append(('face', references))
            elif record in STATE_RECORDS:
                records.append(('state', line))
            elif record in ('l', 'p'):
                raise ValueError("Unsupported OBJ %s primitive on line %s" % (record, line_number))
            else:
                preamble.append(line)

    if not vertices:
        raise ValueError("OBJ file has no vertices")

    return {
        'vertices': vertices,
        'texcoords': texcoords,
        'normals': normals,
        'vertex_lines': vertex_lines,
        'texcoord_lines': texcoord_lines,
        'normal_lines': normal_lines,
        'preamble': preamble,
        'records': records,
    }


def _value_key(values, precision=9):
    return tuple(round(value, precision) for value in values)


def _format_record(record, values):
    return record + " " + " ".join("%.17g" % value for value in values) + "\n"


def _attribute_cache(values):
    result = {}
    for index, value in enumerate(values):
        result.setdefault(_value_key(value), index)
    return result


def _append_attribute(values, lines, cache, record, value):
    key = _value_key(value)
    index = cache.get(key)
    if index is not None:
        return index
    index = len(values)
    values.append(tuple(value))
    lines.append(_format_record(record, value))
    cache[key] = index
    return index


def _signed_area(coordinates):
    return (
        coordinates[0][0] * (coordinates[1][1] - coordinates[2][1]) +
        coordinates[1][0] * (coordinates[2][1] - coordinates[0][1]) +
        coordinates[2][0] * (coordinates[0][1] - coordinates[1][1])
    ) * 0.5


def _barycentric_weights(coordinates, point):
    x1, y1 = coordinates[0]
    x2, y2 = coordinates[1]
    x3, y3 = coordinates[2]
    denominator = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(denominator) < 1e-12:
        return None
    first = ((y2 - y3) * (point[0] - x3) + (x3 - x2) * (point[1] - y3)) / denominator
    second = ((y3 - y1) * (point[0] - x3) + (x1 - x3) * (point[1] - y3)) / denominator
    return first, second, 1.0 - first - second


def _interpolate(values, weights):
    dimensions = min(len(value) for value in values)
    return tuple(
        sum(weights[index] * values[index][dimension] for index in range(3))
        for dimension in range(dimensions)
    )


def _reference_at(point, references, data, caches):
    coordinates = [data['vertices'][reference[0]][:2] for reference in references]
    for index, coordinate in enumerate(coordinates):
        if abs(point[0] - coordinate[0]) < 1e-9 and abs(point[1] - coordinate[1]) < 1e-9:
            return references[index]

    weights = _barycentric_weights(coordinates, point)
    if weights is None:
        return None

    vertex_value = list(_interpolate([data['vertices'][reference[0]] for reference in references], weights))
    vertex_value[0] = point[0]
    vertex_value[1] = point[1]
    vertex = _append_attribute(data['vertices'], data['vertex_lines'], caches['vertices'],
                               'v', vertex_value)

    texcoord = None
    if all(reference[1] is not None for reference in references):
        texcoord_value = _interpolate(
            [data['texcoords'][reference[1]] for reference in references], weights)
        texcoord = _append_attribute(data['texcoords'], data['texcoord_lines'],
                                     caches['texcoords'], 'vt', texcoord_value)

    normal = None
    if all(reference[2] is not None for reference in references):
        normal_value = list(_interpolate(
            [data['normals'][reference[2]] for reference in references], weights))
        length = math.sqrt(sum(value * value for value in normal_value[:3]))
        if length > 0:
            normal_value[:3] = [value / length for value in normal_value[:3]]
        normal = _append_attribute(data['normals'], data['normal_lines'],
                                   caches['normals'], 'vn', normal_value)

    return vertex, texcoord, normal


def _polygon_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == 'Polygon':
        yield geometry
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from _polygon_parts(part)


def _clip_triangle(references, data, boundary_polygon, prepared_boundary,
                   boundary_is_convex, inside_boundary, caches):
    coordinates = [data['vertices'][reference[0]][:2] for reference in references]
    source_area = _signed_area(coordinates)
    all_inside = all(inside_boundary[reference[0]] for reference in references)

    if abs(source_area) < 1e-12:
        return [references] if all_inside else []

    triangle = Polygon(coordinates)
    if all_inside and (boundary_is_convex or prepared_boundary.covers(triangle)):
        return [references]
    if not prepared_boundary.intersects(triangle):
        return []

    clipped = triangle.intersection(boundary_polygon)
    result = []
    for polygon in _polygon_parts(clipped):
        if polygon.area < 1e-12:
            continue
        triangles = constrained_delaunay_triangles(polygon)
        for triangle_part in triangles.geoms:
            triangle_coordinates = list(triangle_part.exterior.coords)[:-1]
            if len(triangle_coordinates) != 3:
                continue
            if _signed_area(triangle_coordinates) * source_area < 0:
                triangle_coordinates[1], triangle_coordinates[2] = \
                    triangle_coordinates[2], triangle_coordinates[1]
            output_references = [
                _reference_at(point, references, data, caches)
                for point in triangle_coordinates
            ]
            if all(reference is not None for reference in output_references):
                if len(set(reference[0] for reference in output_references)) == 3:
                    result.append(output_references)
    return result


def _component_filter(faces, vertices, minimum_faces, minimum_ratio):
    if not faces:
        return set()

    position_nodes = {}
    parent = []
    sizes = []

    def node_for(vertex_index):
        key = _value_key(vertices[vertex_index][:3], precision=6)
        node = position_nodes.get(key)
        if node is None:
            node = len(parent)
            position_nodes[key] = node
            parent.append(node)
            sizes.append(1)
        return node

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        left = find(left)
        right = find(right)
        if left == right:
            return
        if sizes[left] < sizes[right]:
            left, right = right, left
        parent[right] = left
        sizes[left] += sizes[right]

    face_nodes = []
    for face in faces:
        nodes = [node_for(reference[0]) for reference in face]
        for node in nodes[1:]:
            union(nodes[0], node)
        face_nodes.append(nodes[0])

    roots = [find(node) for node in face_nodes]
    counts = Counter(roots)
    largest_root, largest_faces = counts.most_common(1)[0]
    threshold = max(minimum_faces, int(math.ceil(largest_faces * minimum_ratio)))
    kept_roots = {
        root for root, count in counts.items()
        if root == largest_root or count >= threshold
    }
    return {
        face_index for face_index, root in enumerate(roots)
        if root in kept_roots
    }


def _reference_token(reference, vertex_map, texcoord_map, normal_map):
    vertex, texcoord, normal = reference
    token = str(vertex_map[vertex])
    if texcoord is not None or normal is not None:
        token += '/' + (str(texcoord_map[texcoord]) if texcoord is not None else '')
        if normal is not None:
            token += '/' + str(normal_map[normal])
    return token


def _write_obj(output_obj, data, records, faces, kept_faces):
    vertex_map = {}
    texcoord_map = {}
    normal_map = {}

    for face_index in sorted(kept_faces):
        for vertex, texcoord, normal in faces[face_index]:
            if vertex not in vertex_map:
                vertex_map[vertex] = len(vertex_map) + 1
            if texcoord is not None and texcoord not in texcoord_map:
                texcoord_map[texcoord] = len(texcoord_map) + 1
            if normal is not None and normal not in normal_map:
                normal_map[normal] = len(normal_map) + 1

    with open(output_obj, 'w') as target:
        target.writelines(data['preamble'])
        for index in vertex_map:
            target.write(data['vertex_lines'][index])
        for index in texcoord_map:
            target.write(data['texcoord_lines'][index])
        for index in normal_map:
            target.write(data['normal_lines'][index])

        for record, value in records:
            if record == 'state':
                target.write(value)
            elif value in kept_faces:
                references = faces[value]
                target.write("f %s\n" % " ".join(
                    _reference_token(reference, vertex_map, texcoord_map, normal_map)
                    for reference in references
                ))


def clip_obj_by_boundary(input_obj, output_obj, boundary_coords,
                         minimum_component_faces=20, minimum_component_ratio=0.001):
    if os.path.abspath(input_obj) == os.path.abspath(output_obj):
        raise ValueError("Input and output OBJ paths must be different")

    boundary_polygon = Polygon([(coordinate[0], coordinate[1]) for coordinate in boundary_coords])
    if boundary_polygon.is_empty or not boundary_polygon.is_valid or boundary_polygon.area == 0:
        raise ValueError("Invalid boundary polygon")

    data = _load_obj(input_obj)
    prepared_boundary = prep(boundary_polygon)
    boundary_is_convex = boundary_polygon.equals(boundary_polygon.convex_hull)
    inside_boundary = [
        prepared_boundary.covers(Point(vertex[0], vertex[1]))
        for vertex in data['vertices']
    ]
    caches = {
        'vertices': _attribute_cache(data['vertices']),
        'texcoords': _attribute_cache(data['texcoords']),
        'normals': _attribute_cache(data['normals']),
    }

    clipped_records = []
    faces = []
    for record, value in data['records']:
        if record == 'state':
            clipped_records.append((record, value))
            continue

        references = value
        triangles = [
            [references[0], references[index], references[index + 1]]
            for index in range(1, len(references) - 1)
        ]
        for triangle in triangles:
            for clipped_face in _clip_triangle(
                    triangle, data, boundary_polygon, prepared_boundary,
                    boundary_is_convex, inside_boundary, caches):
                face_index = len(faces)
                faces.append(clipped_face)
                clipped_records.append(('face', face_index))

    kept_faces = _component_filter(
        faces, data['vertices'], minimum_component_faces, minimum_component_ratio)
    _write_obj(output_obj, data, clipped_records, faces, kept_faces)
    return len(kept_faces)
